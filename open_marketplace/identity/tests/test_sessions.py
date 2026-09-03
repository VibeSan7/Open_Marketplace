from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import IntegrityError, transaction
from django.db.models.deletion import PROTECT
from django.http import HttpResponse
from django.test import TestCase
from django.utils.crypto import get_random_string

from open_marketplace.audit.public import AuditQuery, query_audit_entries
from open_marketplace.common.errors import AuthenticationDenied, InputRejected
from open_marketplace.common.types import AuthorizationDecision, OperationContext
from open_marketplace.identity.models import Account


class SessionTests(TestCase):
    now = datetime(2026, 9, 2, 12, tzinfo=UTC)
    password = f"T3st!{uuid4().hex}"

    def public_module(self):
        public = import_module("open_marketplace.identity.public")
        for name in (
            "SessionRevocationReason",
            "SessionSecuritySnapshot",
            "SessionView",
            "get_session_security_snapshot",
            "require_live_session_security_snapshot",
            "list_sessions",
            "log_out_session",
            "revoke_other_sessions",
            "revoke_session",
            "revoke_sessions_for_security_event",
        ):
            self.assertTrue(hasattr(public, name), f"{name} must be public.")
        return public

    def session_model(self):
        models = import_module("open_marketplace.identity.models")
        self.assertTrue(hasattr(models, "AccountSession"), "AccountSession must exist.")
        return models.AccountSession

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
        block_metadata = {}
        if state == Account.State.BLOCKED:
            block_metadata = {
                "blocked_at": self.now,
                "blocked_by_id": uuid4(),
                "block_reason": "Test fixture block.",
                "block_audit_id": uuid4(),
            }
        return create(
            email=email or f"person-{uuid4()}@example.com",
            password=self.password,
            state=state,
            email_verified_at=self.now - timedelta(days=1),
            **block_metadata,
        )

    def create_django_session(self, *, expires_at=None):
        key = get_random_string(32, "abcdefghijklmnopqrstuvwxyz0123456789")
        Session.objects.create(
            session_key=key,
            session_data=SessionStore().encode({}),
            expire_date=expires_at or self.now + timedelta(days=31),
        )
        return key

    def create_registry(
        self,
        *,
        account=None,
        django_key=None,
        created_at=None,
        last_activity_at=None,
        absolute_expires_at=None,
        reauthenticated_at=None,
        device_label="Firefox on Linux",
        revoked_at=None,
        revoked_reason=None,
    ):
        SessionModel = self.session_model()
        account = account or self.create_account()
        created_at = created_at or self.now - timedelta(hours=1)
        key = django_key or self.create_django_session()
        return SessionModel.objects.create(
            account=account,
            django_session_key=key,
            created_at=created_at,
            last_activity_at=last_activity_at or created_at,
            absolute_expires_at=(
                absolute_expires_at or created_at + timedelta(days=30)
            ),
            reauthenticated_at=reauthenticated_at or created_at,
            device_label=device_label,
            revoked_at=revoked_at,
            revoked_reason=revoked_reason,
        )

    def context(self, registry, *, now=None, actor_id=None, session_id=None):
        return OperationContext(
            actor_account_id=registry.account_id if actor_id is None else actor_id,
            session_id=registry.id if session_id is None else session_id,
            request_id=uuid4(),
            source="html",
            source_address="203.0.113.10",
            now=now or self.now,
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
                scopes=("audit:object_type:session", "audit:object_type:account"),
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

    def request_for(self, registry, *, account_id=None, session_id=None, django_key=None):
        store = SessionStore(session_key=django_key or registry.django_session_key)
        store["account_id"] = str(account_id or registry.account_id)
        store["session_id"] = str(session_id or registry.id)
        return SimpleNamespace(session=store, user=AnonymousUser())

    def run_middleware(self, request, *, now=None):
        middleware_module = import_module("open_marketplace.identity.middleware")
        self.assertTrue(
            hasattr(middleware_module, "SessionRegistryMiddleware"),
            "SessionRegistryMiddleware must exist.",
        )
        middleware = middleware_module.SessionRegistryMiddleware(
            lambda received: HttpResponse(str(received.user.pk) if received.user.is_authenticated else "anonymous")
        )
        with patch("open_marketplace.identity.middleware.timezone.now", return_value=now or self.now):
            return middleware(request)

    def test_model_has_exact_sensitive_key_and_revocation_constraints(self):
        SessionModel = self.session_model()
        key_field = SessionModel._meta.get_field("django_session_key")
        self.assertEqual(key_field.max_length, 40)
        self.assertTrue(key_field.unique)
        self.assertFalse(key_field.editable)
        self.assertIs(SessionModel._meta.get_field("account").remote_field.on_delete, PROTECT)
        self.assertEqual(SessionModel._meta.get_field("device_label").max_length, 200)
        self.assertEqual(SessionModel._meta.get_field("revoked_reason").max_length, 64)
        self.assertEqual(
            set(SessionModel.RevocationReason.values),
            {
                "logout",
                "user_revoked",
                "other_sessions_revoked",
                "password_changed",
                "password_reset",
                "optional_totp_disabled",
                "mandatory_totp_recovered",
                "account_blocked",
                "role_changed",
                "compromised",
            },
        )

        account = self.create_account()
        created_at = self.now
        invalid_rows = (
            {
                "absolute_expires_at": created_at,
                "revoked_at": None,
                "revoked_reason": None,
            },
            {
                "absolute_expires_at": created_at + timedelta(hours=1),
                "revoked_at": created_at + timedelta(minutes=1),
                "revoked_reason": None,
            },
            {
                "absolute_expires_at": created_at + timedelta(hours=1),
                "revoked_at": None,
                "revoked_reason": "logout",
            },
            {
                "absolute_expires_at": created_at + timedelta(hours=1),
                "revoked_at": created_at + timedelta(minutes=1),
                "revoked_reason": "arbitrary",
            },
        )
        for values in invalid_rows:
            with self.subTest(values=values), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    SessionModel.objects.create(
                        account=account,
                        django_session_key=self.create_django_session(),
                        created_at=created_at,
                        last_activity_at=created_at,
                        reauthenticated_at=created_at,
                        device_label="Test device",
                        **values,
                    )

    def test_list_returns_only_own_live_sessions_and_marks_current(self):
        public = self.public_module()
        account = self.create_account()
        current = self.create_registry(account=account, created_at=self.now - timedelta(days=2))
        other = self.create_registry(account=account, created_at=self.now - timedelta(days=1))
        self.create_registry(
            account=account,
            revoked_at=self.now - timedelta(minutes=1),
            revoked_reason="user_revoked",
        )
        self.create_registry(
            account=account,
            absolute_expires_at=self.now,
        )
        foreign = self.create_registry(account=self.create_account())

        views = public.list_sessions(context=self.context(current))

        self.assertEqual({view.id for view in views}, {current.id, other.id})
        self.assertEqual(
            {view.id: view.is_current for view in views},
            {current.id: True, other.id: False},
        )
        self.assertNotIn(foreign.id, {view.id for view in views})
        self.assertTrue(all(isinstance(view, public.SessionView) for view in views))
        with self.assertRaises(FrozenInstanceError):
            views[0].device_label = "changed"
        self.assertNotIn(current.django_session_key, repr(views))

    def test_revoke_session_is_own_only_neutral_and_atomic_with_audit(self):
        public = self.public_module()
        account = self.create_account()
        current = self.create_registry(account=account)
        other = self.create_registry(account=account)
        foreign = self.create_registry(account=self.create_account())
        context = self.context(current)

        public.revoke_session(session_id=other.id, context=context)

        other.refresh_from_db()
        current.refresh_from_db()
        foreign.refresh_from_db()
        self.assertEqual(other.revoked_at, context.now)
        self.assertEqual(other.revoked_reason, "user_revoked")
        self.assertIsNone(current.revoked_at)
        self.assertIsNone(foreign.revoked_at)
        entries = self.audit_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].action, "identity.session_revoked")
        self.assertEqual(entries[0].actor_id, account.id)
        self.assertEqual(entries[0].object_id, str(other.id))
        self.assertEqual(entries[0].reason, "user_revoked")
        self.assertNotIn(other.django_session_key, repr(entries))

        messages = set()
        for session_id in (other.id, foreign.id, uuid4()):
            with self.subTest(session_id=session_id), self.assertRaises(AuthenticationDenied) as raised:
                public.revoke_session(session_id=session_id, context=context)
            messages.add(str(raised.exception))
        self.assertEqual(messages, {"Session is unavailable."})

    def test_logout_revokes_current_and_revoke_others_preserves_current(self):
        public = self.public_module()
        account = self.create_account()
        current = self.create_registry(account=account)
        other_one = self.create_registry(account=account)
        other_two = self.create_registry(account=account)
        orphan = self.create_registry(account=account)
        Session.objects.filter(session_key=orphan.django_session_key).delete()
        context = self.context(current)

        count = public.revoke_other_sessions(context=context)

        self.assertEqual(count, 2)
        current.refresh_from_db()
        other_one.refresh_from_db()
        other_two.refresh_from_db()
        orphan.refresh_from_db()
        self.assertIsNone(current.revoked_at)
        self.assertEqual(other_one.revoked_reason, "other_sessions_revoked")
        self.assertEqual(other_two.revoked_reason, "other_sessions_revoked")
        self.assertIsNone(orphan.revoked_at)

        public.log_out_session(context=context)
        current.refresh_from_db()
        self.assertEqual(current.revoked_at, context.now)
        self.assertEqual(current.revoked_reason, "logout")
        with self.assertRaises(AuthenticationDenied):
            public.list_sessions(context=context)

        actions = sorted(entry.action for entry in self.audit_entries())
        self.assertEqual(
            actions,
            ["identity.session_logged_out", "identity.sessions_revoked"],
        )

    def test_security_event_revokes_only_live_sessions_with_allowlisted_reason(self):
        public = self.public_module()
        account = self.create_account()
        current = self.create_registry(account=account)
        other = self.create_registry(account=account)
        expired = self.create_registry(account=account, absolute_expires_at=self.now)
        orphan = self.create_registry(account=account)
        Session.objects.filter(session_key=orphan.django_session_key).delete()
        foreign = self.create_registry(account=self.create_account())
        context = self.context(current)

        with self.assertRaises(InputRejected):
            public.revoke_sessions_for_security_event(
                account_id=account.id,
                reason="arbitrary",
                context=context,
            )
        self.assertEqual(
            public.revoke_sessions_for_security_event(
                account_id=account.id,
                reason="password_changed",
                context=context,
            ),
            2,
        )

        for registry in (current, other):
            registry.refresh_from_db()
            self.assertEqual(registry.revoked_at, context.now)
            self.assertEqual(registry.revoked_reason, "password_changed")
        expired.refresh_from_db()
        orphan.refresh_from_db()
        foreign.refresh_from_db()
        self.assertIsNone(expired.revoked_at)
        self.assertIsNone(orphan.revoked_at)
        self.assertIsNone(foreign.revoked_at)
        entry = self.audit_entries()[0]
        self.assertEqual(entry.action, "identity.sessions_revoked_for_security_event")
        self.assertEqual(entry.reason, "password_changed")
        self.assertEqual(entry.after, {"revoked_session_count": 2})

    def test_security_snapshot_is_immutable_scoped_and_never_exposes_key(self):
        public = self.public_module()
        registry = self.create_registry()

        snapshot = public.get_session_security_snapshot(
            session_id=registry.id,
            account_id=registry.account_id,
        )

        self.assertIsInstance(snapshot, public.SessionSecuritySnapshot)
        self.assertEqual(snapshot.id, registry.id)
        self.assertEqual(snapshot.account_id, registry.account_id)
        self.assertEqual(snapshot.revoked_at, registry.revoked_at)
        self.assertEqual(snapshot.absolute_expires_at, registry.absolute_expires_at)
        self.assertEqual(snapshot.reauthenticated_at, registry.reauthenticated_at)
        self.assertNotIn(registry.django_session_key, repr(snapshot))
        with self.assertRaises(FrozenInstanceError):
            snapshot.account_id = uuid4()
        for session_id, account_id in (
            (uuid4(), registry.account_id),
            (registry.id, uuid4()),
        ):
            with self.assertRaises(AuthenticationDenied):
                public.get_session_security_snapshot(
                    session_id=session_id,
                    account_id=account_id,
                )

    def test_live_security_snapshot_enforces_complete_identity_session_liveness(self):
        public = self.public_module()
        service = self.create_account(kind=Account.Kind.SERVICE)
        valid = self.create_registry(
            account=service,
            last_activity_at=self.now - timedelta(minutes=29, seconds=59),
            absolute_expires_at=self.now + timedelta(hours=1),
        )

        snapshot = public.require_live_session_security_snapshot(
            session_id=valid.id,
            account_id=service.id,
            now=self.now,
        )

        self.assertEqual(snapshot.id, valid.id)
        self.assertIsInstance(snapshot, public.SessionSecuritySnapshot)

        revoked = self.create_registry(
            account=service,
            revoked_at=self.now - timedelta(seconds=1),
            revoked_reason="user_revoked",
            absolute_expires_at=self.now + timedelta(hours=1),
        )
        absolute_expired = self.create_registry(
            account=service,
            last_activity_at=self.now - timedelta(minutes=1),
            absolute_expires_at=self.now,
        )
        idle_expired = self.create_registry(
            account=service,
            last_activity_at=self.now - timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=1),
        )
        backing_expired = self.create_registry(
            account=service,
            django_key=self.create_django_session(expires_at=self.now),
            last_activity_at=self.now - timedelta(minutes=1),
            absolute_expires_at=self.now + timedelta(hours=1),
        )
        orphan = self.create_registry(
            account=service,
            last_activity_at=self.now - timedelta(minutes=1),
            absolute_expires_at=self.now + timedelta(hours=1),
        )
        Session.objects.filter(session_key=orphan.django_session_key).delete()

        for registry in (revoked, absolute_expired, idle_expired, backing_expired, orphan):
            with self.subTest(session_id=registry.id), self.assertRaises(AuthenticationDenied):
                public.require_live_session_security_snapshot(
                    session_id=registry.id,
                    account_id=service.id,
                    now=self.now,
                )

        with self.assertRaises(AuthenticationDenied):
            public.require_live_session_security_snapshot(
                session_id=valid.id,
                account_id=uuid4(),
                now=self.now,
            )

    def test_live_security_snapshot_rejects_invalid_boundary_values(self):
        public = self.public_module()
        registry = self.create_registry(account=self.create_account(kind=Account.Kind.SERVICE))

        for values in (
            {"session_id": "not-a-uuid", "account_id": registry.account_id, "now": self.now},
            {"session_id": registry.id, "account_id": "not-a-uuid", "now": self.now},
            {"session_id": registry.id, "account_id": registry.account_id, "now": self.now.replace(tzinfo=None)},
        ):
            with self.subTest(values=values), self.assertRaises(InputRejected):
                public.require_live_session_security_snapshot(**values)

    def test_middleware_loads_user_then_updates_activity_at_most_once_per_minute(self):
        account = self.create_account()
        registry = self.create_registry(
            account=account,
            last_activity_at=self.now - timedelta(seconds=59),
            absolute_expires_at=self.now + timedelta(days=1),
        )
        request = self.request_for(registry)

        response = self.run_middleware(request)

        self.assertEqual(response.content.decode(), str(account.id))
        self.assertEqual(request.user.id, account.id)
        registry.refresh_from_db()
        self.assertEqual(registry.last_activity_at, self.now - timedelta(seconds=59))

        response = self.run_middleware(request, now=self.now + timedelta(seconds=1))

        self.assertEqual(response.content.decode(), str(account.id))
        registry.refresh_from_db()
        self.assertEqual(registry.last_activity_at, self.now + timedelta(seconds=1))

    def test_middleware_flushes_revoked_expired_blocked_idle_and_mismatched_sessions(self):
        valid_account = self.create_account()
        blocked_account = self.create_account(state=Account.State.BLOCKED)
        other_account = self.create_account()
        cases = (
            self.create_registry(
                account=valid_account,
                revoked_at=self.now - timedelta(minutes=1),
                revoked_reason="user_revoked",
            ),
            self.create_registry(
                account=valid_account,
                absolute_expires_at=self.now,
            ),
            self.create_registry(
                account=self.create_account(kind=Account.Kind.SERVICE),
                last_activity_at=self.now - timedelta(minutes=30),
                absolute_expires_at=self.now + timedelta(hours=1),
            ),
            self.create_registry(
                account=blocked_account,
                absolute_expires_at=self.now + timedelta(days=1),
            ),
        )
        requests = [self.request_for(registry) for registry in cases]
        mismatch = self.create_registry(account=valid_account)
        requests.extend(
            (
                self.request_for(mismatch, account_id=other_account.id),
                self.request_for(mismatch, session_id=uuid4()),
                self.request_for(mismatch, django_key=self.create_django_session()),
            )
        )

        for request in requests:
            with self.subTest(values=dict(request.session.items())):
                response = self.run_middleware(request)
                self.assertEqual(response.content.decode(), "anonymous")
                self.assertFalse(request.user.is_authenticated)
                self.assertIsNone(request.session.session_key)

        for registry in cases:
            registry.refresh_from_db()
        self.assertIsNone(cases[1].revoked_at)
        self.assertIsNone(cases[2].revoked_at)
        self.assertEqual(self.audit_entries(), ())

    def test_database_revocation_is_enforced_on_the_next_request(self):
        registry = self.create_registry(
            last_activity_at=self.now,
            absolute_expires_at=self.now + timedelta(days=1),
        )
        first_request = self.request_for(registry)
        self.run_middleware(first_request)
        self.assertTrue(first_request.user.is_authenticated)

        registry.revoked_at = self.now
        registry.revoked_reason = "compromised"
        registry.save(update_fields={"revoked_at", "revoked_reason"})
        next_request = self.request_for(registry)

        response = self.run_middleware(next_request, now=self.now + timedelta(seconds=1))

        self.assertEqual(response.content.decode(), "anonymous")
        self.assertFalse(next_request.user.is_authenticated)
        self.assertIsNone(next_request.session.session_key)
