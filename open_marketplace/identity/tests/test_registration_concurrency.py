import json
from datetime import UTC, datetime, timedelta
from importlib import import_module
from threading import Barrier, Lock, Thread
from uuid import uuid4

from cryptography.fernet import Fernet
from django.conf import settings
from django.db import close_old_connections
from django.test import TransactionTestCase

from open_marketplace.audit.public import AuditQuery, query_audit_entries
from open_marketplace.common.errors import InputRejected
from open_marketplace.common.types import AuthorizationDecision, OperationContext
from open_marketplace.identity.models import Account
from open_marketplace.outbox.public import claim_ready_messages


class RegistrationConcurrencyTests(TransactionTestCase):
    reset_sequences = True
    email = "concurrent@example.com"
    password = "V9!qL2@xP7#z"
    now = datetime(2026, 9, 2, 12, tzinfo=UTC)

    def public_module(self):
        public = import_module("open_marketplace.identity.public")
        self.assertTrue(hasattr(public, "register_account"))
        self.assertTrue(hasattr(public, "verify_email"))
        return public

    def token_model(self):
        models = import_module("open_marketplace.identity.models")
        self.assertTrue(hasattr(models, "OneTimeToken"))
        return models.OneTimeToken

    def context(self, *, now=None):
        return OperationContext(
            actor_account_id=None,
            session_id=None,
            request_id=uuid4(),
            source="html",
            source_address="203.0.113.20",
            now=now or self.now,
        )

    def raw_token_from_outbox(self):
        messages = self.claim_outbox()
        self.assertEqual(len(messages), 1)
        message = messages[0]
        plaintext = Fernet(settings.OUTBOX_ENCRYPTION_KEY.encode("ascii")).decrypt(
            bytes(message.encrypted_delivery)
        )
        delivery = json.loads(plaintext.decode("utf-8"))
        prefix = f"{settings.APP_BASE_URL}/identity/verify-email/"
        url = delivery["absolute_token_url"]
        self.assertTrue(url.startswith(prefix))
        self.assertTrue(url.endswith("/"))
        return url[len(prefix) : -1]

    def claim_outbox(self, *, now=None):
        return claim_ready_messages(
            worker_id=f"test:{uuid4()}",
            now=now or self.now,
            lease_seconds=300,
            limit=100,
        )

    def audit_entries(self, *, action=None):
        actor_id = uuid4()
        context = OperationContext(
            actor_account_id=actor_id,
            session_id=None,
            request_id=uuid4(),
            source="admin",
            source_address=None,
            now=self.now + timedelta(days=30),
        )

        def authorize(_context, permission):
            self.assertEqual(permission, "audit.read")
            return AuthorizationDecision(
                account_id=actor_id,
                permission="audit.read",
                effective_roles=("security_admin",),
                scopes=("audit:result:succeeded",),
                reauthenticated_at=context.now,
            )

        return query_audit_entries(
            query=AuditQuery(
                from_at=None,
                to_at=None,
                actor_id=None,
                action=action,
                object_type=None,
                object_id=None,
                result=None,
                limit=100,
                cursor=None,
            ),
            context=context,
            authorize=authorize,
        )

    def run_parallel(self, operation):
        barrier = Barrier(3)
        guard = Lock()
        results = []
        errors = []

        def worker(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                result = operation(index)
                with guard:
                    results.append(result)
            except Exception as error:
                with guard:
                    errors.append(error)
            finally:
                close_old_connections()

        threads = [Thread(target=worker, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=10)
        for thread in threads:
            thread.join(timeout=15)
        self.assertFalse(any(thread.is_alive() for thread in threads), "Concurrent operation deadlocked.")
        return results, errors

    def test_simultaneous_registration_creates_one_account_and_one_active_token(self):
        public = self.public_module()
        Token = self.token_model()

        results, errors = self.run_parallel(
            lambda index: public.register_account(
                email=self.email.upper() if index else self.email,
                password=self.password,
                context=self.context(),
            )
        )

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertTrue(all(result.accepted for result in results))
        self.assertEqual(Account.objects.filter(email=self.email).count(), 1)
        account = Account.objects.get(email=self.email)
        self.assertEqual(account.state, Account.State.PENDING_EMAIL_VERIFICATION)
        self.assertEqual(account.version, 1)
        self.assertTrue(account.check_password(self.password))
        self.assertEqual(Token.objects.filter(account=account).count(), 2)
        self.assertEqual(
            Token.objects.filter(
                account=account,
                purpose="email_verification",
                used_at__isnull=True,
                revoked_at__isnull=True,
                expires_at__gt=self.now,
            ).count(),
            1,
        )
        self.assertEqual(len(self.claim_outbox()), 2)
        self.assertEqual(len(self.audit_entries()), 2)

    def test_concurrent_verification_succeeds_once_without_deadlock(self):
        public = self.public_module()
        Token = self.token_model()
        public.register_account(
            email=self.email,
            password=self.password,
            context=self.context(),
        )
        raw_token = self.raw_token_from_outbox()
        verify_time = self.now + timedelta(minutes=1)

        results, errors = self.run_parallel(
            lambda _index: public.verify_email(
                raw_token=raw_token,
                context=self.context(now=verify_time),
            )
        )

        account = Account.objects.get(email=self.email)
        token = Token.objects.get(account=account)
        self.assertEqual(results, [account.id])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], InputRejected)
        self.assertEqual(str(errors[0]), "Email verification token is invalid.")
        self.assertEqual(account.state, Account.State.ACTIVE)
        self.assertEqual(account.version, 2)
        self.assertEqual(token.used_at, verify_time)
        self.assertEqual(len(self.audit_entries(action="identity.email_verified")), 1)
