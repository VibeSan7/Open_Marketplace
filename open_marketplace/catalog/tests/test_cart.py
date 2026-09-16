from decimal import Decimal
from uuid import uuid4

from django.test import override_settings

from open_marketplace.catalog.models import Variant
from open_marketplace.demo_orders.models import DemoOrder
from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.common.errors import ConcurrentConflict, InputRejected, PermissionDenied


@override_settings(DEMO_ORDERS_ENABLED=True)
class CartPublicTests(CatalogTestCase):
    def setUp(self):
        super().setUp()
        self.first_product, self.first_variant, _ = self.product(title="Первая покупка", price="12.50")
        self.second_product, self.second_variant, _ = self.product(
            title="Вторая покупка", price="7.00", context=self.other_context,
        )

    def test_cart_persists_two_items_and_server_calculates_total(self):
        from open_marketplace.demo_orders import cart

        cart.add_cart_item(variant_id=self.first_variant, quantity="1", context=self.buyer_context)
        cart.add_cart_item(variant_id=self.second_variant, quantity="2", context=self.buyer_context)

        result = cart.get_cart(context=self.buyer_context)

        self.assertEqual(result["item_count"], 2)
        self.assertEqual(result["total"], Decimal("26.50"))
        self.assertEqual({item["variant_id"] for item in result["items"]}, {str(self.first_variant), str(self.second_variant)})
        self.assertTrue(result["checkout_available"])
        self.assertEqual(result["intent_id"], cart.get_cart(context=self.buyer_context)["intent_id"])

    def test_update_and_remove_change_revision_and_refresh_price_explicitly(self):
        from open_marketplace.demo_orders import cart

        cart.add_cart_item(variant_id=self.first_variant, quantity="1", context=self.buyer_context)
        Variant.objects.filter(pk=self.first_variant).update(price="15.00")
        stale = cart.get_cart(context=self.buyer_context)
        self.assertFalse(stale["checkout_available"])
        self.assertIn("изменилась", stale["items"][0]["message"])

        refreshed = cart.update_cart_item(variant_id=self.first_variant, quantity="2", context=self.buyer_context)
        self.assertEqual(refreshed["items"][0]["unit_price"], Decimal("15.00"))
        self.assertTrue(refreshed["checkout_available"])
        removed = cart.remove_cart_item(variant_id=self.first_variant, context=self.buyer_context)
        self.assertEqual(removed["items"], ())

    def test_checkout_is_atomic_and_repeat_returns_same_orders(self):
        from open_marketplace.demo_orders import cart

        cart.add_cart_item(variant_id=self.first_variant, quantity="1", context=self.buyer_context)
        cart.add_cart_item(variant_id=self.second_variant, quantity="1", context=self.buyer_context)
        intent_id = cart.get_cart(context=self.buyer_context)["intent_id"]

        orders = cart.checkout_cart(intent_id=intent_id, context=self.buyer_context)
        repeated = cart.checkout_cart(intent_id=intent_id, context=self.buyer_context)

        self.assertEqual([order["id"] for order in orders], [order["id"] for order in repeated])
        self.assertEqual(DemoOrder.objects.filter(buyer_id=self.buyer.id).count(), 2)
        self.assertEqual(cart.get_cart(context=self.buyer_context)["items"], ())

    def test_unavailable_second_item_rolls_back_first_reservation_and_orders(self):
        from open_marketplace.demo_orders import cart
        from open_marketplace.demo_orders.models import DemoInventory

        cart.add_cart_item(variant_id=self.first_variant, quantity="1", context=self.buyer_context)
        cart.add_cart_item(variant_id=self.second_variant, quantity="1", context=self.buyer_context)
        stock = self.catalog.get_own_product(product_id=self.second_product, context=self.other_context)["variants"][0]["stocks"][0]
        self.catalog.set_offer(
            variant_id=self.second_variant, field="stock", value="0", expected_version=stock["version"], context=self.other_context,
        )
        intent_id = cart.get_cart(context=self.buyer_context)["intent_id"]

        with self.assertRaises(PermissionDenied):
            cart.checkout_cart(intent_id=intent_id, context=self.buyer_context)

        self.assertEqual(DemoOrder.objects.filter(buyer_id=self.buyer.id).count(), 0)
        self.assertFalse(DemoInventory.objects.filter(variant_id=self.first_variant).exists())

    def test_invalid_quantity_self_purchase_and_disabled_write_are_rejected(self):
        from open_marketplace.demo_orders import cart

        with self.assertRaises(InputRejected):
            cart.add_cart_item(variant_id=self.first_variant, quantity="999999999999999999999", context=self.buyer_context)
        with self.assertRaises(PermissionDenied):
            cart.add_cart_item(variant_id=self.first_variant, quantity="1", context=self.seller_context)
        with override_settings(DEMO_ORDERS_ENABLED=False), self.assertRaises(PermissionDenied):
            cart.add_cart_item(variant_id=self.first_variant, quantity="1", context=self.buyer_context)

    def test_price_or_revision_change_blocks_checkout_without_creating_orders(self):
        from open_marketplace.demo_orders import cart

        before = cart.add_cart_item(variant_id=self.first_variant, quantity="1", context=self.buyer_context)
        Variant.objects.filter(pk=self.first_variant).update(price="99.00")
        with self.assertRaises(ConcurrentConflict):
            cart.checkout_cart(intent_id=before["intent_id"], context=self.buyer_context)
        updated = cart.update_cart_item(variant_id=self.first_variant, quantity="1", context=self.buyer_context)
        with self.assertRaises(ConcurrentConflict):
            cart.checkout_cart(intent_id=before["intent_id"], context=self.buyer_context)
        self.assertFalse(DemoOrder.objects.exists())
        order, = cart.checkout_cart(intent_id=updated["intent_id"], context=self.buyer_context)
        self.assertEqual(order["total"], Decimal("99.00"))

    def test_fractional_free_offer_is_owned_by_buyer_and_rejects_invalid_precision(self):
        from open_marketplace.demo_orders import cart

        _, variant, _ = self.product(unit="kg", price="0", stock="1")
        for quantity in ("1e-1", "NaN", "-1", "0", "0.0001"):
            with self.subTest(quantity=quantity), self.assertRaises(InputRejected):
                cart.add_cart_item(variant_id=variant, quantity=quantity, context=self.buyer_context)
        result = cart.add_cart_item(variant_id=variant, quantity="0,125", context=self.buyer_context)
        self.assertEqual(result["total"], Decimal("0.00"))
        self.assertEqual(cart.get_cart(context=self.other_context)["items"], ())
        with self.assertRaises(PermissionDenied):
            cart.update_cart_item(variant_id=variant, quantity="1", context=self.other_context)
        order, = cart.checkout_cart(intent_id=result["intent_id"], context=self.buyer_context)
        self.assertEqual(order["quantity"], Decimal("0.125"))
        self.assertEqual(order["total"], Decimal("0.00"))
