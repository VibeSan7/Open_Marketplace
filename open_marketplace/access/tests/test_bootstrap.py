from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import uuid4

from django.apps import apps
from django.core.management import call_command, load_command_class
from django.core.management.base import CommandError
from django.test import TestCase

from open_marketplace.common.errors import InvalidState
from open_marketplace.common.types import OperationContext


Account = apps.get_model("identity", "Account")


class BootstrapCommandTests(TestCase):
    now = datetime(2026, 9, 2, 12, tzinfo=UTC)

    def context(self):
        return OperationContext(
            actor_account_id=None,
            session_id=None,
            request_id=uuid4(),
            source="command",
            source_address=None,
            now=self.now,
        )

    def public(self):
        return import_module("open_marketplace.access.public")

    def invitation_model(self):
        return apps.get_model("access", "StaffInvitation")

    def test_bootstrap_command_accepts_only_email_and_creates_one_live_invitation(self):
        public = self.public()
        first = public.bootstrap_security_admin(email=" Admin@Example.COM ", context=self.context())
        second = public.bootstrap_security_admin(email="admin@example.com", context=self.context())
        self.assertEqual(first, second)
        Invitation = self.invitation_model()
        invitation = Invitation.objects.get(pk=first)
        self.assertEqual(invitation.email, "admin@example.com")
        self.assertEqual(invitation.role, "security_admin")
        self.assertIsNone(invitation.created_by_id)
        self.assertEqual(
            Invitation.objects.filter(
                role="security_admin",
                accepted_at__isnull=True,
                revoked_at__isnull=True,
                expires_at__gt=self.now,
            ).count(),
            1,
        )

        with self.assertRaises(CommandError):
            call_command(
                "bootstrap_security_admin",
                "--email",
                "another@example.com",
                "--password",
                "not-allowed",
            )

    def test_expiry_allows_new_bootstrap_but_active_security_admin_does_not(self):
        public = self.public()
        first = public.bootstrap_security_admin(email="admin@example.com", context=self.context())
        self.invitation_model().objects.filter(pk=first).update(
            created_at=self.now - timedelta(days=2),
            expires_at=self.now - timedelta(seconds=1)
        )
        second = public.bootstrap_security_admin(email="other@example.com", context=self.context())
        self.assertNotEqual(first, second)

        admin = Account.objects.create_service_account(
            email="active-admin@example.com",
            password=f"Strong password {uuid4().hex}",
            state=Account.State.ACTIVE,
            email_verified_at=self.now,
        )
        apps.get_model("identity", "TotpCredential").objects.create(
            account=admin,
            encrypted_secret=b"secret",
            confirmed_at=self.now,
            last_accepted_counter=1,
        )
        apps.get_model("access", "RoleAssignment").objects.create(
            account_id=admin.id,
            role="security_admin",
            assigned_reason="accepted bootstrap invitation",
            active_from=self.now,
        )
        with self.assertRaises(InvalidState):
            public.bootstrap_security_admin(email="third@example.com", context=self.context())

    def test_management_command_help_does_not_offer_password(self):
        command = load_command_class("open_marketplace.access", "bootstrap_security_admin")
        help_text = command.create_parser("manage.py", "bootstrap_security_admin").format_help()
        self.assertIn("--email", help_text)
        self.assertNotIn("--password", help_text)
