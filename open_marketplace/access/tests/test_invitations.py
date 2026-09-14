import json
from datetime import UTC, datetime, timedelta
from importlib import import_module
from unittest.mock import patch
from uuid import uuid4

import pyotp
from cryptography.fernet import Fernet
from django.apps import apps
from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.test import TestCase, TransactionTestCase
from django.utils.crypto import get_random_string

from open_marketplace.common.crypto import generate_one_time_token
from open_marketplace.common.errors import (
    AuthenticationDenied,
    InputRejected,
    InvalidState,
    PermissionDenied,
    RateLimited,
)
from open_marketplace.common.types import OperationContext
from open_marketplace.identity import public as identity_public


Account = apps.get_model("identity", "Account")
AuditEntry = apps.get_model("audit", "AuditEntry")
OutboxMessage = apps.get_model("outbox", "OutboxMessage")
RoleAssignment = apps.get_model("access", "RoleAssignment")
StaffInvitation = apps.get_model("access", "StaffInvitation")
StaffInvitationAcceptance = apps.get_model("access", "StaffInvitationAcceptance")
TotpCredential = apps.get_model("identity", "TotpCredential")
SecurityThrottle = apps.get_model("identity", "SecurityThrottle")
TotpRequirement = apps.get_model("identity", "TotpRequirement")
TotpSetup = apps.get_model("identity", "TotpSetup")
OneTimeToken = apps.get_model("identity", "OneTimeToken")


class InvitationTestCase(TestCase):
    now = datetime(2026, 9, 2, 12, tzinfo=UTC)
    password = f"T3st!{uuid4().hex}"

    def public(self):
        return import_module("open_marketplace.access.public")

    def create_account(self, *, kind=Account.Kind.SERVICE, email=None, totp=False):
        create = (
            Account.objects.create_service_account
            if kind == Account.Kind.SERVICE
            else Account.objects.create_user
        )
        account = create(
            email=email or f"user-{uuid4()}@example.com",
            password=self.password,
            state=Account.State.ACTIVE,
            email_verified_at=self.now - timedelta(days=1),
        )
        if totp:
            secret = pyotp.random_base32()
            TotpCredential.objects.create(
                account=account,
                encrypted_secret=Fernet(settings.TOTP_ENCRYPTION_KEY.encode("ascii")).encrypt(secret.encode("ascii")),
                confirmed_at=self.now - timedelta(days=1),
                last_accepted_counter=1,
            )
            account._test_totp_secret = secret
        return account

    def session(self, account):
        key = get_random_string(32, "abcdefghijklmnopqrstuvwxyz0123456789")
        Session.objects.create(
            session_key=key,
            session_data=SessionStore().encode({}),
            expire_date=self.now + timedelta(days=1),
        )
        return apps.get_model("identity", "AccountSession").objects.create(
            account=account,
            django_session_key=key,
            created_at=self.now - timedelta(hours=1),
            last_activity_at=self.now - timedelta(minutes=1),
            absolute_expires_at=self.now + timedelta(hours=1),
            reauthenticated_at=self.now - timedelta(minutes=1),
            device_label="test",
        )

    def context(
        self,
        account=None,
        registry=None,
        *,
        now=None,
        source="admin",
        source_address="203.0.113.10",
    ):
        return OperationContext(
            actor_account_id=account.id if account else None,
            session_id=registry.id if registry else None,
            request_id=uuid4(),
            source=source,
            source_address=source_address,
            now=now or self.now,
        )

    def authorized_admin(self):
        admin = self.create_account(totp=True)
        RoleAssignment = apps.get_model("access", "RoleAssignment")
        RoleAssignment.objects.create(
            account_id=admin.id,
            role="security_admin",
            assigned_reason="test fixture",
            active_from=self.now - timedelta(days=1),
        )
        registry = self.session(admin)
        return admin, self.context(admin, registry)

    def invitation_token(self, invitation_id):
        message = OutboxMessage.objects.get(
            message_type="access.staff_invitation",
            payload__invitation_id=str(invitation_id),
        )
        delivery = json.loads(
            Fernet(settings.OUTBOX_ENCRYPTION_KEY.encode("ascii"))
            .decrypt(bytes(message.encrypted_delivery))
        )
        return delivery["absolute_token_url"].rsplit("/", 2)[-2]

    def test_public_contract_and_invitation_creation_store_only_digest(self):
        public = self.public()
        for name in (
            "StaffInvitationQuery",
            "StaffInvitationView",
            "StaffAcceptanceSetup",
            "StaffAcceptanceResult",
            "list_staff_invitations",
            "invite_staff_member",
            "begin_staff_invitation_acceptance",
            "accept_staff_invitation",
            "revoke_staff_invitation",
            "bootstrap_security_admin",
        ):
            self.assertTrue(hasattr(public, name), name)
        admin, context = self.authorized_admin()

        invitation_id = public.invite_staff_member(
            email=" New.Staff@example.com ",
            role="seller_reviewer",
            context=context,
        )
        Invitation = apps.get_model("access", "StaffInvitation")
        invitation = Invitation.objects.get(pk=invitation_id)
        raw_token = self.invitation_token(invitation_id)

        self.assertEqual(invitation.email, "new.staff@example.com")
        self.assertEqual(len(invitation.token_digest), 64)
        self.assertNotIn(raw_token, invitation.token_digest)
        audit_text = " ".join(
            str(value)
            for value in AuditEntry.objects.values_list("reason", "before", "after")
        )
        self.assertNotIn(raw_token, audit_text)
        self.assertEqual(invitation.created_by_id, admin.id)

    def test_new_invitation_is_unprivileged_until_bound_totp_completion_and_is_one_time(self):
        public = self.public()
        admin, context = self.authorized_admin()
        invitation_id = public.invite_staff_member(
            email="new-staff@example.com", role="security_admin", context=context
        )
        raw_token = self.invitation_token(invitation_id)

        setup = public.begin_staff_invitation_acceptance(
            raw_token=raw_token,
            password=f"Strong password {uuid4().hex}",
            context=self.context(),
        )
        account = Account.objects.get(pk=setup.account_id)
        self.assertEqual(account.kind, "service")
        self.assertEqual(account.state, "active")
        self.assertIsNotNone(account.email_verified_at)
        self.assertFalse(apps.get_model("access", "RoleAssignment").objects.filter(account_id=account.id).exists())
        self.assertFalse(TotpRequirement.objects.filter(account=account).exists())

        retry_context = self.context(account, self.session(account))
        login_throttle_before = SecurityThrottle.objects.filter(scope="login").count()
        repeated = public.begin_staff_invitation_acceptance(
            raw_token=raw_token,
            password="the password is ignored for an idempotent retry",
            context=retry_context,
        )
        self.assertEqual(repeated.acceptance_id, setup.acceptance_id)
        self.assertEqual(repeated.account_id, setup.account_id)
        self.assertIsNone(repeated.totp_setup)
        self.assertEqual(SecurityThrottle.objects.filter(scope="login").count(), login_throttle_before)
        self.assertFalse(
            AuditEntry.objects.filter(request_id=retry_context.request_id).exists()
        )

        secret = Fernet(settings.TOTP_ENCRYPTION_KEY.encode("ascii")).decrypt(
            bytes(apps.get_model("identity", "TotpSetup").objects.get(pk=setup.totp_setup.setup_id).encrypted_secret)
        ).decode()
        result = public.accept_staff_invitation(
            acceptance_id=setup.acceptance_id,
            raw_token=raw_token,
            totp_code=pyotp.TOTP(secret).at(self.now),
            context=self.context(),
        )
        self.assertEqual(len(result.recovery_codes), settings.RECOVERY_CODE_COUNT)
        self.assertEqual(
            apps.get_model("access", "RoleAssignment").objects.filter(
                account_id=account.id, role="security_admin", state="active"
            ).count(),
            1,
        )
        self.assertEqual(TotpRequirement.objects.filter(account=account, removed_at=None).count(), 1)
        with self.assertRaises((AuthenticationDenied, InvalidState)):
            public.accept_staff_invitation(
                acceptance_id=setup.acceptance_id,
                raw_token=raw_token,
                totp_code=pyotp.TOTP(secret).at(self.now),
                context=self.context(),
            )

    def test_expired_pending_new_service_setup_restarts_at_expiry_boundary(self):
        public = self.public()
        _, context = self.authorized_admin()
        invitation_id = public.invite_staff_member(
            email="expired-new-staff@example.com",
            role="security_admin",
            context=context,
        )
        raw_token = self.invitation_token(invitation_id)
        password = f"Strong password {uuid4().hex}"
        started = self.now - settings.TOTP_SETUP_TTL

        initial = public.begin_staff_invitation_acceptance(
            raw_token=raw_token,
            password=password,
            context=self.context(now=started),
        )
        account = Account.objects.get(pk=initial.account_id)
        old_setup = TotpSetup.objects.get(pk=initial.totp_setup.setup_id)
        old_encrypted_secret = bytes(old_setup.encrypted_secret)
        old_password = account.password
        invitation = StaffInvitation.objects.get(pk=invitation_id)

        restart_context = self.context(now=old_setup.expires_at)
        restarted = public.begin_staff_invitation_acceptance(
            raw_token=raw_token,
            password=password,
            context=restart_context,
        )

        self.assertEqual(restarted.acceptance_id, initial.acceptance_id)
        self.assertEqual(restarted.account_id, account.id)
        self.assertEqual(restarted.mode, "new_service_account")
        self.assertIsNotNone(restarted.totp_setup)
        self.assertNotEqual(restarted.totp_setup.setup_id, old_setup.id)
        new_setup = TotpSetup.objects.get(pk=restarted.totp_setup.setup_id)
        self.assertNotEqual(bytes(new_setup.encrypted_secret), old_encrypted_secret)
        self.assertEqual(new_setup.created_at, old_setup.expires_at)
        self.assertEqual(new_setup.expires_at, self.now + settings.TOTP_SETUP_TTL)
        restart_audit = AuditEntry.objects.get(request_id=restart_context.request_id)
        self.assertEqual(restart_audit.action, "identity.invited_service_totp_restarted")
        self.assertEqual(restart_audit.object_type, "account")
        self.assertEqual(restart_audit.object_id, str(account.id))
        self.assertEqual(restart_audit.result, "succeeded")
        self.assertEqual(restart_audit.before, {"totp_enabled": False})
        self.assertEqual(restart_audit.after["totp_enabled"], False)
        self.assertIn("expires_at", restart_audit.after)
        serialized_audit = repr(restart_audit)
        for value in (password, account.email, restart_context.source_address):
            self.assertNotIn(value, serialized_audit)
        old_setup.refresh_from_db()
        self.assertEqual(old_setup.invalidated_at, self.now)
        acceptance = StaffInvitationAcceptance.objects.get(pk=initial.acceptance_id)
        self.assertEqual(acceptance.totp_setup_id, new_setup.id)

        account.refresh_from_db()
        invitation.refresh_from_db()
        self.assertEqual(account.password, old_password)
        self.assertIsNone(invitation.accepted_at)
        self.assertFalse(
            TotpCredential.objects.filter(account=account, disabled_at__isnull=True).exists()
        )
        self.assertFalse(
            RoleAssignment.objects.filter(account_id=account.id, state="active").exists()
        )
        self.assertFalse(
            TotpRequirement.objects.filter(account=account, removed_at__isnull=True).exists()
        )

        with self.assertRaises(AuthenticationDenied):
            identity_public.enable_invited_service_totp(
                account_id=account.id,
                setup_id=old_setup.id,
                code="000000",
                invitation_id=invitation.id,
                context=self.context(now=self.now),
            )

        result = public.accept_staff_invitation(
            acceptance_id=restarted.acceptance_id,
            raw_token=raw_token,
            totp_code=pyotp.TOTP(restarted.totp_setup.manual_secret).at(self.now),
            context=self.context(now=self.now),
        )

        self.assertEqual(len(result.recovery_codes), settings.RECOVERY_CODE_COUNT)
        self.assertEqual(
            RoleAssignment.objects.filter(
                account_id=account.id,
                role="security_admin",
                state="active",
            ).count(),
            1,
        )
        self.assertEqual(
            TotpCredential.objects.filter(account=account, disabled_at__isnull=True).count(),
            1,
        )
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.accepted_at)

    def test_expired_pending_restart_with_wrong_password_is_neutral_and_unchanged(self):
        public = self.public()
        _, context = self.authorized_admin()
        invitation_id = public.invite_staff_member(
            email="wrong-password-staff@example.com",
            role="seller_reviewer",
            context=context,
        )
        raw_token = self.invitation_token(invitation_id)
        password = f"Strong password {uuid4().hex}"
        initial = public.begin_staff_invitation_acceptance(
            raw_token=raw_token,
            password=password,
            context=self.context(now=self.now - settings.TOTP_SETUP_TTL),
        )
        old_setup = TotpSetup.objects.get(pk=initial.totp_setup.setup_id)
        account = Account.objects.get(pk=initial.account_id)
        old_password = Account.objects.get(pk=initial.account_id).password

        failed_context = self.context(now=old_setup.expires_at)
        with self.assertRaises(AuthenticationDenied):
            public.begin_staff_invitation_acceptance(
                raw_token=raw_token,
                password=f"Wrong password {uuid4().hex}",
                context=failed_context,
            )

        failed_audit = AuditEntry.objects.get(request_id=failed_context.request_id)
        self.assertEqual(failed_audit.action, "identity.invited_service_totp_restart_failed")
        self.assertEqual(failed_audit.object_type, "authentication_attempt")
        self.assertEqual(failed_audit.object_id, str(failed_context.request_id))
        self.assertEqual(failed_audit.result, "failed")
        self.assertEqual(
            set(failed_audit.after), {"subject_fingerprint", "source_fingerprint"}
        )
        serialized_audit = repr(failed_audit)
        for value in (password, account.email, failed_context.source_address):
            self.assertNotIn(value, serialized_audit)
        self.assertEqual(
            SecurityThrottle.objects.filter(scope="login", allowed_attempt_count=1).count(),
            2,
        )

        old_setup.refresh_from_db()
        acceptance = StaffInvitationAcceptance.objects.get(pk=initial.acceptance_id)
        invitation = StaffInvitation.objects.get(pk=invitation_id)
        self.assertIsNone(old_setup.invalidated_at)
        self.assertEqual(acceptance.totp_setup_id, old_setup.id)
        self.assertEqual(TotpSetup.objects.filter(account=account).count(), 1)
        self.assertEqual(account.password, old_password)
        self.assertIsNone(invitation.accepted_at)
        self.assertFalse(TotpCredential.objects.filter(account=account).exists())
        self.assertFalse(RoleAssignment.objects.filter(account_id=account.id).exists())

    def test_expired_pending_restart_blocks_password_attempts_after_login_limit(self):
        public = self.public()
        _, context = self.authorized_admin()
        invitation_id = public.invite_staff_member(
            email="throttled-restart@example.com",
            role="seller_reviewer",
            context=context,
        )
        raw_token = self.invitation_token(invitation_id)
        password = f"Strong password {uuid4().hex}"
        initial = public.begin_staff_invitation_acceptance(
            raw_token=raw_token,
            password=password,
            context=self.context(now=self.now - settings.TOTP_SETUP_TTL),
        )
        old_setup = TotpSetup.objects.get(pk=initial.totp_setup.setup_id)

        for _ in range(settings.LOGIN_THROTTLE_THRESHOLD):
            with self.assertRaises(AuthenticationDenied):
                public.begin_staff_invitation_acceptance(
                    raw_token=raw_token,
                    password=f"Wrong password {uuid4().hex}",
                    context=self.context(now=old_setup.expires_at),
                )

        with self.assertRaises(RateLimited):
            public.begin_staff_invitation_acceptance(
                raw_token=raw_token,
                password=password,
                context=self.context(now=old_setup.expires_at),
            )
        old_setup.refresh_from_db()
        acceptance = StaffInvitationAcceptance.objects.get(pk=initial.acceptance_id)
        self.assertIsNone(old_setup.invalidated_at)
        self.assertEqual(acceptance.totp_setup_id, old_setup.id)

    def test_expired_pending_restart_allows_correct_password_after_login_cooldown(self):
        public = self.public()
        _, context = self.authorized_admin()
        invitation_id = public.invite_staff_member(
            email="cooldown-restart@example.com",
            role="seller_reviewer",
            context=context,
        )
        raw_token = self.invitation_token(invitation_id)
        password = f"Strong password {uuid4().hex}"
        initial = public.begin_staff_invitation_acceptance(
            raw_token=raw_token,
            password=password,
            context=self.context(now=self.now - settings.TOTP_SETUP_TTL),
        )
        old_setup = TotpSetup.objects.get(pk=initial.totp_setup.setup_id)

        for _ in range(settings.LOGIN_THROTTLE_THRESHOLD):
            with self.assertRaises(AuthenticationDenied):
                public.begin_staff_invitation_acceptance(
                    raw_token=raw_token,
                    password=f"Wrong password {uuid4().hex}",
                    context=self.context(now=old_setup.expires_at),
                )

        with self.assertRaises(RateLimited):
            public.begin_staff_invitation_acceptance(
                raw_token=raw_token,
                password=password,
                context=self.context(now=old_setup.expires_at),
            )

        restarted = public.begin_staff_invitation_acceptance(
            raw_token=raw_token,
            password=password,
            context=self.context(
                now=old_setup.expires_at
                + timedelta(seconds=settings.LOGIN_THROTTLE_DELAYS[0])
            ),
        )
        self.assertIsNotNone(restarted.totp_setup)
        self.assertNotEqual(restarted.totp_setup.setup_id, old_setup.id)

    def test_expired_restart_failure_blocks_login_using_shared_login_buckets(self):
        public = self.public()
        _, context = self.authorized_admin()
        invitation_id = public.invite_staff_member(
            email="shared-login-bucket@example.com",
            role="seller_reviewer",
            context=context,
        )
        raw_token = self.invitation_token(invitation_id)
        password = f"Strong password {uuid4().hex}"
        initial = public.begin_staff_invitation_acceptance(
            raw_token=raw_token,
            password=password,
            context=self.context(now=self.now - settings.TOTP_SETUP_TTL),
        )
        account = Account.objects.get(pk=initial.account_id)
        old_setup = TotpSetup.objects.get(pk=initial.totp_setup.setup_id)

        for _ in range(settings.LOGIN_THROTTLE_THRESHOLD):
            with self.assertRaises(AuthenticationDenied):
                public.begin_staff_invitation_acceptance(
                    raw_token=raw_token,
                    password=f"Wrong password {uuid4().hex}",
                    context=self.context(now=old_setup.expires_at),
                )

        django_session_key = get_random_string(32, "abcdefghijklmnopqrstuvwxyz0123456789")
        Session.objects.create(
            session_key=django_session_key,
            session_data=SessionStore().encode({}),
            expire_date=self.now + timedelta(hours=1),
        )
        with self.assertRaises(RateLimited):
            identity_public.authenticate_account(
                email=account.email,
                password=password,
                second_factor=None,
                django_session_key=django_session_key,
                device_label="test",
                context=self.context(now=old_setup.expires_at),
            )

    def test_expired_pending_restart_rolls_back_old_setup_invalidation_on_creation_failure(self):
        public = self.public()
        _, context = self.authorized_admin()
        invitation_id = public.invite_staff_member(
            email="rollback-staff@example.com",
            role="seller_reviewer",
            context=context,
        )
        raw_token = self.invitation_token(invitation_id)
        password = f"Strong password {uuid4().hex}"
        initial = public.begin_staff_invitation_acceptance(
            raw_token=raw_token,
            password=password,
            context=self.context(now=self.now - settings.TOTP_SETUP_TTL),
        )
        old_setup = TotpSetup.objects.get(pk=initial.totp_setup.setup_id)

        with patch(
            "open_marketplace.identity.application._create_invited_service_totp_setup",
            side_effect=RuntimeError("test creation failure"),
        ):
            with self.assertRaises(RuntimeError):
                public.begin_staff_invitation_acceptance(
                    raw_token=raw_token,
                    password=password,
                    context=self.context(now=old_setup.expires_at),
                )

        old_setup.refresh_from_db()
        acceptance = StaffInvitationAcceptance.objects.get(pk=initial.acceptance_id)
        self.assertIsNone(old_setup.invalidated_at)
        self.assertEqual(acceptance.totp_setup_id, old_setup.id)
        self.assertEqual(TotpSetup.objects.filter(account_id=initial.account_id).count(), 1)

    def test_expired_pending_restart_rolls_back_success_audit_on_pointer_save_failure(self):
        public = self.public()
        _, context = self.authorized_admin()
        invitation_id = public.invite_staff_member(
            email="pointer-save-failure@example.com",
            role="seller_reviewer",
            context=context,
        )
        raw_token = self.invitation_token(invitation_id)
        password = f"Strong password {uuid4().hex}"
        initial = public.begin_staff_invitation_acceptance(
            raw_token=raw_token,
            password=password,
            context=self.context(now=self.now - settings.TOTP_SETUP_TTL),
        )
        old_setup = TotpSetup.objects.get(pk=initial.totp_setup.setup_id)
        restart_context = self.context(now=old_setup.expires_at)
        original_save = StaffInvitationAcceptance.save

        def fail_pointer_save(acceptance, *args, **kwargs):
            if set(kwargs.get("update_fields") or ()) == {"totp_setup_id"}:
                raise RuntimeError("test pointer save failure")
            return original_save(acceptance, *args, **kwargs)

        with patch.object(StaffInvitationAcceptance, "save", fail_pointer_save):
            with self.assertRaises(RuntimeError):
                public.begin_staff_invitation_acceptance(
                    raw_token=raw_token,
                    password=password,
                    context=restart_context,
                )

        old_setup.refresh_from_db()
        acceptance = StaffInvitationAcceptance.objects.get(pk=initial.acceptance_id)
        self.assertIsNone(old_setup.invalidated_at)
        self.assertEqual(acceptance.totp_setup_id, old_setup.id)
        self.assertEqual(TotpSetup.objects.filter(account_id=initial.account_id).count(), 1)
        self.assertFalse(
            AuditEntry.objects.filter(
                request_id=restart_context.request_id,
                action="identity.invited_service_totp_restarted",
            ).exists()
        )

    def test_restart_rejects_cross_account_consumed_and_invalidated_setups(self):
        public = self.public()
        _, context = self.authorized_admin()

        def pending(email):
            invitation_id = public.invite_staff_member(
                email=email,
                role="seller_reviewer",
                context=context,
            )
            raw_token = self.invitation_token(invitation_id)
            password = f"Strong password {uuid4().hex}"
            setup = public.begin_staff_invitation_acceptance(
                raw_token=raw_token,
                password=password,
                context=self.context(now=self.now - settings.TOTP_SETUP_TTL),
            )
            return invitation_id, raw_token, password, setup

        first = pending("cross-account-one@example.com")
        second = pending("cross-account-two@example.com")
        first_setup = TotpSetup.objects.get(pk=first[3].totp_setup.setup_id)
        second_setup = TotpSetup.objects.get(pk=second[3].totp_setup.setup_id)

        StaffInvitationAcceptance.objects.filter(pk=first[3].acceptance_id).update(
            totp_setup_id=second_setup.id
        )
        with self.assertRaises(AuthenticationDenied):
            public.begin_staff_invitation_acceptance(
                raw_token=first[1],
                password=first[2],
                context=self.context(now=first_setup.expires_at),
            )

        second_setup.invalidated_at = self.now
        second_setup.save(update_fields={"invalidated_at"})
        with self.assertRaises(AuthenticationDenied):
            public.begin_staff_invitation_acceptance(
                raw_token=second[1],
                password=second[2],
                context=self.context(now=second_setup.expires_at),
            )

        third = pending("consumed-setup@example.com")
        third_setup = TotpSetup.objects.get(pk=third[3].totp_setup.setup_id)
        third_setup.consumed_at = self.now
        third_setup.save(update_fields={"consumed_at"})
        with self.assertRaises(AuthenticationDenied):
            public.begin_staff_invitation_acceptance(
                raw_token=third[1],
                password=third[2],
                context=self.context(now=third_setup.expires_at),
            )

    def test_restart_rejects_active_totp_credential_without_rotating_setup(self):
        public = self.public()
        _, context = self.authorized_admin()
        invitation_id = public.invite_staff_member(
            email="active-credential-staff@example.com",
            role="security_admin",
            context=context,
        )
        raw_token = self.invitation_token(invitation_id)
        password = f"Strong password {uuid4().hex}"
        initial = public.begin_staff_invitation_acceptance(
            raw_token=raw_token,
            password=password,
            context=self.context(now=self.now - settings.TOTP_SETUP_TTL),
        )
        setup = TotpSetup.objects.get(pk=initial.totp_setup.setup_id)
        TotpCredential.objects.create(
            account_id=initial.account_id,
            encrypted_secret=Fernet(settings.TOTP_ENCRYPTION_KEY.encode("ascii")).encrypt(
                pyotp.random_base32().encode("ascii")
            ),
            confirmed_at=self.now,
            last_accepted_counter=0,
        )

        with self.assertRaises(AuthenticationDenied):
            public.begin_staff_invitation_acceptance(
                raw_token=raw_token,
                password=password,
                context=self.context(now=setup.expires_at),
            )

        setup.refresh_from_db()
        acceptance = StaffInvitationAcceptance.objects.get(pk=initial.acceptance_id)
        self.assertIsNone(setup.invalidated_at)
        self.assertEqual(acceptance.totp_setup_id, setup.id)
        self.assertEqual(TotpSetup.objects.filter(account_id=initial.account_id).count(), 1)

    def test_existing_service_account_requires_matching_authenticated_actor_and_totp(self):
        public = self.public()
        _, admin_context = self.authorized_admin()
        existing = self.create_account(email="existing@example.com", totp=True)
        existing_registry = self.session(existing)
        invitation_id = public.invite_staff_member(
            email=existing.email, role="seller_reviewer", context=admin_context
        )
        raw_token = self.invitation_token(invitation_id)

        with self.assertRaises((AuthenticationDenied, PermissionDenied, InvalidState)):
            public.begin_staff_invitation_acceptance(
                raw_token=raw_token,
                password=self.password,
                context=self.context(),
            )
        setup = public.begin_staff_invitation_acceptance(
            raw_token=raw_token,
            password=self.password,
            context=self.context(existing, existing_registry),
        )
        self.assertEqual(setup.mode, "existing_service_account")
        self.assertIsNone(setup.totp_setup)
        result = public.accept_staff_invitation(
            acceptance_id=setup.acceptance_id,
            raw_token=raw_token,
            totp_code=pyotp.TOTP(existing._test_totp_secret).at(self.now),
            context=self.context(existing, existing_registry),
        )
        self.assertEqual(result.recovery_codes, ())

    def test_ordinary_accounts_cross_bindings_and_terminal_invitations_are_rejected(self):
        public = self.public()
        admin, context = self.authorized_admin()
        ordinary = self.create_account(kind=Account.Kind.ORDINARY)
        with self.assertRaises((InvalidState, InputRejected)):
            public.invite_staff_member(email=ordinary.email, role="seller_reviewer", context=context)

        first_id = public.invite_staff_member(email="first@example.com", role="seller_reviewer", context=context)
        second_id = public.invite_staff_member(email="second@example.com", role="security_admin", context=context)
        first_token = self.invitation_token(first_id)
        second_token = self.invitation_token(second_id)
        first_setup = public.begin_staff_invitation_acceptance(
            raw_token=first_token, password=f"Strong password {uuid4().hex}", context=self.context()
        )
        with self.assertRaises((AuthenticationDenied, InvalidState)):
            public.accept_staff_invitation(
                acceptance_id=first_setup.acceptance_id,
                raw_token=second_token,
                totp_code="000000",
                context=self.context(),
            )

        Invitation = apps.get_model("access", "StaffInvitation")
        Invitation.objects.filter(pk=first_id).update(
            created_at=self.now - timedelta(days=2),
            expires_at=self.now - timedelta(seconds=1),
        )
        with self.assertRaises((AuthenticationDenied, InvalidState)):
            public.begin_staff_invitation_acceptance(
                raw_token=first_token, password=self.password, context=self.context()
            )
        public.revoke_staff_invitation(invitation_id=second_id, reason="cancelled", context=context)
        with self.assertRaises((AuthenticationDenied, InvalidState)):
            public.begin_staff_invitation_acceptance(
                raw_token=second_token, password=self.password, context=self.context()
            )
        self.assertNotEqual(admin.id, ordinary.id)

    def test_listing_uses_security_permission_scopes_uuid_cursor_and_bounded_limit(self):
        public = self.public()
        _, context = self.authorized_admin()
        ids = [
            public.invite_staff_member(
                email=f"staff-{index}@example.com",
                role="seller_reviewer" if index % 2 else "security_admin",
                context=context,
            )
            for index in range(3)
        ]
        query = public.StaffInvitationQuery(
            state="pending", role="seller_reviewer", canonical_email=None, limit=1, cursor=None
        )
        first = public.list_staff_invitations(query=query, context=context)
        self.assertEqual(len(first), 1)
        next_page = public.list_staff_invitations(
            query=public.StaffInvitationQuery(
                state="pending", role="seller_reviewer", canonical_email=None, limit=1, cursor=first[-1].id
            ),
            context=context,
        )
        self.assertTrue(all(view.role == "seller_reviewer" for view in first + next_page))
        with self.assertRaises(InputRejected):
            public.list_staff_invitations(
                query=public.StaffInvitationQuery(
                    state=None, role=None, canonical_email=None, limit=101, cursor=None
                ),
                context=context,
            )

        reviewer = self.create_account(totp=True)
        apps.get_model("access", "RoleAssignment").objects.create(
            account_id=reviewer.id,
            role="seller_reviewer",
            assigned_reason="test fixture",
            active_from=self.now - timedelta(days=1),
        )
        with self.assertRaises(PermissionDenied):
            public.list_staff_invitations(query=query, context=self.context(reviewer, self.session(reviewer)))


class ExpiredRestartTransactionTests(TransactionTestCase):
    now = datetime(2026, 9, 2, 12, tzinfo=UTC)

    def test_failed_restart_commits_security_records_after_outer_transaction_exits(self):
        raw_invitation_token, invitation_digest = generate_one_time_token()
        account_password = f"Strong password {uuid4().hex}"
        account = Account.objects.create_service_account(
            email=f"transaction-restart-{uuid4().hex}@example.com",
            password=account_password,
            state=Account.State.ACTIVE,
            email_verified_at=self.now - timedelta(days=1),
        )
        _, setup_token_digest = generate_one_time_token()
        setup_token = OneTimeToken.objects.create(
            account=account,
            purpose=OneTimeToken.Purpose.MANDATORY_TOTP_RECOVERY,
            token_digest=setup_token_digest,
            created_at=self.now - settings.TOTP_SETUP_TTL,
            expires_at=self.now,
        )
        setup = TotpSetup.objects.create(
            account=account,
            session=None,
            recovery_token=setup_token,
            encrypted_secret=Fernet(
                settings.TOTP_ENCRYPTION_KEY.encode("ascii")
            ).encrypt(pyotp.random_base32().encode("ascii")),
            created_at=self.now - settings.TOTP_SETUP_TTL,
            expires_at=self.now,
        )
        invitation = StaffInvitation.objects.create(
            email=account.email,
            role="seller_reviewer",
            created_by_id=uuid4(),
            token_digest=invitation_digest,
            created_at=self.now - timedelta(hours=1),
            expires_at=self.now + timedelta(hours=1),
        )
        acceptance = StaffInvitationAcceptance.objects.create(
            invitation=invitation,
            token_digest=invitation_digest,
            account_id=account.id,
            totp_setup_id=setup.id,
            created_at=self.now - timedelta(minutes=5),
        )
        context = OperationContext(
            actor_account_id=None,
            session_id=None,
            request_id=uuid4(),
            source="html",
            source_address="198.51.100.44",
            now=self.now,
        )

        with self.assertRaises(AuthenticationDenied):
            import_module("open_marketplace.access.public").begin_staff_invitation_acceptance(
                raw_token=raw_invitation_token,
                password=f"Wrong password {uuid4().hex}",
                context=context,
            )

        throttle_rows = SecurityThrottle.objects.filter(scope="login")
        self.assertEqual(throttle_rows.count(), 2)
        self.assertTrue(all(row.allowed_attempt_count == 1 for row in throttle_rows))
        audit = AuditEntry.objects.get(request_id=context.request_id)
        self.assertEqual(audit.action, "identity.invited_service_totp_restart_failed")
        self.assertEqual(audit.result, "failed")
        self.assertEqual(audit.actor_id, None)
        self.assertEqual(audit.object_id, str(context.request_id))
        self.assertEqual(
            set(audit.after), {"subject_fingerprint", "source_fingerprint"}
        )
        acceptance.refresh_from_db()
        setup.refresh_from_db()
        self.assertEqual(acceptance.totp_setup_id, setup.id)
        self.assertIsNone(setup.invalidated_at)
