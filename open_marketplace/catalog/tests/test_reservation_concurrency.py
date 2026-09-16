from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from django.apps import apps
from django.db import close_old_connections, connections
from django.test import TransactionTestCase

from open_marketplace.catalog.models import Stock
from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.common.errors import ConcurrentConflict, InputRejected


class InventoryConcurrencyTests(TransactionTestCase):
    def setUp(self):
        # Reuse fixture setup, not TestCase's outer transaction: workers need
        # committed setup rows and their own real PostgreSQL connections.
        self.fixtures = CatalogTestCase()
        self.addCleanup(self.fixtures.doCleanups)
        self.fixtures.setUp()
        self.catalog = self.fixtures.catalog
        self.product_id, self.variant_id, _ = self.fixtures.product(stock="1")

    def line(self, variant_id=None):
        return {"variant_id": str(variant_id or self.variant_id), "quantity": "1", "expected_unit_price": "120"}

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
                    return ("ok", operation())
                except (InputRejected, ConcurrentConflict) as exc:
                    return ("rejected", type(exc).__name__)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(operations)) as executor:
            futures = [executor.submit(run, operation) for operation in operations]
            return [future.result(timeout=45) for future in futures]

    def test_two_buyers_cannot_reserve_the_last_unit(self):
        results = self.parallel([
            lambda: self.catalog.reserve_inventory(intent_id=uuid4(), lines=[self.line()], context=self.fixtures.buyer_context),
            lambda: self.catalog.reserve_inventory(intent_id=uuid4(), lines=[self.line()], context=self.fixtures.other_context),
        ])
        self.assertEqual(sorted(result[0] for result in results), ["ok", "rejected"])
        stock = Stock.objects.get(variant_id=self.variant_id)
        self.assertEqual((stock.quantity, stock.reserved_quantity, stock.available_quantity), (1, 1, 0))
        self.assertEqual(apps.get_model("catalog", "InventoryReservation").objects.count(), 1)
        self.assertEqual(apps.get_model("catalog", "InventoryAllocation").objects.count(), 1)

    def test_concurrent_same_intent_has_one_effect(self):
        intent_id = uuid4()
        operation = lambda: self.catalog.reserve_inventory(intent_id=intent_id, lines=[self.line()], context=self.fixtures.buyer_context)
        results = self.parallel([operation, operation])
        self.assertEqual([result[0] for result in results], ["ok", "ok"])
        self.assertEqual(results[0][1], results[1][1])
        self.assertEqual(Stock.objects.get(variant_id=self.variant_id).reserved_quantity, 1)
        self.assertEqual(apps.get_model("catalog", "InventoryReservation").objects.count(), 1)
        self.assertEqual(apps.get_model("catalog", "InventoryAllocation").objects.count(), 1)

    def test_opposite_basket_order_does_not_deadlock_or_partially_reserve(self):
        _, second_id, _ = self.fixtures.product(stock="1")
        lines = [self.line(), self.line(second_id)]
        results = self.parallel([
            lambda: self.catalog.reserve_inventory(intent_id=uuid4(), lines=lines, context=self.fixtures.buyer_context),
            lambda: self.catalog.reserve_inventory(intent_id=uuid4(), lines=list(reversed(lines)), context=self.fixtures.other_context),
        ])
        self.assertEqual(sorted(result[0] for result in results), ["ok", "rejected"])
        self.assertEqual(apps.get_model("catalog", "InventoryReservation").objects.count(), 1)
        self.assertEqual(apps.get_model("catalog", "InventoryAllocation").objects.count(), 2)
        self.assertTrue(all(stock.available_quantity == 0 for stock in Stock.objects.all()))

    def test_commit_and_release_race_has_only_one_terminal_effect(self):
        held = self.catalog.reserve_inventory(intent_id=uuid4(), lines=[self.line()], context=self.fixtures.buyer_context)
        results = self.parallel([
            lambda: self.catalog.commit_inventory(reservation_id=held["id"]),
            lambda: self.catalog.release_inventory(reservation_id=held["id"]),
        ])
        self.assertEqual(sorted(result[0] for result in results), ["ok", "rejected"])
        reservation = apps.get_model("catalog", "InventoryReservation").objects.get(pk=held["id"])
        stock = Stock.objects.get(variant_id=self.variant_id)
        self.assertEqual(stock.reserved_quantity, 0)
        self.assertIn(reservation.state, {"committed", "released"})
        self.assertEqual(stock.quantity, 0 if reservation.state == "committed" else 1)

    def test_new_reserve_and_other_basket_release_keep_consistent_balances(self):
        Stock.objects.filter(variant_id=self.variant_id).update(quantity=2)
        _, second_id, _ = self.fixtures.product(stock="2")
        lines = [self.line(), self.line(second_id)]
        previous = self.catalog.reserve_inventory(intent_id=uuid4(), lines=lines, context=self.fixtures.buyer_context)
        current_id = uuid4()
        results = self.parallel([
            lambda: self.catalog.reserve_inventory(intent_id=current_id, lines=list(reversed(lines)), context=self.fixtures.other_context),
            lambda: self.catalog.release_inventory(reservation_id=previous["id"]),
        ])
        self.assertEqual([result[0] for result in results], ["ok", "ok"])
        self.assertEqual(results[0][1]["state"], "held")
        self.assertEqual(results[1][1]["state"], "released")
        self.assertTrue(all((stock.quantity, stock.reserved_quantity, stock.available_quantity) == (2, 1, 1) for stock in Stock.objects.all()))
