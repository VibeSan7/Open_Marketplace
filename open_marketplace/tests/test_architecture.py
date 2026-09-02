import os
import subprocess
import sys
from base64 import urlsafe_b64encode
from datetime import UTC, datetime, timedelta
from unittest import TestCase
from uuid import uuid4

from django.conf import settings
from django.test import SimpleTestCase


class CommonPrimitivesTests(TestCase):
    def test_operation_context_preserves_actor_metadata(self):
        from open_marketplace.common import types

        self.assertTrue(hasattr(types, "OperationContext"))
        OperationContext = types.OperationContext

        actor_account_id = uuid4()
        session_id = uuid4()
        request_id = uuid4()
        now = datetime.now(UTC)

        context = OperationContext(
            actor_account_id=actor_account_id,
            session_id=session_id,
            request_id=request_id,
            source="html",
            source_address="192.0.2.1",
            now=now,
        )

        self.assertEqual(context.actor_account_id, actor_account_id)
        self.assertEqual(context.session_id, session_id)
        self.assertEqual(context.request_id, request_id)
        self.assertEqual(context.source, "html")
        self.assertEqual(context.source_address, "192.0.2.1")
        self.assertEqual(context.now, now)

    def test_authorization_decision_preserves_scope_metadata(self):
        from open_marketplace.common import types

        self.assertTrue(hasattr(types, "AuthorizationDecision"))
        AuthorizationDecision = types.AuthorizationDecision

        account_id = uuid4()
        reauthenticated_at = datetime.now(UTC)

        decision = AuthorizationDecision(
            account_id=account_id,
            permission="seller.review",
            effective_roles=("reviewer",),
            scopes=("seller:pending",),
            reauthenticated_at=reauthenticated_at,
        )

        self.assertEqual(decision.account_id, account_id)
        self.assertEqual(decision.permission, "seller.review")
        self.assertEqual(decision.effective_roles, ("reviewer",))
        self.assertEqual(decision.scopes, ("seller:pending",))
        self.assertEqual(decision.reauthenticated_at, reauthenticated_at)

    def test_system_clock_returns_current_utc_time(self):
        from open_marketplace.common import clock

        self.assertTrue(hasattr(clock, "SystemClock"))
        SystemClock = clock.SystemClock

        before = datetime.now(UTC)
        current = SystemClock().now()
        after = datetime.now(UTC)

        self.assertLessEqual(before, current)
        self.assertLessEqual(current, after)
        self.assertIs(current.tzinfo, UTC)


class EnvironmentValidationTests(TestCase):
    required_secrets = (
        "DJANGO_SECRET_KEY",
        "DATABASE_PASSWORD",
        "TOTP_ENCRYPTION_KEY",
        "OUTBOX_ENCRYPTION_KEY",
        "LINK_EXCHANGE_ENCRYPTION_KEY",
        "THROTTLE_HASH_KEY",
    )

    def run_settings_import(self, *, unset=None, overrides=None):
        environment = os.environ.copy()
        if unset is not None:
            environment.pop(unset, None)
        environment.update(overrides or {})
        return subprocess.run(
            [sys.executable, "-c", "import open_marketplace.config.settings"],
            capture_output=True,
            check=False,
            env=environment,
            text=True,
        )

    def assert_rejected_without_value(self, name, *, unset=False, value=None):
        result = self.run_settings_import(
            unset=name if unset else None,
            overrides=None if unset else {name: value},
        )
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(name, output)
        if value:
            self.assertNotIn(value, output)

    def test_required_secrets_reject_missing_and_empty_values(self):
        for name in self.required_secrets:
            with self.subTest(name=name, case="missing"):
                self.assert_rejected_without_value(name, unset=True)
            with self.subTest(name=name, case="empty"):
                self.assert_rejected_without_value(name, value="")

    def test_fernet_keys_reject_malformed_or_wrong_length_values(self):
        invalid_values = (
            "not-a-fernet-key",
            urlsafe_b64encode(b"x" * 31).decode("ascii"),
        )
        for name in (
            "TOTP_ENCRYPTION_KEY",
            "OUTBOX_ENCRYPTION_KEY",
            "LINK_EXCHANGE_ENCRYPTION_KEY",
        ):
            for value in invalid_values:
                with self.subTest(name=name, value_kind=len(value)):
                    self.assert_rejected_without_value(name, value=value)

    def test_throttle_hash_key_rejects_fewer_than_32_bytes(self):
        value = urlsafe_b64encode(b"x" * 31).decode("ascii")
        self.assert_rejected_without_value("THROTTLE_HASH_KEY", value=value)

    def test_app_base_url_rejects_values_that_are_not_a_clean_origin(self):
        self.assert_rejected_without_value("APP_BASE_URL", unset=True)
        self.assert_rejected_without_value("APP_BASE_URL", value="")
        invalid_values = (
            "localhost:8000",
            "ftp://localhost",
            "http://localhost:",
            "http://local host",
            "http://user:password@localhost",
            "http://localhost/path",
            "http://localhost/?query=1",
            "http://localhost/#fragment",
        )
        for case, value in enumerate(invalid_values):
            with self.subTest(case=case):
                self.assert_rejected_without_value("APP_BASE_URL", value=value)


class ProjectSmokeTests(SimpleTestCase):
    def test_postgresql_is_the_only_database_engine(self):
        self.assertEqual(
            settings.DATABASES["default"]["ENGINE"],
            "django.db.backends.postgresql",
        )

    def test_drf_is_not_installed(self):
        self.assertNotIn("rest_framework", settings.INSTALLED_APPS)

    def test_phase_one_security_values_are_exact(self):
        expected = {
            "EMAIL_VERIFICATION_TTL": timedelta(hours=24),
            "PASSWORD_RESET_TTL": timedelta(minutes=30),
            "STAFF_INVITATION_TTL": timedelta(hours=24),
            "MANDATORY_TOTP_RECOVERY_TTL": timedelta(minutes=30),
            "SENSITIVE_ACTION_REAUTH_TTL": timedelta(minutes=15),
            "TOTP_SETUP_TTL": timedelta(minutes=10),
            "RECOVERY_CODE_COUNT": 10,
            "PASSWORD_MIN_LENGTH": 12,
            "PASSWORD_MAX_LENGTH": 128,
            "ORDINARY_SESSION_ABSOLUTE_TTL": timedelta(days=30),
            "SERVICE_SESSION_ABSOLUTE_TTL": timedelta(hours=12),
            "SERVICE_SESSION_IDLE_TTL": timedelta(minutes=30),
            "LOGIN_THROTTLE_THRESHOLD": 5,
            "LOGIN_THROTTLE_WINDOW": timedelta(minutes=15),
            "EMAIL_THROTTLE_LIMIT": 3,
            "EMAIL_THROTTLE_WINDOW": timedelta(hours=1),
        }
        for name, value in expected.items():
            with self.subTest(name=name):
                self.assertEqual(getattr(settings, name), value)

        validators = {
            item["NAME"] for item in settings.AUTH_PASSWORD_VALIDATORS
        }
        self.assertIn(
            "django.contrib.auth.password_validation.CommonPasswordValidator",
            validators,
        )
