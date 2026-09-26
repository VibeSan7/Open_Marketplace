from uuid import uuid4

from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.common.errors import ConcurrentConflict, InputRejected, InvalidState, PermissionDenied
from open_marketplace.commerce.models import CommerceOrder, FulfillmentEvent, FulfillmentShipment


class PhysicalFulfillmentTests(CatalogTestCase):
    def setUp(self):
        super().setUp()
        from open_marketplace.commerce import public

        self.commerce = public
        self.product_id, self.variant_id, _ = self.product(price="120", stock="2")
        self.second_product_id, self.second_variant_id, _ = self.product(
            context=self.other_context,
            title="Шарф",
            price="80",
            stock="3",
        )
        self.order = self.commerce.create_order(
            intent_id=uuid4(),
            lines=[
                self.line(self.variant_id, price="120"),
                self.line(self.second_variant_id, price="80", quantity="2"),
            ],
            context=self.buyer_context,
        )
        CommerceOrder.objects.filter(pk=self.order["id"]).update(state=CommerceOrder.State.PAID)

    def line(self, variant_id, *, price, quantity="1"):
        return {
            "variant_id": str(variant_id),
            "quantity": quantity,
            "expected_unit_price": price,
        }

    def modes(self, first="cdek", second="seller"):
        return {
            self.order["lines"][0]["seller_account_id"]: first,
            self.order["lines"][1]["seller_account_id"]: second,
        }

    def plan(self, modes=None):
        return self.commerce.create_fulfillment_plan(
            order_id=self.order["id"],
            delivery_modes=modes or self.modes(),
            context=self.buyer_context,
        )

    def test_paid_multi_seller_order_creates_immutable_shipment_snapshots(self):
        result = self.plan()

        self.assertEqual(len(result), 2)
        self.assertEqual({row["delivery_mode"] for row in result}, {"cdek", "seller"})
        self.assertEqual({row["state"] for row in result}, {"pending"})
        self.assertEqual({len(row["client_reference"]) for row in result}, {26})
        self.assertEqual(FulfillmentShipment.objects.count(), 2)
        self.assertEqual(FulfillmentEvent.objects.count(), 2)
        self.assertEqual(sum(len(row["lines"]) for row in result), 2)
        by_seller = {row["seller_account_id"]: row for row in result}
        for line in self.order["lines"]:
            self.assertIn(line["seller_account_id"], by_seller)
            self.assertIn(line, by_seller[line["seller_account_id"]]["lines"])

    def test_replay_is_idempotent_and_conflicting_replay_is_rejected(self):
        first = self.plan()
        repeated = self.plan()

        self.assertEqual(repeated, first)
        self.assertEqual(FulfillmentShipment.objects.count(), 2)
        self.assertEqual(FulfillmentEvent.objects.count(), 2)

        with self.assertRaises(ConcurrentConflict):
            self.plan(self.modes(first="seller", second="seller"))
        self.assertEqual(FulfillmentShipment.objects.count(), 2)

    def test_delivery_mode_map_must_exactly_match_order_sellers(self):
        first_seller = self.order["lines"][0]["seller_account_id"]
        with self.assertRaises(InputRejected):
            self.plan({first_seller: "cdek"})
        with self.assertRaises(InputRejected):
            self.plan({**self.modes(), str(uuid4()): "seller"})
        with self.assertRaises(InputRejected):
            self.plan(self.modes(first="postal"))
        self.assertEqual(FulfillmentShipment.objects.count(), 0)

    def test_unpaid_order_cannot_create_shipment(self):
        CommerceOrder.objects.filter(pk=self.order["id"]).update(
            state=CommerceOrder.State.AWAITING_PAYMENT,
        )

        with self.assertRaises(InvalidState):
            self.plan()
        self.assertEqual(FulfillmentShipment.objects.count(), 0)

    def test_foreign_order_is_not_exposed(self):
        account = self.create_account(kind="ordinary")
        registry = self.create_registry(account)
        other_context = self.context(registry)

        with self.assertRaises(PermissionDenied):
            self.commerce.create_fulfillment_plan(
                order_id=self.order["id"],
                delivery_modes=self.modes(),
                context=other_context,
            )

    def test_plan_does_not_claim_address_fee_waybill_or_delivery(self):
        result = self.plan()

        self.assertTrue(all(set(row) == {
            "id", "order_id", "seller_account_id", "seller_profile_id", "delivery_mode",
            "client_reference", "lines", "packages", "state", "created_at", "updated_at",
        } for row in result))
        self.assertFalse(any("address" in row for row in result))
        self.assertFalse(any("waybill" in row for row in result))
        self.assertFalse(any("fee" in row for row in result))

    def test_seller_can_replace_pending_package_manifest_idempotently(self):
        result = self.plan()
        seller_row = next(row for row in result if row["seller_account_id"] == str(self.seller.id))
        packages = [{
            "weight_grams": 1000,
            "length_cm": 10,
            "width_cm": 10,
            "height_cm": 10,
        }]

        first = self.commerce.set_fulfillment_packages(
            shipment_id=seller_row["id"],
            packages=packages,
            context=self.seller_context,
        )
        repeated = self.commerce.set_fulfillment_packages(
            shipment_id=seller_row["id"],
            packages=packages,
            context=self.seller_context,
        )

        self.assertEqual(first, repeated)
        self.assertEqual(first["packages"], packages)
        self.assertEqual(
            FulfillmentShipment.objects.get(pk=seller_row["id"]).packages,
            packages,
        )

    def test_package_manifest_rejects_invalid_values_without_mutation(self):
        result = self.plan()
        seller_row = next(row for row in result if row["seller_account_id"] == str(self.seller.id))

        with self.assertRaises(InputRejected):
            self.commerce.set_fulfillment_packages(
                shipment_id=seller_row["id"],
                packages=[{"weight_grams": 0, "length_cm": 10, "width_cm": 10, "height_cm": 10}],
                context=self.seller_context,
            )
        with self.assertRaises(InputRejected):
            self.commerce.set_fulfillment_packages(
                shipment_id=seller_row["id"],
                packages=[{"weight_grams": 1000, "length_cm": 10, "width_cm": 10}],
                context=self.seller_context,
            )
        self.assertEqual(FulfillmentShipment.objects.get(pk=seller_row["id"]).packages, [])

    def test_package_manifest_is_seller_owned_and_pending_only(self):
        result = self.plan(self.modes(first="seller", second="seller"))
        seller_row = next(row for row in result if row["seller_account_id"] == str(self.seller.id))
        packages = [{
            "weight_grams": 1000,
            "length_cm": 10,
            "width_cm": 10,
            "height_cm": 10,
        }]
        foreign_context = self.context(self.create_registry(self.create_account(kind="ordinary")))

        with self.assertRaises(PermissionDenied):
            self.commerce.set_fulfillment_packages(
                shipment_id=seller_row["id"],
                packages=packages,
                context=foreign_context,
            )
        self.commerce.set_fulfillment_packages(
            shipment_id=seller_row["id"],
            packages=packages,
            context=self.seller_context,
        )
        self.commerce.transition_fulfillment(
            shipment_id=seller_row["id"],
            target_state=FulfillmentShipment.State.READY,
            context=self.seller_context,
        )
        with self.assertRaises(InvalidState):
            self.commerce.set_fulfillment_packages(
                shipment_id=seller_row["id"],
                packages=packages,
                context=self.seller_context,
            )

    def test_buyer_and_seller_can_read_only_their_shipments(self):
        result = self.plan(self.modes(first="seller", second="cdek"))
        seller_row = next(row for row in result if row["delivery_mode"] == "seller")
        seller_context = (
            self.seller_context
            if seller_row["seller_account_id"] == str(self.seller.id)
            else self.other_context
        )
        self.commerce.set_fulfillment_packages(
            shipment_id=seller_row["id"],
            packages=[{"weight_grams": 1000, "length_cm": 10, "width_cm": 10, "height_cm": 10}],
            context=seller_context,
        )
        self.commerce.transition_fulfillment(
            shipment_id=seller_row["id"],
            target_state=FulfillmentShipment.State.READY,
            context=seller_context,
        )
        self.commerce.transition_fulfillment(
            shipment_id=seller_row["id"],
            target_state=FulfillmentShipment.State.IN_TRANSIT,
            context=seller_context,
        )
        buyer_transition = self.commerce.transition_fulfillment(
            shipment_id=seller_row["id"],
            target_state=FulfillmentShipment.State.DELIVERED,
            context=self.buyer_context,
        )
        self.assertNotIn("packages", buyer_transition)
        own = self.commerce.list_fulfillment_shipments(context=self.buyer_context)
        self.assertEqual({row["id"] for row in own}, {row["id"] for row in result})
        other_row = next(row for row in result if row["id"] != seller_row["id"])
        seller = self.commerce.get_fulfillment_shipment(
            shipment_id=seller_row["id"],
            context=seller_context,
        )
        self.assertEqual(seller["id"], seller_row["id"])
        self.assertEqual(seller["packages"][0]["weight_grams"], 1000)
        self.assertNotIn("delivery_address", seller)
        buyer_row = next(row for row in own if row["id"] == seller_row["id"])
        self.assertNotIn("packages", buyer_row)
        with self.assertRaises(PermissionDenied):
            self.commerce.get_fulfillment_shipment(
                shipment_id=other_row["id"],
                context=seller_context,
            )

    def test_unknown_shipment_is_not_exposed(self):
        with self.assertRaises(PermissionDenied):
            self.commerce.get_fulfillment_shipment(
                shipment_id=uuid4(),
                context=self.buyer_context,
            )
