from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from django.db import close_old_connections
from django.test import TransactionTestCase, override_settings

from open_marketplace.catalog.models import Stock
from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.common.errors import InputRejected
from open_marketplace.demo_orders import public


@override_settings(DEMO_ORDERS_ENABLED=True)
class DemoOrdersConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.fixture = CatalogTestCase(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.context_one = self.fixture.buyer_context
        self.context_two = self.fixture.other_context
        self.same_buyer_context = self.context_one
        _, self.variant_id, _ = self.fixture.product(title="Один экземпляр", price="10.00")
        Stock.objects.filter(variant_id=self.variant_id).update(quantity="1")

    def test_two_real_connections_reserve_last_simulated_unit_once(self):
        start = Barrier(2)

        def reserve(context):
            close_old_connections()
            try:
                start.wait(timeout=15)
                return public.create_order(
                    variant_id=self.variant_id,
                    quantity="1",
                    intent_id=uuid4(),
                    context=context,
                )
            except InputRejected:
                return "unavailable"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(reserve, (self.context_one, self.context_two)))
        self.assertEqual(sum(result != "unavailable" for result in results), 1)

    def test_two_real_connections_replay_same_intent_once(self):
        start = Barrier(2)
        intent_id = uuid4()

        def create(context):
            close_old_connections()
            try:
                start.wait(timeout=15)
                return public.create_order(
                    variant_id=self.variant_id,
                    quantity="1",
                    intent_id=intent_id,
                    context=context,
                )["id"]
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(create, (self.same_buyer_context, self.same_buyer_context)))
        self.assertEqual(results[0], results[1])
