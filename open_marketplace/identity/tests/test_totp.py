import json
import re
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from importlib import import_module
from urllib.parse import parse_qs, unquote, urlparse
from uuid import uuid4

import pyotp
from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db.models.deletion import PROTECT
from django.test import TestCase
from django.utils.crypto import get_random_string

from open_marketplace.audit.public import AuditQuery, query_audit_entries
from open_marketplace.common.errors import AuthenticationDenied, InvalidState
from open_marketplace.common.types import AuthorizationDecision, OperationContext
from open_marketplace.identity.models import Account, AccountSession
from open_marketplace.outbox.public import claim_ready_messages


class TotpTestCase(TestCase):
    now = datetime(2026, 9, 2, 12, tzinfo=UTC)
    password = f"T3st!{uuid4().hex}"

    def public_module(self):
        public = import_module("open_marketplace.identity.public")
        for name in (
            "TotpSetupView",
            "add_totp_requirement",
            "begin_totp_setup",
            "disable_optional_totp",
            "enable_totp",
            "reauthenticate_session",
            "remove_totp_requirement",
            "replace_recovery_codes",
        ):
            self.assertTrue(hasattr(public, name), f"{name} must be public.")
        return public

    def models(self):
        models = import_module("open_marketplace.identity.models")
        for name in ("TotpSetup", "TotpCredential", "TotpRequirement", "RecoveryCode"):
            self.assertTrue(hasattr(models, name), f"{name} must exist.")
        return models

    def create_account(self, *, email=None, kind=Account.Kind.ORDINARY):
        create = (
            Account.objects.create_service_account
            if kind == Account.Kind.SERVICE
            else Account.objects.create_user
        )
        return create(
            email=email or f"person-{uuid4()}@example.com",
            password=self.password,
            state=Account.State.ACTIVE,
            email_verified_at=self.now - timedelta(days=1),
        )

    def create_registry(self, account, *, reauthenticated_at=None):
        key = self.create_django_session()
        created_at = self.now - timedelta(hours=1)
        return AccountSession.objects.create(
            account=account,
            django_session_key=key,
            created_at=created_at,
            last_activity_at=created_at,
            absolute_expires_at=self.now + timedelta(days=1),
            reauthenticated_at=reauthenticated_at or created_at,
            device_label="Firefox on Linux",
        )

    def create_django_session(self, *, expires_at=None):
        key = get_random_string(32, "abcdefghijklmnopqrstuvwxyz0123456789")
        Session.objects.create(
            session_key=key,
            session_data=SessionStore().encode({}),
            expire_date=expires_at or self.now + timedelta(days=31),
        )
        return key

    def context(self, registry, *, now=None, request_id=None):
        return OperationContext(
            actor_account_id=registry.account_id,
            session_id=registry.id,
            request_id=request_id or uuid4(),
            source="html",
            source_address="203.0.113.10",
            now=now or self.now,
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

    def begin(self, registry, *, password=None, now=None):
        return self.public_module().begin_totp_setup(
            current_password=self.password if password is None else password,
            context=self.context(registry, now=now),
        )

    def enable(self, registry, setup_view, *, code=None, now=None):
        now = now or self.now
        code = code or pyotp.TOTP(setup_view.manual_secret).at(now)
        return self.public_module().enable_totp(
            setup_id=setup_view.setup_id,
            code=code,
            context=self.context(registry, now=now),
        )

    def authenticate(self, account, *, second_factor=None, now=None):
        now = now or self.now
        return self.public_module().authenticate_account(
            email=account.email,
            password=self.password,
            second_factor=second_factor,
            django_session_key=self.create_django_session(),
            device_label="Firefox on Linux",
            context=self.anonymous_context(now=now),
        )

    def decrypt_secret(self, ciphertext):
        return Fernet(settings.TOTP_ENCRYPTION_KEY.encode("ascii")).decrypt(
            bytes(ciphertext)
        ).decode("ascii")

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
            return AuthorizationDecision(
                account_id=actor_id,
                permission=permission,
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


class TotpFlowTests(TotpTestCase):
    def test_setup_is_session_bound_encrypted_expiring_and_superseded(self):
        models = self.models()
        public = self.public_module()
        account = self.create_account(email="person@example.com")
        registry = self.create_registry(account)

        view = self.begin(registry)

        self.assertIsInstance(view, public.TotpSetupView)
        self.assertRegex(view.manual_secret, r"^[A-Z2-7]{32}$")
        self.assertEqual(view.expires_at, self.now + timedelta(minutes=10))
        self.assertEqual(settings.TOTP_SETUP_TTL, timedelta(minutes=10))
        parsed = urlparse(view.provisioning_uri)
        self.assertEqual(parsed.scheme, "otpauth")
        self.assertEqual(parsed.netloc, "totp")
        self.assertIn(account.email, unquote(parsed.path))
        query = parse_qs(parsed.query)
        self.assertEqual(query["issuer"], ["Open Marketplace"])
        self.assertEqual(query.get("digits", ["6"]), ["6"])
        self.assertEqual(query.get("period", ["30"]), ["30"])
        with self.assertRaises(FrozenInstanceError):
            view.manual_secret = "changed"

        setup = models.TotpSetup.objects.get()
        self.assertEqual(setup.id, view.setup_id)
        self.assertEqual(setup.account_id, account.id)
        self.assertEqual(setup.session_id, registry.id)
        self.assertEqual(setup.created_at, self.now)
        self.assertEqual(setup.expires_at, view.expires_at)
        self.assertIsNone(setup.consumed_at)
        self.assertIsNone(setup.invalidated_at)
        self.assertEqual(self.decrypt_secret(setup.encrypted_secret), view.manual_secret)
        self.assertNotIn(view.manual_secret.encode("ascii"), bytes(setup.encrypted_secret))
        self.assertNotIn(view.manual_secret, repr(setup))
        self.assertNotIn(view.provisioning_uri, repr(setup))
        self.assertIs(setup._meta.get_field("account").remote_field.on_delete, PROTECT)
        self.assertIs(setup._meta.get_field("session").remote_field.on_delete, PROTECT)

        second = self.begin(registry, now=self.now + timedelta(minutes=1))
        setup.refresh_from_db()
        self.assertEqual(setup.invalidated_at, self.now + timedelta(minutes=1))
        self.assertNotEqual(second.setup_id, setup.id)
        self.assertNotEqual(second.manual_secret, view.manual_secret)
        with self.assertRaises(AuthenticationDenied):
            self.begin(registry, password=f"Wrong!{uuid4().hex}")

    def test_enable_accepts_adjacent_window_once_and_creates_encrypted_credential_and_codes(self):
        models = self.models()
        account = self.create_account()
        registry = self.create_registry(account)
        view = self.begin(registry)
        totp = pyotp.TOTP(view.manual_secret, digits=6, interval=30)
        previous_code = totp.at(self.now - timedelta(seconds=30))

        codes = self.enable(registry, view, code=previous_code)

        self.assertEqual(len(codes), 10)
        setup = models.TotpSetup.objects.get(pk=view.setup_id)
        credential = models.TotpCredential.objects.get()
        self.assertEqual(setup.consumed_at, self.now)
        self.assertEqual(credential.account_id, account.id)
        self.assertEqual(credential.confirmed_at, self.now)
        self.assertIsNone(credential.disabled_at)
        self.assertEqual(
            credential.last_accepted_counter,
            totp.timecode(self.now) - 1,
        )
        self.assertEqual(self.decrypt_secret(credential.encrypted_secret), view.manual_secret)
        self.assertNotIn(view.manual_secret.encode("ascii"), bytes(credential.encrypted_secret))
        registry.refresh_from_db()
        self.assertEqual(registry.reauthenticated_at, self.now)
        self.assertEqual(models.RecoveryCode.objects.count(), 10)
        self.assertEqual(len(set(models.RecoveryCode.objects.values_list("set_id", flat=True))), 1)

        actions = sorted(entry.action for entry in self.audit_entries())
        self.assertEqual(
            actions,
            ["identity.recovery_codes_issued", "identity.totp_enabled"],
        )
        messages = self.claim_outbox()
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].message_type, "identity.protected_account_change")
        self.assertEqual(
            dict(messages[0].payload),
            {"account_id": str(account.id), "change": "totp_enabled"},
        )
        self.assertEqual(self.decrypt_delivery(messages[0]), {"recipient": account.email})
        serialized = repr((credential, self.audit_entries(), messages[0].payload))
        self.assertNotIn(view.manual_secret, serialized)
        for code in codes:
            self.assertNotIn(code, serialized)

    def test_invalid_expired_wrong_session_and_replayed_setup_are_generic_and_safe(self):
        models = self.models()
        account = self.create_account()
        registry = self.create_registry(account)
        other = self.create_registry(account)
        view = self.begin(registry)
        setup = models.TotpSetup.objects.get(pk=view.setup_id)
        messages = set()

        attempts = (
            (registry, "000000", self.now),
            (other, pyotp.TOTP(view.manual_secret).at(self.now), self.now),
            (registry, pyotp.TOTP(view.manual_secret).at(self.now + timedelta(minutes=10)), self.now + timedelta(minutes=10)),
        )
        for received_registry, code, now in attempts:
            with self.subTest(now=now, session=received_registry.id), self.assertRaises(AuthenticationDenied) as raised:
                self.enable(received_registry, view, code=code, now=now)
            messages.add(str(raised.exception))
            setup.refresh_from_db()
            self.assertIsNone(setup.consumed_at)

        valid_code = pyotp.TOTP(view.manual_secret).at(self.now)
        self.enable(registry, view, code=valid_code)
        with self.assertRaises(AuthenticationDenied) as raised:
            self.enable(registry, view, code=valid_code)
        messages.add(str(raised.exception))
        self.assertEqual(len(messages), 1)

    def test_login_requires_active_factor_rejects_replay_and_allows_pre_setup_requirement(self):
        models = self.models()
        public = self.public_module()
        account = self.create_account(email="factor@example.com")
        registry = self.create_registry(account)
        view = self.begin(registry)
        totp = pyotp.TOTP(view.manual_secret)
        enabling_code = totp.at(self.now)
        self.enable(registry, view, code=enabling_code)

        failures = (None, "000000", enabling_code)
        messages = set()
        for factor in failures:
            with self.subTest(factor=factor), self.assertRaises(AuthenticationDenied) as raised:
                self.authenticate(account, second_factor=factor, now=self.now)
            messages.add(str(raised.exception))
        self.assertEqual(messages, {"Authentication failed."})

        login_now = self.now + timedelta(seconds=30)
        result = self.authenticate(
            account,
            second_factor=totp.at(login_now),
            now=login_now,
        )
        self.assertEqual(result.account_id, account.id)
        credential = models.TotpCredential.objects.get(account=account)
        self.assertEqual(credential.last_accepted_counter, totp.timecode(login_now))

        setup_limited = self.create_account(email="setup-limited@example.com")
        source_id = uuid4()
        public.add_totp_requirement(
            account_id=setup_limited.id,
            source_type="seller_profile",
            source_id=source_id,
            context=self.context(self.create_registry(setup_limited)),
        )
        restricted_result = self.authenticate(setup_limited, second_factor=None)
        self.assertEqual(restricted_result.account_id, setup_limited.id)
        self.assertTrue(
            models.TotpRequirement.objects.filter(
                account=setup_limited,
                source_id=source_id,
                removed_at__isnull=True,
            ).exists()
        )

    def test_reauthentication_is_bound_to_current_session_and_updates_freshness(self):
        models = self.models()
        public = self.public_module()
        account = self.create_account()
        registry = self.create_registry(account, reauthenticated_at=self.now - timedelta(hours=1))
        view = self.begin(registry)
        self.enable(registry, view)
        credential = models.TotpCredential.objects.get()
        secret = self.decrypt_secret(credential.encrypted_secret)
        reauth_now = self.now + timedelta(seconds=30)

        result = public.reauthenticate_session(
            password=self.password,
            second_factor=pyotp.TOTP(secret).at(reauth_now),
            context=self.context(registry, now=reauth_now),
        )

        self.assertEqual(result, reauth_now)
        registry.refresh_from_db()
        self.assertEqual(registry.reauthenticated_at, reauth_now)
        snapshot = public.get_session_security_snapshot(
            session_id=registry.id,
            account_id=account.id,
        )
        self.assertLess(
            reauth_now + timedelta(minutes=14, seconds=59),
            snapshot.reauthenticated_at + settings.SENSITIVE_ACTION_REAUTH_TTL,
        )
        self.assertEqual(
            reauth_now + timedelta(minutes=15),
            snapshot.reauthenticated_at + settings.SENSITIVE_ACTION_REAUTH_TTL,
        )
        with self.assertRaises(AuthenticationDenied):
            public.reauthenticate_session(
                password=self.password,
                second_factor=pyotp.TOTP(secret).at(reauth_now),
                context=self.context(registry, now=reauth_now),
            )

        no_totp = self.create_account()
        no_totp_session = self.create_registry(no_totp)
        self.assertEqual(
            public.reauthenticate_session(
                password=self.password,
                second_factor=None,
                context=self.context(no_totp_session),
            ),
            self.now,
        )

    def test_requirements_are_independent_idempotent_tombstones(self):
        models = self.models()
        public = self.public_module()
        account = self.create_account()
        registry = self.create_registry(account)
        context = self.context(registry)
        role_id = uuid4()
        seller_id = uuid4()

        for _ in range(2):
            public.add_totp_requirement(
                account_id=account.id,
                source_type="staff_role",
                source_id=role_id,
                context=context,
            )
        public.add_totp_requirement(
            account_id=account.id,
            source_type="seller_profile",
            source_id=seller_id,
            context=context,
        )
        self.assertEqual(models.TotpRequirement.objects.count(), 2)

        public.remove_totp_requirement(
            account_id=account.id,
            source_type="staff_role",
            source_id=role_id,
            context=context,
        )
        public.remove_totp_requirement(
            account_id=account.id,
            source_type="staff_role",
            source_id=role_id,
            context=context,
        )
        public.remove_totp_requirement(
            account_id=account.id,
            source_type="staff_role",
            source_id=uuid4(),
            context=context,
        )
        role = models.TotpRequirement.objects.get(source_id=role_id)
        seller = models.TotpRequirement.objects.get(source_id=seller_id)
        self.assertEqual(role.removed_at, self.now)
        self.assertIsNone(seller.removed_at)

        public.add_totp_requirement(
            account_id=account.id,
            source_type="staff_role",
            source_id=role_id,
            context=self.context(registry, now=self.now + timedelta(minutes=1)),
        )
        role.refresh_from_db()
        self.assertEqual(role.removed_at, self.now)
        self.assertEqual(models.TotpRequirement.objects.count(), 2)

        for field in ("account",):
            self.assertIs(
                models.TotpRequirement._meta.get_field(field).remote_field.on_delete,
                PROTECT,
            )
        self.assertEqual(
            set(models.TotpRequirement.SourceType.values),
            {"staff_role", "seller_profile"},
        )

        view = self.begin(registry)
        self.enable(registry, view)
        with self.assertRaises(InvalidState):
            public.disable_optional_totp(
                password=self.password,
                second_factor=pyotp.TOTP(view.manual_secret).at(self.now + timedelta(seconds=30)),
                context=self.context(registry, now=self.now + timedelta(seconds=30)),
            )

    def test_account_snapshot_reflects_active_credential(self):
        public = self.public_module()
        account = self.create_account()
        registry = self.create_registry(account)
        self.assertFalse(public.get_account_snapshot(account.id).totp_enabled)
        view = self.begin(registry)
        self.enable(registry, view)
        self.assertTrue(public.get_account_snapshot(account.id).totp_enabled)
