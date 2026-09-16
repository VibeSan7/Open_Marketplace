from unittest.mock import patch
from uuid import uuid4

from django.apps import apps

from open_marketplace.catalog.tests.fixtures import CatalogTestCase
from open_marketplace.common.errors import ConcurrentConflict, InputRejected, PermissionDenied
from open_marketplace.commerce.models import PaymentEvent, PaymentIntent


class PaymentLedgerTests(CatalogTestCase):
    def setUp(self):
        super().setUp()
        from open_marketplace.commerce import public

        self.commerce = public
        _, self.variant_id, _ = self.product(price="120", stock="1")
        self.order = self.commerce.create_order(
            intent_id=uuid4(),
            lines=[{
                "variant_id": str(self.variant_id),
                "quantity": "1",
                "expected_unit_price": "120",
            }],
            context=self.buyer_context,
        )

    def prepare(self):
        return self.commerce.prepare_payment(
            order_id=self.order["id"],
            context=self.buyer_context,
        )

    def bind(self, payment, *, payment_id="pay-1", deal_id="12345"):
        return self.commerce.bind_tbank_reference(
            order_id=self.order["id"],
            payment_id=payment_id,
            deal_id=deal_id,
        )

    def notice(self, payment, *, status="CONFIRMED", amount=12000, success=True):
        return {
            "order_id": payment["provider_order_id"],
            "payment_id": payment["payment_id"],
            "deal_id": payment["deal_id"],
            "amount": amount,
            "status": status,
            "success": success,
        }

    def stock(self):
        return apps.get_model("catalog", "Stock").objects.get(variant_id=self.variant_id)

    def test_prepare_persists_exact_amount_and_is_idempotent_without_provider_call(self):
        with patch("open_marketplace.payments.tbank.TBankClient") as client:
            first = self.prepare()
            second = self.prepare()
            client.assert_not_called()

        self.assertEqual(first, second)
        self.assertEqual(first["amount_kopecks"], 12000)
        self.assertEqual(first["currency"], "RUB")
        self.assertEqual(first["state"], "pending")
        self.assertEqual(PaymentIntent.objects.count(), 1)

    def test_binding_provider_reference_is_stable(self):
        payment = self.prepare()
        first = self.bind(payment)
        second = self.bind(payment, payment_id="pay-1", deal_id="12345")

        self.assertEqual(first, second)
        self.assertEqual(first["payment_id"], "pay-1")
        self.assertEqual(first["deal_id"], "12345")

    def test_conflicting_reference_or_amount_is_rejected(self):
        payment = self.prepare()
        self.bind(payment)

        with self.assertRaises(ConcurrentConflict):
            self.bind(payment, payment_id="pay-2")
        with self.assertRaises(InputRejected):
            self.commerce.apply_verified_tbank_notice(
                order_id=self.order["id"],
                notice=self.notice(payment, amount=11999),
            )
        self.assertEqual(PaymentEvent.objects.count(), 0)

    def test_authorized_notification_keeps_reservation_held(self):
        payment = self.bind(self.prepare())

        result = self.commerce.apply_verified_tbank_notice(
            order_id=self.order["id"],
            notice=self.notice(payment, status="AUTHORIZED"),
        )

        self.assertEqual(result["payment_state"], "authorized")
        self.assertEqual(result["order_state"], "awaiting_payment")
        self.assertEqual(self.stock().reserved_quantity, 1)

    def test_confirmed_notification_commits_inventory_once(self):
        payment = self.bind(self.prepare())

        result = self.commerce.apply_verified_tbank_notice(
            order_id=self.order["id"],
            notice=self.notice(payment),
        )
        repeated = self.commerce.apply_verified_tbank_notice(
            order_id=self.order["id"],
            notice=self.notice(payment),
        )

        self.assertEqual(result, repeated)
        self.assertEqual(result["payment_state"], "confirmed")
        self.assertEqual(result["order_state"], "paid")
        self.assertEqual(self.stock().reserved_quantity, 0)
        self.assertEqual(self.stock().quantity, 0)
        self.assertEqual(PaymentEvent.objects.count(), 1)

    def test_stale_authorized_notification_cannot_downgrade_confirmed_payment(self):
        payment = self.bind(self.prepare())
        self.commerce.apply_verified_tbank_notice(
            order_id=self.order["id"],
            notice=self.notice(payment),
        )

        result = self.commerce.apply_verified_tbank_notice(
            order_id=self.order["id"],
            notice=self.notice(payment, status="AUTHORIZED"),
        )

        self.assertEqual(result["payment_state"], "confirmed")
        self.assertEqual(result["order_state"], "paid")
        self.assertEqual(self.stock().quantity, 0)
        self.assertEqual(PaymentEvent.objects.count(), 2)

    def test_rejected_notification_releases_pre_payment_reservation(self):
        payment = self.bind(self.prepare())

        result = self.commerce.apply_verified_tbank_notice(
            order_id=self.order["id"],
            notice=self.notice(payment, status="REJECTED", success=False),
        )

        self.assertEqual(result["payment_state"], "rejected")
        self.assertEqual(result["order_state"], "cancelled")
        self.assertEqual(self.stock().reserved_quantity, 0)
        self.assertEqual(self.stock().quantity, 1)

    def test_reversed_authorization_releases_pre_payment_reservation(self):
        payment = self.bind(self.prepare())
        self.commerce.apply_verified_tbank_notice(
            order_id=self.order["id"],
            notice=self.notice(payment, status="AUTHORIZED"),
        )

        result = self.commerce.apply_verified_tbank_notice(
            order_id=self.order["id"],
            notice=self.notice(payment, status="REVERSED"),
        )

        self.assertEqual(result["payment_state"], "reversed")
        self.assertEqual(result["order_state"], "cancelled")
        self.assertEqual(self.stock().reserved_quantity, 0)

    def test_refund_after_commit_is_recorded_without_resurrecting_stock(self):
        payment = self.bind(self.prepare())
        self.commerce.apply_verified_tbank_notice(
            order_id=self.order["id"],
            notice=self.notice(payment),
        )

        result = self.commerce.apply_verified_tbank_notice(
            order_id=self.order["id"],
            notice=self.notice(payment, status="REFUNDED", amount=12000),
        )

        self.assertEqual(result["payment_state"], "refunded")
        self.assertEqual(result["order_state"], "paid")
        self.assertEqual(self.stock().quantity, 0)
        self.assertEqual(self.stock().reserved_quantity, 0)

    def test_partial_refund_remains_distinct_from_full_refund(self):
        payment = self.bind(self.prepare())
        self.commerce.apply_verified_tbank_notice(
            order_id=self.order["id"],
            notice=self.notice(payment),
        )

        result = self.commerce.apply_verified_tbank_notice(
            order_id=self.order["id"],
            notice=self.notice(payment, status="PARTIAL_REFUNDED", amount=6000),
        )

        self.assertEqual(result["payment_state"], "partial_refund")
        self.assertEqual(result["order_state"], "paid")
        self.assertEqual(self.stock().quantity, 0)

    def test_refund_before_confirmation_releases_reservation(self):
        payment = self.bind(self.prepare())

        result = self.commerce.apply_verified_tbank_notice(
            order_id=self.order["id"],
            notice=self.notice(payment, status="REFUNDED", amount=0),
        )

        self.assertEqual(result["payment_state"], "refunded")
        self.assertEqual(result["order_state"], "cancelled")
        self.assertEqual(self.stock().reserved_quantity, 0)
        self.assertEqual(self.stock().quantity, 1)

    def test_buyer_cannot_prepare_payment_for_another_order(self):
        payment = self.prepare()
        _, other_context = self.make_other_buyer()

        with self.assertRaises(PermissionDenied):
            self.commerce.prepare_payment(
                order_id=payment["order_id"],
                context=other_context,
            )

    def make_other_buyer(self):
        account = self.create_account(kind="ordinary")
        registry = self.create_registry(account)
        self.catalog.set_participant(
            account_id=account.id,
            allowed=True,
            context=self.staff_context,
        )
        return account, self.context(registry)
