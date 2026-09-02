from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from importlib import import_module
from importlib.util import find_spec
from uuid import UUID, uuid4

from django.apps import apps
from django.contrib import admin
from django.db import models, transaction
from django.test import TestCase

from open_marketplace.common.types import AuthorizationDecision, OperationContext


class AuditTestCase(TestCase):
    def require_module(self, module_name):
        self.assertIsNotNone(find_spec(module_name))
        return import_module(module_name)

    def public_module(self):
        public = self.require_module("open_marketplace.audit.public")
        for name in (
            "AuditEntryView",
            "AuditQuery",
            "append_audit_entry",
            "query_audit_entries",
        ):
            self.assertTrue(hasattr(public, name), name)
        return public

    def errors_module(self):
        return self.require_module("open_marketplace.common.errors")

    def audit_entry_model(self):
        audit_models = import_module("open_marketplace.audit.models")
        self.assertTrue(hasattr(audit_models, "AuditEntry"))
        return audit_models.AuditEntry

    def make_context(
        self,
        *,
        actor_id=None,
        now=None,
        source="admin",
        request_id=None,
    ):
        return OperationContext(
            actor_account_id=actor_id if actor_id is not None else uuid4(),
            session_id=uuid4(),
            request_id=request_id if request_id is not None else uuid4(),
            source=source,
            source_address="192.0.2.10",
            now=now if now is not None else datetime(2026, 9, 2, 12, tzinfo=UTC),
        )

    def append_entry(self, *, context=None, **overrides):
        public = self.public_module()
        values = {
            "context": context if context is not None else self.make_context(),
            "action": "account.block",
            "object_type": "account",
            "object_id": str(uuid4()),
            "result": "succeeded",
            "reason": "security review",
            "before": {"state": "active"},
            "after": {"state": "blocked"},
            "effective_role": "security_admin",
        }
        values.update(overrides)
        return public.append_audit_entry(**values)

    def make_query(self, **overrides):
        public = self.public_module()
        values = {
            "from_at": None,
            "to_at": None,
            "actor_id": None,
            "action": None,
            "object_type": None,
            "object_id": None,
            "result": None,
            "limit": 100,
            "cursor": None,
        }
        values.update(overrides)
        return public.AuditQuery(**values)

    def make_authorize(
        self,
        *,
        context,
        scopes,
        account_id=None,
        permission="audit.read",
    ):
        calls = []

        def authorize(received_context, requested_permission):
            calls.append((received_context, requested_permission))
            return AuthorizationDecision(
                account_id=account_id or context.actor_account_id,
                permission=permission,
                effective_roles=("security_admin",),
                scopes=tuple(scopes),
                reauthenticated_at=context.now,
            )

        return authorize, calls

    def query_entries(self, *, query=None, context=None, scopes=()):
        public = self.public_module()
        context = context if context is not None else self.make_context()
        query = query if query is not None else self.make_query()
        authorize, calls = self.make_authorize(context=context, scopes=scopes)
        result = public.query_audit_entries(
            query=query,
            context=context,
            authorize=authorize,
        )
        return result, calls

    def raw_entry_values(self, **overrides):
        values = {
            "id": uuid4(),
            "occurred_at": datetime(2026, 9, 2, 12, tzinfo=UTC),
            "actor_id": uuid4(),
            "effective_role": "security_admin",
            "action": "account.block",
            "object_type": "account",
            "object_id": str(uuid4()),
            "result": "succeeded",
            "reason": "security review",
            "request_id": uuid4(),
            "before": {"state": "active"},
            "after": {"state": "blocked"},
            "source": "admin",
        }
        values.update(overrides)
        return values


class SharedErrorContractTests(AuditTestCase):
    def test_shared_application_errors_are_available_from_one_module(self):
        errors = self.errors_module()
        expected = (
            "InputRejected",
            "AuthenticationDenied",
            "PermissionDenied",
            "InvalidState",
            "ConcurrentConflict",
            "TokenRejected",
            "RateLimited",
        )

        self.assertTrue(hasattr(errors, "ApplicationError"))
        for name in expected:
            with self.subTest(name=name):
                self.assertTrue(hasattr(errors, name))
                self.assertTrue(issubclass(getattr(errors, name), errors.ApplicationError))


class AuditAppendTests(AuditTestCase):
    def test_append_persists_the_complete_operation_context_and_returns_uuid(self):
        AuditEntry = self.audit_entry_model()
        context = self.make_context(source="worker")
        object_id = str(uuid4())

        entry_id = self.append_entry(
            context=context,
            action="outbox.manual_review",
            object_type="outbox_message",
            object_id=object_id,
            result="failed",
            reason="attempt limit reached",
            before={"attempt_number": 4},
            after={"attempt_number": 5},
            effective_role=None,
        )

        self.assertIsInstance(entry_id, UUID)
        entry = AuditEntry.objects.get(pk=entry_id)
        self.assertEqual(entry.occurred_at, context.now)
        self.assertEqual(entry.actor_id, context.actor_account_id)
        self.assertIsNone(entry.effective_role)
        self.assertEqual(entry.action, "outbox.manual_review")
        self.assertEqual(entry.object_type, "outbox_message")
        self.assertEqual(entry.object_id, object_id)
        self.assertEqual(entry.result, "failed")
        self.assertEqual(entry.reason, "attempt limit reached")
        self.assertEqual(entry.request_id, context.request_id)
        self.assertEqual(entry.before, {"attempt_number": 4})
        self.assertEqual(entry.after, {"attempt_number": 5})
        self.assertEqual(entry.source, "worker")

    def test_append_accepts_a_system_actor_without_an_account(self):
        AuditEntry = self.audit_entry_model()
        context = OperationContext(
            actor_account_id=None,
            session_id=None,
            request_id=uuid4(),
            source="command",
            source_address=None,
            now=datetime(2026, 9, 2, 12, tzinfo=UTC),
        )

        entry_id = self.append_entry(context=context, effective_role=None)

        entry = AuditEntry.objects.get(pk=entry_id)
        self.assertIsNone(entry.actor_id)
        self.assertEqual(entry.source, "command")

    def test_audit_model_is_installed_but_not_registered_with_admin(self):
        AuditEntry = self.audit_entry_model()

        self.assertIs(apps.get_model("audit", "AuditEntry"), AuditEntry)
        self.assertNotIn(AuditEntry, admin.site._registry)

    def test_public_query_objects_and_views_are_immutable_non_orm_values(self):
        public = self.public_module()
        context = self.make_context()
        entry_id = self.append_entry(context=context)
        query = self.make_query(object_type="account")
        authorize, calls = self.make_authorize(
            context=context,
            scopes=("audit:object_type:account",),
        )

        entries = public.query_audit_entries(
            query=query,
            context=context,
            authorize=authorize,
        )

        self.assertIsInstance(entries, tuple)
        self.assertEqual(len(entries), 1)
        view = entries[0]
        self.assertIsInstance(view, public.AuditEntryView)
        self.assertNotIsInstance(view, models.Model)
        self.assertEqual(view.id, entry_id)
        self.assertEqual(calls, [(context, "audit.read")])
        with self.assertRaises(FrozenInstanceError):
            query.limit = 1
        with self.assertRaises(FrozenInstanceError):
            view.result = "changed"


class AuditAppendOnlyTests(AuditTestCase):
    def test_instance_save_and_delete_paths_are_rejected(self):
        AuditEntry = self.audit_entry_model()
        entry_id = self.append_entry()
        existing = AuditEntry.objects.get(pk=entry_id)
        new_entry = AuditEntry(**self.raw_entry_values())
        operations = {
            "new_instance_save": lambda: new_entry.save(),
            "existing_save": lambda: existing.save(),
            "existing_save_update_fields": lambda: existing.save(
                update_fields={"reason"}
            ),
            "existing_delete": lambda: existing.delete(),
        }

        for name, operation in operations.items():
            with self.subTest(name=name):
                with transaction.atomic(), self.assertRaises(RuntimeError):
                    operation()

        self.assertTrue(AuditEntry.objects.filter(pk=entry_id).exists())
        self.assertFalse(AuditEntry.objects.filter(pk=new_entry.pk).exists())

    def test_queryset_and_manager_mutation_paths_are_rejected(self):
        AuditEntry = self.audit_entry_model()
        entry_id = self.append_entry(reason="original")
        entry = AuditEntry.objects.get(pk=entry_id)
        entry.reason = "changed"
        operations = {
            "queryset_update": lambda: AuditEntry.objects.filter(
                pk=entry_id
            ).update(reason="changed"),
            "queryset_delete": lambda: AuditEntry.objects.filter(pk=entry_id).delete(),
            "bulk_update": lambda: AuditEntry.objects.bulk_update(
                [entry], ["reason"]
            ),
            "manager_update_or_create": lambda: AuditEntry.objects.update_or_create(
                id=entry_id,
                defaults={"reason": "changed"},
            ),
            "manager_create": lambda: AuditEntry.objects.create(
                **self.raw_entry_values()
            ),
            "manager_get_or_create": lambda: AuditEntry.objects.get_or_create(
                **self.raw_entry_values()
            ),
            "manager_bulk_create": lambda: AuditEntry.objects.bulk_create(
                [AuditEntry(**self.raw_entry_values())]
            ),
        }

        for name, operation in operations.items():
            with self.subTest(name=name):
                with transaction.atomic(), self.assertRaises(RuntimeError):
                    operation()

        entry.refresh_from_db()
        self.assertEqual(entry.reason, "original")
        self.assertEqual(AuditEntry.objects.count(), 1)


class AuditPayloadValidationTests(AuditTestCase):
    def test_every_allowlisted_key_and_scalar_type_is_accepted(self):
        AuditEntry = self.audit_entry_model()
        payload = {
            "kind": "service",
            "state": "active",
            "email_verified": True,
            "totp_enabled": False,
            "role": None,
            "requirement_source": "staff_role",
            "version": 1,
            "decision": "approve",
            "session_count": 3,
            "revoked_session_count": 2,
            "message_type": "identity.email_verification",
            "format_version": 1,
            "attempt_number": 4,
            "next_attempt_at": "2026-09-02T12:30:00+00:00",
            "token_purpose": "email_verification",
            "subject_fingerprint": "a" * 64,
            "source_fingerprint": "b" * 64,
            "expires_at": "2026-09-03T12:00:00Z",
        }

        entry_id = self.append_entry(before=payload, after=payload)

        entry = AuditEntry.objects.get(pk=entry_id)
        self.assertEqual(entry.before, payload)
        self.assertEqual(entry.after, payload)

    def test_payload_scalar_boundaries_are_accepted(self):
        AuditEntry = self.audit_entry_model()
        payload = {"decision": "x" * 256, "version": 2**63 - 1}

        entry_id = self.append_entry(before=payload, after={})

        self.assertEqual(AuditEntry.objects.get(pk=entry_id).before, payload)

    def test_unknown_nested_non_scalar_and_out_of_range_values_are_rejected(self):
        InputRejected = self.errors_module().InputRejected
        cases = {
            "unknown_key": {"unknown": "value"},
            "nested_dict": {"state": {"old": "active"}},
            "nested_list": {"state": ["active"]},
            "nested_tuple": {"state": ("active",)},
            "non_scalar": {"state": object()},
            "overlong_string": {"decision": "x" * 257},
            "negative_integer": {"version": -1},
            "oversized_integer": {"version": 2**63},
        }

        for name, payload in cases.items():
            with self.subTest(name=name), self.assertRaises(InputRejected):
                self.append_entry(before=payload, after={})

    def test_sensitive_keys_are_rejected_even_inside_attempted_nesting(self):
        InputRejected = self.errors_module().InputRejected
        cases = {
            "password": {"password": "clear"},
            "token": {"wrapper": {"token": "clear"}},
            "secret": {"wrapper": [{"secret": "clear"}]},
            "totp": {"wrapper": {"deeper": {"totp": "123456"}}},
            "recovery_code": {"wrapper": ({"recovery_code": "clear"},)},
        }

        for name, payload in cases.items():
            with self.subTest(name=name), self.assertRaises(InputRejected):
                self.append_entry(before=payload, after={})

    def test_fingerprints_must_be_exact_lowercase_sha256_hex(self):
        InputRejected = self.errors_module().InputRejected
        values = ("a" * 63, "A" * 64, "g" * 64, "a" * 65)

        for value in values:
            with self.subTest(value=value), self.assertRaises(InputRejected):
                self.append_entry(
                    before={"subject_fingerprint": value},
                    after={},
                )

    def test_audit_datetimes_must_be_utc_iso8601_strings(self):
        InputRejected = self.errors_module().InputRejected
        values = (
            "2026-09-02T12:00:00",
            "2026-09-02T12:00:00+03:00",
            "tomorrow",
        )

        for value in values:
            with self.subTest(value=value), self.assertRaises(InputRejected):
                self.append_entry(
                    before={"expires_at": value},
                    after={},
                )

    def test_structural_fields_accept_the_exact_maximum_lengths(self):
        entry_id = self.append_entry(
            action="a" * 64,
            object_type="o" * 64,
            object_id="i" * 128,
            result="r" * 64,
            reason="x" * 1024,
            effective_role="e" * 64,
        )

        self.assertIsInstance(entry_id, UUID)

    def test_structural_fields_reject_values_over_the_maximum_lengths(self):
        InputRejected = self.errors_module().InputRejected
        cases = {
            "action": {"action": "a" * 65},
            "object_type": {"object_type": "o" * 65},
            "object_id": {"object_id": "i" * 129},
            "result": {"result": "r" * 65},
            "reason": {"reason": "x" * 1025},
            "effective_role": {"effective_role": "e" * 65},
        }

        for name, overrides in cases.items():
            with self.subTest(name=name), self.assertRaises(InputRejected):
                self.append_entry(**overrides)


class AuditAuthorizationTests(AuditTestCase):
    def test_query_calls_authorize_for_audit_read_and_propagates_denial(self):
        public = self.public_module()
        PermissionDenied = self.errors_module().PermissionDenied
        context = self.make_context()
        calls = []

        def deny(received_context, permission):
            calls.append((received_context, permission))
            raise PermissionDenied("denied")

        with self.assertRaises(PermissionDenied):
            public.query_audit_entries(
                query=self.make_query(),
                context=context,
                authorize=deny,
            )

        self.assertEqual(calls, [(context, "audit.read")])

    def test_query_rejects_wrong_actor_or_permission_decisions(self):
        public = self.public_module()
        PermissionDenied = self.errors_module().PermissionDenied
        context = self.make_context()
        cases = {
            "wrong_actor": {"account_id": uuid4(), "permission": "audit.read"},
            "wrong_permission": {
                "account_id": context.actor_account_id,
                "permission": "account.read",
            },
        }

        for name, decision_values in cases.items():
            authorize, _ = self.make_authorize(
                context=context,
                scopes=("audit:object_type:account",),
                **decision_values,
            )
            with self.subTest(name=name), self.assertRaises(PermissionDenied):
                public.query_audit_entries(
                    query=self.make_query(),
                    context=context,
                    authorize=authorize,
                )

    def test_empty_malformed_or_unknown_audit_scopes_deny_access(self):
        PermissionDenied = self.errors_module().PermissionDenied
        context = self.make_context()
        invalid_scope_sets = (
            (),
            ("",),
            ("account:object_type:account",),
            ("audit:unknown:account",),
            ("audit:object_type:",),
            ("audit:object_type",),
        )

        for scopes in invalid_scope_sets:
            with self.subTest(scopes=scopes), self.assertRaises(PermissionDenied):
                self.query_entries(context=context, scopes=scopes)

    def test_same_field_scopes_are_or_and_different_fields_are_and(self):
        context = self.make_context()
        application_a = str(uuid4())
        application_b = str(uuid4())
        application_c = str(uuid4())
        id_a = self.append_entry(
            object_type="seller_application",
            object_id=application_a,
            result="succeeded",
        )
        id_b = self.append_entry(
            object_type="seller_application",
            object_id=application_b,
            result="succeeded",
        )
        self.append_entry(
            object_type="seller_application",
            object_id=application_c,
            result="failed",
        )
        self.append_entry(object_type="account", result="succeeded")
        scopes = (
            "audit:object_type:seller_application",
            f"audit:object_id:{application_a}",
            f"audit:object_id:{application_b}",
            "audit:result:succeeded",
        )

        entries, _ = self.query_entries(context=context, scopes=scopes)

        self.assertEqual({entry.id for entry in entries}, {id_a, id_b})

    def test_requested_filters_can_narrow_but_never_widen_scopes(self):
        context = self.make_context()
        visible_object_id = str(uuid4())
        visible_id = self.append_entry(
            object_type="seller_application",
            object_id=visible_object_id,
        )
        self.append_entry(object_type="account")
        scopes = ("audit:object_type:seller_application",)

        narrowed, _ = self.query_entries(
            query=self.make_query(object_id=visible_object_id),
            context=context,
            scopes=scopes,
        )
        widened, _ = self.query_entries(
            query=self.make_query(object_type="account"),
            context=context,
            scopes=scopes,
        )

        self.assertEqual(tuple(entry.id for entry in narrowed), (visible_id,))
        self.assertEqual(widened, ())

    def test_security_scopes_can_union_multiple_allowed_object_types(self):
        context = self.make_context()
        account_id = self.append_entry(object_type="account")
        invitation_id = self.append_entry(object_type="staff_invitation")
        self.append_entry(object_type="seller_application")

        entries, _ = self.query_entries(
            context=context,
            scopes=(
                "audit:object_type:account",
                "audit:object_type:staff_invitation",
            ),
        )

        self.assertEqual({entry.id for entry in entries}, {account_id, invitation_id})


class AuditQueryTests(AuditTestCase):
    def test_all_requested_filters_are_applied(self):
        actor_id = uuid4()
        now = datetime(2026, 9, 2, 12, tzinfo=UTC)
        matching_context = self.make_context(actor_id=actor_id, now=now)
        matching_id = self.append_entry(
            context=matching_context,
            action="seller_application.approve",
            object_type="seller_application",
            object_id="application-1",
            result="succeeded",
        )
        self.append_entry(
            context=self.make_context(actor_id=actor_id, now=now - timedelta(hours=2)),
            action="seller_application.approve",
            object_type="seller_application",
            object_id="application-1",
            result="succeeded",
        )
        query_context = self.make_context()
        query = self.make_query(
            from_at=now - timedelta(minutes=1),
            to_at=now + timedelta(minutes=1),
            actor_id=actor_id,
            action="seller_application.approve",
            object_type="seller_application",
            object_id="application-1",
            result="succeeded",
        )

        entries, _ = self.query_entries(
            query=query,
            context=query_context,
            scopes=("audit:object_type:seller_application",),
        )

        self.assertEqual(tuple(entry.id for entry in entries), (matching_id,))

    def test_query_limit_accepts_one_and_one_hundred_but_rejects_outside(self):
        InputRejected = self.errors_module().InputRejected
        context = self.make_context()
        self.append_entry(object_type="account")

        for limit in (1, 100):
            with self.subTest(limit=limit):
                entries, _ = self.query_entries(
                    query=self.make_query(limit=limit),
                    context=context,
                    scopes=("audit:object_type:account",),
                )
                self.assertLessEqual(len(entries), limit)

        for limit in (0, 101):
            with self.subTest(limit=limit), self.assertRaises(InputRejected):
                self.query_entries(
                    query=self.make_query(limit=limit),
                    context=context,
                    scopes=("audit:object_type:account",),
                )

    def test_results_are_ordered_newest_first_by_time_then_uuid(self):
        time = datetime(2026, 9, 2, 12, tzinfo=UTC)
        older_id = self.append_entry(
            context=self.make_context(now=time - timedelta(minutes=1)),
            object_type="account",
        )
        same_time_ids = [
            self.append_entry(
                context=self.make_context(now=time),
                object_type="account",
            )
            for _ in range(2)
        ]

        entries, _ = self.query_entries(
            scopes=("audit:object_type:account",),
        )

        expected = tuple(sorted(same_time_ids, reverse=True)) + (older_id,)
        self.assertEqual(tuple(entry.id for entry in entries), expected)

    def test_cursor_resumes_after_the_previous_page_and_rejects_unknown_cursor(self):
        InputRejected = self.errors_module().InputRejected
        base_time = datetime(2026, 9, 2, 12, tzinfo=UTC)
        ids = [
            self.append_entry(
                context=self.make_context(now=base_time - timedelta(minutes=index)),
                object_type="account",
            )
            for index in range(3)
        ]
        context = self.make_context()
        scopes = ("audit:object_type:account",)

        first_page, _ = self.query_entries(
            query=self.make_query(limit=2),
            context=context,
            scopes=scopes,
        )
        second_page, _ = self.query_entries(
            query=self.make_query(limit=2, cursor=first_page[-1].id),
            context=context,
            scopes=scopes,
        )

        self.assertEqual(tuple(entry.id for entry in first_page), tuple(ids[:2]))
        self.assertEqual(tuple(entry.id for entry in second_page), (ids[2],))
        with self.assertRaises(InputRejected):
            self.query_entries(
                query=self.make_query(limit=2, cursor=uuid4()),
                context=context,
                scopes=scopes,
            )

    def test_cursor_outside_the_authorized_result_is_rejected(self):
        InputRejected = self.errors_module().InputRejected
        authorized_id = self.append_entry(object_type="account")
        unauthorized_id = self.append_entry(object_type="staff_invitation")
        context = self.make_context()

        with self.assertRaises(InputRejected):
            self.query_entries(
                query=self.make_query(cursor=unauthorized_id),
                context=context,
                scopes=("audit:object_type:account",),
            )

        entries, _ = self.query_entries(
            context=context,
            scopes=("audit:object_type:account",),
        )
        self.assertEqual(tuple(entry.id for entry in entries), (authorized_id,))
