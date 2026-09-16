from decimal import Decimal
from uuid import uuid4

from django.test import override_settings
from django.urls import reverse

from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.catalog.tests import test_web
from open_marketplace.common.errors import InputRejected
from open_marketplace.demo_orders import public as orders


class DemoIntegrationTests(CatalogTestCase):
    client_for = test_web.CatalogWebTests.client_for

    def setUp(self):
        super().setUp()
        self.product_id, self.variant_id, self.location_id = self.product(title="Тестовая покупка")
        self.client = self.client_for(self.buyer_registry)

    def test_disabled_feature_has_no_order_navigation(self):
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, 'href="/demo-orders/"')
        response = self.client.get(reverse("catalog-product", kwargs={"product_id": self.product_id}))
        self.assertNotContains(response, "Создать тестовый заказ")

    @override_settings(DEMO_ORDERS_ENABLED=True)
    def test_enabled_navigation_and_selected_offer_checkout(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'href="/demo-orders/"')
        response = self.client.get(reverse("catalog-product", kwargs={"product_id": self.product_id}))
        self.assertContains(response, reverse("demo-order-create", kwargs={"variant_id": self.variant_id}))

    @override_settings(DEMO_ORDERS_ENABLED=True)
    def test_nonfinite_decimal_is_rejected_without_order(self):
        for value in (Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity")):
            with self.subTest(value=str(value)), self.assertRaises(InputRejected):
                orders.create_order(variant_id=self.variant_id, quantity=value, intent_id=uuid4(), context=self.buyer_context)

    @override_settings(DEMO_ORDERS_ENABLED=True)
    def test_fractional_paid_cancellation_restores_simulation_only(self):
        for unit in ("kg", "m"):
            product_id, variant_id, _ = self.product(unit=unit, price="10", stock="0.003")
            order = orders.create_order(variant_id=variant_id, quantity="0.001", intent_id=uuid4(), context=self.buyer_context)
            self.assertEqual(order["total"], Decimal("0.01"))
            orders.act_on_order(order_id=order["id"], action="simulate_success", context=self.buyer_context)
            for _ in range(2):
                result = orders.act_on_order(order_id=order["id"], action="cancel", context=self.buyer_context)
                self.assertEqual(result["simulated_payment_status"], "refunded")
            seller = orders.get_order(order_id=order["id"], context=self.seller_context)
            self.assertEqual(seller["simulated_remaining_quantity"], Decimal("0.003"))
            catalog = self.catalog.get_own_product(product_id=product_id, context=self.seller_context)
            self.assertEqual(catalog["variants"][0]["stocks"][0]["quantity"], Decimal("0.003"))

    @override_settings(DEMO_ORDERS_ENABLED=True)
    def test_stock_withdrawal_blocks_new_orders_but_keeps_history(self):
        from open_marketplace.common.errors import PermissionDenied
        first = orders.create_order(variant_id=self.variant_id, quantity="1", intent_id=uuid4(), context=self.buyer_context)
        own = self.catalog.get_own_product(product_id=self.product_id, context=self.seller_context)
        stock = own["variants"][0]["stocks"][0]
        self.catalog.set_offer(variant_id=self.variant_id, field="stock", value="0", expected_version=stock["version"], context=self.seller_context)
        with self.assertRaises(PermissionDenied):
            orders.create_order(variant_id=self.variant_id, quantity="1", intent_id=uuid4(), context=self.buyer_context)
        with self.assertRaises(PermissionDenied):
            orders.get_offer_preview(variant_id=self.variant_id, context=self.buyer_context)
        self.assertEqual(orders.get_order(order_id=first["id"], context=self.buyer_context)["id"], first["id"])
        self.assertEqual(orders.act_on_order(order_id=first["id"], action="cancel", context=self.buyer_context)["state"], "cancelled")

    @override_settings(DEMO_ORDERS_ENABLED=True)
    def test_large_valid_values_keep_exact_total(self):
        _, variant_id, _ = self.product(price="9999999999999999.99", stock="9999999999999999")
        order = orders.create_order(variant_id=variant_id, quantity="9999999999999999", intent_id=uuid4(), context=self.buyer_context)
        from decimal import localcontext
        with localcontext() as precision:
            precision.prec = 40
            expected = Decimal("9999999999999999.99") * Decimal("9999999999999999")
        self.assertEqual(order["total"], expected)
        stored = orders.get_order(order_id=order["id"], context=self.buyer_context)
        self.assertEqual(stored["total"], expected)

    @override_settings(DEMO_ORDERS_ENABLED=True)
    def test_repeated_action_still_requires_its_actor_role(self):
        from open_marketplace.common.errors import PermissionDenied
        order = orders.create_order(variant_id=self.variant_id, quantity="1", intent_id=uuid4(), context=self.buyer_context)
        orders.act_on_order(order_id=order["id"], action="simulate_success", context=self.buyer_context)
        with self.assertRaises(PermissionDenied):
            orders.act_on_order(order_id=order["id"], action="simulate_success", context=self.seller_context)

    @override_settings(DEMO_ORDERS_ENABLED=True)
    def test_buyers_cannot_read_stock_counts_via_demo_dtos(self):
        order = orders.create_order(variant_id=self.variant_id, quantity="1", intent_id=uuid4(), context=self.buyer_context)
        self.assertIsNone(order.get("simulated_remaining_quantity"))
        self.assertIsNone(orders.get_order(order_id=order["id"], context=self.buyer_context).get("simulated_remaining_quantity"))
        self.assertIsNone(orders.get_offer_preview(variant_id=self.variant_id, context=self.buyer_context).get("simulated_remaining_quantity"))
        self.assertNotIn("hand_over", order["available_actions"])
