from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

from django.apps import apps
from django.db import IntegrityError, transaction

from open_marketplace.catalog.models import Stock, Variant
from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.common.errors import ConcurrentConflict, InputRejected, PermissionDenied


class InventoryReservationTests(CatalogTestCase):
    def setUp(self):
        super().setUp()
        for name in ("reserve_inventory", "commit_inventory", "release_inventory"):
            self.assertTrue(callable(getattr(self.catalog, name, None)), f"Missing real inventory operation: {name}")
        self.product_id, self.variant_id, _ = self.product()
        self.intent_id = uuid4()

    def reserve(self, *, lines=None, intent_id=None, context=None):
        return self.catalog.reserve_inventory(
            intent_id=intent_id or self.intent_id,
            lines=lines if lines is not None else [self.line()],
            context=context or self.buyer_context,
        )

    def line(self, *, variant_id=None, quantity="1", price="120"):
        return {"variant_id": str(variant_id or self.variant_id), "quantity": quantity, "expected_unit_price": price}

    def stock(self, variant_id=None):
        return Stock.objects.get(variant_id=variant_id or self.variant_id)

    def test_reserve_holds_real_stock_without_selling_it(self):
        held = self.reserve()
        stock = self.stock()
        self.assertEqual(stock.quantity, Decimal("2"))
        self.assertEqual(stock.reserved_quantity, Decimal("1"))
        self.assertEqual(stock.available_quantity, Decimal("1"))
        self.assertEqual(stock.version, 2)
        self.assertEqual(held["state"], "held")
        self.assertEqual(held["buyer_id"], str(self.buyer.id))
        self.assertEqual(held["lines"][0]["product_id"], str(self.product_id))
        self.assertEqual(held["lines"][0]["seller_profile_id"], str(Variant.objects.get(pk=self.variant_id).product.seller_id))
        self.assertEqual(held["lines"][0]["unit_price"], "120.00")
        self.assertEqual(held["lines"][0]["quantity"], "1")
        self.assertEqual(held["lines"][0]["unit"], "pc")

    def test_identical_retry_has_one_effect(self):
        first = self.reserve()
        second = self.reserve(lines=[self.line(price="120.00")])
        self.assertEqual(second, first)
        self.assertEqual(self.stock().reserved_quantity, Decimal("1"))
        self.assertEqual(apps.get_model("catalog", "InventoryReservation").objects.count(), 1)
        self.assertEqual(apps.get_model("catalog", "InventoryAllocation").objects.count(), 1)

    def test_retry_returns_original_snapshot_after_offer_changes(self):
        held = self.reserve()
        self.catalog.set_offer(variant_id=self.variant_id, field="price", value="240", expected_version=1, context=self.seller_context)
        self.catalog.withdraw_product(product_id=self.product_id, context=self.seller_context)
        self.assertEqual(self.reserve(), held)
        self.assertEqual(self.stock().reserved_quantity, Decimal("1"))

    def test_retry_cannot_change_quantity_or_price(self):
        self.reserve()
        for line in (self.line(quantity="2"), self.line(price="121")):
            with self.subTest(line=line), self.assertRaises(ConcurrentConflict):
                self.reserve(lines=[line])
        self.assertEqual(self.stock().reserved_quantity, Decimal("1"))

    def test_another_buyer_cannot_reuse_intent(self):
        self.reserve()
        with self.assertRaises(PermissionDenied):
            self.reserve(context=self.other_context)
        self.assertEqual(self.stock().reserved_quantity, Decimal("1"))

    def test_stale_price_has_no_reservation_or_stock_effect(self):
        with self.assertRaises(ConcurrentConflict):
            self.reserve(lines=[self.line(price="119.99")])
        self.assertEqual(self.stock().reserved_quantity, 0)
        self.assertFalse(apps.get_model("catalog", "InventoryReservation").objects.exists())

    def test_unavailable_or_invalid_second_line_rolls_back_entire_basket(self):
        _, second_id, _ = self.product(context=self.other_context, stock="0")
        with self.assertRaises(InputRejected):
            self.reserve(lines=[self.line(), self.line(variant_id=second_id)])
        self.assertEqual(self.stock().reserved_quantity, 0)
        self.assertFalse(apps.get_model("catalog", "InventoryReservation").objects.exists())
        self.assertFalse(apps.get_model("catalog", "InventoryAllocation").objects.exists())

    def test_multiple_sellers_and_line_order_have_one_stable_intent(self):
        _, second_id, _ = self.product(context=self.other_context, stock="3")
        lines = [self.line(), self.line(variant_id=second_id, quantity="2")]
        held = self.reserve(lines=lines)
        self.assertEqual(self.reserve(lines=list(reversed(lines))), held)
        self.assertEqual(self.stock().reserved_quantity, 1)
        self.assertEqual(self.stock(second_id).reserved_quantity, 2)
        self.assertEqual(len(held["lines"]), 2)

    def test_stock_is_allocated_and_released_at_original_locations(self):
        location = self.catalog.create_location(name="Второй склад", context=self.seller_context)
        self.catalog.set_offer(variant_id=self.variant_id, field="stock", value="3", expected_version=0, context=self.seller_context, location_id=location)
        held = self.reserve(lines=[self.line(quantity="5")])
        stocks = list(Stock.objects.filter(variant_id=self.variant_id))
        self.assertEqual(sum(row.reserved_quantity for row in stocks), 5)
        self.assertTrue(all(row.available_quantity == 0 for row in stocks))
        self.catalog.release_inventory(reservation_id=held["id"])
        self.assertTrue(all(row.reserved_quantity == 0 for row in Stock.objects.filter(variant_id=self.variant_id)))
        self.assertEqual(Stock.objects.get(variant_id=self.variant_id, location_id=location).quantity, 3)

    def test_fractional_weight_is_exact(self):
        _, variant_id, _ = self.product(unit="kg", stock="1.250", price="199.95")
        held = self.reserve(lines=[self.line(variant_id=variant_id, quantity="0.125", price="199.95")])
        self.assertEqual(self.stock(variant_id).available_quantity, Decimal("1.125"))
        self.assertEqual(held["lines"][0]["quantity"], "0.125")

    def test_rejects_nonpositive_fractional_piece_and_nonfinite_quantities(self):
        for value in ("0", "-1", "0.5", "1e0", "NaN", Decimal("Infinity"), True, 1.0):
            with self.subTest(value=value), self.assertRaises(InputRejected):
                self.reserve(lines=[self.line(quantity=value)])
        self.assertEqual(self.stock().reserved_quantity, 0)

    def test_rejects_invalid_request_shapes_and_duplicate_variants(self):
        for lines in ([], {}, [self.line(), self.line()], [{**self.line(), "seller_id": str(uuid4())}], [None]):
            with self.subTest(lines=lines), self.assertRaises(InputRejected):
                self.reserve(lines=lines)
        with self.assertRaises(InputRejected):
            self.reserve(intent_id="not-an-id")
        self.assertEqual(self.stock().reserved_quantity, 0)

    def test_buyer_session_and_catalog_visibility_are_required(self):
        with self.assertRaises(PermissionDenied):
            self.reserve(context=replace(self.buyer_context, session_id=None))
        self.catalog.set_participant(account_id=self.buyer.id, allowed=False, context=self.staff_context)
        with self.assertRaises(PermissionDenied):
            self.reserve()
        self.assertEqual(self.stock().reserved_quantity, 0)

    def test_public_product_does_not_require_private_catalog_membership(self):
        self.catalog.set_public_listing(product_id=self.product_id, enabled=True, context=self.seller_context)
        self.catalog.set_participant(account_id=self.buyer.id, allowed=False, context=self.staff_context)
        self.assertEqual(self.reserve()["state"], "held")

    def test_self_purchase_and_withdrawn_variants_are_rejected(self):
        with self.assertRaises(PermissionDenied):
            self.reserve(context=self.seller_context)
        self.catalog.withdraw_variant(variant_id=self.variant_id, context=self.seller_context)
        with self.assertRaises(PermissionDenied):
            self.reserve()
        self.assertEqual(self.stock().reserved_quantity, 0)

    def test_seller_cannot_set_on_hand_below_reserved(self):
        self.reserve()
        with self.assertRaises(InputRejected):
            self.catalog.set_offer(variant_id=self.variant_id, field="stock", value="0", expected_version=2, context=self.seller_context)
        self.assertEqual(self.stock().quantity, 2)
        with self.assertRaises(ConcurrentConflict):
            self.catalog.set_offer(variant_id=self.variant_id, field="stock", value="3", expected_version=1, context=self.seller_context)

    def test_all_held_stock_is_unavailable_to_buyer_and_demo_snapshot(self):
        self.reserve(lines=[self.line(quantity="2")])
        card = self.catalog.get_product(product_id=self.product_id, variant_id=self.variant_id, context=self.buyer_context)
        self.assertFalse(card["selected_variant"]["in_stock"])
        with self.assertRaises(PermissionDenied):
            self.catalog.get_demo_offer_snapshot(variant_id=self.variant_id, context=self.buyer_context)
        with self.assertRaises(InputRejected):
            self.reserve(intent_id=uuid4())

    def test_commit_consumes_stock_once_and_cannot_be_released(self):
        held = self.reserve()
        committed = self.catalog.commit_inventory(reservation_id=held["id"])
        self.assertEqual(committed["state"], "committed")
        self.assertEqual(self.catalog.commit_inventory(reservation_id=held["id"]), committed)
        with self.assertRaises(ConcurrentConflict):
            self.catalog.release_inventory(reservation_id=held["id"])
        stock = self.stock()
        self.assertEqual((stock.quantity, stock.reserved_quantity, stock.available_quantity), (1, 0, 1))
        self.assertEqual(self.reserve(), committed)

    def test_release_preserves_on_hand_once_and_cannot_be_committed(self):
        held = self.reserve()
        released = self.catalog.release_inventory(reservation_id=held["id"])
        self.assertEqual(released["state"], "released")
        self.assertEqual(self.catalog.release_inventory(reservation_id=held["id"]), released)
        with self.assertRaises(ConcurrentConflict):
            self.catalog.commit_inventory(reservation_id=held["id"])
        stock = self.stock()
        self.assertEqual((stock.quantity, stock.reserved_quantity, stock.available_quantity), (2, 0, 2))
        self.assertEqual(self.reserve(), released)

    def test_database_rejects_invalid_reserved_balance(self):
        for quantity, reserved in ((2, -1), (2, 3), (None, 1)):
            with self.subTest(quantity=quantity, reserved=reserved), self.assertRaises(IntegrityError), transaction.atomic():
                Stock.objects.filter(pk=self.stock().id).update(quantity=quantity, reserved_quantity=reserved)
