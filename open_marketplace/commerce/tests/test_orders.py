from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.apps import apps
from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.common.errors import ConcurrentConflict, InputRejected, PermissionDenied
from open_marketplace.commerce.models import CommerceOrder


class CommerceOrderTests(CatalogTestCase):
    def setUp(self):
        super().setUp()
        from open_marketplace.commerce import public

        self.commerce = public
        self.product_id, self.variant_id, _ = self.product(price="120", stock="2")
        self.intent_id = uuid4()

    def line(self, *, variant_id=None, quantity="1", price="120"):
        return {
            "variant_id": str(variant_id or self.variant_id),
            "quantity": quantity,
            "expected_unit_price": price,
        }

    def stock(self, variant_id=None):
        return apps.get_model("catalog", "Stock").objects.get(
            variant_id=variant_id or self.variant_id,
        )

    def make_buyer_context(self):
        account = self.create_account(kind="ordinary")
        registry = self.create_registry(account)
        self.catalog.set_participant(account_id=account.id, allowed=True, context=self.staff_context)
        return account, self.context(registry)

    def create(self, *, lines=None, intent_id=None, context=None):
        return self.commerce.create_order(
            intent_id=intent_id or self.intent_id,
            lines=lines if lines is not None else [self.line()],
            context=context or self.buyer_context,
        )

    def test_mixed_seller_order_persists_exact_snapshot_and_total(self):
        _, second_variant_id, _ = self.product(
            context=self.other_context,
            price="80",
            stock="3",
            title="Шарф",
        )
        result = self.create(
            lines=[self.line(), self.line(variant_id=second_variant_id, quantity="2", price="80")]
        )

        self.assertEqual(result["state"], "awaiting_payment")
        self.assertEqual(result["currency"], "RUB")
        self.assertEqual(result["total"], Decimal("280.00"))
        self.assertEqual(len(result["lines"]), 2)
        self.assertEqual(CommerceOrder.objects.count(), 1)
        self.assertEqual(apps.get_model("catalog", "InventoryReservation").objects.count(), 1)
        self.assertEqual(self.stock().reserved_quantity, 1)
        self.assertEqual(self.stock(second_variant_id).reserved_quantity, 2)

    def test_identical_retry_returns_one_order_and_one_reservation(self):
        first = self.create()
        second = self.create(lines=[self.line(price="120.00")])

        self.assertEqual(second, first)
        self.assertEqual(CommerceOrder.objects.count(), 1)
        self.assertEqual(apps.get_model("catalog", "InventoryReservation").objects.count(), 1)
        self.assertEqual(self.stock().reserved_quantity, 1)

    def test_snapshot_survives_catalog_price_and_listing_changes(self):
        first = self.create()
        self.catalog.set_offer(
            variant_id=self.variant_id,
            field="price",
            value="240",
            expected_version=1,
            context=self.seller_context,
        )
        self.catalog.withdraw_product(product_id=self.product_id, context=self.seller_context)

        self.assertEqual(self.create(), first)
        self.assertEqual(first["lines"][0]["unit_price"], "120.00")

    def test_changed_intent_body_is_rejected_without_mutation(self):
        self.create()

        with self.assertRaises(ConcurrentConflict):
            self.create(lines=[self.line(quantity="2")])
        self.assertEqual(CommerceOrder.objects.count(), 1)
        self.assertEqual(self.stock().reserved_quantity, 1)

    def test_failed_second_line_rolls_back_order_reservation_and_stock(self):
        _, second_variant_id, _ = self.product(
            context=self.other_context,
            price="80",
            stock="0",
            title="Шарф",
        )

        with self.assertRaises(InputRejected):
            self.create(
                lines=[self.line(), self.line(variant_id=second_variant_id, price="80")]
            )
        self.assertEqual(CommerceOrder.objects.count(), 0)
        self.assertEqual(apps.get_model("catalog", "InventoryReservation").objects.count(), 0)
        self.assertEqual(self.stock().reserved_quantity, 0)

    def test_different_buyer_cannot_reuse_intent(self):
        self.create()
        _, context = self.make_buyer_context()

        with self.assertRaises(PermissionDenied):
            self.create(context=context)
        self.assertEqual(CommerceOrder.objects.count(), 1)
        self.assertEqual(self.stock().reserved_quantity, 1)

    def test_cancel_releases_awaiting_payment_order_once(self):
        created = self.create()

        cancelled = self.commerce.cancel_order(order_id=created["id"], context=self.buyer_context)
        repeated = self.commerce.cancel_order(order_id=created["id"], context=self.buyer_context)

        self.assertEqual(cancelled["state"], "cancelled")
        self.assertEqual(repeated, cancelled)
        self.assertEqual(self.stock().reserved_quantity, 0)
        self.assertEqual(self.stock().quantity, 2)

    def test_cancel_does_not_allow_paid_order_shortcut(self):
        created = self.create()
        CommerceOrder.objects.filter(pk=created["id"]).update(state="paid")

        with self.assertRaises(ConcurrentConflict):
            self.commerce.cancel_order(order_id=created["id"], context=self.buyer_context)
        self.assertEqual(self.stock().reserved_quantity, 1)

    def test_order_read_is_buyer_scoped_and_does_not_call_provider(self):
        created = self.create()
        other_buyer, context = self.make_buyer_context()

        with patch("open_marketplace.payments.tbank.TBankClient") as client:
            self.assertEqual(
                self.commerce.get_order(order_id=created["id"], context=self.buyer_context),
                created,
            )
            with self.assertRaises(PermissionDenied):
                self.commerce.get_order(order_id=created["id"], context=context)
            client.assert_not_called()
        self.assertEqual(other_buyer.kind, "ordinary")
