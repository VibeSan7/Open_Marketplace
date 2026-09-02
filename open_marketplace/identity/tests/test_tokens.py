from datetime import timedelta
from importlib import import_module
from uuid import uuid4
from unittest.mock import patch

from django.contrib import admin
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError

from open_marketplace.common.errors import InputRejected
from open_marketplace.identity.models import Account

from open_marketplace.identity.tests.test_registration import RegistrationTestCase


class OneTimeTokenTests(RegistrationTestCase):
    rejected_message = "Email verification token is invalid."

    def register_and_raw_token(self, *, email=None, context=None):
        self.register(email=email, context=context)
        messages = self.claim_outbox(now=context.now if context is not None else self.now)
        self.assertEqual(len(messages), 1)
        message = messages[0]
        raw_token, _ = self.raw_token_from_message(message)
        account = Account.objects.get(email=self.email if email is None else email.casefold())
        token = self.token_model().objects.get(id=message.payload["token_id"])
        return account, token, raw_token

    def create_token(
        self,
        *,
        account,
        raw_token,
        purpose="email_verification",
        created_at=None,
        expires_at=None,
        used_at=None,
        revoked_at=None,
        revoked_reason=None,
    ):
        crypto = self.crypto_module()
        created_at = created_at or self.now
        return self.token_model().objects.create(
            account=account,
            purpose=purpose,
            token_digest=crypto.hash_one_time_token(raw_token),
            created_at=created_at,
            expires_at=expires_at or created_at + timedelta(hours=24),
            used_at=used_at,
            revoked_at=revoked_at,
            revoked_reason=revoked_reason,
        )

    def crypto_module(self):
        try:
            module = import_module("open_marketplace.common.crypto")
        except ModuleNotFoundError:
            self.fail("open_marketplace.common.crypto must exist.")
        self.assertTrue(hasattr(module, "generate_one_time_token"))
        self.assertTrue(hasattr(module, "hash_one_time_token"))
        return module

    def assert_token_rejected(self, raw_token, *, now=None):
        public = self.public_module()
        with self.assertRaises(InputRejected) as caught:
            public.verify_email(
                raw_token=raw_token,
                context=self.context(now=now or self.now),
            )
        self.assertEqual(str(caught.exception), self.rejected_message)

    def test_crypto_primitive_generates_exact_urlsafe_token_and_digest(self):
        crypto = self.crypto_module()

        raw_token, digest = crypto.generate_one_time_token()

        self.assertRegex(raw_token, r"^[A-Za-z0-9_-]{43}$")
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertEqual(digest, crypto.hash_one_time_token(raw_token))
        self.assertNotEqual(raw_token, digest)

    def test_model_has_protected_owner_and_database_state_constraints(self):
        Token = self.token_model()
        self.public_module()
        account = Account.objects.create_user(email=self.email, password=self.password)
        crypto = self.crypto_module()

        self.assertEqual(
            Token._meta.get_field("account").remote_field.on_delete.__name__,
            "PROTECT",
        )
        self.assertNotIn(Token, admin.site._registry)
        constraint_names = {constraint.name for constraint in Token._meta.constraints}
        self.assertEqual(
            constraint_names,
            {
                "identity_token_expiry_after_create",
                "identity_token_not_used_and_revoked",
                "identity_token_revocation_pair",
            },
        )

        raw, digest = crypto.generate_one_time_token()
        valid = Token.objects.create(
            account=account,
            purpose="email_verification",
            token_digest=digest,
            created_at=self.now,
            expires_at=self.now + timedelta(hours=24),
        )
        self.assertEqual(valid.token_digest, crypto.hash_one_time_token(raw))
        with self.assertRaises(ProtectedError):
            account.delete()

        invalid_values = (
            {
                "expires_at": self.now,
            },
            {
                "used_at": self.now + timedelta(minutes=1),
                "revoked_at": self.now + timedelta(minutes=1),
                "revoked_reason": "superseded",
            },
            {
                "revoked_at": self.now + timedelta(minutes=1),
                "revoked_reason": None,
            },
            {
                "revoked_at": None,
                "revoked_reason": "superseded",
            },
        )
        for values in invalid_values:
            _, invalid_digest = crypto.generate_one_time_token()
            fields = {
                "account": account,
                "purpose": "email_verification",
                "token_digest": invalid_digest,
                "created_at": self.now,
                "expires_at": self.now + timedelta(hours=24),
            }
            fields.update(values)
            with self.subTest(values=values), self.assertRaises(IntegrityError), transaction.atomic():
                Token.objects.create(**fields)

    def test_verify_email_activates_once_increments_version_and_audits(self):
        public = self.public_module()
        account, token, raw_token = self.register_and_raw_token()
        verify_time = self.now + timedelta(minutes=1)

        result = public.verify_email(
            raw_token=raw_token,
            context=self.context(now=verify_time),
        )

        self.assertEqual(result, account.id)
        account.refresh_from_db()
        token.refresh_from_db()
        self.assertEqual(account.state, Account.State.ACTIVE)
        self.assertEqual(account.email_verified_at, verify_time)
        self.assertEqual(account.version, 2)
        self.assertEqual(token.used_at, verify_time)
        self.assertIsNone(token.revoked_at)
        self.assertEqual(self.claim_outbox(now=verify_time), [])
        audits = self.audit_entries(action="identity.email_verified")
        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertEqual(audit.object_id, str(account.id))
        self.assertEqual(
            audit.before,
            {
                "state": "pending_email_verification",
                "email_verified": False,
                "version": 1,
                "token_purpose": "email_verification",
            },
        )
        self.assertEqual(
            audit.after,
            {
                "state": "active",
                "email_verified": True,
                "version": 2,
            },
        )
        self.assertNotIn(raw_token, str(audit.before))
        self.assertNotIn(raw_token, str(audit.after))

        self.assert_token_rejected(raw_token, now=verify_time + timedelta(seconds=1))
        self.assertEqual(len(self.audit_entries(action="identity.email_verified")), 1)

    def test_expiry_is_valid_just_before_and_invalid_at_or_after_deadline(self):
        public = self.public_module()
        contexts = (
            ("before@example.com", timedelta(microseconds=-1), True),
            ("at@example.com", timedelta(0), False),
            ("after@example.com", timedelta(microseconds=1), False),
        )
        for email, offset, succeeds in contexts:
            with self.subTest(email=email, offset=offset):
                registration_context = self.context(now=self.now)
                account, token, raw_token = self.register_and_raw_token(
                    email=email,
                    context=registration_context,
                )
                verify_context = self.context(now=token.expires_at + offset)
                if succeeds:
                    self.assertEqual(
                        public.verify_email(raw_token=raw_token, context=verify_context),
                        account.id,
                    )
                else:
                    self.assert_token_rejected(raw_token, now=verify_context.now)
                    account.refresh_from_db()
                    token.refresh_from_db()
                    self.assertEqual(account.state, Account.State.PENDING_EMAIL_VERIFICATION)
                    self.assertIsNone(token.used_at)

    def test_malformed_unknown_and_wrong_purpose_tokens_share_one_rejection(self):
        self.public_module()
        account = Account.objects.create_user(email=self.email, password=self.password)
        wrong_purpose_raw = "B" * 43
        self.create_token(
            account=account,
            raw_token=wrong_purpose_raw,
            purpose="password_reset",
        )

        invalid_tokens = (
            None,
            42,
            "",
            "A" * 42,
            "A" * 44,
            "A" * 42 + "!",
            "C" * 43,
            wrong_purpose_raw,
        )
        for raw_token in invalid_tokens:
            with self.subTest(raw_token=raw_token):
                self.assert_token_rejected(raw_token)

    def test_revoked_wrong_kind_and_wrong_state_tokens_share_one_rejection(self):
        self.public_module()
        _, old_token, old_raw = self.register_and_raw_token()
        self.register(context=self.context(now=self.now + timedelta(minutes=1)))
        old_token.refresh_from_db()
        self.assertEqual(old_token.revoked_reason, "superseded")
        self.assert_token_rejected(old_raw, now=self.now + timedelta(minutes=2))

        service = Account.objects.create_service_account(
            email="service@example.com",
            password=self.password,
        )
        service_raw = "S" * 43
        self.create_token(account=service, raw_token=service_raw)
        self.assert_token_rejected(service_raw)

        for index, state in enumerate((Account.State.ACTIVE, Account.State.BLOCKED)):
            account = Account.objects.create_user(
                email=f"state-{index}@example.com",
                password=self.password,
            )
            account.state = state
            account.save(update_fields={"state", "updated_at"})
            raw_token = chr(ord("D") + index) * 43
            self.create_token(account=account, raw_token=raw_token)
            self.assert_token_rejected(raw_token)

    def test_success_revokes_every_other_unconsumed_verification_token(self):
        public = self.public_module()
        account, selected, raw_token = self.register_and_raw_token()
        sibling_raw = "R" * 43
        sibling = self.create_token(
            account=account,
            raw_token=sibling_raw,
            created_at=self.now + timedelta(seconds=1),
        )
        verify_time = self.now + timedelta(minutes=1)

        public.verify_email(
            raw_token=raw_token,
            context=self.context(now=verify_time),
        )

        selected.refresh_from_db()
        sibling.refresh_from_db()
        self.assertEqual(selected.used_at, verify_time)
        self.assertEqual(sibling.revoked_at, verify_time)
        self.assertEqual(sibling.revoked_reason, "account_verified")
        self.assert_token_rejected(sibling_raw, now=verify_time + timedelta(seconds=1))

    def test_verify_email_requires_anonymous_valid_context_and_rolls_back_audit_failure(self):
        public = self.public_module()
        account, token, raw_token = self.register_and_raw_token()
        invalid_contexts = (
            self.context(actor_account_id=uuid4()),
            self.context(session_id=uuid4()),
            self.context(now=self.now.replace(tzinfo=None)),
            self.context(source="unknown"),
        )
        for context in invalid_contexts:
            with self.subTest(context=context), self.assertRaises(InputRejected):
                public.verify_email(raw_token=raw_token, context=context)

        with patch(
            "open_marketplace.identity.application.append_audit_entry",
            side_effect=RuntimeError("audit unavailable"),
        ), self.assertRaises(RuntimeError):
            public.verify_email(
                raw_token=raw_token,
                context=self.context(now=self.now + timedelta(minutes=1)),
            )

        account.refresh_from_db()
        token.refresh_from_db()
        self.assertEqual(account.state, Account.State.PENDING_EMAIL_VERIFICATION)
        self.assertEqual(account.version, 1)
        self.assertIsNone(account.email_verified_at)
        self.assertIsNone(token.used_at)
        self.assertEqual(self.audit_entries(action="identity.email_verified"), ())
