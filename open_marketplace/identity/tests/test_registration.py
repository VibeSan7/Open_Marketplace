import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from importlib import import_module
from unittest.mock import patch
from uuid import uuid4

from cryptography.fernet import Fernet
from django.conf import settings
from django.test import TestCase, override_settings

from open_marketplace.audit.public import AuditQuery, query_audit_entries
from open_marketplace.common.errors import InputRejected
from open_marketplace.common.types import AuthorizationDecision, OperationContext
from open_marketplace.identity.models import Account
from open_marketplace.outbox.public import claim_ready_messages


class RegistrationTestCase(TestCase):
    email = "person@example.com"
    password = "V9!qL2@xP7#z"
    now = datetime(2026, 9, 2, 12, tzinfo=UTC)

    def public_module(self):
        public = import_module("open_marketplace.identity.public")
        self.assertTrue(
            hasattr(public, "register_account"),
            "register_account must be public.",
        )
        self.assertTrue(
            hasattr(public, "verify_email"),
            "verify_email must be public.",
        )
        self.assertTrue(
            hasattr(public, "NeutralAccepted"),
            "NeutralAccepted must be public.",
        )
        return public

    def token_model(self):
        models = import_module("open_marketplace.identity.models")
        self.assertTrue(
            hasattr(models, "OneTimeToken"),
            "OneTimeToken must exist.",
        )
        return models.OneTimeToken

    def context(
        self,
        *,
        now=None,
        actor_account_id=None,
        session_id=None,
        request_id=None,
        source="html",
        source_address="203.0.113.10",
    ):
        return OperationContext(
            actor_account_id=actor_account_id,
            session_id=session_id,
            request_id=request_id or uuid4(),
            source=source,
            source_address=source_address,
            now=now or self.now,
        )

    def register(self, *, email=None, password=None, context=None):
        public = self.public_module()
        return public.register_account(
            email=self.email if email is None else email,
            password=self.password if password is None else password,
            context=context or self.context(),
        )

    def decrypt_delivery(self, message):
        plaintext = Fernet(settings.OUTBOX_ENCRYPTION_KEY.encode("ascii")).decrypt(
            bytes(message.encrypted_delivery)
        )
        return json.loads(plaintext.decode("utf-8"))

    def raw_token_from_message(self, message):
        delivery = self.decrypt_delivery(message)
        prefix = f"{settings.APP_BASE_URL}/identity/verify-email/"
        url = delivery["absolute_token_url"]
        self.assertTrue(url.startswith(prefix))
        self.assertTrue(url.endswith("/"))
        return url[len(prefix) : -1], delivery

    def claim_outbox(self, *, now=None, limit=100):
        return claim_ready_messages(
            worker_id=f"test:{uuid4()}",
            now=now or self.now,
            lease_seconds=300,
            limit=limit,
        )

    def audit_entries(self, *, action=None):
        actor_id = uuid4()
        context = self.context(
            now=self.now + timedelta(days=30),
            actor_account_id=actor_id,
        )

        def authorize(received_context, permission):
            self.assertIs(received_context, context)
            self.assertEqual(permission, "audit.read")
            return AuthorizationDecision(
                account_id=actor_id,
                permission="audit.read",
                effective_roles=("security_admin",),
                scopes=("audit:result:succeeded",),
                reauthenticated_at=context.now,
            )

        query = AuditQuery(
            from_at=None,
            to_at=None,
            actor_id=None,
            action=action,
            object_type=None,
            object_id=None,
            result=None,
            limit=100,
            cursor=None,
        )
        return query_audit_entries(
            query=query,
            context=context,
            authorize=authorize,
        )


class RegistrationFlowTests(RegistrationTestCase):
    def test_new_registration_creates_exact_atomic_account_token_audit_and_outbox(self):
        Token = self.token_model()
        context = self.context()

        result = self.register(email="  Person@Example.COM  ", context=context)

        self.assertTrue(result.accepted)
        with self.assertRaises(FrozenInstanceError):
            result.accepted = False

        account = Account.objects.get()
        self.assertEqual(account.email, self.email)
        self.assertEqual(account.kind, Account.Kind.ORDINARY)
        self.assertEqual(account.state, Account.State.PENDING_EMAIL_VERIFICATION)
        self.assertEqual(account.version, 1)
        self.assertIsNone(account.email_verified_at)
        self.assertNotEqual(account.password, self.password)
        self.assertTrue(account.check_password(self.password))

        token = Token.objects.get()
        self.assertEqual(token.account_id, account.id)
        self.assertEqual(token.purpose, "email_verification")
        self.assertRegex(token.token_digest, r"^[0-9a-f]{64}$")
        self.assertEqual(token.created_at, context.now)
        self.assertEqual(token.expires_at, context.now + timedelta(hours=24))
        self.assertIsNone(token.used_at)
        self.assertIsNone(token.revoked_at)
        self.assertIsNone(token.revoked_reason)

        messages = self.claim_outbox()
        self.assertEqual(len(messages), 1)
        message = messages[0]
        self.assertEqual(message.message_type, "identity.email_verification")
        self.assertEqual(message.format_version, 1)
        self.assertEqual(
            message.payload,
            {"account_id": str(account.id), "token_id": str(token.id)},
        )
        self.assertEqual(
            message.idempotency_key,
            f"identity.email_verification:{token.id}",
        )
        raw_token, delivery = self.raw_token_from_message(message)
        self.assertRegex(raw_token, r"^[A-Za-z0-9_-]{43}$")
        self.assertEqual(delivery["recipient"], self.email)

        crypto = import_module("open_marketplace.common.crypto")
        self.assertEqual(token.token_digest, crypto.hash_one_time_token(raw_token))
        self.assertNotIn(raw_token, token.token_digest)
        self.assertNotIn(raw_token.encode("ascii"), bytes(message.encrypted_delivery))
        self.assertNotIn(self.email.encode("ascii"), bytes(message.encrypted_delivery))

        audits = self.audit_entries(action="identity.account_registered")
        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertEqual(audit.action, "identity.account_registered")
        self.assertEqual(audit.object_type, "account")
        self.assertEqual(audit.object_id, str(account.id))
        self.assertEqual(audit.actor_id, None)
        self.assertEqual(audit.request_id, context.request_id)
        self.assertEqual(audit.occurred_at, context.now)
        self.assertEqual(audit.result, "succeeded")
        self.assertEqual(audit.before, {})
        self.assertEqual(
            audit.after,
            {
                "kind": "ordinary",
                "state": "pending_email_verification",
                "email_verified": False,
                "token_purpose": "email_verification",
                "expires_at": token.expires_at.isoformat(),
            },
        )
        safe_serialized = json.dumps(
            {
                "audit_before": audit.before,
                "audit_after": audit.after,
                "outbox_payload": dict(message.payload),
                "outbox_key": message.idempotency_key,
            },
            sort_keys=True,
        )
        for forbidden in (self.email, self.password, raw_token, token.token_digest):
            self.assertNotIn(forbidden, safe_serialized)

    def test_repeated_pending_registration_rotates_only_token(self):
        Token = self.token_model()
        first_context = self.context()
        self.register(context=first_context)
        account = Account.objects.get()
        original_password_hash = account.password
        original_version = account.version
        first_token = Token.objects.get()

        second_context = self.context(now=self.now + timedelta(minutes=5))
        result = self.register(
            email="PERSON@example.com",
            password="Different9!Passphrase",
            context=second_context,
        )

        self.assertTrue(result.accepted)
        account.refresh_from_db()
        first_token.refresh_from_db()
        self.assertEqual(Account.objects.count(), 1)
        self.assertEqual(account.password, original_password_hash)
        self.assertTrue(account.check_password(self.password))
        self.assertFalse(account.check_password("Different9!Passphrase"))
        self.assertEqual(account.version, original_version)
        self.assertEqual(first_token.revoked_at, second_context.now)
        self.assertEqual(first_token.revoked_reason, "superseded")

        tokens = list(Token.objects.order_by("created_at", "id"))
        self.assertEqual(len(tokens), 2)
        active_tokens = [
            token
            for token in tokens
            if token.used_at is None
            and token.revoked_at is None
            and token.expires_at > second_context.now
        ]
        self.assertEqual(len(active_tokens), 1)
        self.assertEqual(len(self.claim_outbox(now=second_context.now)), 2)
        self.assertEqual(
            [
                entry.action
                for entry in sorted(
                    self.audit_entries(),
                    key=lambda entry: entry.occurred_at,
                )
            ],
            ["identity.account_registered", "identity.email_verification_reissued"],
        )

    def test_active_blocked_and_all_service_accounts_are_neutral_no_ops(self):
        Token = self.token_model()
        cases = (
            (Account.Kind.ORDINARY, Account.State.ACTIVE),
            (Account.Kind.ORDINARY, Account.State.BLOCKED),
            (Account.Kind.SERVICE, Account.State.PENDING_EMAIL_VERIFICATION),
            (Account.Kind.SERVICE, Account.State.ACTIVE),
            (Account.Kind.SERVICE, Account.State.BLOCKED),
        )
        for index, (kind, state) in enumerate(cases):
            with self.subTest(kind=kind, state=state):
                email = f"existing-{index}@example.com"
                create = (
                    Account.objects.create_user
                    if kind == Account.Kind.ORDINARY
                    else Account.objects.create_service_account
                )
                account = create(email=email, password=self.password)
                account.state = state
                account.save(update_fields={"state", "updated_at"})
                original_password = account.password
                original_version = account.version
                token_count = Token.objects.count()

                result = self.register(
                    email=email.upper(),
                    password="Different9!Passphrase",
                    context=self.context(now=self.now + timedelta(minutes=index + 1)),
                )

                self.assertTrue(result.accepted)
                account.refresh_from_db()
                self.assertEqual(account.state, state)
                self.assertEqual(account.password, original_password)
                self.assertEqual(account.version, original_version)
                self.assertEqual(Token.objects.count(), token_count)
        self.assertEqual(self.audit_entries(), ())
        self.assertEqual(self.claim_outbox(), [])

    def test_email_and_password_security_boundaries_are_enforced_before_mutation(self):
        self.public_module()
        invalid_inputs = (
            {"email": 42},
            {"email": "not-an-email"},
            {
                "email": "a" * 64 + "@" + "b" * 63 + "." + "c" * 63 + "." + "d" * 63,
            },
            {"password": 42},
            {"password": "V9!qL2@xP7#"},
            {"password": "Z9!" + "q" * 126},
            {"password": "password1234"},
            {"password": "123456789012"},
            {"email": "similarname@example.com", "password": "similarname2026!"},
        )
        for values in invalid_inputs:
            with self.subTest(values=values), self.assertRaises(InputRejected):
                self.register(**values)
        self.assertEqual(Account.objects.count(), 0)
        self.assertEqual(self.audit_entries(), ())
        self.assertEqual(self.claim_outbox(), [])

        max_email = "a" * 64 + "@" + "b" * 63 + "." + "c" * 63 + "." + "d" * 61
        self.assertEqual(len(max_email), 254)
        self.register(email="min-password@example.com", password="V9!qL2@xP7#z")
        self.register(email=max_email, password="Z9!" + "q" * 125)
        self.assertEqual(Account.objects.count(), 2)

    def test_registration_requires_valid_anonymous_operation_context(self):
        self.public_module()
        invalid_contexts = (
            object(),
            self.context(actor_account_id=uuid4()),
            self.context(session_id=uuid4()),
            self.context(now=datetime(2026, 9, 2, 12)),
            self.context(request_id="not-a-uuid"),
            self.context(source="unknown"),
        )
        for context in invalid_contexts:
            with self.subTest(context=context), self.assertRaises(InputRejected):
                self.register(context=context)
        self.assertEqual(Account.objects.count(), 0)

    @override_settings(APP_BASE_URL="https://configured.example")
    def test_verification_link_uses_only_configured_origin(self):
        self.token_model()
        hostile = "evil.example\nX-Forwarded-Host: attacker.example"

        self.register(context=self.context(source_address=hostile))

        messages = self.claim_outbox()
        self.assertEqual(len(messages), 1)
        message = messages[0]
        raw_token, delivery = self.raw_token_from_message(message)
        self.assertTrue(raw_token)
        self.assertEqual(
            delivery["absolute_token_url"],
            f"https://configured.example/identity/verify-email/{raw_token}/",
        )
        self.assertNotIn("evil.example", delivery["absolute_token_url"])
        self.assertNotIn("attacker.example", delivery["absolute_token_url"])

    def test_registration_rolls_back_on_audit_or_outbox_failure(self):
        self.token_model()
        with patch(
            "open_marketplace.identity.application.append_audit_entry",
            side_effect=RuntimeError("audit unavailable"),
        ), self.assertRaises(RuntimeError):
            self.register(email="audit-failure@example.com")
        self.assertFalse(Account.objects.filter(email="audit-failure@example.com").exists())

        with patch(
            "open_marketplace.identity.application.enqueue_outbox_message",
            side_effect=RuntimeError("outbox unavailable"),
        ), self.assertRaises(RuntimeError):
            self.register(email="outbox-failure@example.com")
        self.assertFalse(Account.objects.filter(email="outbox-failure@example.com").exists())
        self.assertEqual(self.audit_entries(), ())
        self.assertEqual(self.claim_outbox(), [])

    def test_failed_pending_reissue_preserves_prior_active_token_and_password(self):
        Token = self.token_model()
        self.register()
        account = Account.objects.get()
        original_password = account.password
        token = Token.objects.get()

        with patch(
            "open_marketplace.identity.application.enqueue_outbox_message",
            side_effect=RuntimeError("outbox unavailable"),
        ), self.assertRaises(RuntimeError):
            self.register(
                password="Different9!Passphrase",
                context=self.context(now=self.now + timedelta(minutes=5)),
            )

        account.refresh_from_db()
        token.refresh_from_db()
        self.assertEqual(account.password, original_password)
        self.assertIsNone(token.revoked_at)
        self.assertEqual(Token.objects.count(), 1)
        self.assertEqual(len(self.audit_entries()), 1)
        self.assertEqual(len(self.claim_outbox()), 1)
