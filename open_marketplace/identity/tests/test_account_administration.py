from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import UUID, uuid4
from unittest.mock import patch

from django.apps import apps
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils.crypto import get_random_string

from open_marketplace.common.errors import InputRejected, InvalidState, PermissionDenied
from open_marketplace.common.types import AuthorizationDecision, OperationContext


Account = apps.get_model("identity", "Account")
AccountSession = apps.get_model("identity", "AccountSession")
AuditEntry = apps.get_model("audit", "AuditEntry")
OutboxMessage = apps.get_model("outbox", "OutboxMessage")


class AccountAdministrationTests(TestCase):
    now = datetime(2026, 9, 2, 12, tzinfo=UTC)
    password = f"T3st!{uuid4().hex}"

    def public_module(self):
        return import_module("open_marketplace.identity.public")

    def create_account(
        self,
        *,
        account_id=None,
        email=None,
        kind=Account.Kind.ORDINARY,
        state=Account.State.ACTIVE,
        verified=True,
        **extra_fields,
    ):
        create = (
            Account.objects.create_service_account
            if kind == Account.Kind.SERVICE
            else Account.objects.create_user
        )
        values = {
            "email": email or f"person-{uuid4()}@example.com",
            "password": self.password,
            "state": state,
            "email_verified_at": self.now - timedelta(days=1) if verified else None,
            **extra_fields,
        }
        if account_id is not None:
            values["id"] = account_id
        return create(**values)

    def create_blocked_account(self, **overrides):
        values = {
            "state": Account.State.BLOCKED,
            "blocked_at": self.now - timedelta(hours=1),
            "blocked_by_id": uuid4(),
            "block_reason": "confirmed compromise",
            "block_audit_id": uuid4(),
        }
        values.update(overrides)
        return self.create_account(**values)

    def create_registry(self, account):
        key = get_random_string(32, "abcdefghijklmnopqrstuvwxyz0123456789")
        Session.objects.create(
            session_key=key,
            session_data=SessionStore().encode({}),
            expire_date=self.now + timedelta(days=1),
        )
        return AccountSession.objects.create(
            account=account,
            django_session_key=key,
            created_at=self.now - timedelta(hours=1),
            last_activity_at=self.now - timedelta(minutes=1),
            absolute_expires_at=self.now + timedelta(hours=1),
            reauthenticated_at=self.now - timedelta(minutes=1),
            device_label="Firefox on Linux",
        )

    def context(self, actor):
        registry = self.create_registry(actor)
        return OperationContext(
            actor_account_id=actor.id,
            session_id=registry.id,
            request_id=uuid4(),
            source="admin",
            source_address="203.0.113.10",
            now=self.now,
        )

    def authorize(self, context, expected_permission, *, actor_id=None, permission=None):
        calls = []
        operation_context = context
        decision_permission = permission or expected_permission

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

    def test_public_contract_exposes_frozen_query_and_exact_operations(self):
        public = self.public_module()
        for name in (
            "AccountQuery",
            "block_account",
            "unblock_account",
            "query_accounts",
            "recover_mandatory_totp",
            "begin_mandatory_totp_recovery",
            "complete_mandatory_totp_recovery",
        ):
            self.assertTrue(hasattr(public, name), f"{name} must be public.")

        query = public.AccountQuery(
            kind=None,
            state=None,
            canonical_email=None,
            limit=25,
            cursor=None,
        )
        with self.assertRaises(FrozenInstanceError):
            query.limit = 50

    def test_database_rejects_incomplete_or_mismatched_block_metadata(self):
        field_names = {field.name for field in Account._meta.fields}
        self.assertTrue(
            {"blocked_at", "blocked_by_id", "block_reason", "block_audit_id"}
            <= field_names
        )
        constraint_names = {constraint.name for constraint in Account._meta.constraints}
        self.assertIn("identity_account_block_metadata_state", constraint_names)
        self.assertIn("identity_account_block_reason_present", constraint_names)

        invalid_rows = (
            {
                "state": Account.State.BLOCKED,
            },
            {
                "state": Account.State.ACTIVE,
                "blocked_at": self.now,
                "blocked_by_id": uuid4(),
                "block_reason": "must not remain on active account",
                "block_audit_id": uuid4(),
            },
            {
                "state": Account.State.BLOCKED,
                "blocked_at": self.now,
                "blocked_by_id": uuid4(),
                "block_reason": "",
                "block_audit_id": uuid4(),
            },
        )
        for values in invalid_rows:
            with self.subTest(values=values), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    self.create_account(**values)

    def test_block_sets_current_metadata_revokes_sessions_and_writes_atomic_records(self):
        public = self.public_module()
        actor = self.create_account(kind=Account.Kind.SERVICE)
        target = self.create_account()
        sessions = (self.create_registry(target), self.create_registry(target))
        context = self.context(actor)
        authorize, calls = self.authorize(context, "account.block")
        original_version = target.version

        result = public.block_account(
            account_id=target.id,
            reason="  confirmed compromise  ",
            context=context,
            authorize=authorize,
        )

        self.assertIsNone(result)
        self.assertEqual(calls, [(context, "account.block")])
        target.refresh_from_db()
        self.assertEqual(target.state, Account.State.BLOCKED)
        self.assertEqual(target.blocked_at, context.now)
        self.assertEqual(target.blocked_by_id, actor.id)
        self.assertEqual(target.block_reason, "confirmed compromise")
        self.assertEqual(target.version, original_version + 1)
        for registry in sessions:
            registry.refresh_from_db()
            self.assertEqual(registry.revoked_at, context.now)
            self.assertEqual(registry.revoked_reason, "account_blocked")

        block_entry = AuditEntry.objects.get(action="identity.account_blocked")
        self.assertEqual(target.block_audit_id, block_entry.id)
        self.assertEqual(block_entry.actor_id, actor.id)
        self.assertEqual(block_entry.effective_role, "security_admin")
        self.assertEqual(block_entry.reason, "confirmed compromise")
        self.assertEqual(block_entry.before["state"], "active")
        self.assertEqual(block_entry.after["state"], "blocked")
        self.assertEqual(block_entry.after["revoked_session_count"], 2)
        self.assertEqual(
            AuditEntry.objects.filter(
                action="identity.sessions_revoked_for_security_event"
            ).count(),
            1,
        )
        message = OutboxMessage.objects.get(
            message_type="identity.protected_account_change"
        )
        self.assertEqual(
            message.payload,
            {"account_id": str(target.id), "change": "account_blocked"},
        )

    def test_self_block_and_invalid_state_transitions_do_not_mutate(self):
        public = self.public_module()
        actor = self.create_account(kind=Account.Kind.SERVICE)
        active_target = self.create_account()
        pending_target = self.create_account(
            state=Account.State.PENDING_EMAIL_VERIFICATION,
            verified=False,
        )
        blocked_target = self.create_blocked_account()
        context = self.context(actor)

        cases = (
            (actor, "account.block"),
            (pending_target, "account.block"),
            (blocked_target, "account.block"),
            (active_target, "account.unblock"),
        )
        for target, permission in cases:
            authorize, _ = self.authorize(context, permission)
            operation = (
                public.block_account if permission == "account.block" else public.unblock_account
            )
            with self.subTest(target=target.id, permission=permission), self.assertRaises(
                InvalidState
            ):
                operation(
                    account_id=target.id,
                    reason="reviewed incident",
                    context=context,
                    authorize=authorize,
                )
        self.assertEqual(AuditEntry.objects.count(), 0)
        self.assertEqual(OutboxMessage.objects.count(), 0)

    def test_unblock_clears_current_metadata_without_creating_or_revoking_sessions(self):
        public = self.public_module()
        actor = self.create_account(kind=Account.Kind.SERVICE)
        target = self.create_blocked_account()
        registry = self.create_registry(target)
        context = self.context(actor)
        authorize, calls = self.authorize(context, "account.unblock")
        original_version = target.version
        original_registry_count = AccountSession.objects.filter(account=target).count()

        result = public.unblock_account(
            account_id=target.id,
            reason="  owner identity rechecked  ",
            context=context,
            authorize=authorize,
        )

        self.assertIsNone(result)
        self.assertEqual(calls, [(context, "account.unblock")])
        target.refresh_from_db()
        registry.refresh_from_db()
        self.assertEqual(target.state, Account.State.ACTIVE)
        self.assertIsNone(target.blocked_at)
        self.assertIsNone(target.blocked_by_id)
        self.assertIsNone(target.block_reason)
        self.assertIsNone(target.block_audit_id)
        self.assertEqual(target.version, original_version + 1)
        self.assertIsNone(registry.revoked_at)
        self.assertEqual(
            AccountSession.objects.filter(account=target).count(),
            original_registry_count,
        )
        entry = AuditEntry.objects.get(action="identity.account_unblocked")
        self.assertEqual(entry.actor_id, actor.id)
        self.assertEqual(entry.reason, "owner identity rechecked")
        self.assertEqual(entry.before["state"], "blocked")
        self.assertEqual(entry.after["state"], "active")
        message = OutboxMessage.objects.get(
            message_type="identity.protected_account_change"
        )
        self.assertEqual(message.payload["change"], "account_unblocked")

    def test_authorization_denial_spoofed_decision_and_invalid_reason_are_rejected(self):
        public = self.public_module()
        actor = self.create_account(kind=Account.Kind.SERVICE)
        target = self.create_account()
        context = self.context(actor)

        def denied(*args, **kwargs):
            raise PermissionDenied("denied")

        for operation, permission in (
            (public.block_account, "account.block"),
            (public.unblock_account, "account.unblock"),
        ):
            with self.subTest(operation=operation.__name__, case="denied"), self.assertRaises(
                PermissionDenied
            ):
                operation(
                    account_id=target.id,
                    reason="reviewed incident",
                    context=context,
                    authorize=denied,
                )
            spoofed, _ = self.authorize(
                context,
                permission,
                actor_id=uuid4(),
            )
            with self.subTest(operation=operation.__name__, case="actor"), self.assertRaises(
                PermissionDenied
            ):
                operation(
                    account_id=target.id,
                    reason="reviewed incident",
                    context=context,
                    authorize=spoofed,
                )
            wrong_permission, _ = self.authorize(
                context,
                permission,
                permission="account.read",
            )
            with self.subTest(operation=operation.__name__, case="permission"), self.assertRaises(
                PermissionDenied
            ):
                operation(
                    account_id=target.id,
                    reason="reviewed incident",
                    context=context,
                    authorize=wrong_permission,
                )

        authorize, _ = self.authorize(context, "account.block")
        for reason in (None, 1, "", "   ", "x" * 1025):
            with self.subTest(reason=reason), self.assertRaises(InputRejected):
                public.block_account(
                    account_id=target.id,
                    reason=reason,
                    context=context,
                    authorize=authorize,
                )
        self.assertEqual(Account.objects.get(pk=target.id).state, Account.State.ACTIVE)
        self.assertEqual(AuditEntry.objects.count(), 0)
        self.assertEqual(OutboxMessage.objects.count(), 0)

    def test_query_is_authorized_filtered_bounded_and_cursor_ordered(self):
        public = self.public_module()
        actor = self.create_account(kind=Account.Kind.SERVICE)
        context = self.context(actor)
        authorize, calls = self.authorize(context, "account.read")
        ids = [UUID(int=value) for value in (301, 101, 401, 201)]
        accounts = (
            self.create_account(account_id=ids[0], email="z@example.com"),
            self.create_account(account_id=ids[1], email="a@example.com"),
            self.create_account(account_id=ids[2], email="service@example.com", kind=Account.Kind.SERVICE),
            self.create_blocked_account(account_id=ids[3], email="blocked@example.com"),
        )

        rows = public.query_accounts(
            query=public.AccountQuery(
                kind="ordinary",
                state=None,
                canonical_email=None,
                limit=2,
                cursor=UUID(int=100),
            ),
            context=context,
            authorize=authorize,
        )

        expected = sorted(
            (account for account in accounts if account.kind == Account.Kind.ORDINARY),
            key=lambda account: account.id,
        )[:2]
        self.assertEqual([row.id for row in rows], [account.id for account in expected])
        self.assertTrue(all(type(row) is public.AccountSnapshot for row in rows))
        self.assertEqual(calls, [(context, "account.read")])

        exact = public.query_accounts(
            query=public.AccountQuery(
                kind=None,
                state="active",
                canonical_email="a@example.com",
                limit=100,
                cursor=None,
            ),
            context=context,
            authorize=authorize,
        )
        self.assertEqual(tuple(row.id for row in exact), (UUID(int=101),))

        invalid_queries = (
            public.AccountQuery(None, None, None, 0, None),
            public.AccountQuery(None, None, None, 101, None),
            public.AccountQuery(None, None, None, True, None),
            public.AccountQuery("unknown", None, None, 1, None),
            public.AccountQuery(None, "unknown", None, 1, None),
            public.AccountQuery(None, None, " Person@example.com ", 1, None),
            public.AccountQuery(None, None, None, 1, "not-a-uuid"),
        )
        for query in invalid_queries:
            with self.subTest(query=query), self.assertRaises(InputRejected):
                public.query_accounts(
                    query=query,
                    context=context,
                    authorize=authorize,
                )

    def test_block_and_unblock_roll_back_every_effect_when_audit_or_outbox_fails(self):
        public = self.public_module()
        actor = self.create_account(kind=Account.Kind.SERVICE)
        context = self.context(actor)

        for dependency in ("append_audit_entry", "enqueue_outbox_message"):
            target = self.create_account()
            registry = self.create_registry(target)
            authorize, _ = self.authorize(context, "account.block")
            with self.subTest(operation="block", dependency=dependency), patch(
                f"open_marketplace.identity.application.{dependency}",
                side_effect=RuntimeError("dependency unavailable"),
            ), self.assertRaises(RuntimeError):
                public.block_account(
                    account_id=target.id,
                    reason="confirmed incident",
                    context=context,
                    authorize=authorize,
                )
            target.refresh_from_db()
            registry.refresh_from_db()
            self.assertEqual(target.state, Account.State.ACTIVE)
            self.assertIsNone(registry.revoked_at)

        for dependency in ("append_audit_entry", "enqueue_outbox_message"):
            target = self.create_blocked_account()
            authorize, _ = self.authorize(context, "account.unblock")
            with self.subTest(operation="unblock", dependency=dependency), patch(
                f"open_marketplace.identity.application.{dependency}",
                side_effect=RuntimeError("dependency unavailable"),
            ), self.assertRaises(RuntimeError):
                public.unblock_account(
                    account_id=target.id,
                    reason="identity rechecked",
                    context=context,
                    authorize=authorize,
                )
            target.refresh_from_db()
            self.assertEqual(target.state, Account.State.BLOCKED)
            self.assertEqual(target.block_reason, "confirmed compromise")
