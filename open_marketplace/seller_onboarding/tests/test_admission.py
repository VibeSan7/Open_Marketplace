"""Task 13 RED admission tests: seller profile, TOTP activation, admission state.

All new seller profile operations are missing; every test below fails until
Task 13 implements them.
"""
from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import uuid4

import pyotp
from django.apps import apps
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.test import TestCase
from django.utils.crypto import get_random_string

from open_marketplace.common.errors import (
    InputRejected,
    InvalidState,
    PermissionDenied,
)
from open_marketplace.common.types import OperationContext

Account = apps.get_model("identity", "Account")
AccountSession = apps.get_model("identity", "AccountSession")
TotpCredential = apps.get_model("identity", "TotpCredential")
TotpRequirement = apps.get_model("identity", "TotpRequirement")
AuditEntry = apps.get_model("audit", "AuditEntry")
OutboxMessage = apps.get_model("outbox", "OutboxMessage")


class SellerAdmissionTestCase(TestCase):
    now = datetime(2026, 9, 3, 12, tzinfo=UTC)
    password = f"T3st!{uuid4().hex}"

    def setUp(self):
        self.public = import_module("open_marketplace.seller_onboarding.public")
        self.models = import_module("open_marketplace.seller_onboarding.models")
        self.identity = import_module("open_marketplace.identity.public")
        try:
            self.workflows = import_module("open_marketplace.workflows.totp")
        except ImportError:
            self.workflows = None

    # --- fixtures -------------------------------------------------------

    def owner(self, *, totp=False):
        account = Account.objects.create_user(
            email=f"owner-{uuid4().hex}@example.com",
            password=self.password,
            state="active",
            email_verified_at=self.now - timedelta(days=1),
        )
        if totp:
            self.enable_totp(account)
        return account

    def service_account(self, role="security_admin"):
        account = Account.objects.create_service_account(
            email=f"staff-{uuid4().hex}@example.com",
            password=self.password,
            state="active",
            email_verified_at=self.now - timedelta(days=1),
        )
        self.enable_totp(account)
        apps.get_model("access", "RoleAssignment").objects.create(
            account_id=account.id,
            role=role,
            state="active",
            assigned_by_id=uuid4(),
            assigned_reason="test fixture",
            active_from=self.now - timedelta(days=1),
        )
        registry = self.registry(account)
        return account, registry

    def enable_totp(self, account):
        return TotpCredential.objects.create(
            account=account,
            encrypted_secret=b"encrypted-test-secret",
            confirmed_at=self.now - timedelta(days=1),
            last_accepted_counter=1,
        )

    def django_session(self):
        key = get_random_string(32, "abcdefghijklmnopqrstuvwxyz0123456789")
        Session.objects.create(
            session_key=key,
            session_data=SessionStore().encode({}),
            expire_date=self.now + timedelta(days=31),
        )
        return key

    def registry(self, account, *, reauthenticated_at=None):
        created_at = self.now - timedelta(hours=1)
        return AccountSession.objects.create(
            account=account,
            django_session_key=self.django_session(),
            created_at=created_at,
            last_activity_at=self.now - timedelta(minutes=1),
            absolute_expires_at=self.now + timedelta(days=1),
            reauthenticated_at=reauthenticated_at
            if reauthenticated_at is not None
            else (self.now - timedelta(minutes=1)),
            device_label="Firefox on Linux",
        )

    def context(self, account, *, registry=None, request_id=None, now=None, source="admin"):
        return OperationContext(
            actor_account_id=account.id,
            session_id=registry.id if registry is not None else None,
            request_id=request_id or uuid4(),
            source=source,
            source_address="203.0.113.10",
            now=now or self.now,
        )

    def owner_context(self, owner, *, source="html"):
        return self.context(owner, registry=self.registry(owner), source=source)

    def admin_context(self):
        account, registry = self.service_account("security_admin")
        return self.context(account, registry=registry)

    def draft(self, **overrides):
        values = {
            "business_form": "sole_proprietor",
            "display_name": "Test shop",
            "official_name": "Test business",
            "registration_identifier": "TEST-123",
            "contact_email": "owner@example.com",
            "test_data_attested": True,
        }
        values.update(overrides)
        return self.public.SellerDraftData(**values)

    def submitted_application(self, owner):
        context = self.owner_context(owner)
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
        return application_id, context

    def reviewed_application(self, owner, *, approve=True):
        account, registry = self.service_account("seller_reviewer")
        reviewer_context = self.context(account, registry=registry)
        application_id, owner_context = self.submitted_application(owner)
        self.public.start_seller_application_review(
            application_id=application_id,
            context=reviewer_context,
        )
        if approve:
            seller_id = self.public.approve_seller_application(
                application_id=application_id,
                reason="All test fields are correct.",
                context=reviewer_context,
            )
            return application_id, owner_context, seller_id, reviewer_context
        self.public.reject_seller_application(
            application_id=application_id,
            reason="Not eligible.",
            context=reviewer_context,
        )
        return application_id, owner_context, None, reviewer_context

    def totp_setup_and_code(self, owner, owner_context):
        setup = self.identity.begin_totp_setup(
            current_password=self.password,
            context=owner_context,
        )
        code = pyotp.TOTP(setup.manual_secret).at(self.now)
        return setup, code

    # --- tests ----------------------------------------------------------

    def test_approve_without_owner_totp_creates_awaiting_profile_and_requirement(self):
        owner = self.owner(totp=False)
        application_id, _, seller_id, _ = self.reviewed_application(owner)
        self.assertIsNotNone(seller_id)

        profile = self.models.SellerProfile.objects.get(pk=seller_id)
        self.assertEqual(profile.state, "awaiting_owner_totp")
        requirement = TotpRequirement.objects.get(
            account_id=owner.id,
            source_type="seller_profile",
            source_id=seller_id,
        )
        self.assertIsNone(requirement.removed_at)

    def test_approve_with_active_totp_creates_active_profile(self):
        owner = self.owner(totp=True)
        application_id, _, seller_id, _ = self.reviewed_application(owner)
        profile = self.models.SellerProfile.objects.get(pk=seller_id)
        self.assertEqual(profile.state, "active")
        self.assertTrue(
            TotpRequirement.objects.filter(
                account_id=owner.id,
                source_type="seller_profile",
                source_id=seller_id,
                removed_at__isnull=True,
            ).exists()
        )

    def test_workflow_enable_totp_activates_waiting_seller_atomically(self):
        if self.workflows is None:
            self.fail("open_marketplace.workflows.totp is missing")
        owner = self.owner(totp=False)
        application_id, owner_context, seller_id, _ = self.reviewed_application(owner)
        setup, code = self.totp_setup_and_code(owner, owner_context)

        codes = self.workflows.enable_totp_and_activate_waiting_seller(
            setup_id=setup.setup_id,
            code=code,
            context=owner_context,
        )
        self.assertIsInstance(codes, tuple)
        self.assertTrue(codes)

        profile = self.models.SellerProfile.objects.get(pk=seller_id)
        self.assertEqual(profile.state, "active")
        self.assertTrue(
            TotpCredential.objects.filter(
                account_id=owner.id,
                disabled_at__isnull=True,
            ).exists()
        )
        self.assertTrue(
            OutboxMessage.objects.filter(
                message_type="seller_onboarding.admission_change",
                payload__seller_id=str(seller_id),
                payload__state="active",
            ).exists()
        )

    def test_workflow_enable_totp_rolls_back_when_profile_activation_fails(self):
        if self.workflows is None:
            self.fail("open_marketplace.workflows.totp is missing")
        owner = self.owner(totp=False)
        application_id, owner_context, seller_id, _ = self.reviewed_application(owner)
        setup, code = self.totp_setup_and_code(owner, owner_context)

        # a revoked seller cannot be activated; the whole operation rolls back
        self.models.SellerProfile.objects.filter(pk=seller_id).update(state="revoked")
        with self.assertRaises(InvalidState):
            self.workflows.enable_totp_and_activate_waiting_seller(
                setup_id=setup.setup_id,
                code=code,
                context=owner_context,
            )

        self.assertFalse(
            TotpCredential.objects.filter(
                account_id=owner.id,
                disabled_at__isnull=True,
            ).exists()
        )
        self.assertFalse(
            OutboxMessage.objects.filter(
                message_type="seller_onboarding.admission_change",
                payload__seller_id=str(seller_id),
                payload__state="active",
            ).exists()
        )

    def test_activate_seller_after_totp_requires_owner_totp_and_awaiting_state(self):
        owner = self.owner(totp=False)
        application_id, owner_context, seller_id, _ = self.reviewed_application(owner)

        with self.assertRaises(InvalidState):
            self.public.activate_seller_after_totp(
                seller_id=seller_id,
                context=owner_context,
            )

        setup, code = self.totp_setup_and_code(owner, owner_context)
        self.identity.enable_totp(
            setup_id=setup.setup_id,
            code=code,
            context=owner_context,
        )
        self.public.activate_seller_after_totp(
            seller_id=seller_id,
            context=owner_context,
        )
        profile = self.models.SellerProfile.objects.get(pk=seller_id)
        self.assertEqual(profile.state, "active")

        with self.assertRaises(InvalidState):
            self.public.activate_seller_after_totp(
                seller_id=seller_id,
                context=owner_context,
            )

    def test_activate_is_owner_only(self):
        owner = self.owner(totp=False)
        application_id, owner_context, seller_id, _ = self.reviewed_application(owner)
        other = self.owner(totp=True)
        other_context = self.owner_context(other)
        with self.assertRaises(PermissionDenied):
            self.public.activate_seller_after_totp(
                seller_id=seller_id,
                context=other_context,
            )

    def test_suspend_restore_keep_requirement_and_require_admin_reason_and_state(self):
        owner = self.owner(totp=True)
        application_id, _, seller_id, _ = self.reviewed_application(owner)

        with self.assertRaises(InputRejected):
            self.public.suspend_seller(
                seller_id=seller_id,
                reason="  ",
                context=self.admin_context(),
            )
        admin_context = self.admin_context()
        self.public.suspend_seller(
            seller_id=seller_id,
            reason="Reviewing the shop.",
            context=admin_context,
        )
        profile = self.models.SellerProfile.objects.get(pk=seller_id)
        self.assertEqual(profile.state, "suspended")
        self.assertEqual(profile.restriction_reason, "Reviewing the shop.")
        self.assertTrue(
            TotpRequirement.objects.filter(
                account_id=owner.id,
                source_type="seller_profile",
                source_id=seller_id,
                removed_at__isnull=True,
            ).exists()
        )

        with self.assertRaises(InvalidState):
            self.public.suspend_seller(
                seller_id=seller_id,
                reason="Again.",
                context=admin_context,
            )

        self.public.restore_seller(
            seller_id=seller_id,
            reason="Cleared.",
            context=admin_context,
        )
        profile = self.models.SellerProfile.objects.get(pk=seller_id)
        self.assertEqual(profile.state, "active")

    def test_revoke_is_terminal_and_removes_only_that_profiles_totp_requirement(self):
        owner = self.owner(totp=True)
        application_id, _, seller_id, _ = self.reviewed_application(owner)
        admin_context = self.admin_context()
        self.public.revoke_seller(
            seller_id=seller_id,
            reason="Violation.",
            context=admin_context,
        )
        profile = self.models.SellerProfile.objects.get(pk=seller_id)
        self.assertEqual(profile.state, "revoked")
        requirement = TotpRequirement.objects.get(
            account_id=owner.id,
            source_type="seller_profile",
            source_id=seller_id,
        )
        self.assertIsNotNone(requirement.removed_at)
        with self.assertRaises(InvalidState):
            self.public.restore_seller(
                seller_id=seller_id,
                reason="Too late.",
                context=admin_context,
            )
        with self.assertRaises(InvalidState):
            self.public.suspend_seller(
                seller_id=seller_id,
                reason="Too late.",
                context=admin_context,
            )

    def test_suspend_restore_keep_requirement_and_revoke_removes_it(self):
        owner = self.owner(totp=True)
        application_id, _, seller_id, _ = self.reviewed_application(owner)
        admin_context = self.admin_context()

        self.public.suspend_seller(
            seller_id=seller_id,
            reason="Temporary hold.",
            context=admin_context,
        )
        self.public.restore_seller(
            seller_id=seller_id,
            reason="Hold lifted.",
            context=admin_context,
        )
        self.assertIsNotNone(
            TotpRequirement.objects.get(
                account_id=owner.id,
                source_type="seller_profile",
                source_id=seller_id,
                removed_at__isnull=True,
            )
        )

        self.public.revoke_seller(
            seller_id=seller_id,
            reason="Terminated.",
            context=admin_context,
        )
        self.assertIsNotNone(
            TotpRequirement.objects.get(
                account_id=owner.id,
                source_type="seller_profile",
                source_id=seller_id,
            ).removed_at
        )

    def test_profile_queries_are_security_admin_scoped_and_owner_view_is_private(self):
        owner = self.owner(totp=True)
        application_id, owner_context, seller_id, _ = self.reviewed_application(owner)

        owner_view = self.public.get_seller_profile_for_owner(context=owner_context)
        self.assertEqual(owner_view.id, seller_id)
        self.assertEqual(owner_view.state, "active")

        admin_context = self.admin_context()
        profiles = self.public.query_seller_profiles(
            query=self.public.SellerProfileQuery(
                state=None,
                owner_id=None,
                limit=100,
                cursor=None,
            ),
            context=admin_context,
        )
        self.assertEqual({profile.id for profile in profiles}, {seller_id})

        with self.assertRaises(PermissionDenied):
            self.public.query_seller_profiles(
                query=self.public.SellerProfileQuery(
                    state=None,
                    owner_id=None,
                    limit=100,
                    cursor=None,
                ),
                context=owner_context,
            )

    def test_ordinary_account_without_profile_has_no_owner_view(self):
        owner = self.owner(totp=True)
        owner_context = self.owner_context(owner)
        self.assertIsNone(self.public.get_seller_profile_for_owner(context=owner_context))

    def test_service_account_cannot_own_profile_and_reviewer_cannot_query_profiles(self):
        reviewer_account, reviewer_registry = self.service_account("seller_reviewer")
        reviewer_context = self.context(reviewer_account, registry=reviewer_registry)
        self.assertIsNone(
            self.public.get_seller_profile_for_owner(context=reviewer_context)
        )

        owner = self.owner(totp=True)
        application_id, _, _, _ = self.reviewed_application(owner)
        with self.assertRaises(PermissionDenied):
            self.public.query_seller_profiles(
                query=self.public.SellerProfileQuery(
                    state=None,
                    owner_id=None,
                    limit=100,
                    cursor=None,
                ),
                context=reviewer_context,
            )
