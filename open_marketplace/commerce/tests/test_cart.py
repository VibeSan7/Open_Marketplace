from decimal import Decimal
from uuid import uuid4

from django.apps import apps
from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.common.errors import ConcurrentConflict, InputRejected, PermissionDenied
from open_marketplace.commerce.models import CommerceCart, CommerceOrder
from open_marketplace.commerce.public import (
    add_commerce_cart_item,
    checkout_commerce_cart,
    get_commerce_cart,
    remove_commerce_cart_item,
    update_commerce_cart_item,
)


class CommerceCartTestCase(CatalogTestCase):
    def setUp(self):
        super().setUp()
        self.product_id, self.variant_id, _ = self.product()
        self.other_product_id, self.other_variant_id, _ = self.product(
            context=self.other_context,
            title="Шарф",
            price="30",
            stock="4",
            color="Синий",
            size="M",
        )

    def test_add_and_update_keep_server_snapshot(self):
        cart = add_commerce_cart_item(
            variant_id=self.variant_id,
            quantity="1",
            context=self.buyer_context,
        )
        self.assertEqual(cart["items"][0]["quantity"], Decimal("1"))
        self.assertEqual(cart["items"][0]["unit_price"], Decimal("120.00"))
        updated = update_commerce_cart_item(
            variant_id=self.variant_id,
            quantity="2",
            context=self.buyer_context,
        )
        self.assertEqual(updated["items"][0]["quantity"], Decimal("2"))
        self.assertEqual(updated["total"], Decimal("240.00"))

    def test_add_rejects_seller_and_insufficient_quantity(self):
        with self.assertRaises(PermissionDenied):
            add_commerce_cart_item(variant_id=self.variant_id, quantity="1", context=self.seller_context)
        with self.assertRaises(InputRejected):
            add_commerce_cart_item(variant_id=self.variant_id, quantity="3", context=self.buyer_context)

    def test_cart_revalidates_changed_price_before_checkout(self):
        add_commerce_cart_item(variant_id=self.variant_id, quantity="1", context=self.buyer_context)
        variant = self.catalog.get_own_product(product_id=self.product_id, context=self.seller_context)["variants"][0]
        self.catalog.set_offer(
            variant_id=self.variant_id,
            field="price",
            value="125",
            expected_version=variant["price_version"],
            context=self.seller_context,
        )
        view = get_commerce_cart(context=self.buyer_context)
        self.assertFalse(view["checkout_available"])
        with self.assertRaises(ConcurrentConflict):
            checkout_commerce_cart(intent_id=view["intent_id"], context=self.buyer_context)

    def test_checkout_creates_one_multiseller_order_and_is_idempotent(self):
        add_commerce_cart_item(variant_id=self.variant_id, quantity="1", context=self.buyer_context)
        add_commerce_cart_item(variant_id=self.other_variant_id, quantity="2", context=self.buyer_context)
        cart = get_commerce_cart(context=self.buyer_context)
        first = checkout_commerce_cart(intent_id=cart["intent_id"], context=self.buyer_context)
        second = checkout_commerce_cart(intent_id=cart["intent_id"], context=self.buyer_context)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["total"], Decimal("180.00"))
        order = CommerceOrder.objects.get(pk=first[0]["id"])
        self.assertEqual(len(order.lines), 2)
        reservation_model = apps.get_model("catalog", "InventoryReservation")
        self.assertEqual(reservation_model.objects.filter(buyer_id=self.buyer.id).count(), 1)
        self.assertEqual(CommerceCart.objects.get(buyer_id=self.buyer.id).items, [])

    def test_checkout_rejects_stale_intent_and_foreign_buyer(self):
        add_commerce_cart_item(variant_id=self.variant_id, quantity="1", context=self.buyer_context)
        stale = get_commerce_cart(context=self.buyer_context)["intent_id"]
        add_commerce_cart_item(variant_id=self.other_variant_id, quantity="1", context=self.buyer_context)
        with self.assertRaises(ConcurrentConflict):
            checkout_commerce_cart(intent_id=stale, context=self.buyer_context)
        foreign = self.create_account(kind="ordinary")
        foreign_context = self.context(self.create_registry(foreign))
        with self.assertRaises(ConcurrentConflict):
            checkout_commerce_cart(intent_id=stale, context=foreign_context)

    def test_remove_clears_line_and_empty_checkout_is_rejected(self):
        add_commerce_cart_item(variant_id=self.variant_id, quantity="1", context=self.buyer_context)
        view = remove_commerce_cart_item(variant_id=self.variant_id, context=self.buyer_context)
        self.assertEqual(view["items"], ())
        with self.assertRaises(InputRejected):
            checkout_commerce_cart(intent_id=view["intent_id"], context=self.buyer_context)
