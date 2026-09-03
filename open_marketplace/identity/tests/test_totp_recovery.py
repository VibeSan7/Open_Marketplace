import json
from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import uuid4
from unittest.mock import patch

import pyotp
from cryptography.fernet import Fernet
from django.apps import apps
from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils.crypto import get_random_string

from open_marketplace.common.crypto import generate_one_time_token, hash_one_time_token
from open_marketplace.common.errors import (
    AuthenticationDenied,
    InputRejected,
    InvalidState,
    PermissionDenied,
)
from open_marketplace.common.types import AuthorizationDecision, OperationContext


Account = apps.get_model("identity", "Account")
AccountSession = apps.get_model("identity", "AccountSession")
AuditEntry = apps.get_model("audit", "AuditEntry")
OneTimeToken = apps.get_model("identity", "OneTimeToken")
OutboxMessage = apps.get_model("outbox", "OutboxMessage")
RecoveryCode = apps.get_model("identity", "RecoveryCode")
TotpCredential = apps.get_model("identity", "TotpCredential")
TotpRequirement = apps.get_model("identity", "TotpRequirement")
TotpSetup = apps.get_model("identity", "TotpSetup")


class MandatoryTotpRecoveryTests(TestCase):
    now = datetime(2026, 9, 2, 12, tzinfo=UTC)
    password = f"T3st!{uuid4().hex}"

    def public_module(self):
        return import_module("open_marketplace.identity.public")

    def create_account(
        self,
        *,
        email=None,
        kind=Account.Kind.SERVICE,
        state=Account.State.ACTIVE,
        verified=True,
        **extra_fields,
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
            email_verified_at=self.now - timedelta(days=1) if verified else None,
            **extra_fields,
        )

    def create_registry(self, account, *, now=None):
        now = now or self.now
        key = get_random_string(32, "abcdefghijklmnopqrstuvwxyz0123456789")
        Session.objects.create(
            session_key=key,
            session_data=SessionStore().encode({}),
            expire_date=now + timedelta(days=1),
        )
        return AccountSession.objects.create(
            account=account,
            django_session_key=key,
            created_at=now - timedelta(hours=1),
            last_activity_at=now - timedelta(minutes=1),
            absolute_expires_at=now + timedelta(hours=1),
            reauthenticated_at=now - timedelta(minutes=1),
            device_label="Firefox on Linux",
        )

    def admin_context(self, actor, *, now=None):
        now = now or self.now
        registry = self.create_registry(actor, now=now)
        return OperationContext(
            actor_account_id=actor.id,
            session_id=registry.id,
            request_id=uuid4(),
            source="admin",
            source_address="203.0.113.10",
            now=now,
        )

    def anonymous_context(self, *, now=None):
        return OperationContext(
            actor_account_id=None,
            session_id=None,
            request_id=uuid4(),
            source="html",
            source_address="203.0.113.10",
            now=now or self.now,
        )

    def authorize(self, context, *, actor_id=None, permission=None):
        calls = []
        operation_context = context
        decision_permission = permission or "identity.mandatory_totp_recover"

        def callback(*, context, permission):
            calls.append((context, permission))
            return AuthorizationDecision(
                account_id=actor_id or operation_context.actor_account_id,
                permission=decision_permission,
                effective_roles=("security_admin",),
                scopes=(),
                reauthenticated_at=operation_context.now,
            )

        return callback, calls

    def encrypt_secret(self, secret):
        return Fernet(settings.TOTP_ENCRYPTION_KEY.encode("ascii")).encrypt(
            secret.encode("ascii")
        )

    def decrypt_delivery(self, message):
        plaintext = Fernet(settings.OUTBOX_ENCRYPTION_KEY.encode("ascii")).decrypt(
            bytes(message.encrypted_delivery)
        )
        return json.loads(plaintext.decode("utf-8"))

    def enable_mandatory_totp(self, account):
        secret = pyotp.random_base32(length=32)
        credential = TotpCredential.objects.create(
            account=account,
            encrypted_secret=self.encrypt_secret(secret),
            confirmed_at=self.now - timedelta(days=1),
            last_accepted_counter=1,
        )
        requirement = TotpRequirement.objects.create(
            account=account,
            source_type="staff_role",
            source_id=uuid4(),
            created_at=self.now - timedelta(days=1),
        )
        codes = tuple(f"old-recovery-{uuid4()}" for _ in range(2))
        set_id = uuid4()
        RecoveryCode.objects.bulk_create(
            RecoveryCode(
                account=account,
                set_id=set_id,
                code_digest=hash_one_time_token(code),
                issued_at=self.now - timedelta(days=1),
            )
            for code in codes
        )
        return credential, requirement, codes

    def seed_token(
        self,
        account,
        *,
        purpose="mandatory_totp_recovery",
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

    def start_recovery(self, target, actor=None, *, now=None, reason="device rechecked"):
        public = self.public_module()
        actor = actor or self.create_account()
        context = self.admin_context(actor, now=now)
        authorize, calls = self.authorize(context)
        result = public.recover_mandatory_totp(
            account_id=target.id,
            reason=reason,
            context=context,
            authorize=authorize,
        )
        message = OutboxMessage.objects.get(
            message_type="identity.mandatory_totp_recovery",
            payload__account_id=str(target.id),
        )
        delivery = self.decrypt_delivery(message)
        prefix = f"{settings.APP_BASE_URL}/identity/recover-mandatory-totp/"
        url = delivery["absolute_token_url"]
        self.assertTrue(url.startswith(prefix))
        self.assertTrue(url.endswith("/"))
        return url[len(prefix) : -1], context, calls, result, message, delivery

    def prepare_target(self, *, sessions=2):
        target = self.create_account()
        credential, requirement, codes = self.enable_mandatory_totp(target)
        registries = tuple(self.create_registry(target) for _ in range(sessions))
        return target, credential, requirement, codes, registries

    def test_admin_start_disables_old_factor_revokes_access_and_issues_digest_only_link(self):
        target, credential, requirement, codes, registries = self.prepare_target()
        active_setup = TotpSetup.objects.create(
            account=target,
            session=registries[0],
            encrypted_secret=self.encrypt_secret(pyotp.random_base32(length=32)),
            created_at=self.now - timedelta(minutes=1),
            expires_at=self.now + timedelta(minutes=9),
        )
        _, previous_token = self.seed_token(target)
        actor = self.create_account()

        raw_token, context, calls, result, message, delivery = self.start_recovery(
            target,
            actor,
            reason="  manual identity recheck completed  ",
        )

        self.assertIsNone(result)
        self.assertEqual(calls, [(context, "identity.mandatory_totp_recover")])
        credential.refresh_from_db()
        active_setup.refresh_from_db()
        previous_token.refresh_from_db()
        self.assertEqual(credential.disabled_at, context.now)
        self.assertEqual(active_setup.invalidated_at, context.now)
        self.assertEqual(previous_token.revoked_at, context.now)
        self.assertEqual(previous_token.revoked_reason, "superseded")
        self.assertEqual(
            RecoveryCode.objects.filter(account=target, revoked_at=context.now).count(),
            len(codes),
        )
        for registry in registries:
            registry.refresh_from_db()
            self.assertEqual(registry.revoked_at, context.now)
            self.assertEqual(registry.revoked_reason, "mandatory_totp_recovered")

        token = OneTimeToken.objects.get(
            account=target,
            purpose="mandatory_totp_recovery",
            revoked_at__isnull=True,
        )
        self.assertEqual(token.created_at, context.now)
        self.assertEqual(token.expires_at, context.now + timedelta(minutes=30))
        self.assertEqual(token.token_digest, hash_one_time_token(raw_token))
        self.assertRegex(raw_token, r"^[A-Za-z0-9_-]{43}$")
        self.assertIsNone(token.used_at)
        self.assertEqual(
            message.payload,
            {"account_id": str(target.id), "token_id": str(token.id)},
        )
        self.assertEqual(delivery["recipient"], target.email)
        start_entry = AuditEntry.objects.get(
            action="identity.mandatory_totp_recovery_started"
        )
        self.assertEqual(start_entry.actor_id, actor.id)
        self.assertEqual(start_entry.reason, "manual identity recheck completed")
        self.assertEqual(start_entry.after["revoked_session_count"], len(registries))
        serialized = repr((token, message.payload, start_entry.before, start_entry.after))
        for secret in (raw_token, token.token_digest, target.email):
            self.assertNotIn(secret, serialized)
        self.assertIsNone(requirement.removed_at)

    def test_admin_cannot_start_recovery_for_their_own_account(self):
        public = self.public_module()
        actor, credential, _, _, _ = self.prepare_target(sessions=0)
        context = self.admin_context(actor)
        authorize, calls = self.authorize(context)

        with self.assertRaises(InvalidState):
            public.recover_mandatory_totp(
                account_id=actor.id,
                reason="self recovery attempt",
                context=context,
                authorize=authorize,
            )

        self.assertEqual(calls, [(context, "identity.mandatory_totp_recover")])
        credential.refresh_from_db()
        self.assertIsNone(credential.disabled_at)
        self.assertFalse(
            OneTimeToken.objects.filter(
                account=actor,
                purpose="mandatory_totp_recovery",
            ).exists()
        )

    def test_admin_can_reissue_an_unfinished_recovery_link(self):
        public = self.public_module()
        target, credential, _, codes, _ = self.prepare_target(sessions=0)
        actor = self.create_account()
        raw_token, _, _, _, _, _ = self.start_recovery(target, actor)
        first_token = OneTimeToken.objects.get(
            token_digest=hash_one_time_token(raw_token)
        )
        reissue_at = self.now + timedelta(minutes=5)
        context = self.admin_context(actor, now=reissue_at)
        authorize, calls = self.authorize(context)

        result = public.recover_mandatory_totp(
            account_id=target.id,
            reason="replacement link requested",
            context=context,
            authorize=authorize,
        )

        self.assertIsNone(result)
        self.assertEqual(calls, [(context, "identity.mandatory_totp_recover")])
        first_token.refresh_from_db()
        credential.refresh_from_db()
        self.assertEqual(first_token.revoked_at, reissue_at)
        self.assertEqual(first_token.revoked_reason, "superseded")
        self.assertEqual(credential.disabled_at, self.now)
        self.assertFalse(
            RecoveryCode.objects.filter(account=target, revoked_at__isnull=True).exists()
        )
        self.assertEqual(RecoveryCode.objects.filter(account=target).count(), len(codes))
        replacement = OneTimeToken.objects.get(
            account=target,
            purpose="mandatory_totp_recovery",
            revoked_at__isnull=True,
        )
        self.assertEqual(replacement.created_at, reissue_at)
        self.assertEqual(replacement.expires_at, reissue_at + timedelta(minutes=30))
        self.assertEqual(
            OutboxMessage.objects.filter(
                message_type="identity.mandatory_totp_recovery",
                payload__account_id=str(target.id),
            ).count(),
            2,
        )

    def test_password_only_login_is_denied_while_mandatory_recovery_is_open(self):
        public = self.public_module()
        target, _, _, _, _ = self.prepare_target(sessions=0)
        raw_token, _, _, _, _, _ = self.start_recovery(target)
        login_at = self.now + timedelta(minutes=1)
        django_session_key = get_random_string(
            32,
            "abcdefghijklmnopqrstuvwxyz0123456789",
        )
        Session.objects.create(
            session_key=django_session_key,
            session_data=SessionStore().encode({}),
            expire_date=login_at + timedelta(hours=1),
        )
        context = self.anonymous_context(now=login_at)

        with self.assertRaises(AuthenticationDenied):
            public.authenticate_account(
                email=target.email,
                password=self.password,
                second_factor=None,
                django_session_key=django_session_key,
                device_label="Firefox on Linux",
                context=context,
            )

        self.assertFalse(
            AccountSession.objects.filter(django_session_key=django_session_key).exists()
        )
        token = OneTimeToken.objects.get(token_digest=hash_one_time_token(raw_token))
        self.assertIsNone(token.used_at)
        self.assertTrue(
            AuditEntry.objects.filter(
                request_id=context.request_id,
                action="identity.authentication_failed",
                result="failed",
            ).exists()
        )

    def test_standard_totp_setup_is_denied_while_mandatory_recovery_is_open(self):
        public = self.public_module()
        target, _, _, _, _ = self.prepare_target(sessions=0)
        raw_token, _, _, _, _, _ = self.start_recovery(target)
        attempt_at = self.now + timedelta(minutes=1)
        registry = self.create_registry(target, now=attempt_at)
        context = OperationContext(
            actor_account_id=target.id,
            session_id=registry.id,
            request_id=uuid4(),
            source="html",
            source_address="203.0.113.10",
            now=attempt_at,
        )

        with self.assertRaises(AuthenticationDenied):
            public.begin_totp_setup(
                current_password=self.password,
                context=context,
            )

        token = OneTimeToken.objects.get(token_digest=hash_one_time_token(raw_token))
        self.assertFalse(TotpSetup.objects.filter(recovery_token=token).exists())
        self.assertFalse(TotpSetup.objects.filter(session=registry).exists())

    def test_standard_totp_enable_is_denied_while_mandatory_recovery_is_open(self):
        public = self.public_module()
        target, _, _, _, _ = self.prepare_target(sessions=0)
        self.start_recovery(target)
        attempt_at = self.now + timedelta(minutes=1)
        registry = self.create_registry(target, now=attempt_at)
        secret = pyotp.random_base32(length=32)
        setup = TotpSetup.objects.create(
            account=target,
            session=registry,
            recovery_token=None,
            encrypted_secret=self.encrypt_secret(secret),
            created_at=attempt_at,
            expires_at=attempt_at + timedelta(minutes=10),
        )
        context = OperationContext(
            actor_account_id=target.id,
            session_id=registry.id,
            request_id=uuid4(),
            source="html",
            source_address="203.0.113.10",
            now=attempt_at,
        )

        with self.assertRaises(AuthenticationDenied):
            public.enable_totp(
                setup_id=setup.id,
                code=pyotp.TOTP(secret).at(attempt_at),
                context=context,
            )

        setup.refresh_from_db()
        self.assertIsNone(setup.consumed_at)
        self.assertFalse(
            TotpCredential.objects.filter(
                account=target,
                disabled_at__isnull=True,
            ).exists()
        )

    def test_start_requires_exact_authorization_reason_and_eligible_active_account(self):
        public = self.public_module()
        actor = self.create_account()
        context = self.admin_context(actor)
        eligible, credential, _, _, _ = self.prepare_target(sessions=0)

        def denied(*args, **kwargs):
            raise PermissionDenied("denied")

        with self.assertRaises(PermissionDenied):
            public.recover_mandatory_totp(
                account_id=eligible.id,
                reason="identity rechecked",
                context=context,
                authorize=denied,
            )
        for authorize in (
            self.authorize(context, actor_id=uuid4())[0],
            self.authorize(context, permission="account.read")[0],
        ):
            with self.assertRaises(PermissionDenied):
                public.recover_mandatory_totp(
                    account_id=eligible.id,
                    reason="identity rechecked",
                    context=context,
                    authorize=authorize,
                )
        valid_authorize, _ = self.authorize(context)
        for reason in (None, 1, "", "   ", "x" * 1025):
            with self.subTest(reason=reason), self.assertRaises(InputRejected):
                public.recover_mandatory_totp(
                    account_id=eligible.id,
                    reason=reason,
                    context=context,
                    authorize=valid_authorize,
                )

        blocked = self.create_account(
            state=Account.State.BLOCKED,
            blocked_at=self.now,
            blocked_by_id=actor.id,
            block_reason="separate incident",
            block_audit_id=uuid4(),
        )
        self.enable_mandatory_totp(blocked)
        unverified = self.create_account(verified=False)
        self.enable_mandatory_totp(unverified)
        no_requirement = self.create_account()
        TotpCredential.objects.create(
            account=no_requirement,
            encrypted_secret=self.encrypt_secret(pyotp.random_base32(length=32)),
            confirmed_at=self.now,
            last_accepted_counter=1,
        )
        no_credential = self.create_account()
        TotpRequirement.objects.create(
            account=no_credential,
            source_type="staff_role",
            source_id=uuid4(),
            created_at=self.now,
        )
        for target in (blocked, unverified, no_requirement, no_credential):
            with self.subTest(target=target.id), self.assertRaises(InvalidState):
                public.recover_mandatory_totp(
                    account_id=target.id,
                    reason="identity rechecked",
                    context=context,
                    authorize=valid_authorize,
                )
        credential.refresh_from_db()
        self.assertIsNone(credential.disabled_at)
        self.assertFalse(
            OneTimeToken.objects.filter(
                account=eligible,
                purpose="mandatory_totp_recovery",
            ).exists()
        )

    def test_begin_requires_password_anonymous_context_and_live_purpose_isolated_token(self):
        public = self.public_module()
        target, _, _, _, _ = self.prepare_target(sessions=0)
        raw_token, _, _, _, _, _ = self.start_recovery(target)
        token = OneTimeToken.objects.get(token_digest=hash_one_time_token(raw_token))

        with self.assertRaises(AuthenticationDenied):
            public.begin_mandatory_totp_recovery(
                raw_token=raw_token,
                current_password="wrong password",
                context=self.anonymous_context(now=self.now + timedelta(minutes=1)),
            )
        authenticated = OperationContext(
            actor_account_id=target.id,
            session_id=uuid4(),
            request_id=uuid4(),
            source="html",
            source_address="203.0.113.10",
            now=self.now + timedelta(minutes=1),
        )
        with self.assertRaises(InputRejected):
            public.begin_mandatory_totp_recovery(
                raw_token=raw_token,
                current_password=self.password,
                context=authenticated,
            )
        self.assertFalse(TotpSetup.objects.filter(recovery_token=token).exists())
        token.refresh_from_db()
        self.assertIsNone(token.used_at)

        invalid_tokens = (
            "malformed",
            generate_one_time_token()[0],
        )
        for candidate in invalid_tokens:
            with self.subTest(candidate=candidate), self.assertRaises(AuthenticationDenied):
                public.begin_mandatory_totp_recovery(
                    raw_token=candidate,
                    current_password=self.password,
                    context=self.anonymous_context(now=self.now + timedelta(minutes=1)),
                )

        wrong_raw, _ = self.seed_token(
            target,
            purpose="password_reset",
            created_at=self.now,
        )
        for candidate, mutate in (
            (wrong_raw, None),
            (raw_token, {"expires_at": self.now + timedelta(minutes=1)}),
            (raw_token, {"used_at": self.now}),
            (raw_token, {"revoked_at": self.now, "revoked_reason": "superseded"}),
        ):
            if mutate is not None:
                token_updates = {
                    "used_at": None,
                    "revoked_at": None,
                    "revoked_reason": None,
                    "expires_at": self.now + timedelta(minutes=30),
                }
                token_updates.update(mutate)
                OneTimeToken.objects.filter(pk=token.id).update(**token_updates)
            with self.subTest(candidate=candidate, mutate=mutate), self.assertRaises(
                AuthenticationDenied
            ):
                public.begin_mandatory_totp_recovery(
                    raw_token=candidate,
                    current_password=self.password,
                    context=self.anonymous_context(now=self.now + timedelta(minutes=1)),
                )

    def test_begin_creates_only_token_bound_encrypted_setup_and_supersedes_previous(self):
        public = self.public_module()
        target, _, _, _, _ = self.prepare_target(sessions=0)
        raw_token, _, _, _, _, _ = self.start_recovery(target)
        begin_at = self.now + timedelta(minutes=1)

        first = public.begin_mandatory_totp_recovery(
            raw_token=raw_token,
            current_password=self.password,
            context=self.anonymous_context(now=begin_at),
        )
        second = public.begin_mandatory_totp_recovery(
            raw_token=raw_token,
            current_password=self.password,
            context=self.anonymous_context(now=begin_at + timedelta(minutes=1)),
        )

        first_setup = TotpSetup.objects.get(pk=first.setup_id)
        second_setup = TotpSetup.objects.get(pk=second.setup_id)
        token = OneTimeToken.objects.get(token_digest=hash_one_time_token(raw_token))
        self.assertEqual(first_setup.invalidated_at, begin_at + timedelta(minutes=1))
        self.assertIsNone(first_setup.session_id)
        self.assertEqual(first_setup.recovery_token_id, token.id)
        self.assertIsNone(second_setup.session_id)
        self.assertEqual(second_setup.recovery_token_id, token.id)
        self.assertEqual(second.expires_at, begin_at + timedelta(minutes=11))
        self.assertNotIn(second.manual_secret.encode("ascii"), bytes(second_setup.encrypted_secret))
        decrypted = Fernet(settings.TOTP_ENCRYPTION_KEY.encode("ascii")).decrypt(
            bytes(second_setup.encrypted_secret)
        ).decode("ascii")
        self.assertEqual(decrypted, second.manual_secret)
        token.refresh_from_db()
        self.assertIsNone(token.used_at)

        constraint_names = {constraint.name for constraint in TotpSetup._meta.constraints}
        self.assertIn("identity_totp_setup_exactly_one_binding", constraint_names)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TotpSetup.objects.create(
                    account=target,
                    session=None,
                    recovery_token=None,
                    encrypted_secret=self.encrypt_secret(pyotp.random_base32(length=32)),
                    created_at=begin_at,
                    expires_at=begin_at + timedelta(minutes=10),
                )
        registry = self.create_registry(target, now=begin_at)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TotpSetup.objects.create(
                    account=target,
                    session=registry,
                    recovery_token=token,
                    encrypted_secret=self.encrypt_secret(pyotp.random_base32(length=32)),
                    created_at=begin_at,
                    expires_at=begin_at + timedelta(minutes=10),
                )

    def test_failed_recovery_password_is_audited_without_secrets(self):
        public = self.public_module()
        target, _, _, _, _ = self.prepare_target(sessions=0)
        raw_token, _, _, _, _, _ = self.start_recovery(target)
        context = self.anonymous_context(now=self.now + timedelta(minutes=1))
        wrong_password = "wrong password"

        with self.assertRaises(AuthenticationDenied):
            public.begin_mandatory_totp_recovery(
                raw_token=raw_token,
                current_password=wrong_password,
                context=context,
            )

        entry = AuditEntry.objects.get(
            request_id=context.request_id,
            action="identity.mandatory_totp_recovery_failed",
        )
        self.assertIsNone(entry.actor_id)
        self.assertEqual(entry.result, "failed")
        self.assertEqual(entry.reason, "mandatory_totp_recovery_failed")
        self.assertEqual(
            set(entry.after),
            {"subject_fingerprint", "source_fingerprint"},
        )
        serialized = repr((entry.object_id, entry.reason, entry.before, entry.after))
        for secret in (target.email, raw_token, wrong_password, context.source_address):
            self.assertNotIn(secret, serialized)

    def test_failed_recovery_totp_is_audited_without_secrets(self):
        public = self.public_module()
        target, _, _, _, _ = self.prepare_target(sessions=0)
        raw_token, _, _, _, _, _ = self.start_recovery(target)
        attempt_at = self.now + timedelta(minutes=1)
        view = public.begin_mandatory_totp_recovery(
            raw_token=raw_token,
            current_password=self.password,
            context=self.anonymous_context(now=attempt_at),
        )
        accepted_codes = {
            pyotp.TOTP(view.manual_secret).at(
                attempt_at + timedelta(seconds=offset * 30)
            )
            for offset in (-1, 0, 1)
        }
        wrong_code = next(
            candidate
            for candidate in ("000000", "111111", "222222", "333333")
            if candidate not in accepted_codes
        )
        context = self.anonymous_context(now=attempt_at)

        with self.assertRaises(AuthenticationDenied):
            public.complete_mandatory_totp_recovery(
                raw_token=raw_token,
                setup_id=view.setup_id,
                code=wrong_code,
                context=context,
            )

        entry = AuditEntry.objects.get(
            request_id=context.request_id,
            action="identity.mandatory_totp_recovery_failed",
        )
        self.assertEqual(entry.result, "failed")
        self.assertEqual(entry.reason, "mandatory_totp_recovery_failed")
        serialized = repr((entry.object_id, entry.reason, entry.before, entry.after))
        for secret in (target.email, raw_token, view.manual_secret, wrong_code):
            self.assertNotIn(secret, serialized)

    def test_setup_never_outlives_recovery_token(self):
        public = self.public_module()
        target, _, _, _, _ = self.prepare_target(sessions=0)
        raw_token, _, _, _, _, _ = self.start_recovery(target)
        begin_at = self.now + timedelta(minutes=29, seconds=59)

        view = public.begin_mandatory_totp_recovery(
            raw_token=raw_token,
            current_password=self.password,
            context=self.anonymous_context(now=begin_at),
        )

        self.assertEqual(view.expires_at, self.now + timedelta(minutes=30))

    def test_complete_replaces_credential_once_preserves_requirement_and_notifies(self):
        public = self.public_module()
        target, old_credential, requirement, _, _ = self.prepare_target(sessions=1)
        raw_token, _, _, _, _, _ = self.start_recovery(target)
        begin_at = self.now + timedelta(minutes=1)
        complete_at = self.now + timedelta(minutes=2)
        view = public.begin_mandatory_totp_recovery(
            raw_token=raw_token,
            current_password=self.password,
            context=self.anonymous_context(now=begin_at),
        )
        code = pyotp.TOTP(view.manual_secret, digits=6, interval=30).at(complete_at)

        codes = public.complete_mandatory_totp_recovery(
            raw_token=raw_token,
            setup_id=view.setup_id,
            code=code,
            context=self.anonymous_context(now=complete_at),
        )

        self.assertEqual(len(codes), settings.RECOVERY_CODE_COUNT)
        self.assertEqual(len(codes), len(set(codes)))
        active = TotpCredential.objects.get(account=target, disabled_at__isnull=True)
        self.assertNotEqual(active.id, old_credential.id)
        self.assertEqual(active.confirmed_at, complete_at)
        decrypted = Fernet(settings.TOTP_ENCRYPTION_KEY.encode("ascii")).decrypt(
            bytes(active.encrypted_secret)
        ).decode("ascii")
        self.assertEqual(decrypted, view.manual_secret)
        token = OneTimeToken.objects.get(token_digest=hash_one_time_token(raw_token))
        setup = TotpSetup.objects.get(pk=view.setup_id)
        self.assertEqual(token.used_at, complete_at)
        self.assertEqual(setup.consumed_at, complete_at)
        requirement.refresh_from_db()
        self.assertIsNone(requirement.removed_at)
        self.assertEqual(
            RecoveryCode.objects.filter(
                account=target,
                issued_at=complete_at,
                used_at__isnull=True,
                revoked_at__isnull=True,
            ).count(),
            settings.RECOVERY_CODE_COUNT,
        )
        for code_value in codes:
            self.assertTrue(
                RecoveryCode.objects.filter(
                    account=target,
                    code_digest=hash_one_time_token(code_value),
                ).exists()
            )
        entry = AuditEntry.objects.get(
            action="identity.mandatory_totp_recovery_completed"
        )
        self.assertIsNone(entry.actor_id)
        self.assertEqual(entry.after["totp_enabled"], True)
        notification = OutboxMessage.objects.get(
            message_type="identity.protected_account_change",
            payload__change="totp_recovered",
        )
        self.assertEqual(notification.payload["account_id"], str(target.id))
        serialized = repr((entry.before, entry.after, notification.payload))
        for secret in (raw_token, view.manual_secret, *codes):
            self.assertNotIn(secret, serialized)

    def test_wrong_binding_invalid_code_and_replay_are_generic_and_nonmutating(self):
        public = self.public_module()
        first, _, _, _, _ = self.prepare_target(sessions=0)
        second, _, _, _, _ = self.prepare_target(sessions=0)
        first_raw, _, _, _, _, _ = self.start_recovery(first)
        second_raw, _, _, _, _, _ = self.start_recovery(second)
        begin_at = self.now + timedelta(minutes=1)
        first_view = public.begin_mandatory_totp_recovery(
            raw_token=first_raw,
            current_password=self.password,
            context=self.anonymous_context(now=begin_at),
        )
        second_view = public.begin_mandatory_totp_recovery(
            raw_token=second_raw,
            current_password=self.password,
            context=self.anonymous_context(now=begin_at),
        )

        first_totp = pyotp.TOTP(first_view.manual_secret)
        accepted_codes = {
            first_totp.at(begin_at + timedelta(seconds=offset * 30))
            for offset in (-1, 0, 1)
        }
        invalid_code = next(
            candidate for candidate in ("000000", "111111", "222222", "333333")
            if candidate not in accepted_codes
        )
        invalid_calls = (
            (first_raw, second_view.setup_id, pyotp.TOTP(second_view.manual_secret).at(begin_at)),
            (second_raw, first_view.setup_id, first_totp.at(begin_at)),
            (first_raw, first_view.setup_id, invalid_code),
        )
        for raw_token, setup_id, code in invalid_calls:
            with self.subTest(setup_id=setup_id), self.assertRaises(AuthenticationDenied):
                public.complete_mandatory_totp_recovery(
                    raw_token=raw_token,
                    setup_id=setup_id,
                    code=code,
                    context=self.anonymous_context(now=begin_at),
                )
        first_token = OneTimeToken.objects.get(token_digest=hash_one_time_token(first_raw))
        first_setup = TotpSetup.objects.get(pk=first_view.setup_id)
        self.assertIsNone(first_token.used_at)
        self.assertIsNone(first_setup.consumed_at)
        self.assertFalse(
            TotpCredential.objects.filter(account=first, disabled_at__isnull=True).exists()
        )

        valid_code = pyotp.TOTP(first_view.manual_secret).at(begin_at)
        public.complete_mandatory_totp_recovery(
            raw_token=first_raw,
            setup_id=first_view.setup_id,
            code=valid_code,
            context=self.anonymous_context(now=begin_at),
        )
        with self.assertRaises(AuthenticationDenied):
            public.complete_mandatory_totp_recovery(
                raw_token=first_raw,
                setup_id=first_view.setup_id,
                code=valid_code,
                context=self.anonymous_context(now=begin_at),
            )
        self.assertEqual(
            TotpCredential.objects.filter(account=first, disabled_at__isnull=True).count(),
            1,
        )
        self.assertEqual(
            RecoveryCode.objects.filter(
                account=first,
                revoked_at__isnull=True,
                used_at__isnull=True,
            ).count(),
            settings.RECOVERY_CODE_COUNT,
        )

    def test_start_and_completion_roll_back_all_effects_on_dependency_failure(self):
        public = self.public_module()
        for dependency in ("append_audit_entry", "enqueue_outbox_message"):
            target, credential, _, _, registries = self.prepare_target(sessions=1)
            actor = self.create_account()
            context = self.admin_context(actor)
            authorize, _ = self.authorize(context)
            with self.subTest(stage="start", dependency=dependency), patch(
                f"open_marketplace.identity.application.{dependency}",
                side_effect=RuntimeError("dependency unavailable"),
            ), self.assertRaises(RuntimeError):
                public.recover_mandatory_totp(
                    account_id=target.id,
                    reason="identity rechecked",
                    context=context,
                    authorize=authorize,
                )
            credential.refresh_from_db()
            registries[0].refresh_from_db()
            self.assertIsNone(credential.disabled_at)
            self.assertIsNone(registries[0].revoked_at)
            self.assertFalse(
                OneTimeToken.objects.filter(
                    account=target,
                    purpose="mandatory_totp_recovery",
                ).exists()
            )
            self.assertTrue(
                RecoveryCode.objects.filter(account=target, revoked_at__isnull=True).exists()
            )

        for dependency in ("append_audit_entry", "enqueue_outbox_message"):
            target, _, _, _, _ = self.prepare_target(sessions=0)
            raw_token, _, _, _, _, _ = self.start_recovery(target)
            begin_at = self.now + timedelta(minutes=1)
            view = public.begin_mandatory_totp_recovery(
                raw_token=raw_token,
                current_password=self.password,
                context=self.anonymous_context(now=begin_at),
            )
            code = pyotp.TOTP(view.manual_secret).at(begin_at)
            token = OneTimeToken.objects.get(token_digest=hash_one_time_token(raw_token))
            old_code_count = RecoveryCode.objects.filter(account=target).count()
            with self.subTest(stage="complete", dependency=dependency), patch(
                f"open_marketplace.identity.application.{dependency}",
                side_effect=RuntimeError("dependency unavailable"),
            ), self.assertRaises(RuntimeError):
                public.complete_mandatory_totp_recovery(
                    raw_token=raw_token,
                    setup_id=view.setup_id,
                    code=code,
                    context=self.anonymous_context(now=begin_at),
                )
            token.refresh_from_db()
            setup = TotpSetup.objects.get(pk=view.setup_id)
            self.assertIsNone(token.used_at)
            self.assertIsNone(setup.consumed_at)
            self.assertFalse(
                TotpCredential.objects.filter(account=target, disabled_at__isnull=True).exists()
            )
            self.assertEqual(
                RecoveryCode.objects.filter(account=target).count(),
                old_code_count,
            )
