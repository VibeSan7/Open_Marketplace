from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

from django.db import OperationalError, close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings

from open_marketplace.catalog.models import Participant, Product
from open_marketplace.catalog.public import get_demo_offer_snapshot
from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.demo_orders import cart


@override_settings(DEMO_ORDERS_ENABLED=True)
class PublicBuyerConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.fixture = CatalogTestCase(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.product_id, self.variant_id, _ = self.fixture.product()
        self.fixture.catalog.set_public_listing(product_id=self.product_id, enabled=True, context=self.fixture.seller_context)

    def test_two_first_cart_additions_serialize_without_granting_private_access(self):
        Participant.objects.filter(account_id=self.fixture.buyer.id).delete()
        initial_read = Barrier(2)

        def add():
            close_old_connections()
            first = True

            def synchronize(execute, sql, params, many, context):
                nonlocal first
                result = execute(sql, params, many, context)
                if first and sql.startswith("SELECT") and '"catalog_participant"' in sql:
                    first = False
                    initial_read.wait(timeout=15)
                return result

            try:
                with connection.execute_wrapper(synchronize):
                    return cart.add_cart_item(variant_id=self.variant_id, quantity="1", context=self.fixture.buyer_context)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(add), pool.submit(add)]
            for future in futures:
                future.result(timeout=30)
        self.assertFalse(Participant.objects.get(account_id=self.fixture.buyer.id).allowed)
        result = cart.get_cart(context=self.fixture.buyer_context)
        self.assertEqual(result["items"][0]["quantity"], Decimal("2"))

    def test_locked_offer_serializes_with_product_visibility_changes(self):
        def change_visibility():
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '500ms'")
                    Product.objects.filter(pk=self.product_id).update(public_listing=False)
                return "changed"
            except OperationalError as error:
                if getattr(error.__cause__, "sqlstate", None) == "55P03":
                    return "locked"
                raise
            finally:
                close_old_connections()

        with transaction.atomic():
            get_demo_offer_snapshot(variant_id=self.variant_id, context=self.fixture.buyer_context, lock=True)
            with ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(change_visibility).result(timeout=10)
            self.assertEqual(result, "locked")
