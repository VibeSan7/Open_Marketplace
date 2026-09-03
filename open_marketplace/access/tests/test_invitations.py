import json
from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import uuid4

import pyotp
from cryptography.fernet import Fernet
from django.apps import apps
from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.test import TestCase
from django.utils.crypto import get_random_string

from open_marketplace.common.errors import (
    AuthenticationDenied,
    InputRejected,
    InvalidState,
    PermissionDenied,
)
from open_marketplace.common.types import OperationContext


Account = apps.get_model("identity", "Account")
AuditEntry = apps.get_model("audit", "AuditEntry")
OutboxMessage = apps.get_model("outbox", "OutboxMessage")
TotpCredential = apps.get_model("identity", "TotpCredential")
TotpRequirement = apps.get_model("identity", "TotpRequirement")


class InvitationTestCase(TestCase):
    now = datetime(2026, 9, 2, 12, tzinfo=UTC)
    password = f"T3st!{uuid4().hex}"

    def public(self):
        return import_module("open_marketplace.access.public")

    def create_account(self, *, kind=Account.Kind.SERVICE, email=None, totp=False):
        create = (
            Account.objects.create_service_account
            if kind == Account.Kind.SERVICE
            else Account.objects.create_user
        )
        account = create(
            email=email or f"user-{uuid4()}@example.com",
            password=self.password,
            state=Account.State.ACTIVE,
            email_verified_at=self.now - timedelta(days=1),
        )
        if totp:
            secret = pyotp.random_base32()
            TotpCredential.objects.create(
                account=account,
                encrypted_secret=Fernet(settings.TOTP_ENCRYPTION_KEY.encode("ascii")).encrypt(secret.encode("ascii")),
                confirmed_at=self.now - timedelta(days=1),
                last_accepted_counter=1,
            )
            account._test_totp_secret = secret
        return account

    def session(self, account):
        key = get_random_string(32, "abcdefghijklmnopqrstuvwxyz0123456789")
        Session.objects.create(
            session_key=key,
            session_data=SessionStore().encode({}),
            expire_date=self.now + timedelta(days=1),
        )
        return apps.get_model("identity", "AccountSession").objects.create(
            account=account,
            django_session_key=key,
            created_at=self.now - timedelta(hours=1),
            last_activity_at=self.now - timedelta(minutes=1),
            absolute_expires_at=self.now + timedelta(hours=1),
            reauthenticated_at=self.now - timedelta(minutes=1),
            device_label="test",
        )

    def context(self, account=None, registry=None, *, now=None, source="admin"):
        return OperationContext(
            actor_account_id=account.id if account else None,
            session_id=registry.id if registry else None,
            request_id=uuid4(),
            source=source,
            source_address="203.0.113.10" if account else None,
            now=now or self.now,
        )

    def authorized_admin(self):
        admin = self.create_account(totp=True)
        RoleAssignment = apps.get_model("access", "RoleAssignment")
        RoleAssignment.objects.create(
            account_id=admin.id,
            role="security_admin",
            assigned_reason="test fixture",
            active_from=self.now - timedelta(days=1),
        )
        registry = self.session(admin)
        return admin, self.context(admin, registry)

    def invitation_token(self, invitation_id):
        message = OutboxMessage.objects.get(
            message_type="access.staff_invitation",
            payload__invitation_id=str(invitation_id),
        )
        delivery = json.loads(
            Fernet(settings.OUTBOX_ENCRYPTION_KEY.encode("ascii"))
            .decrypt(bytes(message.encrypted_delivery))
        )
        return delivery["absolute_token_url"].rsplit("/", 2)[-2]

    def test_public_contract_and_invitation_creation_store_only_digest(self):
        public = self.public()
        for name in (
            "StaffInvitationQuery",
            "StaffInvitationView",
            "StaffAcceptanceSetup",
            "StaffAcceptanceResult",
            "list_staff_invitations",
            "invite_staff_member",
            "begin_staff_invitation_acceptance",
            "accept_staff_invitation",
            "revoke_staff_invitation",
            "bootstrap_security_admin",
        ):
            self.assertTrue(hasattr(public, name), name)
        admin, context = self.authorized_admin()

        invitation_id = public.invite_staff_member(
            email=" New.Staff@example.com ",
            role="seller_reviewer",
            context=context,
        )
        Invitation = apps.get_model("access", "StaffInvitation")
        invitation = Invitation.objects.get(pk=invitation_id)
        raw_token = self.invitation_token(invitation_id)

        self.assertEqual(invitation.email, "new.staff@example.com")
        self.assertEqual(len(invitation.token_digest), 64)
        self.assertNotIn(raw_token, invitation.token_digest)
        audit_text = " ".join(
            str(value)
            for value in AuditEntry.objects.values_list("reason", "before", "after")
        )
        self.assertNotIn(raw_token, audit_text)
        self.assertEqual(invitation.created_by_id, admin.id)

    def test_new_invitation_is_unprivileged_until_bound_totp_completion_and_is_one_time(self):
        public = self.public()
        admin, context = self.authorized_admin()
        invitation_id = public.invite_staff_member(
            email="new-staff@example.com", role="security_admin", context=context
        )
        raw_token = self.invitation_token(invitation_id)

        setup = public.begin_staff_invitation_acceptance(
            raw_token=raw_token,
            password=f"Strong password {uuid4().hex}",
            context=self.context(),
        )
        account = Account.objects.get(pk=setup.account_id)
        self.assertEqual(account.kind, "service")
        self.assertEqual(account.state, "active")
        self.assertIsNotNone(account.email_verified_at)
        self.assertFalse(apps.get_model("access", "RoleAssignment").objects.filter(account_id=account.id).exists())
        self.assertFalse(TotpRequirement.objects.filter(account=account).exists())

        repeated = public.begin_staff_invitation_acceptance(
            raw_token=raw_token,
            password="the password is ignored for an idempotent retry",
            context=self.context(),
        )
        self.assertEqual(repeated.acceptance_id, setup.acceptance_id)
        self.assertEqual(repeated.account_id, setup.account_id)
        self.assertIsNone(repeated.totp_setup)

        secret = Fernet(settings.TOTP_ENCRYPTION_KEY.encode("ascii")).decrypt(
            bytes(apps.get_model("identity", "TotpSetup").objects.get(pk=setup.totp_setup.setup_id).encrypted_secret)
        ).decode()
        result = public.accept_staff_invitation(
            acceptance_id=setup.acceptance_id,
            raw_token=raw_token,
            totp_code=pyotp.TOTP(secret).at(self.now),
            context=self.context(),
        )
        self.assertEqual(len(result.recovery_codes), settings.RECOVERY_CODE_COUNT)
        self.assertEqual(
            apps.get_model("access", "RoleAssignment").objects.filter(
                account_id=account.id, role="security_admin", state="active"
            ).count(),
            1,
        )
        self.assertEqual(TotpRequirement.objects.filter(account=account, removed_at=None).count(), 1)
        with self.assertRaises((AuthenticationDenied, InvalidState)):
            public.accept_staff_invitation(
                acceptance_id=setup.acceptance_id,
                raw_token=raw_token,
                totp_code=pyotp.TOTP(secret).at(self.now),
                context=self.context(),
            )

    def test_existing_service_account_requires_matching_authenticated_actor_and_totp(self):
        public = self.public()
        _, admin_context = self.authorized_admin()
        existing = self.create_account(email="existing@example.com", totp=True)
        existing_registry = self.session(existing)
        invitation_id = public.invite_staff_member(
            email=existing.email, role="seller_reviewer", context=admin_context
        )
        raw_token = self.invitation_token(invitation_id)

        with self.assertRaises((AuthenticationDenied, PermissionDenied, InvalidState)):
            public.begin_staff_invitation_acceptance(
                raw_token=raw_token,
                password=self.password,
                context=self.context(),
            )
        setup = public.begin_staff_invitation_acceptance(
            raw_token=raw_token,
            password=self.password,
            context=self.context(existing, existing_registry),
        )
        self.assertEqual(setup.mode, "existing_service_account")
        self.assertIsNone(setup.totp_setup)
        result = public.accept_staff_invitation(
            acceptance_id=setup.acceptance_id,
            raw_token=raw_token,
            totp_code=pyotp.TOTP(existing._test_totp_secret).at(self.now),
            context=self.context(existing, existing_registry),
        )
        self.assertEqual(result.recovery_codes, ())

    def test_ordinary_accounts_cross_bindings_and_terminal_invitations_are_rejected(self):
        public = self.public()
        admin, context = self.authorized_admin()
        ordinary = self.create_account(kind=Account.Kind.ORDINARY)
        with self.assertRaises((InvalidState, InputRejected)):
            public.invite_staff_member(email=ordinary.email, role="seller_reviewer", context=context)

        first_id = public.invite_staff_member(email="first@example.com", role="seller_reviewer", context=context)
        second_id = public.invite_staff_member(email="second@example.com", role="security_admin", context=context)
        first_token = self.invitation_token(first_id)
        second_token = self.invitation_token(second_id)
        first_setup = public.begin_staff_invitation_acceptance(
            raw_token=first_token, password=f"Strong password {uuid4().hex}", context=self.context()
        )
        with self.assertRaises((AuthenticationDenied, InvalidState)):
            public.accept_staff_invitation(
                acceptance_id=first_setup.acceptance_id,
                raw_token=second_token,
                totp_code="000000",
                context=self.context(),
            )

        Invitation = apps.get_model("access", "StaffInvitation")
        Invitation.objects.filter(pk=first_id).update(
            created_at=self.now - timedelta(days=2),
            expires_at=self.now - timedelta(seconds=1),
        )
        with self.assertRaises((AuthenticationDenied, InvalidState)):
            public.begin_staff_invitation_acceptance(
                raw_token=first_token, password=self.password, context=self.context()
            )
        public.revoke_staff_invitation(invitation_id=second_id, reason="cancelled", context=context)
        with self.assertRaises((AuthenticationDenied, InvalidState)):
            public.begin_staff_invitation_acceptance(
                raw_token=second_token, password=self.password, context=self.context()
            )
        self.assertNotEqual(admin.id, ordinary.id)

    def test_listing_uses_security_permission_scopes_uuid_cursor_and_bounded_limit(self):
        public = self.public()
        _, context = self.authorized_admin()
        ids = [
            public.invite_staff_member(
                email=f"staff-{index}@example.com",
                role="seller_reviewer" if index % 2 else "security_admin",
                context=context,
            )
            for index in range(3)
        ]
        query = public.StaffInvitationQuery(
            state="pending", role="seller_reviewer", canonical_email=None, limit=1, cursor=None
        )
        first = public.list_staff_invitations(query=query, context=context)
        self.assertEqual(len(first), 1)
        next_page = public.list_staff_invitations(
            query=public.StaffInvitationQuery(
                state="pending", role="seller_reviewer", canonical_email=None, limit=1, cursor=first[-1].id
            ),
            context=context,
        )
        self.assertTrue(all(view.role == "seller_reviewer" for view in first + next_page))
        with self.assertRaises(InputRejected):
            public.list_staff_invitations(
                query=public.StaffInvitationQuery(
                    state=None, role=None, canonical_email=None, limit=101, cursor=None
                ),
                context=context,
            )

        reviewer = self.create_account(totp=True)
        apps.get_model("access", "RoleAssignment").objects.create(
            account_id=reviewer.id,
            role="seller_reviewer",
            assigned_reason="test fixture",
            active_from=self.now - timedelta(days=1),
        )
        with self.assertRaises(PermissionDenied):
            public.list_staff_invitations(query=query, context=self.context(reviewer, self.session(reviewer)))
