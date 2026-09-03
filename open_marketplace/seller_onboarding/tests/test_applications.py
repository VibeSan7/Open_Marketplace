from datetime import UTC, datetime
from importlib import import_module
from uuid import uuid4

from django.apps import apps
from django.test import TestCase

from open_marketplace.common.errors import (
    ConcurrentConflict,
    InputRejected,
    InvalidState,
    PermissionDenied,
)
from open_marketplace.common.types import OperationContext


class SellerApplicationTestCase(TestCase):
    now = datetime(2026, 9, 2, 12, tzinfo=UTC)

    def setUp(self):
        self.public = import_module("open_marketplace.seller_onboarding.public")
        self.models = import_module("open_marketplace.seller_onboarding.models")
        self.Account = apps.get_model("identity", "Account")
        self.AuditEntry = apps.get_model("audit", "AuditEntry")
        self.OutboxMessage = apps.get_model("outbox", "OutboxMessage")

    def account(self, *, kind="ordinary", active=True, verified=True):
        create = (
            self.Account.objects.create_user
            if kind == "ordinary"
            else self.Account.objects.create_service_account
        )
        account = create(
            email=f"person-{uuid4()}@example.com",
            password="correct horse battery staple",
            state="active" if active else "pending_email_verification",
            email_verified_at=self.now if verified else None,
        )
        return account

    def context(self, account_id=None):
        return OperationContext(
            actor_account_id=account_id,
            session_id=None,
            request_id=uuid4(),
            source="html",
            source_address="192.0.2.10",
            now=self.now,
        )

    def draft(self, **overrides):
        values = {
            "business_form": "sole_proprietor",
            "display_name": "  Test shop  ",
            "official_name": "  Test business  ",
            "registration_identifier": "  TEST-123  ",
            "contact_email": "  Owner@Example.COM ",
            "test_data_attested": True,
        }
        values.update(overrides)
        return self.public.SellerDraftData(**values)

    def test_public_contract_and_ordinary_account_lifecycle(self):
        account = self.account()
        context = self.context(account.id)

        application_id = self.public.create_seller_application(context=context)
        view, versions = self.public.get_own_seller_application(
            application_id=application_id,
            context=context,
        )

        self.assertEqual(view.id, application_id)
        self.assertEqual(view.applicant_id, account.id)
        self.assertEqual(view.state, "draft")
        self.assertEqual(view.current_version, 0)
        self.assertEqual(versions, ())

        self.public.update_seller_application_draft(
            application_id=application_id,
            data=self.draft(),
            context=context,
        )
        version_id = self.public.submit_seller_application(
            application_id=application_id,
            context=context,
        )

        view, versions = self.public.get_own_seller_application(
            application_id=application_id,
            context=context,
        )
        self.assertEqual(view.state, "submitted")
        self.assertEqual(view.current_version, 1)
        self.assertEqual(versions[0].data.display_name, "Test shop")
        self.assertEqual(versions[0].data.contact_email, "owner@example.com")
        self.assertEqual(versions[0].application_id, application_id)
        self.assertEqual(version_id, self.models.SellerApplicationVersion.objects.get(pk=version_id).id)

        message = self.OutboxMessage.objects.get(message_type="seller_onboarding.application_submitted")
        self.assertEqual(message.format_version, 1)
        self.assertEqual(message.payload, {"application_id": str(application_id), "version_id": str(version_id)})
        self.assertIsNone(message.encrypted_delivery)

        actions = set(
            self.AuditEntry.objects.values_list("action", flat=True)
        )
        self.assertTrue(
            {
                "seller_onboarding.application_created",
                "seller_onboarding.application_updated",
                "seller_onboarding.application_submitted",
            }.issubset(actions)
        )
        for entry in self.AuditEntry.objects.all():
            self.assertNotIn("display_name", entry.before)
            self.assertNotIn("official_name", entry.after)
            self.assertNotIn("contact_email", entry.after)
            self.assertNotIn("registration_identifier", entry.after)

    def test_only_active_verified_ordinary_accounts_are_allowed(self):
        cases = (
            self.account(active=False),
            self.account(verified=False),
            self.account(kind="service"),
        )
        for account in cases:
            with self.subTest(account=account), self.assertRaises(PermissionDenied):
                self.public.create_seller_application(context=self.context(account.id))

    def test_one_unfinished_application_and_new_history_after_withdrawal(self):
        account = self.account()
        context = self.context(account.id)
        first_id = self.public.create_seller_application(context=context)
        with self.assertRaises(ConcurrentConflict):
            self.public.create_seller_application(context=context)

        self.public.update_seller_application_draft(
            application_id=first_id,
            data=self.draft(),
            context=context,
        )
        self.public.submit_seller_application(
            application_id=first_id,
            context=context,
        )
        self.public.withdraw_seller_application(
            application_id=first_id,
            context=context,
        )
        second_id = self.public.create_seller_application(context=context)
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(
            self.public.get_own_seller_application(
                application_id=first_id,
                context=context,
            )[0].state,
            "withdrawn",
        )
        self.assertEqual(
            self.models.SellerApplicationVersion.objects.filter(
                application_id=first_id
            ).count(),
            1,
        )

    def test_own_only_access_and_editable_state_rules(self):
        owner = self.account()
        other = self.account()
        owner_context = self.context(owner.id)
        other_context = self.context(other.id)
        application_id = self.public.create_seller_application(context=owner_context)
        other_application_id = self.public.create_seller_application(
            context=other_context
        )

        self.assertEqual(
            tuple(
                application.id
                for application in self.public.list_own_seller_applications(
                    context=owner_context
                )
            ),
            (application_id,),
        )
        self.assertEqual(
            tuple(
                application.id
                for application in self.public.list_own_seller_applications(
                    context=other_context
                )
            ),
            (other_application_id,),
        )

        with self.assertRaises(PermissionDenied):
            self.public.get_own_seller_application(
                application_id=application_id,
                context=other_context,
            )
        with self.assertRaises(PermissionDenied):
            self.public.update_seller_application_draft(
                application_id=application_id,
                data=self.draft(),
                context=other_context,
            )

        self.public.update_seller_application_draft(
            application_id=application_id,
            data=self.draft(),
            context=owner_context,
        )
        self.public.submit_seller_application(
            application_id=application_id,
            context=owner_context,
        )
        with self.assertRaises(InvalidState):
            self.public.update_seller_application_draft(
                application_id=application_id,
                data=self.draft(display_name="changed"),
                context=owner_context,
            )

    def test_missing_application_is_denied_neutrally_for_every_own_operation(self):
        account = self.account()
        context = self.context(account.id)
        missing_id = uuid4()

        with self.assertRaises(PermissionDenied):
            self.public.get_own_seller_application(
                application_id=missing_id,
                context=context,
            )
        with self.assertRaises(PermissionDenied):
            self.public.update_seller_application_draft(
                application_id=missing_id,
                data=self.draft(),
                context=context,
            )
        with self.assertRaises(PermissionDenied):
            self.public.submit_seller_application(
                application_id=missing_id,
                context=context,
            )
        with self.assertRaises(PermissionDenied):
            self.public.withdraw_seller_application(
                application_id=missing_id,
                context=context,
            )

    def test_withdraw_accepts_each_unfinished_state_and_rejects_repeats(self):
        account = self.account()
        context = self.context(account.id)

        for state in ("draft", "submitted", "under_review", "changes_requested"):
            with self.subTest(state=state):
                application_id = self.public.create_seller_application(context=context)
                if state == "submitted":
                    self.public.update_seller_application_draft(
                        application_id=application_id,
                        data=self.draft(),
                        context=context,
                    )
                    self.public.submit_seller_application(
                        application_id=application_id,
                        context=context,
                    )
                elif state != "draft":
                    self.models.SellerApplication.objects.filter(
                        pk=application_id
                    ).update(state=state)

                self.public.withdraw_seller_application(
                    application_id=application_id,
                    context=context,
                )
                with self.assertRaises(InvalidState):
                    self.public.withdraw_seller_application(
                        application_id=application_id,
                        context=context,
                    )

    def test_submit_rejects_repeat_and_other_terminal_states(self):
        account = self.account()
        context = self.context(account.id)

        application_id = self.public.create_seller_application(context=context)
        self.public.update_seller_application_draft(
            application_id=application_id,
            data=self.draft(),
            context=context,
        )
        self.public.submit_seller_application(
            application_id=application_id,
            context=context,
        )
        with self.assertRaises(InvalidState):
            self.public.submit_seller_application(
                application_id=application_id,
                context=context,
            )
        self.public.withdraw_seller_application(
            application_id=application_id,
            context=context,
        )

        for state in ("approved", "rejected"):
            with self.subTest(state=state):
                application_id = self.public.create_seller_application(context=context)
                self.models.SellerApplication.objects.filter(pk=application_id).update(
                    state=state
                )
                with self.assertRaises(InvalidState):
                    self.public.update_seller_application_draft(
                        application_id=application_id,
                        data=self.draft(),
                        context=context,
                    )
                with self.assertRaises(InvalidState):
                    self.public.submit_seller_application(
                        application_id=application_id,
                        context=context,
                    )
                with self.assertRaises(InvalidState):
                    self.public.withdraw_seller_application(
                        application_id=application_id,
                        context=context,
                    )

    def test_invalid_or_incomplete_data_is_rejected_at_application_boundary(self):
        account = self.account()
        context = self.context(account.id)
        application_id = self.public.create_seller_application(context=context)

        for overrides in (
            {"business_form": "partnership"},
            {"business_form": []},
            {"display_name": "   "},
            {"official_name": ""},
            {"registration_identifier": "   "},
            {"contact_email": "not-an-email"},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(InputRejected):
                self.public.update_seller_application_draft(
                    application_id=application_id,
                    data=self.draft(**overrides),
                    context=context,
                )

        incomplete = self.draft(test_data_attested=False)
        self.public.update_seller_application_draft(
            application_id=application_id,
            data=incomplete,
            context=context,
        )
        with self.assertRaises(InputRejected):
            self.public.submit_seller_application(
                application_id=application_id,
                context=context,
            )

    def test_all_mutations_roll_back_when_audit_or_outbox_fails(self):
        account = self.account()
        context = self.context(account.id)
        application_module = import_module("open_marketplace.seller_onboarding.application")

        from unittest.mock import patch

        audit_count = self.AuditEntry.objects.count()
        with patch.object(application_module, "append_audit_entry", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                self.public.create_seller_application(context=context)
        self.assertFalse(self.models.SellerApplication.objects.filter(applicant_id=account.id).exists())
        self.assertEqual(self.AuditEntry.objects.count(), audit_count)

        application_id = self.public.create_seller_application(context=context)
        audit_count = self.AuditEntry.objects.count()
        with patch.object(application_module, "append_audit_entry", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                self.public.update_seller_application_draft(
                    application_id=application_id,
                    data=self.draft(),
                    context=context,
                )
        application = self.models.SellerApplication.objects.get(pk=application_id)
        self.assertIsNone(application.business_form)
        self.assertEqual(self.AuditEntry.objects.count(), audit_count)

        self.public.update_seller_application_draft(
            application_id=application_id,
            data=self.draft(),
            context=context,
        )
        audit_count = self.AuditEntry.objects.count()
        outbox_count = self.OutboxMessage.objects.count()
        with patch.object(application_module, "append_audit_entry", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                self.public.submit_seller_application(
                    application_id=application_id,
                    context=context,
                )
        application = self.models.SellerApplication.objects.get(pk=application_id)
        self.assertEqual(application.state, "draft")
        self.assertEqual(application.current_version, 0)
        self.assertFalse(
            self.models.SellerApplicationVersion.objects.filter(
                application_id=application_id
            ).exists()
        )
        self.assertEqual(self.AuditEntry.objects.count(), audit_count)
        self.assertEqual(self.OutboxMessage.objects.count(), outbox_count)

        audit_count = self.AuditEntry.objects.count()
        outbox_count = self.OutboxMessage.objects.count()
        with patch.object(application_module, "enqueue_outbox_message", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                self.public.submit_seller_application(
                    application_id=application_id,
                    context=context,
                )
        application = self.models.SellerApplication.objects.get(pk=application_id)
        self.assertEqual(application.state, "draft")
        self.assertEqual(application.current_version, 0)
        self.assertFalse(self.models.SellerApplicationVersion.objects.filter(application_id=application_id).exists())
        self.assertEqual(self.AuditEntry.objects.count(), audit_count)
        self.assertEqual(self.OutboxMessage.objects.count(), outbox_count)

        audit_count = self.AuditEntry.objects.count()
        with patch.object(application_module, "append_audit_entry", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                self.public.withdraw_seller_application(
                    application_id=application_id,
                    context=context,
                )
        self.assertEqual(
            self.models.SellerApplication.objects.get(pk=application_id).state,
            "draft",
        )
        self.assertEqual(self.AuditEntry.objects.count(), audit_count)
