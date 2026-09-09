"""Task 19 tests: restore probe commands.

Prove an empty database fails verification, a seeded graph passes, deleting
each required row or relationship fails verification with a bounded error,
and command output never contains emails, tokens, passwords or secret names.
"""

from io import StringIO
from unittest.mock import patch
from uuid import uuid4

from django.apps import apps
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
from django.test import TestCase

RoleAssignment = apps.get_model("access", "RoleAssignment")
Account = apps.get_model("identity", "Account")
AuditEntry = apps.get_model("audit", "AuditEntry")
SellerProfile = apps.get_model("seller_onboarding", "SellerProfile")
SellerReviewDecision = apps.get_model("seller_onboarding", "SellerReviewDecision")
Session = apps.get_model("sessions", "Session")
OutboxMessage = apps.get_model("outbox", "OutboxMessage")

SECRET_SUBSTRINGS = (
    "@example.test",
    "password",
    "T3st!",
    "recovery_code",
    "manual_secret",
    "DJANGO_SECRET_KEY",
    "DATABASE_PASSWORD",
    "TOTP_ENCRYPTION_KEY",
    "OUTBOX_ENCRYPTION_KEY",
    "LINK_EXCHANGE_ENCRYPTION_KEY",
    "THROTTLE_HASH_KEY",
)


class RestoreProbeTests(TestCase):
    def setUp(self):
        self.marker = f"t{uuid4().hex[:12]}"
        self.out = StringIO()

    def seed(self):
        call_command("seed_restore_probe", "--marker", self.marker, stdout=self.out)

    def verify(self):
        return call_command(
            "verify_restore_probe", "--marker", self.marker, stdout=self.out
        )

    def test_empty_database_fails_verification(self):
        with self.assertRaises(CommandError) as raised:
            self.verify()
        self.assertIn("restore verification failed", str(raised.exception))

    def test_seed_refuses_non_test_database(self):
        with patch.dict(
            connection.settings_dict,
            {"HOST": "postgres", "NAME": "open_marketplace"},
        ):
            with self.assertRaises(CommandError) as raised:
                self.seed()
        self.assertIn("disposable postgres-test database", str(raised.exception))
        self.assertEqual(Account.objects.count(), 0)
        self.assertEqual(RoleAssignment.objects.count(), 0)

    def test_seeded_graph_passes_verification_and_prints_only_safe_output(self):
        self.seed()
        self.verify()
        output = self.out.getvalue()
        self.assertIn("restore_verification_complete marker=", output)
        self.assertIn("row_kind=seller_profile", output)
        self.assertIn("migration_leaf", output)
        for secret in SECRET_SUBSTRINGS:
            self.assertNotIn(secret, output)
        self.assertNotRegex(output, r"[A-Za-z0-9_-]{40,}")

    def test_deleted_staff_session_fails_verification(self):
        self.seed()
        Session.objects.all().delete()
        with self.assertRaises(CommandError) as raised:
            self.verify()
        self.assertIn("restore verification failed", str(raised.exception))

    def test_deleted_role_assignment_fails_verification(self):
        self.seed()
        RoleAssignment.objects.all().delete()
        audit_count = AuditEntry.objects.count()
        with self.assertRaises(CommandError) as raised:
            self.verify()
        self.assertIn("restore verification failed", str(raised.exception))
        self.assertEqual(AuditEntry.objects.count(), audit_count)

    def test_deleted_application_version_fails_verification(self):
        self.seed()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM seller_onboarding_sellerapplicationversion")
        with self.assertRaises(CommandError) as raised:
            self.verify()
        self.assertIn("restore verification failed", str(raised.exception))

    def test_deleted_review_decision_fails_verification(self):
        self.seed()
        SellerReviewDecision.objects.all().delete()
        with self.assertRaises(CommandError) as raised:
            self.verify()
        self.assertIn("restore verification failed", str(raised.exception))

    def test_deleted_seller_profile_fails_verification(self):
        self.seed()
        SellerProfile.objects.all().delete()
        with self.assertRaises(CommandError) as raised:
            self.verify()
        self.assertIn("restore verification failed", str(raised.exception))

    def test_deleted_decision_audit_fails_verification(self):
        self.seed()
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM audit_auditentry WHERE action = %s",
                ["seller_onboarding.application_decided"],
            )
        with self.assertRaises(CommandError) as raised:
            self.verify()
        self.assertIn("restore verification failed", str(raised.exception))

    def test_deleted_outbox_rows_fail_verification(self):
        self.seed()
        OutboxMessage.objects.all().delete()
        with self.assertRaises(CommandError) as raised:
            self.verify()
        self.assertIn("restore verification failed", str(raised.exception))

    def test_deleted_applied_migration_record_fails_verification(self):
        self.seed()
        MigrationRecorder(connection).migration_qs.all().delete()
        with self.assertRaises(CommandError) as raised:
            self.verify()
        self.assertIn("missing migrations:", str(raised.exception))

    def test_marker_format_is_bounded(self):
        for bad_marker in ("", "spaces not allowed", "a" * 65, "colon:bad"):
            with self.subTest(marker=bad_marker), self.assertRaises(CommandError):
                call_command("seed_restore_probe", "--marker", bad_marker, stdout=self.out)
