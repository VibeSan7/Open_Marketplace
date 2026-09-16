from uuid import uuid4

from django.test import Client, override_settings

from open_marketplace.catalog.models import Stock, Variant
from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.catalog.tests import test_web
from open_marketplace.common.errors import ConcurrentConflict, InputRejected, PermissionDenied


@override_settings(DEMO_ORDERS_ENABLED=True)
class DemoOrdersPublicTests(CatalogTestCase):
    client_for = test_web.CatalogWebTests.client_for

    def setUp(self):
        super().setUp()
        _, variant_id, _ = self.product(title="Тёплая куртка", price="12.50")
        self.variant = Variant.objects.get(pk=variant_id)
        self.original_variant_label = self.variant.published["label"]

    def test_create_decline_then_success_does_not_deduct_twice(self):
        from open_marketplace.demo_orders import public

        first = public.create_order(
            variant_id=self.variant.id,
            quantity="1",
            intent_id=uuid4(),
            context=self.buyer_context,
        )
        self.assertEqual(first["state"], "pending")
        self.assertEqual(first["simulated_payment_status"], "pending")
        declined = public.act_on_order(order_id=first["id"], action="simulate_decline", context=self.buyer_context)
        self.assertEqual(declined["state"], "pending")
        self.assertEqual(declined["simulated_payment_status"], "declined")
        second = public.create_order(
            variant_id=self.variant.id,
            quantity="1",
            intent_id=first["intent_id"],
            context=self.buyer_context,
        )
        self.assertEqual(second["id"], first["id"])
        paid = public.act_on_order(order_id=first["id"], action="simulate_success", context=self.buyer_context)
        self.assertEqual(paid["state"], "paid")

    def test_same_intent_with_changed_payload_is_conflict(self):
        from open_marketplace.demo_orders import public

        intent_id = uuid4()
        public.create_order(variant_id=self.variant.id, quantity="1", intent_id=intent_id, context=self.buyer_context)
        with self.assertRaises(ConcurrentConflict):
            public.create_order(variant_id=self.variant.id, quantity="2", intent_id=intent_id, context=self.buyer_context)

    def test_pending_cancellation_restores_simulated_inventory_exactly_once(self):
        from open_marketplace.demo_orders import public
        from open_marketplace.demo_orders.models import DemoInventory, DemoOrderEvent

        order = public.create_order(variant_id=self.variant.id, quantity="1", intent_id=uuid4(), context=self.buyer_context)
        public.act_on_order(order_id=order["id"], action="cancel", context=self.buyer_context)
        public.act_on_order(order_id=order["id"], action="cancel", context=self.buyer_context)
        self.assertEqual(DemoInventory.objects.get(variant_id=self.variant.id).quantity, 2)
        self.assertEqual(DemoOrderEvent.objects.filter(order_id=order["id"]).count(), 2)

    def test_disabled_public_write_is_rejected(self):
        from open_marketplace.demo_orders import public

        with override_settings(DEMO_ORDERS_ENABLED=False), self.assertRaises(PermissionDenied):
            public.create_order(
                variant_id=self.variant.id,
                quantity="1",
                intent_id=uuid4(),
                context=self.buyer_context,
            )

    def test_self_purchase_and_invalid_quantity_are_rejected_without_catalog_mutation(self):
        from open_marketplace.demo_orders import public

        before = (self.variant.price, Stock.objects.get(variant_id=self.variant.id).quantity)
        with self.assertRaises(PermissionDenied):
            public.create_order(
                variant_id=self.variant.id,
                quantity="1",
                intent_id=uuid4(),
                context=self.seller_context,
            )
        with self.assertRaises(InputRejected):
            public.create_order(
                variant_id=self.variant.id,
                quantity="1.00",
                intent_id=uuid4(),
                context=self.buyer_context,
            )
        self.assertEqual(before, (self.variant.price, Stock.objects.get(variant_id=self.variant.id).quantity))

    def test_seller_can_hand_over_buyer_can_complete_and_snapshot_is_immutable(self):
        from open_marketplace.demo_orders import public

        order = public.create_order(variant_id=self.variant.id, quantity="1", intent_id=uuid4(), context=self.buyer_context)
        public.act_on_order(order_id=order["id"], action="simulate_success", context=self.buyer_context)
        handed = public.act_on_order(order_id=order["id"], action="hand_over", context=self.seller_context)
        completed = public.act_on_order(order_id=order["id"], action="complete", context=self.buyer_context)
        self.assertEqual(handed["state"], "handed_over")
        self.assertEqual(completed["state"], "completed")
        Variant.objects.filter(pk=self.variant.id).update(price="99.99", published={"label": "Новое", "attributes": {}, "photo_ids": []})
        current = public.get_order(order_id=order["id"], context=self.buyer_context)
        self.assertEqual(str(current["unit_price"]), "12.50")
        self.assertEqual(current["variant_label"], self.original_variant_label)

    def test_foreign_and_unknown_reads_are_identical(self):
        from open_marketplace.demo_orders import public

        order = public.create_order(variant_id=self.variant.id, quantity="1", intent_id=uuid4(), context=self.buyer_context)
        foreign_context = self.other_context
        with self.assertRaises(PermissionDenied) as foreign_error:
            public.get_order(order_id=order["id"], context=foreign_context)
        with self.assertRaises(PermissionDenied) as unknown_error:
            public.get_order(order_id=uuid4(), context=foreign_context)
        self.assertEqual(str(foreign_error.exception), str(unknown_error.exception))

    def test_disabled_http_routes_return_404_before_login(self):
        with override_settings(DEMO_ORDERS_ENABLED=False):
            response = Client().get("/demo-orders/")
        self.assertEqual(response.status_code, 404)

    def test_foreign_and_unknown_web_reads_are_identical_without_form_or_csrf(self):
        from open_marketplace.demo_orders import public

        order = public.create_order(variant_id=self.variant.id, quantity="1", intent_id=uuid4(), context=self.buyer_context)
        foreign = self.other
        response = self.client_for(self.other_registry).get(f"/demo-orders/{order['id']}/")
        unknown = self.client_for(self.other_registry).get(f"/demo-orders/{uuid4()}/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.content, unknown.content)
        self.assertNotContains(response, 'method="post"', status_code=403)
        self.assertNotContains(response, "csrfmiddlewaretoken", status_code=403)

    def test_create_page_has_csrf_and_action_without_csrf_is_rejected(self):
        from open_marketplace.demo_orders import public

        client = self.client_for(self.buyer_registry)
        page = client.get(f"/demo-orders/new/{self.variant.id}/")
        self.assertContains(page, "Тестовый заказ — реальные деньги не списываются.")
        self.assertContains(page, "csrfmiddlewaretoken")
        order = public.create_order(
            variant_id=self.variant.id,
            quantity="1",
            intent_id=uuid4(),
            context=self.buyer_context,
        )
        rejected = client.post(f"/demo-orders/{order['id']}/action/", {"action": "simulate_success"})
        self.assertEqual(rejected.status_code, 403)
