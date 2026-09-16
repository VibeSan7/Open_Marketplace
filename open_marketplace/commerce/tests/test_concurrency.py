from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from django.db import close_old_connections, connections
from django.test import TransactionTestCase

from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.common.errors import ConcurrentConflict, InputRejected
from open_marketplace.commerce import public
from open_marketplace.commerce.models import CommerceOrder


class CommerceOrderConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.fixtures = CatalogTestCase()
        self.addCleanup(self.fixtures.doCleanups)
        self.fixtures.setUp()
        self.product_id, self.variant_id, _ = self.fixtures.product(stock="1")

    def line(self):
        return {
            "variant_id": str(self.variant_id),
            "quantity": "1",
            "expected_unit_price": "120",
        }

    def parallel(self, operations):
        barrier = Barrier(len(operations))

        def run(operation):
            close_old_connections()
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                    cursor.execute("SET statement_timeout = '20s'")
                barrier.wait(timeout=30)
                try:
                    return "ok", operation()
                except (InputRejected, ConcurrentConflict) as exc:
                    return "rejected", type(exc).__name__
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(operations)) as executor:
            futures = [executor.submit(run, operation) for operation in operations]
            return [future.result(timeout=45) for future in futures]

    def test_same_intent_converges_to_one_order(self):
        intent_id = uuid4()
        operation = lambda: public.create_order(
            intent_id=intent_id,
            lines=[self.line()],
            context=self.fixtures.buyer_context,
        )

        results = self.parallel([operation, operation])

        self.assertEqual([result[0] for result in results], ["ok", "ok"])
        self.assertEqual(results[0][1], results[1][1])
        self.assertEqual(CommerceOrder.objects.count(), 1)
