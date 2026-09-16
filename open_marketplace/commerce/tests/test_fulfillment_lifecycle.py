from uuid import uuid4

from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.common.errors import InputRejected, InvalidState, PermissionDenied
from open_marketplace.commerce.models import CommerceOrder, FulfillmentEvent, FulfillmentShipment


class FulfillmentLifecycleTests(CatalogTestCase):
    def setUp(self):
        super().setUp()
        self.commerce = __import__("open_marketplace.commerce.public", fromlist=["public"])
        self.shipment_id = self.make_shipment("seller")

    def make_shipment(self, mode):
        _, variant_id, _ = self.product(price="120", stock="2")
        order = self.commerce.create_order(
            intent_id=uuid4(),
            lines=[{
                "variant_id": str(variant_id),
                "quantity": "1",
                "expected_unit_price": "120",
            }],
            context=self.buyer_context,
        )
        CommerceOrder.objects.filter(pk=order["id"]).update(state=CommerceOrder.State.PAID)
        plan = self.commerce.create_fulfillment_plan(
            order_id=order["id"],
            delivery_modes={order["lines"][0]["seller_account_id"]: mode},
            context=self.buyer_context,
        )
        return plan[0]["id"]

    def transition(self, target, *, context=None, shipment_id=None):
        return self.commerce.transition_fulfillment(
            shipment_id=shipment_id or self.shipment_id,
            target_state=target,
            context=context or self.seller_context,
        )

    def test_seller_delivery_can_progress_and_buyer_confirms_receipt(self):
        ready = self.transition(FulfillmentShipment.State.READY)
        self.assertEqual(ready["state"], "ready")
        self.assertEqual(self.transition(FulfillmentShipment.State.READY), ready)
        in_transit = self.transition(FulfillmentShipment.State.IN_TRANSIT)
        self.assertEqual(in_transit["state"], "in_transit")
        delivered = self.transition(
            FulfillmentShipment.State.DELIVERED,
            context=self.buyer_context,
        )
        self.assertEqual(delivered["state"], "delivered")
        self.assertEqual(
            list(FulfillmentEvent.objects.values_list("action", flat=True)),
            ["planned", "ready", "in_transit", "delivered"],
        )

    def test_cdek_cannot_be_marked_as_delivered_by_local_service(self):
        cdek_id = self.make_shipment("cdek")
        self.transition(
            FulfillmentShipment.State.READY,
            shipment_id=cdek_id,
        )
        with self.assertRaises(InvalidState):
            self.transition(
                FulfillmentShipment.State.IN_TRANSIT,
                shipment_id=cdek_id,
            )
        with self.assertRaises(InvalidState):
            self.transition(
                FulfillmentShipment.State.DELIVERED,
                context=self.buyer_context,
                shipment_id=cdek_id,
            )

    def test_transitions_reject_skips_reversals_and_wrong_actors(self):
        with self.assertRaises(InvalidState):
            self.transition(FulfillmentShipment.State.IN_TRANSIT)
        with self.assertRaises(PermissionDenied):
            self.transition(
                FulfillmentShipment.State.READY,
                context=self.buyer_context,
            )
        with self.assertRaises(PermissionDenied):
            self.transition(
                FulfillmentShipment.State.READY,
                context=self.other_context,
            )
        self.transition(FulfillmentShipment.State.READY)
        with self.assertRaises(PermissionDenied):
            self.transition(FulfillmentShipment.State.DELIVERED)
        self.transition(FulfillmentShipment.State.IN_TRANSIT)
        self.transition(FulfillmentShipment.State.DELIVERED, context=self.buyer_context)
        with self.assertRaises(InvalidState):
            self.transition(FulfillmentShipment.State.READY, context=self.seller_context)
        self.assertEqual(FulfillmentEvent.objects.count(), 4)

    def test_target_state_and_context_are_validated(self):
        with self.assertRaises(InputRejected):
            self.transition("unknown")
        foreign = self.create_account(kind="ordinary")
        foreign_context = self.context(self.create_registry(foreign))
        with self.assertRaises(PermissionDenied):
            self.transition(
                FulfillmentShipment.State.READY,
                context=foreign_context,
            )
