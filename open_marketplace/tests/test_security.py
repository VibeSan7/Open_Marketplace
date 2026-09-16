import hmac
import logging
from base64 import urlsafe_b64decode
from dataclasses import FrozenInstanceError, is_dataclass, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import StringIO
from importlib import import_module
from threading import Barrier, Lock, Thread
from unittest.mock import patch
from uuid import uuid4

from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from open_marketplace.common.errors import (
    ApplicationError,
    AuthenticationDenied,
    InputRejected,
    RateLimited,
)
from open_marketplace.common.types import OperationContext
from open_marketplace.identity.public import NeutralAccepted
from open_marketplace.staff_admin.tests.helpers import StaffAdminTestCase


class SecurityTestCase(TestCase):
    now = datetime(2026, 9, 2, 12, tzinfo=UTC)
    password = "Correct Horse Battery Staple 42!"

    def public(self):
        return import_module("open_marketplace.identity.public")

    def access_public(self):
        return import_module("open_marketplace.access.public")

    def account_model(self):
        return apps.get_model("identity", "Account")

    def token_model(self):
        return apps.get_model("identity", "OneTimeToken")

    def context(self, *, source="html", source_address="203.0.113.10", now=None):
        return OperationContext(
            actor_account_id=None,
            session_id=None,
            request_id=uuid4(),
            source=source,
            source_address=source_address,
            now=now or self.now,
        )

    def active_account(self, email="owner@example.com"):
        Account = self.account_model()
        return Account.objects.create_user(
            email=email,
            password=self.password,
            state=Account.State.ACTIVE,
            email_verified_at=self.now - timedelta(days=1),
        )

    def django_session_key(self):
        key = get_random_string(32, "abcdefghijklmnopqrstuvwxyz0123456789")
        Session.objects.create(
            session_key=key,
            session_data=SessionStore().encode({}),
            expire_date=self.now + timedelta(days=1),
        )
        return key

    def throttle(self, *, scope, account_key_hash, source_key_hash, now=None):
        public = self.public()
        self.assertTrue(hasattr(public, "check_throttle"))
        return public.check_throttle(
            scope=scope,
            account_key_hash=account_key_hash,
            source_key_hash=source_key_hash,
            now=now or self.now,
        )

    def throttle_model(self):
        try:
            return apps.get_model("identity", "SecurityThrottle")
        except LookupError:
            self.fail("Task 17 must add identity.SecurityThrottle.")

    def throttle_rows_text(self):
        model = self.throttle_model()
        return " ".join(
            str(value)
            for row in model.objects.all()
            for field in model._meta.concrete_fields
            for value in [getattr(row, field.name)]
        )

    def assert_decision(self, decision, *, allowed, retry_after_seconds):
        self.assertEqual(decision.allowed, allowed)
        self.assertEqual(decision.retry_after_seconds, retry_after_seconds)

    def request_password_reset(self, email, *, source_address):
        return self.public().request_password_reset(
            email=email,
            context=self.context(source_address=source_address),
        )

    def register(self, email, *, source_address):
        return self.public().register_account(
            email=email,
            password=self.password,
            context=self.context(source_address=source_address),
        )

    def authenticate(self, *, email, password, source_address, now=None):
        return self.public().authenticate_account(
            email=email,
            password=password,
            second_factor=None,
            django_session_key=self.django_session_key(),
            device_label="Security test browser",
            context=self.context(source_address=source_address, now=now),
        )

    def test_public_throttle_contract_is_immutable_and_returns_bounded_decisions(self):
        public = self.public()
        self.assertTrue(hasattr(public, "ThrottleDecision"))
        self.assertTrue(hasattr(public, "check_throttle"))
        decision_type = public.ThrottleDecision
        self.assertTrue(is_dataclass(decision_type))
        decision = decision_type(allowed=True, retry_after_seconds=0)
        self.assertEqual(
            {field.name for field in decision_type.__dataclass_fields__.values()},
            {"allowed", "retry_after_seconds"},
        )
        with self.assertRaises(FrozenInstanceError):
            decision.allowed = False
        self.assertEqual(decision.retry_after_seconds, 0)

    def test_throttle_rejects_invalid_scope_hashes_and_naive_time_without_creating_rows(self):
        valid = {
            "scope": "login",
            "account_key_hash": "a" * 64,
            "source_key_hash": "b" * 64,
            "now": self.now,
        }
        invalid_cases = (
            {"scope": "unknown"},
            {"account_key_hash": "A" * 64},
            {"source_key_hash": "short"},
            {"now": self.now.replace(tzinfo=None)},
        )

        for replacement in invalid_cases:
            with self.subTest(replacement=replacement), self.assertRaises(InputRejected):
                self.public().check_throttle(**(valid | replacement))

        self.assertEqual(self.throttle_model().objects.count(), 0)

    def test_cleanup_deletes_only_safely_expired_throttle_rows(self):
        model = self.throttle_model()
        stale_login = model.objects.create(
            scope=model.Scope.LOGIN,
            key_kind=model.KeyKind.ACCOUNT,
            key_hash="1" * 64,
            window_started_at=self.now - timedelta(minutes=17),
            allowed_attempt_count=6,
            blocked_until=self.now - timedelta(minutes=1),
        )
        stale_email = model.objects.create(
            scope=model.Scope.REGISTRATION_EMAIL,
            key_kind=model.KeyKind.SOURCE,
            key_hash="2" * 64,
            window_started_at=self.now - timedelta(hours=2),
            allowed_attempt_count=3,
            blocked_until=self.now - timedelta(hours=1),
        )
        active = model.objects.create(
            scope=model.Scope.LOGIN,
            key_kind=model.KeyKind.SOURCE,
            key_hash="3" * 64,
            window_started_at=self.now - timedelta(minutes=14),
            allowed_attempt_count=2,
        )
        still_blocked = model.objects.create(
            scope=model.Scope.LOGIN,
            key_kind=model.KeyKind.ACCOUNT,
            key_hash="4" * 64,
            window_started_at=self.now - timedelta(minutes=30),
            allowed_attempt_count=10,
            blocked_until=self.now + timedelta(minutes=1),
        )

        stdout = StringIO()
        with patch(
            "open_marketplace.identity.management.commands.purge_security_throttles.timezone.now",
            return_value=self.now,
        ):
            call_command("purge_security_throttles", stdout=stdout)

        self.assertEqual(stdout.getvalue(), "Deleted 2 expired security throttle rows.\n")
        self.assertFalse(model.objects.filter(pk__in=(stale_login.pk, stale_email.pk)).exists())
        self.assertEqual(
            set(model.objects.values_list("pk", flat=True)),
            {active.pk, still_blocked.pk},
        )

    def test_fixed_windows_reset_at_the_exact_boundary(self):
        for scope, window, limit, blocked_at, retry_after in (
            ("login", timedelta(minutes=15), 5, self.now, 5),
            (
                "registration_email",
                timedelta(hours=1),
                3,
                self.now + timedelta(seconds=1),
                3599,
            ),
        ):
            with self.subTest(scope=scope):
                for _ in range(limit):
                    self.assert_decision(
                        self.throttle(
                            scope=scope,
                            account_key_hash="a" * 64,
                            source_key_hash="b" * 64,
                        ),
                        allowed=True,
                        retry_after_seconds=0,
                    )
                self.assert_decision(
                    self.throttle(
                        scope=scope,
                        account_key_hash="a" * 64,
                        source_key_hash="b" * 64,
                        now=blocked_at,
                    ),
                    allowed=False,
                    retry_after_seconds=retry_after,
                )
                self.assert_decision(
                    self.throttle(
                        scope=scope,
                        account_key_hash="a" * 64,
                        source_key_hash="b" * 64,
                        now=self.now + window,
                    ),
                    allowed=True,
                    retry_after_seconds=0,
                )

    def test_login_delay_ladder_is_five_failures_then_5_10_20_40_and_60_seconds(self):
        scope = "login"
        for _ in range(5):
            self.assert_decision(
                self.throttle(
                    scope=scope,
                    account_key_hash="c" * 64,
                    source_key_hash="d" * 64,
                    now=self.now,
                ),
                allowed=True,
                retry_after_seconds=0,
            )

        checks = (
            (0, False, 5),
            (5, True, 0),
            (5, False, 10),
            (15, True, 0),
            (15, False, 20),
            (35, True, 0),
            (35, False, 40),
            (75, True, 0),
            (75, False, 60),
            (135, True, 0),
            (135, False, 60),
        )
        for seconds, allowed, retry_after_seconds in checks:
            with self.subTest(seconds=seconds, allowed=allowed):
                self.assert_decision(
                    self.throttle(
                        scope=scope,
                        account_key_hash="c" * 64,
                        source_key_hash="d" * 64,
                        now=self.now + timedelta(seconds=seconds),
                    ),
                    allowed=allowed,
                    retry_after_seconds=retry_after_seconds,
                )

    def test_login_account_and_source_counters_are_independent_and_success_keeps_evidence(self):
        account = self.active_account()
        for _ in range(4):
            with self.assertRaises(AuthenticationDenied):
                self.authenticate(
                    email=account.email,
                    password="wrong password",
                    source_address="198.51.100.10",
                )

        result = self.authenticate(
            email=account.email,
            password=self.password,
            source_address="198.51.100.11",
        )
        self.assertEqual(result.account_id, account.id)
        account.refresh_from_db()
        self.assertEqual(account.state, self.account_model().State.ACTIVE)

        with self.assertRaises(AuthenticationDenied):
            self.authenticate(
                email=account.email,
                password="wrong password",
                source_address="198.51.100.10",
            )
        try:
            self.authenticate(
                email=account.email,
                password="wrong password",
                source_address="198.51.100.10",
            )
        except RateLimited:
            pass
        except AuthenticationDenied as error:
            self.fail(f"the sixth failed login was not throttled: {error}")
        else:
            self.fail("the sixth failed login was accepted")
        Account = self.account_model()
        self.assertEqual(Account.objects.get(pk=account.pk).state, Account.State.ACTIVE)

    def test_login_block_expires_success_passes_and_failure_history_remains(self):
        account = self.active_account("recovered-login@example.com")
        source_address = "198.51.100.12"
        for _ in range(5):
            with self.assertRaises(AuthenticationDenied):
                self.authenticate(
                    email=account.email,
                    password="wrong password",
                    source_address=source_address,
                )

        with self.assertRaises(RateLimited):
            self.authenticate(
                email=account.email,
                password=self.password,
                source_address=source_address,
                now=self.now + timedelta(seconds=1),
            )

        result = self.authenticate(
            email=account.email,
            password=self.password,
            source_address=source_address,
            now=self.now + timedelta(seconds=6),
        )
        self.assertEqual(result.account_id, account.id)

        with self.assertRaises(AuthenticationDenied):
            self.authenticate(
                email=account.email,
                password="wrong password",
                source_address=source_address,
                now=self.now + timedelta(seconds=6),
            )
        with self.assertRaises(RateLimited):
            self.authenticate(
                email=account.email,
                password="wrong password",
                source_address=source_address,
                now=self.now + timedelta(seconds=6),
            )

    def test_email_limits_are_three_per_fixed_hour_by_purpose_account_and_source(self):
        for scope in ("registration_email", "password_reset_email"):
            with self.subTest(scope=scope, dimension="account"):
                for source_hash in ("1" * 64, "2" * 64, "3" * 64):
                    self.assert_decision(
                        self.throttle(
                            scope=scope,
                            account_key_hash="a" * 64,
                            source_key_hash=source_hash,
                        ),
                        allowed=True,
                        retry_after_seconds=0,
                    )
                self.assert_decision(
                    self.throttle(
                        scope=scope,
                        account_key_hash="a" * 64,
                        source_key_hash="4" * 64,
                    ),
                    allowed=False,
                    retry_after_seconds=3600,
                )

            with self.subTest(scope=scope, dimension="source"):
                for account_hash in ("5" * 64, "6" * 64, "7" * 64):
                    self.assert_decision(
                        self.throttle(
                            scope=scope,
                            account_key_hash=account_hash,
                            source_key_hash="b" * 64,
                        ),
                        allowed=True,
                        retry_after_seconds=0,
                    )
                self.assert_decision(
                    self.throttle(
                        scope=scope,
                        account_key_hash="8" * 64,
                        source_key_hash="b" * 64,
                    ),
                    allowed=False,
                    retry_after_seconds=3600,
                )

            for account_hash, source_hash in (
                ("a" * 64, "4" * 64),
                ("8" * 64, "b" * 64),
            ):
                self.assert_decision(
                    self.throttle(
                        scope=scope,
                        account_key_hash=account_hash,
                        source_key_hash=source_hash,
                        now=self.now + timedelta(hours=1),
                    ),
                    allowed=True,
                    retry_after_seconds=0,
                )

    def test_registration_throttling_keeps_known_and_unknown_requests_neutral_without_side_effects(self):
        known = self.active_account("known-registration@example.com")
        cases = (
            (known.email, "198.51.100.20"),
            ("unknown-registration@example.com", "198.51.100.21"),
        )
        for email, source_address in cases:
            with self.subTest(email=email):
                for _ in range(3):
                    self.assertEqual(
                        self.register(email, source_address=source_address),
                        NeutralAccepted(accepted=True),
                    )
                before = {
                    "accounts": self.account_model().objects.count(),
                    "tokens": self.token_model().objects.count(),
                    "audits": apps.get_model("audit", "AuditEntry").objects.count(),
                    "outbox": apps.get_model("outbox", "OutboxMessage").objects.count(),
                }
                self.assertEqual(
                    self.register(email, source_address=source_address),
                    NeutralAccepted(accepted=True),
                )
                self.assertEqual(
                    {
                        "accounts": self.account_model().objects.count(),
                        "tokens": self.token_model().objects.count(),
                        "audits": apps.get_model("audit", "AuditEntry").objects.count(),
                        "outbox": apps.get_model("outbox", "OutboxMessage").objects.count(),
                    },
                    before,
                )

    def test_password_reset_throttling_keeps_known_and_unknown_requests_neutral_without_side_effects(self):
        known = self.active_account("known-reset@example.com")
        cases = (
            (known.email, "198.51.100.30"),
            ("unknown-reset@example.com", "198.51.100.31"),
        )
        for email, source_address in cases:
            with self.subTest(email=email):
                for _ in range(3):
                    self.assertEqual(
                        self.request_password_reset(email, source_address=source_address),
                        NeutralAccepted(accepted=True),
                    )
                before = {
                    "tokens": self.token_model().objects.count(),
                    "audits": apps.get_model("audit", "AuditEntry").objects.count(),
                    "outbox": apps.get_model("outbox", "OutboxMessage").objects.count(),
                }
                self.assertEqual(
                    self.request_password_reset(email, source_address=source_address),
                    NeutralAccepted(accepted=True),
                )
                self.assertEqual(
                    {
                        "tokens": self.token_model().objects.count(),
                        "audits": apps.get_model("audit", "AuditEntry").objects.count(),
                        "outbox": apps.get_model("outbox", "OutboxMessage").objects.count(),
                    },
                    before,
                )

    def test_html_registration_uses_remote_addr_and_rejects_missing_server_address(self):
        client = Client(enforce_csrf_checks=True)
        response = client.get(reverse("register"), REMOTE_ADDR="198.51.100.40")
        token = client.cookies["csrftoken"].value
        response = client.post(
            reverse("register"),
            {
                "csrfmiddlewaretoken": token,
                "email": "missing-source@example.com",
                "password": self.password,
            },
            REMOTE_ADDR="",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            self.account_model()
            .objects.filter(email="missing-source@example.com")
            .exists()
        )

    def test_hmac_throttle_rows_are_scoped_and_never_contain_email_ip_or_forwarded_header(self):
        email = "Canonical.Security@example.com"
        source = "198.51.100.50"
        spoofed = "203.0.113.250"
        self.active_account("canonical.security@example.com")
        client = Client(enforce_csrf_checks=True)
        client.get(reverse("register"), REMOTE_ADDR=source)
        registration_csrf = client.cookies["csrftoken"].value
        for registration_email, forwarded in (
            (email, spoofed),
            (email.casefold(), "192.0.2.250"),
        ):
            registration_response = client.post(
                reverse("register"),
                {
                    "csrfmiddlewaretoken": registration_csrf,
                    "email": registration_email,
                    "password": self.password,
                },
                REMOTE_ADDR=source,
                HTTP_X_FORWARDED_FOR=forwarded,
            )
            self.assertEqual(registration_response.status_code, 200)
            self.assertContains(registration_response, "Если данные подходят, проверьте электронную почту.")
        get_response = client.get(reverse("password-reset-request"), REMOTE_ADDR=source)
        token = client.cookies["csrftoken"].value
        post_response = client.post(
            reverse("password-reset-request"),
            {
                "csrfmiddlewaretoken": token,
                "email": email,
            },
            REMOTE_ADDR=source,
            HTTP_X_FORWARDED_FOR=spoofed,
        )
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(post_response.status_code, 200)

        model = self.throttle_model()
        rows = list(model.objects.all())
        self.assertTrue(rows)
        self.assertTrue(all(len(row.key_hash) == 64 for row in rows))
        scopes = {row.scope for row in rows}
        self.assertIn("registration_email", scopes)
        self.assertIn("password_reset_email", scopes)
        registration_rows = [
            row for row in rows if row.scope == "registration_email"
        ]
        reset_rows = [row for row in rows if row.scope == "password_reset_email"]
        self.assertEqual(
            {row.key_kind for row in registration_rows},
            {"account", "source"},
        )
        self.assertEqual({row.key_kind for row in reset_rows}, {"account", "source"})
        self.assertEqual(len(registration_rows), 2)
        self.assertEqual(len(reset_rows), 2)

        key = urlsafe_b64decode(settings.THROTTLE_HASH_KEY.encode("ascii"))
        expected_registration_hashes = {
            hmac.new(
                key,
                b"registration_email\0account\0canonical.security@example.com",
                sha256,
            ).hexdigest(),
            hmac.new(
                key,
                b"registration_email\0source\0" + source.encode("ascii"),
                sha256,
            ).hexdigest(),
        }
        self.assertEqual(
            {row.key_hash for row in registration_rows},
            expected_registration_hashes,
        )
        self.assertTrue(
            expected_registration_hashes.isdisjoint(
                {row.key_hash for row in reset_rows}
            )
        )

        audit_text = " ".join(
            str(value)
            for row in apps.get_model("audit", "AuditEntry").objects.all()
            for value in row.__dict__.values()
        )
        self.assertNotIn(email, self.throttle_rows_text())
        self.assertNotIn(source, self.throttle_rows_text())
        self.assertNotIn(spoofed, self.throttle_rows_text())
        self.assertNotIn(email.casefold(), audit_text)
        self.assertNotIn(source, audit_text)
        self.assertNotIn(spoofed, audit_text)

        records = []
        logger = logging.getLogger("open_marketplace")
        handler = logging.Handler()
        handler.emit = records.append
        logger.addHandler(handler)
        try:
            self.register("log-check@example.com", source_address=source)
        finally:
            logger.removeHandler(handler)
        log_text = " ".join(record.getMessage() for record in records)
        self.assertNotIn("log-check@example.com", log_text)
        self.assertNotIn(source, log_text)


class StaffInvitationThrottleTests(StaffAdminTestCase):
    def test_throttled_staff_invitation_is_bounded_and_creates_no_new_rows(self):
        public = self.public_module()
        _, _, context = self.prepare_authorized_actor()
        email = "throttled-invitation@example.com"
        invitation_model = apps.get_model("access", "StaffInvitation")
        outbox_model = apps.get_model("outbox", "OutboxMessage")
        audit_model = apps.get_model("audit", "AuditEntry")

        for _ in range(3):
            public.invite_staff_member(email=email, role="seller_reviewer", context=context)
        before = {
            "invitations": invitation_model.objects.count(),
            "outbox": outbox_model.objects.count(),
            "audits": audit_model.objects.count(),
        }
        with self.assertRaises(RateLimited) as raised:
            public.invite_staff_member(email=email, role="seller_reviewer", context=context)
        self.assertIsInstance(raised.exception, ApplicationError)
        self.assertLessEqual(len(str(raised.exception)), 128)
        self.assertEqual(
            {
                "invitations": invitation_model.objects.count(),
                "outbox": outbox_model.objects.count(),
                "audits": audit_model.objects.count(),
            },
            before,
        )

    def test_admin_staff_invitation_uses_remote_addr_and_bounded_error_page(self):
        self.authenticate_staff("security_admin")
        email = "admin-throttled@example.com"
        url = reverse("admin:staff-invitation-create")
        for _ in range(3):
            response = self.client.get("/admin/", REMOTE_ADDR="198.51.100.60")
            self.assertEqual(response.status_code, 200)
            csrf = self.client.cookies["csrftoken"].value
            response = self.client.post(
                url,
                {
                    "csrfmiddlewaretoken": csrf,
                    "email": email,
                    "role": "seller_reviewer",
                },
                REMOTE_ADDR="198.51.100.60",
            )
            self.assertEqual(response.status_code, 303)
        response = self.client.get("/admin/", REMOTE_ADDR="198.51.100.60")
        self.assertEqual(response.status_code, 200)
        csrf = self.client.cookies["csrftoken"].value
        invitation_count = apps.get_model("access", "StaffInvitation").objects.count()
        outbox_count = apps.get_model("outbox", "OutboxMessage").objects.count()
        response = self.client.post(
            url,
            {
                "csrfmiddlewaretoken": csrf,
                "email": email,
                "role": "seller_reviewer",
            },
            REMOTE_ADDR="198.51.100.60",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The request could not be completed.")
        self.assertNotContains(response, "198.51.100.60")
        self.assertEqual(
            apps.get_model("access", "StaffInvitation").objects.count(),
            invitation_count,
        )
        self.assertEqual(
            apps.get_model("outbox", "OutboxMessage").objects.count(),
            outbox_count,
        )

    def test_admin_application_rejects_missing_server_address_but_bootstrap_command_is_exempt(self):
        command_context = OperationContext(
            actor_account_id=None,
            session_id=None,
            request_id=uuid4(),
            source="command",
            source_address=None,
            now=self.now,
        )
        invitation_id = self.public_module().bootstrap_security_admin(
            email="bootstrap-without-source@example.com",
            context=command_context,
        )
        self.assertIsNotNone(invitation_id)

        actor, registry, context = self.prepare_authorized_actor()
        missing_address = replace(
            context,
            actor_account_id=actor.id,
            session_id=registry.id,
            source_address=None,
        )
        with self.assertRaises(InputRejected):
            self.public_module().invite_staff_member(
                email="missing-admin-source@example.com",
                role="seller_reviewer",
                context=missing_address,
            )


class SecurityThrottleConcurrencyTests(TransactionTestCase):
    reset_sequences = True
    now = datetime(2026, 9, 2, 12, tzinfo=UTC)

    def public(self):
        return import_module("open_marketplace.identity.public")

    def run_parallel(self, operation, *, worker_count):
        barrier = Barrier(worker_count + 1)
        guard = Lock()
        results = []
        errors = []

        def worker(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                value = operation(index)
                with guard:
                    results.append(value)
            except Exception as error:
                with guard:
                    errors.append(error)
            finally:
                close_old_connections()

        threads = [Thread(target=worker, args=(index,)) for index in range(worker_count)]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=10)
        for thread in threads:
            thread.join(timeout=15)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        return results

    def check(self, *, scope):
        return self.public().check_throttle(
            scope=scope,
            account_key_hash="a" * 64,
            source_key_hash="b" * 64,
            now=self.now,
        )

    def test_simultaneous_login_updates_lose_no_attempts(self):
        results = self.run_parallel(self._login_attempt, worker_count=8)
        self.assertEqual(len(results), 8)
        self.assertEqual(sum(result.allowed for result in results), 5)
        self.assertEqual(sum(not result.allowed for result in results), 3)

    def _login_attempt(self, _index):
        return self.check(scope="login")

    def test_simultaneous_email_updates_do_not_over_admit_requests(self):
        results = self.run_parallel(self._email_attempt, worker_count=8)
        self.assertEqual(len(results), 8)
        self.assertEqual(sum(result.allowed for result in results), 3)
        self.assertEqual(sum(not result.allowed for result in results), 5)

    def _email_attempt(self, _index):
        return self.public().check_throttle(
            scope="registration_email",
            account_key_hash="c" * 64,
            source_key_hash="d" * 64,
            now=self.now,
        )
