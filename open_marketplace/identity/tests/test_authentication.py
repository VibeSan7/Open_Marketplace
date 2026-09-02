import hmac
from base64 import urlsafe_b64decode
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from importlib import import_module
from uuid import uuid4
from unittest.mock import patch

from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.test import TestCase
from django.utils.crypto import get_random_string

from open_marketplace.audit.public import AuditQuery, query_audit_entries
from open_marketplace.common.errors import AuthenticationDenied, InputRejected
from open_marketplace.common.types import AuthorizationDecision, OperationContext
from open_marketplace.identity.models import Account


class AuthenticationTests(TestCase):
    now = datetime(2026, 9, 2, 12, tzinfo=UTC)
    password = f"T3st!{uuid4().hex}"
    other_password = f"Alt!{uuid4().hex}"

    def public_module(self):
        public = import_module("open_marketplace.identity.public")
        for name in (
            "AuthenticationResult",
            "SessionSecuritySnapshot",
            "SessionView",
            "authenticate_account",
        ):
            self.assertTrue(hasattr(public, name), f"{name} must be public.")
        return public

    def session_model(self):
        models = import_module("open_marketplace.identity.models")
        self.assertTrue(hasattr(models, "AccountSession"), "AccountSession must exist.")
        return models.AccountSession

    def context(self, *, request_id=None, now=None, source_address="203.0.113.10"):
        return OperationContext(
            actor_account_id=None,
            session_id=None,
            request_id=request_id or uuid4(),
            source="html",
            source_address=source_address,
            now=now or self.now,
        )

    def create_account(
        self,
        *,
        email="person@example.com",
        kind=Account.Kind.ORDINARY,
        state=Account.State.ACTIVE,
        password=None,
    ):
        create = (
            Account.objects.create_service_account
            if kind == Account.Kind.SERVICE
            else Account.objects.create_user
        )
        return create(
            email=email,
            password=password or self.password,
            state=state,
            email_verified_at=(
                None
                if state == Account.State.PENDING_EMAIL_VERIFICATION
                else self.now - timedelta(days=1)
            ),
        )

    def create_django_session(self, *, expires_at=None):
        key = get_random_string(32, "abcdefghijklmnopqrstuvwxyz0123456789")
        Session.objects.create(
            session_key=key,
            session_data=SessionStore().encode({}),
            expire_date=expires_at or self.now + timedelta(hours=1),
        )
        return key

    def authenticate(
        self,
        *,
        email="person@example.com",
        password=None,
        django_session_key=None,
        device_label="Firefox on Linux",
        context=None,
    ):
        return self.public_module().authenticate_account(
            email=email,
            password=self.password if password is None else password,
            second_factor=None,
            django_session_key=(
                self.create_django_session()
                if django_session_key is None
                else django_session_key
            ),
            device_label=device_label,
            context=context or self.context(),
        )

    def audit_entries(self):
        actor_id = uuid4()
        context = OperationContext(
            actor_account_id=actor_id,
            session_id=uuid4(),
            request_id=uuid4(),
            source="admin",
            source_address=None,
            now=self.now + timedelta(days=60),
        )

        def authorize(received_context, permission):
            self.assertIs(received_context, context)
            self.assertEqual(permission, "audit.read")
            return AuthorizationDecision(
                account_id=actor_id,
                permission="audit.read",
                effective_roles=("security_admin",),
                scopes=("audit:object_type:account", "audit:object_type:session", "audit:object_type:authentication_attempt"),
                reauthenticated_at=context.now,
            )

        return query_audit_entries(
            query=AuditQuery(
                from_at=None,
                to_at=None,
                actor_id=None,
                action=None,
                object_type=None,
                object_id=None,
                result=None,
                limit=100,
                cursor=None,
            ),
            context=context,
            authorize=authorize,
        )

    def fingerprint(self, scope, value):
        key = urlsafe_b64decode(settings.THROTTLE_HASH_KEY.encode("ascii"))
        return hmac.new(
            key,
            f"{scope}\0{value}".encode("utf-8"),
            sha256,
        ).hexdigest()

    def test_success_binds_verified_account_to_fresh_server_session_atomically(self):
        SessionModel = self.session_model()
        public = self.public_module()
        account = self.create_account()
        django_key = self.create_django_session()
        context = self.context()
        hostile_label = "  Firefox\x00\n on <script>  " + "x" * 250

        result = self.authenticate(
            django_session_key=django_key,
            device_label=hostile_label,
            context=context,
        )

        self.assertIsInstance(result, public.AuthenticationResult)
        self.assertEqual(result.account_id, account.id)
        self.assertEqual(result.kind, Account.Kind.ORDINARY)
        self.assertEqual(result.authenticated_at, context.now)
        with self.assertRaises(FrozenInstanceError):
            result.account_id = uuid4()

        registry = SessionModel.objects.get()
        self.assertEqual(result.session_id, registry.id)
        self.assertEqual(registry.account_id, account.id)
        self.assertEqual(registry.django_session_key, django_key)
        self.assertEqual(registry.created_at, context.now)
        self.assertEqual(registry.last_activity_at, context.now)
        self.assertEqual(registry.absolute_expires_at, context.now + timedelta(days=30))
        self.assertEqual(registry.reauthenticated_at, context.now)
        self.assertIsNone(registry.revoked_at)
        self.assertIsNone(registry.revoked_reason)
        self.assertEqual(len(registry.device_label), 200)
        self.assertTrue(registry.device_label.startswith("Firefox on <script> "))
        self.assertNotIn("\x00", registry.device_label)
        self.assertNotIn("\n", registry.device_label)

        entries = sorted(self.audit_entries(), key=lambda entry: entry.action)
        self.assertEqual(
            [entry.action for entry in entries],
            ["identity.authentication_succeeded", "identity.session_created"],
        )
        self.assertTrue(all(entry.actor_id == account.id for entry in entries))
        self.assertTrue(all(entry.request_id == context.request_id for entry in entries))
        serialized = repr((result, entries))
        for secret in (django_key, self.password, account.email, context.source_address):
            self.assertNotIn(secret, serialized)

    def test_unknown_wrong_blocked_and_unverified_failures_are_neutral_and_safe(self):
        SessionModel = self.session_model()
        self.public_module()
        active = self.create_account(email="active@example.com")
        blocked = self.create_account(
            email="blocked@example.com",
            state=Account.State.BLOCKED,
        )
        pending = self.create_account(
            email="pending@example.com",
            state=Account.State.PENDING_EMAIL_VERIFICATION,
        )
        attempts = (
            ("unknown@example.com", self.password),
            (active.email, self.other_password),
            (blocked.email, self.password),
            (pending.email, self.password),
        )
        messages = set()
        request_ids = []
        for email, password in attempts:
            context = self.context(request_id=uuid4(), source_address="198.51.100.77")
            request_ids.append(context.request_id)
            with self.subTest(email=email), self.assertRaises(AuthenticationDenied) as raised:
                self.authenticate(email=email, password=password, context=context)
            messages.add(str(raised.exception))
            self.assertNotIn(email, str(raised.exception))
            self.assertNotIn(password, str(raised.exception))

        self.assertEqual(messages, {"Authentication failed."})
        self.assertEqual(SessionModel.objects.count(), 0)
        entries = [
            entry
            for entry in self.audit_entries()
            if entry.request_id in request_ids
        ]
        self.assertEqual(len(entries), 4)
        self.assertTrue(all(entry.action == "identity.authentication_failed" for entry in entries))
        self.assertTrue(all(entry.actor_id is None for entry in entries))
        self.assertTrue(all(entry.object_type == "authentication_attempt" for entry in entries))
        self.assertTrue(all(entry.object_id == str(entry.request_id) for entry in entries))
        self.assertTrue(all(entry.result == "failed" for entry in entries))
        self.assertTrue(all(entry.reason == "authentication_failed" for entry in entries))
        self.assertTrue(
            all(
                set(entry.after) == {"subject_fingerprint", "source_fingerprint"}
                for entry in entries
            )
        )
        self.assertTrue(
            all(
                entry.after["source_fingerprint"]
                == self.fingerprint("login-source", "198.51.100.77")
                for entry in entries
            )
        )
        serialized = repr(entries)
        for value in (
            "unknown@example.com",
            active.email,
            blocked.email,
            pending.email,
            "198.51.100.77",
            self.password,
            self.other_password,
        ):
            self.assertNotIn(value, serialized)

    def test_login_requires_existing_unexpired_unclaimed_django_session_key(self):
        SessionModel = self.session_model()
        self.create_account()
        missing_key = get_random_string(32, "abcdefghijklmnopqrstuvwxyz0123456789")
        expired_key = self.create_django_session(expires_at=self.now)

        for key in (missing_key, expired_key, "short"):
            with self.subTest(key_kind=len(key)), self.assertRaises(InputRejected) as raised:
                self.authenticate(django_session_key=key)
            self.assertNotIn(key, str(raised.exception))
        self.assertEqual(SessionModel.objects.count(), 0)

        claimed_key = self.create_django_session()
        self.authenticate(django_session_key=claimed_key)
        self.assertEqual(SessionModel.objects.count(), 1)
        with self.assertRaises(InputRejected) as raised:
            self.authenticate(django_session_key=claimed_key)
        self.assertNotIn(claimed_key, str(raised.exception))
        self.assertEqual(SessionModel.objects.count(), 1)

    def test_service_account_uses_service_absolute_ttl(self):
        SessionModel = self.session_model()
        account = self.create_account(kind=Account.Kind.SERVICE)

        result = self.authenticate()

        registry = SessionModel.objects.get(pk=result.session_id)
        self.assertEqual(result.account_id, account.id)
        self.assertEqual(result.kind, Account.Kind.SERVICE)
        self.assertEqual(registry.absolute_expires_at, self.now + timedelta(hours=12))

    def test_registry_and_success_audit_roll_back_together(self):
        SessionModel = self.session_model()
        self.create_account()
        django_key = self.create_django_session()

        with patch(
            "open_marketplace.identity.application.append_audit_entry",
            side_effect=RuntimeError("audit unavailable"),
        ), self.assertRaises(RuntimeError):
            self.authenticate(django_session_key=django_key)

        self.assertEqual(SessionModel.objects.count(), 0)
        self.assertTrue(Session.objects.filter(session_key=django_key).exists())
        self.assertEqual(self.audit_entries(), ())
