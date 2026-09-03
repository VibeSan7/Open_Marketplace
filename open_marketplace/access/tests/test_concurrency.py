import json
from datetime import UTC, datetime, timedelta
from importlib import import_module
from threading import Barrier, BrokenBarrierError, Lock, Thread
from uuid import uuid4
from unittest.mock import patch

import pyotp
from cryptography.fernet import Fernet
from django.apps import apps
from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import close_old_connections
from django.test import TransactionTestCase
from django.utils.crypto import get_random_string

from open_marketplace.common.errors import AuthenticationDenied, InvalidState
from open_marketplace.common.types import OperationContext


Account = apps.get_model("identity", "Account")
AuditEntry = apps.get_model("audit", "AuditEntry")
OutboxMessage = apps.get_model("outbox", "OutboxMessage")
RoleAssignment = apps.get_model("access", "RoleAssignment")
StaffInvitation = apps.get_model("access", "StaffInvitation")
StaffInvitationAcceptance = apps.get_model("access", "StaffInvitationAcceptance")
OneTimeToken = apps.get_model("identity", "OneTimeToken")
TotpCredential = apps.get_model("identity", "TotpCredential")
TotpRequirement = apps.get_model("identity", "TotpRequirement")
TotpSetup = apps.get_model("identity", "TotpSetup")
RecoveryCode = apps.get_model("identity", "RecoveryCode")


class StaffInvitationConcurrencyTests(TransactionTestCase):
    reset_sequences = True
    now = datetime(2026, 9, 2, 12, tzinfo=UTC)
    password = f"T3st!{uuid4().hex}"

    def public(self):
        return import_module("open_marketplace.access.public")

    def context(self, account=None, registry=None, *, source="admin"):
        return OperationContext(
            actor_account_id=account.id if account else None,
            session_id=registry.id if registry else None,
            request_id=uuid4(),
            source=source,
            source_address="203.0.113.10" if account else None,
            now=self.now,
        )

    def create_account(self, *, email=None, totp=False):
        account = Account.objects.create_service_account(
            email=email or f"user-{uuid4()}@example.com",
            password=self.password,
            state=Account.State.ACTIVE,
            email_verified_at=self.now - timedelta(days=1),
        )
        if totp:
            secret = pyotp.random_base32()
            TotpCredential.objects.create(
                account=account,
                encrypted_secret=Fernet(settings.TOTP_ENCRYPTION_KEY.encode("ascii")).encrypt(
                    secret.encode("ascii")
                ),
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

    def authorized_admin(self):
        admin = self.create_account(totp=True)
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
            Fernet(settings.OUTBOX_ENCRYPTION_KEY.encode("ascii")).decrypt(
                bytes(message.encrypted_delivery)
            )
        )
        return delivery["absolute_token_url"].rsplit("/", 2)[-2]

    def run_parallel(self, operation, *, worker_count=2):
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
        self.assertFalse(any(thread.is_alive() for thread in threads), "Concurrent operation deadlocked.")
        return results, errors

    def test_concurrent_same_email_and_role_converges_on_one_invitation(self):
        public = self.public()
        _, admin_context = self.authorized_admin()
        application = import_module("open_marketplace.access.application")
        generation_barrier = Barrier(2)
        generate_token = application.generate_one_time_token

        def synchronized_generate_token():
            try:
                generation_barrier.wait(timeout=1)
            except BrokenBarrierError:
                pass
            return generate_token()

        with patch(
            "open_marketplace.access.application.generate_one_time_token",
            side_effect=synchronized_generate_token,
        ):
            results, errors = self.run_parallel(
                lambda index: public.invite_staff_member(
                    email="CONCURRENT@example.com" if index else "concurrent@example.com",
                    role="seller_reviewer",
                    context=admin_context,
                )
            )

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(set(results), {results[0]})
        self.assertEqual(
            StaffInvitation.objects.filter(
                email="concurrent@example.com",
                role="seller_reviewer",
                accepted_at__isnull=True,
                revoked_at__isnull=True,
                expires_at__gt=self.now,
            ).count(),
            1,
        )
        self.assertEqual(
            AuditEntry.objects.filter(action="access.staff_invitation_created").count(),
            1,
        )
        self.assertEqual(
            OutboxMessage.objects.filter(message_type="access.staff_invitation").count(),
            1,
        )

    def test_concurrent_bootstrap_with_different_emails_has_one_live_invitation(self):
        public = self.public()

        results, errors = self.run_parallel(
            lambda index: public.bootstrap_security_admin(
                email=("first@example.com", "second@example.com")[index],
                context=self.context(source="command"),
            )
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], InvalidState)
        self.assertEqual(
            StaffInvitation.objects.filter(
                role="security_admin",
                created_by_id__isnull=True,
                accepted_at__isnull=True,
                revoked_at__isnull=True,
                expires_at__gt=self.now,
            ).count(),
            1,
        )
        self.assertEqual(
            AuditEntry.objects.filter(action="access.staff_invitation_created").count(),
            1,
        )
        self.assertEqual(
            OutboxMessage.objects.filter(message_type="access.staff_invitation").count(),
            1,
        )

    def test_concurrent_acceptance_consumes_one_acceptance_once(self):
        public = self.public()
        _, admin_context = self.authorized_admin()
        invitation_id = public.invite_staff_member(
            email="accept-race@example.com",
            role="security_admin",
            context=admin_context,
        )
        raw_token = self.invitation_token(invitation_id)
        setup = public.begin_staff_invitation_acceptance(
            raw_token=raw_token,
            password=f"Strong password {uuid4().hex}",
            context=self.context(),
        )
        setup_row = TotpSetup.objects.get(pk=setup.totp_setup.setup_id)
        secret = Fernet(settings.TOTP_ENCRYPTION_KEY.encode("ascii")).decrypt(
            bytes(setup_row.encrypted_secret)
        ).decode()

        results, errors = self.run_parallel(
            lambda _index: public.accept_staff_invitation(
                acceptance_id=setup.acceptance_id,
                raw_token=raw_token,
                totp_code=pyotp.TOTP(secret).at(self.now),
                context=self.context(),
            )
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], AuthenticationDenied)
        self.assertEqual(RoleAssignment.objects.filter(account_id=setup.account_id, state="active").count(), 1)
        self.assertEqual(TotpCredential.objects.filter(account_id=setup.account_id).count(), 1)
        self.assertEqual(TotpRequirement.objects.filter(account_id=setup.account_id, removed_at=None).count(), 1)
        self.assertEqual(RecoveryCode.objects.filter(account_id=setup.account_id).count(), settings.RECOVERY_CODE_COUNT)
        self.assertEqual(StaffInvitation.objects.get(pk=invitation_id).accepted_at, self.now)
        self.assertEqual(
            StaffInvitationAcceptance.objects.filter(pk=setup.acceptance_id, consumed_at__isnull=False).count(),
            1,
        )
        self.assertEqual(
            AuditEntry.objects.filter(
                action="access.staff_invitation_accepted",
                object_id=str(invitation_id),
            ).count(),
            1,
        )

    def test_acceptance_rolls_back_all_effects_and_remains_retryable(self):
        public = self.public()
        _, admin_context = self.authorized_admin()
        invitation_id = public.invite_staff_member(
            email="rollback@example.com",
            role="security_admin",
            context=admin_context,
        )
        raw_token = self.invitation_token(invitation_id)
        setup = public.begin_staff_invitation_acceptance(
            raw_token=raw_token,
            password=f"Strong password {uuid4().hex}",
            context=self.context(),
        )
        setup_row = TotpSetup.objects.get(pk=setup.totp_setup.setup_id)
        recovery_token = OneTimeToken.objects.get(pk=setup_row.recovery_token_id)
        secret = Fernet(settings.TOTP_ENCRYPTION_KEY.encode("ascii")).decrypt(
            bytes(setup_row.encrypted_secret)
        ).decode()
        before_counts = {
            "credential": TotpCredential.objects.filter(account_id=setup.account_id).count(),
            "setup": TotpSetup.objects.filter(pk=setup_row.pk).count(),
            "recovery_codes": RecoveryCode.objects.filter(account_id=setup.account_id).count(),
            "totp_requirement": TotpRequirement.objects.filter(account_id=setup.account_id).count(),
            "role": RoleAssignment.objects.filter(account_id=setup.account_id).count(),
            "audit": AuditEntry.objects.count(),
            "outbox": OutboxMessage.objects.count(),
        }

        with patch(
            "open_marketplace.access.application._activate_staff_role",
            side_effect=RuntimeError("injected activation failure"),
        ):
            with self.assertRaises(RuntimeError):
                public.accept_staff_invitation(
                    acceptance_id=setup.acceptance_id,
                    raw_token=raw_token,
                    totp_code=pyotp.TOTP(secret).at(self.now),
                    context=self.context(),
                )

        setup_row.refresh_from_db()
        recovery_token.refresh_from_db()
        acceptance = StaffInvitationAcceptance.objects.get(pk=setup.acceptance_id)
        invitation = StaffInvitation.objects.get(pk=invitation_id)
        self.assertEqual(
            {"credential": TotpCredential.objects.filter(account_id=setup.account_id).count(),
             "setup": TotpSetup.objects.filter(pk=setup_row.pk).count(),
             "recovery_codes": RecoveryCode.objects.filter(account_id=setup.account_id).count(),
             "totp_requirement": TotpRequirement.objects.filter(account_id=setup.account_id).count(),
             "role": RoleAssignment.objects.filter(account_id=setup.account_id).count(),
             "audit": AuditEntry.objects.count(),
             "outbox": OutboxMessage.objects.count()},
            before_counts,
        )
        self.assertIsNone(setup_row.consumed_at)
        self.assertIsNone(recovery_token.used_at)
        self.assertIsNone(acceptance.consumed_at)
        self.assertIsNone(acceptance.invalidated_at)
        self.assertIsNone(invitation.accepted_at)
        self.assertIsNone(invitation.revoked_at)

        result = public.accept_staff_invitation(
            acceptance_id=setup.acceptance_id,
            raw_token=raw_token,
            totp_code=pyotp.TOTP(secret).at(self.now),
            context=self.context(),
        )
        self.assertEqual(len(result.recovery_codes), settings.RECOVERY_CODE_COUNT)
