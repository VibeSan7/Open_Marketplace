import json
from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import uuid4
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.test import TestCase
from django.utils.crypto import get_random_string

from open_marketplace.audit.public import AuditQuery, query_audit_entries
from open_marketplace.common.crypto import generate_one_time_token, hash_one_time_token
from open_marketplace.common.errors import AuthenticationDenied, InputRejected
from open_marketplace.common.types import AuthorizationDecision, OperationContext
from open_marketplace.identity.models import Account, AccountSession, OneTimeToken
from open_marketplace.outbox.public import claim_ready_messages


class PasswordOperationTests(TestCase):
    now = datetime(2026, 9, 2, 12, tzinfo=UTC)
    password = f"T3st!{uuid4().hex}"
    new_password = f"N3w!{uuid4().hex}"

    def public_module(self):
        public = import_module("open_marketplace.identity.public")
        for name in ("request_password_reset", "reset_password", "change_password"):
            self.assertTrue(hasattr(public, name), f"{name} must be public.")
        return public

    def anonymous_context(self, *, now=None, request_id=None):
        return OperationContext(
            actor_account_id=None,
            session_id=None,
            request_id=request_id or uuid4(),
            source="html",
            source_address="203.0.113.10",
            now=now or self.now,
        )

    def authenticated_context(self, registry, *, now=None):
        return OperationContext(
            actor_account_id=registry.account_id,
            session_id=registry.id,
            request_id=uuid4(),
            source="html",
            source_address="203.0.113.10",
            now=now or self.now,
        )

    def create_account(
        self,
        *,
        email=None,
        kind=Account.Kind.ORDINARY,
        state=Account.State.ACTIVE,
    ):
        create = (
            Account.objects.create_service_account
            if kind == Account.Kind.SERVICE
            else Account.objects.create_user
        )
        return create(
            email=email or f"person-{uuid4()}@example.com",
            password=self.password,
            state=state,
            email_verified_at=(
                None
                if state == Account.State.PENDING_EMAIL_VERIFICATION
                else self.now - timedelta(days=1)
            ),
        )

    def create_registry(self, account, *, absolute_expires_at=None):
        key = get_random_string(32, "abcdefghijklmnopqrstuvwxyz0123456789")
        Session.objects.create(
            session_key=key,
            session_data=SessionStore().encode({}),
            expire_date=self.now + timedelta(days=31),
        )
        created_at = self.now - timedelta(hours=1)
        return AccountSession.objects.create(
            account=account,
            django_session_key=key,
            created_at=created_at,
            last_activity_at=created_at,
            absolute_expires_at=absolute_expires_at or self.now + timedelta(days=1),
            reauthenticated_at=created_at,
            device_label="Firefox on Linux",
        )

    def create_token(
        self,
        account,
        *,
        purpose=OneTimeToken.Purpose.PASSWORD_RESET,
        created_at=None,
        expires_at=None,
        used_at=None,
        revoked_at=None,
        revoked_reason=None,
    ):
        raw_token, digest = generate_one_time_token()
        created_at = created_at or self.now
        token = OneTimeToken.objects.create(
            account=account,
            purpose=purpose,
            token_digest=digest,
            created_at=created_at,
            expires_at=expires_at or created_at + timedelta(minutes=30),
            used_at=used_at,
            revoked_at=revoked_at,
            revoked_reason=revoked_reason,
        )
        return raw_token, token

    def request_reset(self, email, *, context=None):
        return self.public_module().request_password_reset(
            email=email,
            context=context or self.anonymous_context(),
        )

    def claim_outbox(self, *, now=None):
        return claim_ready_messages(
            worker_id=f"test:{uuid4()}",
            now=now or self.now,
            lease_seconds=300,
            limit=100,
        )

    def decrypt_delivery(self, message):
        plaintext = Fernet(settings.OUTBOX_ENCRYPTION_KEY.encode("ascii")).decrypt(
            bytes(message.encrypted_delivery)
        )
        return json.loads(plaintext.decode("utf-8"))

    def reset_token_from_message(self, message):
        delivery = self.decrypt_delivery(message)
        prefix = f"{settings.APP_BASE_URL}/identity/reset-password/"
        url = delivery["absolute_token_url"]
        self.assertTrue(url.startswith(prefix))
        self.assertTrue(url.endswith("/"))
        return url[len(prefix) : -1], delivery

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
                scopes=("audit:object_type:account", "audit:object_type:session"),
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

    def test_request_is_neutral_and_issues_exact_digest_only_token_audit_and_outbox(self):
        public = self.public_module()
        account = self.create_account(email="person@example.com")
        context = self.anonymous_context()

        result = self.request_reset(" PERSON@example.com ", context=context)

        self.assertEqual(result, public.NeutralAccepted(accepted=True))
        token = OneTimeToken.objects.get()
        self.assertEqual(token.account_id, account.id)
        self.assertEqual(token.purpose, OneTimeToken.Purpose.PASSWORD_RESET)
        self.assertEqual(token.created_at, context.now)
        self.assertEqual(token.expires_at, context.now + timedelta(minutes=30))
        self.assertRegex(token.token_digest, r"^[0-9a-f]{64}$")
        self.assertIsNone(token.used_at)
        self.assertIsNone(token.revoked_at)

        messages = self.claim_outbox()
        self.assertEqual(len(messages), 1)
        message = messages[0]
        self.assertEqual(message.message_type, "identity.password_reset")
        self.assertEqual(message.format_version, 1)
        self.assertEqual(
            dict(message.payload),
            {"account_id": str(account.id), "token_id": str(token.id)},
        )
        raw_token, delivery = self.reset_token_from_message(message)
        self.assertEqual(token.token_digest, hash_one_time_token(raw_token))
        self.assertEqual(delivery["recipient"], account.email)
        self.assertNotIn(raw_token, repr(token))

        entries = self.audit_entries()
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.action, "identity.password_reset_requested")
        self.assertIsNone(entry.actor_id)
        self.assertEqual(entry.object_id, str(account.id))
        self.assertEqual(entry.after["token_purpose"], "password_reset")
        serialized = repr((entry, message.payload))
        for secret in (raw_token, token.token_digest, account.email):
            self.assertNotIn(secret, serialized)

    def test_unknown_pending_and_invalid_requests_do_not_mutate_while_eligible_kinds_do(self):
        public = self.public_module()
        pending_ordinary = self.create_account(state=Account.State.PENDING_EMAIL_VERIFICATION)
        pending_service = self.create_account(
            kind=Account.Kind.SERVICE,
            state=Account.State.PENDING_EMAIL_VERIFICATION,
        )
        eligible = (
            self.create_account(state=Account.State.BLOCKED),
            self.create_account(kind=Account.Kind.SERVICE),
            self.create_account(kind=Account.Kind.SERVICE, state=Account.State.BLOCKED),
        )

        results = [
            self.request_reset("unknown@example.com"),
            self.request_reset(pending_ordinary.email),
            self.request_reset(pending_service.email),
        ]
        results.extend(self.request_reset(account.email) for account in eligible)

        self.assertTrue(all(result == public.NeutralAccepted(accepted=True) for result in results))
        self.assertEqual(
            set(OneTimeToken.objects.values_list("account_id", flat=True)),
            {account.id for account in eligible},
        )
        self.assertEqual(len(self.claim_outbox()), 3)
        self.assertEqual(len(self.audit_entries()), 3)
        for account in eligible:
            account.refresh_from_db()
        self.assertEqual(eligible[0].state, Account.State.BLOCKED)
        self.assertEqual(eligible[2].state, Account.State.BLOCKED)
        with self.assertRaises(InputRejected):
            self.request_reset("not-an-email")

    def test_new_request_supersedes_only_active_reset_tokens(self):
        account = self.create_account(email="person@example.com")
        email_raw, email_token = self.create_token(
            account,
            purpose=OneTimeToken.Purpose.EMAIL_VERIFICATION,
        )
        self.request_reset(account.email)
        first_reset = OneTimeToken.objects.get(purpose=OneTimeToken.Purpose.PASSWORD_RESET)

        second_context = self.anonymous_context(now=self.now + timedelta(minutes=5))
        self.request_reset(account.email, context=second_context)

        first_reset.refresh_from_db()
        email_token.refresh_from_db()
        reset_tokens = list(
            OneTimeToken.objects.filter(
                purpose=OneTimeToken.Purpose.PASSWORD_RESET
            ).order_by("created_at")
        )
        self.assertEqual(len(reset_tokens), 2)
        self.assertEqual(first_reset.revoked_at, second_context.now)
        self.assertEqual(first_reset.revoked_reason, "superseded")
        self.assertIsNone(reset_tokens[1].revoked_at)
        self.assertIsNone(email_token.revoked_at)
        self.assertTrue(email_raw)

    def test_invalid_reset_tokens_share_one_rejection_without_mutation(self):
        public = self.public_module()
        account = self.create_account()
        original_password = account.password
        wrong_raw, wrong = self.create_token(
            account,
            purpose=OneTimeToken.Purpose.EMAIL_VERIFICATION,
        )
        expired_raw, expired = self.create_token(
            account,
            created_at=self.now - timedelta(minutes=31),
            expires_at=self.now,
        )
        used_raw, used = self.create_token(
            account,
            used_at=self.now - timedelta(seconds=1),
        )
        revoked_raw, revoked = self.create_token(
            account,
            revoked_at=self.now - timedelta(seconds=1),
            revoked_reason="superseded",
        )
        pending = self.create_account(state=Account.State.PENDING_EMAIL_VERIFICATION)
        pending_raw, pending_token = self.create_token(pending)
        unknown_raw, _ = generate_one_time_token()
        cases = ("malformed", unknown_raw, wrong_raw, expired_raw, used_raw, revoked_raw, pending_raw)
        messages = set()

        for raw_token in cases:
            with self.subTest(raw_kind=len(raw_token)), self.assertRaises(InputRejected) as raised:
                public.reset_password(
                    raw_token=raw_token,
                    new_password=self.new_password,
                    context=self.anonymous_context(),
                )
            messages.add(str(raised.exception))

        self.assertEqual(messages, {"Password reset token is invalid."})
        account.refresh_from_db()
        self.assertEqual(account.password, original_password)
        for token in (wrong, expired, used, revoked, pending_token):
            token.refresh_from_db()
        self.assertIsNone(wrong.used_at)
        self.assertIsNone(expired.used_at)
        self.assertIsNotNone(used.used_at)
        self.assertIsNone(revoked.used_at)
        self.assertIsNone(pending_token.used_at)

    def test_successful_reset_at_just_before_expiry_is_atomic_and_preserves_block(self):
        public = self.public_module()
        account = self.create_account(state=Account.State.BLOCKED)
        original_version = account.version
        sessions = (self.create_registry(account), self.create_registry(account))
        expired_session = self.create_registry(account, absolute_expires_at=self.now)
        self.request_reset(account.email)
        reset_message = self.claim_outbox()[0]
        raw_token, _ = self.reset_token_from_message(reset_message)
        selected = OneTimeToken.objects.get(purpose=OneTimeToken.Purpose.PASSWORD_RESET)
        _, sibling = self.create_token(account)
        _, email_token = self.create_token(
            account,
            purpose=OneTimeToken.Purpose.EMAIL_VERIFICATION,
        )
        context = self.anonymous_context(
            now=selected.expires_at - timedelta(microseconds=1)
        )

        public.reset_password(
            raw_token=raw_token,
            new_password=self.new_password,
            context=context,
        )

        account.refresh_from_db()
        selected.refresh_from_db()
        sibling.refresh_from_db()
        email_token.refresh_from_db()
        self.assertTrue(account.check_password(self.new_password))
        self.assertFalse(account.check_password(self.password))
        self.assertEqual(account.version, original_version + 1)
        self.assertEqual(account.state, Account.State.BLOCKED)
        self.assertEqual(selected.used_at, context.now)
        self.assertIsNone(selected.revoked_at)
        self.assertEqual(sibling.revoked_at, context.now)
        self.assertEqual(sibling.revoked_reason, "password_reset_completed")
        self.assertIsNone(email_token.revoked_at)
        for registry in sessions:
            registry.refresh_from_db()
            self.assertEqual(registry.revoked_at, context.now)
            self.assertEqual(registry.revoked_reason, "password_reset")
        expired_session.refresh_from_db()
        self.assertIsNone(expired_session.revoked_at)

        notifications = [
            message
            for message in self.claim_outbox(now=context.now)
            if message.message_type == "identity.protected_account_change"
        ]
        self.assertEqual(len(notifications), 1)
        notification = notifications[0]
        self.assertEqual(notification.message_type, "identity.protected_account_change")
        self.assertEqual(
            dict(notification.payload),
            {"account_id": str(account.id), "change": "password_reset"},
        )
        self.assertEqual(self.decrypt_delivery(notification), {"recipient": account.email})
        actions = sorted(entry.action for entry in self.audit_entries())
        self.assertEqual(
            actions,
            [
                "identity.password_reset_completed",
                "identity.password_reset_requested",
                "identity.sessions_revoked_for_security_event",
            ],
        )
        serialized = repr((self.audit_entries(), notification.payload))
        for secret in (raw_token, selected.token_digest, self.password, self.new_password):
            self.assertNotIn(secret, serialized)

    def test_weak_or_reused_new_password_does_not_consume_token(self):
        public = self.public_module()
        account = self.create_account()
        registry = self.create_registry(account)
        self.request_reset(account.email)
        raw_token, _ = self.reset_token_from_message(self.claim_outbox()[0])
        token = OneTimeToken.objects.get()
        original_password = account.password
        original_version = account.version
        invalid_passwords = (
            "".join(("password", str(1234))),
            self.password,
        )

        for candidate in invalid_passwords:
            with self.subTest(password_kind=len(candidate)), self.assertRaises(InputRejected):
                public.reset_password(
                    raw_token=raw_token,
                    new_password=candidate,
                    context=self.anonymous_context(now=self.now + timedelta(minutes=1)),
                )

        account.refresh_from_db()
        token.refresh_from_db()
        registry.refresh_from_db()
        self.assertEqual(account.password, original_password)
        self.assertEqual(account.version, original_version)
        self.assertIsNone(token.used_at)
        self.assertIsNone(token.revoked_at)
        self.assertIsNone(registry.revoked_at)

    def test_authenticated_change_proves_current_password_and_revokes_every_session_and_reset_token(self):
        public = self.public_module()
        account = self.create_account()
        current = self.create_registry(account)
        other = self.create_registry(account)
        _, reset_token = self.create_token(account)
        context = self.authenticated_context(current)
        original_version = account.version

        public.change_password(
            current_password=self.password,
            new_password=self.new_password,
            context=context,
        )

        account.refresh_from_db()
        reset_token.refresh_from_db()
        self.assertTrue(account.check_password(self.new_password))
        self.assertEqual(account.version, original_version + 1)
        self.assertEqual(reset_token.revoked_at, context.now)
        self.assertEqual(reset_token.revoked_reason, "password_changed")
        for registry in (current, other):
            registry.refresh_from_db()
            self.assertEqual(registry.revoked_at, context.now)
            self.assertEqual(registry.revoked_reason, "password_changed")
        with self.assertRaises(AuthenticationDenied):
            public.list_sessions(context=context)

        messages = self.claim_outbox()
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].message_type, "identity.protected_account_change")
        self.assertEqual(
            dict(messages[0].payload),
            {"account_id": str(account.id), "change": "password_changed"},
        )
        self.assertEqual(self.decrypt_delivery(messages[0]), {"recipient": account.email})
        actions = sorted(entry.action for entry in self.audit_entries())
        self.assertEqual(
            actions,
            [
                "identity.password_changed",
                "identity.sessions_revoked_for_security_event",
            ],
        )

    def test_wrong_current_same_or_weak_new_password_never_mutates_change_state(self):
        public = self.public_module()
        account = self.create_account()
        current = self.create_registry(account)
        _, reset_token = self.create_token(account)
        context = self.authenticated_context(current)
        original_password = account.password
        original_version = account.version
        cases = (
            (f"Wrong!{uuid4().hex}", self.new_password, AuthenticationDenied),
            (self.password, self.password, InputRejected),
            (self.password, "".join(("password", str(1234))), InputRejected),
        )

        for current_password, new_password, error in cases:
            with self.subTest(error=error.__name__), self.assertRaises(error):
                public.change_password(
                    current_password=current_password,
                    new_password=new_password,
                    context=context,
                )

        account.refresh_from_db()
        current.refresh_from_db()
        reset_token.refresh_from_db()
        self.assertEqual(account.password, original_password)
        self.assertEqual(account.version, original_version)
        self.assertIsNone(current.revoked_at)
        self.assertIsNone(reset_token.revoked_at)
        self.assertEqual(self.audit_entries(), ())
        self.assertEqual(self.claim_outbox(), [])

    def test_audit_or_outbox_failure_rolls_back_password_tokens_and_sessions(self):
        public = self.public_module()
        account = self.create_account()
        current = self.create_registry(account)
        self.request_reset(account.email)
        raw_token, _ = self.reset_token_from_message(self.claim_outbox()[0])
        token = OneTimeToken.objects.get()
        original_password = account.password
        original_version = account.version

        with patch(
            "open_marketplace.identity.application.enqueue_outbox_message",
            side_effect=RuntimeError("outbox unavailable"),
        ), self.assertRaises(RuntimeError):
            public.reset_password(
                raw_token=raw_token,
                new_password=self.new_password,
                context=self.anonymous_context(now=self.now + timedelta(minutes=1)),
            )

        account.refresh_from_db()
        current.refresh_from_db()
        token.refresh_from_db()
        self.assertEqual(account.password, original_password)
        self.assertEqual(account.version, original_version)
        self.assertIsNone(current.revoked_at)
        self.assertIsNone(token.used_at)
        self.assertIsNone(token.revoked_at)

        with patch(
            "open_marketplace.identity.application.append_audit_entry",
            side_effect=RuntimeError("audit unavailable"),
        ), self.assertRaises(RuntimeError):
            public.change_password(
                current_password=self.password,
                new_password=self.new_password,
                context=self.authenticated_context(current),
            )

        account.refresh_from_db()
        current.refresh_from_db()
        token.refresh_from_db()
        self.assertEqual(account.password, original_password)
        self.assertEqual(account.version, original_version)
        self.assertIsNone(current.revoked_at)
        self.assertIsNone(token.revoked_at)
