from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import close_old_connections
from django.test import TransactionTestCase

from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.common.errors import ConcurrentConflict


class CatalogConcurrencyTests(TransactionTestCase):
    def test_two_real_database_transactions_cannot_overwrite_one_price_version(self):
        fixture = CatalogTestCase(methodName="runTest")
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        product, variant, photo = fixture.product()
        start = Barrier(2)

        def update(price):
            close_old_connections()
            try:
                start.wait(timeout=15)
                try:
                    fixture.catalog.set_offer(variant_id=variant, field="price", value=price, expected_version=1, context=fixture.seller_context)
                except ConcurrentConflict:
                    return "conflict", price
                return "saved", price
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(update, ("90", "80")))
        self.assertEqual(sorted(result[0] for result in results), ["conflict", "saved"])
        winner = next(price for status, price in results if status == "saved")
        view = fixture.catalog.get_product(product_id=product, context=fixture.buyer_context)
        self.assertEqual(str(view["variants"][0]["price"]), f"{winner}.00")
