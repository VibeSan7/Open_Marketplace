import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from importlib import import_module
from importlib.util import find_spec
from unittest.mock import patch
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
from django.apps import apps
from django.conf import settings
from django.contrib import admin
from django.db import models
from django.test import TestCase

from open_marketplace.common.types import AuthorizationDecision, OperationContext

_UNSET = object()


class OutboxTestCase(TestCase):
    def require_module(self, module_name):
        self.assertIsNotNone(find_spec(module_name))
        return import_module(module_name)

    def public_module(self):
        public = self.require_module("open_marketplace.outbox.public")
        for name in (
            "ClaimedMessage",
            "OutboxMessageView",
            "OutboxQuery",
            "enqueue_outbox_message",
            "claim_ready_messages",
            "mark_message_succeeded",
            "schedule_message_retry",
            "mark_message_for_manual_review",
            "retry_message_from_manual_review",
            "query_manual_review_messages",
        ):
            self.assertTrue(hasattr(public, name), name)
        return public

    def model_class(self):
        module = import_module("open_marketplace.outbox.models")
        self.assertTrue(hasattr(module, "OutboxMessage"))
        return module.OutboxMessage

    def errors_module(self):
        return import_module("open_marketplace.common.errors")

    def context(self, *, actor_id=None, now=None, source="admin"):
        return OperationContext(
            actor_account_id=actor_id if actor_id is not None else uuid4(),
            session_id=uuid4() if source in {"html", "admin"} else None,
            request_id=uuid4(),
            source=source,
            source_address="192.0.2.20" if source in {"html", "admin"} else None,
            now=now if now is not None else datetime(2026, 9, 2, 12, tzinfo=UTC),
        )

    def worker_context(self, *, now):
        return OperationContext(
            actor_account_id=None,
            session_id=None,
            request_id=uuid4(),
            source="worker",
            source_address=None,
            now=now,
        )

    def message_cases(self):
        account_id = str(uuid4())
        token_id = str(uuid4())
        invitation_id = str(uuid4())
        application_id = str(uuid4())
        seller_id = str(uuid4())
        return (
            (
                "identity.email_verification",
                {"account_id": account_id, "token_id": token_id},
                {
                    "recipient": "person@example.com",
                    "absolute_token_url": "https://example.com/verify/EMAIL_TOKEN",
                },
            ),
            (
                "identity.password_reset",
                {"account_id": account_id, "token_id": token_id},
                {
                    "recipient": "person@example.com",
                    "absolute_token_url": "https://example.com/reset/RESET_TOKEN",
                },
            ),
            (
                "access.staff_invitation",
                {"invitation_id": invitation_id, "role": "security_admin"},
                {
                    "recipient": "staff@example.com",
                    "absolute_token_url": "https://example.com/staff/INVITATION_TOKEN",
                },
            ),
            (
                "seller_onboarding.application_decision",
                {"application_id": application_id, "decision": "approve"},
                {"recipient": "seller@example.com"},
            ),
            (
                "identity.protected_account_change",
                {"account_id": account_id, "change": "password_changed"},
                {"recipient": "person@example.com"},
            ),
            (
                "seller_onboarding.admission_change",
                {"seller_id": seller_id, "state": "active"},
                None,
            ),
        )

    def default_message(self):
        return self.message_cases()[0]

    def enqueue(
        self,
        *,
        message_type=_UNSET,
        payload=_UNSET,
        delivery=_UNSET,
        idempotency_key=None,
        format_version=1,
    ):
        public = self.public_module()
        default_type, default_payload, default_delivery = self.default_message()
        return public.enqueue_outbox_message(
            message_type=default_type if message_type is _UNSET else message_type,
            format_version=format_version,
            payload=default_payload if payload is _UNSET else payload,
            delivery=default_delivery if delivery is _UNSET else delivery,
            idempotency_key=(
                idempotency_key
                if idempotency_key is not None
                else f"test:{uuid4()}"
            ),
        )

    def claim(self, *, worker_id="worker:one", now=None, lease_seconds=60, limit=100):
        return self.public_module().claim_ready_messages(
            worker_id=worker_id,
            now=now if now is not None else datetime(2026, 9, 2, 12, tzinfo=UTC),
            lease_seconds=lease_seconds,
            limit=limit,
        )

    def decrypt_delivery(self, ciphertext):
        plaintext = Fernet(settings.OUTBOX_ENCRYPTION_KEY.encode("ascii")).decrypt(bytes(ciphertext))
        return json.loads(plaintext.decode("utf-8"))

    def make_authorize(self, *, context, scopes, account_id=None, permission="outbox.manual_retry"):
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

    def make_query(self, **overrides):
        public = self.public_module()
        values = {
            "state": "manual_review",
            "message_type": None,
            "limit": 100,
            "cursor": None,
        }
        values.update(overrides)
        return public.OutboxQuery(**values)

    def make_manual(
        self,
        *,
        message_type=_UNSET,
        payload=_UNSET,
        delivery=_UNSET,
        now=None,
        safe_error="smtp_timeout",
    ):
        public = self.public_module()
        now = now or datetime(2026, 9, 2, 12, tzinfo=UTC)
        message_id = self.enqueue(message_type=message_type, payload=payload, delivery=delivery)
        claimed = self.claim(now=now, limit=1)[0]
        self.assertEqual(claimed.id, message_id)
        public.mark_message_for_manual_review(
            message_id=message_id,
            worker_id="worker:one",
            attempt_number=claimed.attempt_number,
            now=now + timedelta(seconds=1),
            safe_error=safe_error,
            context=self.worker_context(now=now + timedelta(seconds=1)),
        )
        return message_id


class OutboxPublicContractTests(OutboxTestCase):
    def test_app_is_installed_and_model_is_not_registered_with_admin(self):
        OutboxMessage = self.model_class()

        self.assertIs(apps.get_model("outbox", "OutboxMessage"), OutboxMessage)
        self.assertNotIn(OutboxMessage, admin.site._registry)

    def test_public_claimed_and_view_values_are_frozen_non_orm_dataclasses(self):
        public = self.public_module()
        now = datetime(2026, 9, 2, 12, tzinfo=UTC)
        message_id = self.enqueue()

        claimed = self.claim(now=now, limit=1)[0]

        self.assertEqual(claimed.id, message_id)
        self.assertNotIsInstance(claimed, models.Model)
        with self.assertRaises(FrozenInstanceError):
            claimed.attempt_number = 9
        with self.assertRaises(TypeError):
            claimed.payload["account_id"] = str(uuid4())
        self.assertEqual(
            self.model_class().objects.get(pk=message_id).payload,
            claimed.payload,
        )

        public.mark_message_for_manual_review(
            message_id=message_id,
            worker_id="worker:one",
            attempt_number=claimed.attempt_number,
            now=now + timedelta(seconds=1),
            safe_error="smtp_timeout",
            context=self.worker_context(now=now + timedelta(seconds=1)),
        )
        context = self.context(now=now + timedelta(seconds=2))
        authorize, _ = self.make_authorize(
            context=context,
            scopes=("outbox:state:manual_review",),
        )
        query = self.make_query()
        view = public.query_manual_review_messages(query=query, context=context, authorize=authorize)[0]

        self.assertNotIsInstance(view, models.Model)
        with self.assertRaises(FrozenInstanceError):
            query.limit = 1
        with self.assertRaises(FrozenInstanceError):
            view.state = "pending"


class OutboxEnqueueValidationTests(OutboxTestCase):
    def test_all_six_exact_payload_and_delivery_schemas_are_encrypted_at_rest(self):
        OutboxMessage = self.model_class()

        for index, (message_type, payload, delivery) in enumerate(self.message_cases()):
            with self.subTest(message_type=message_type):
                message_id = self.enqueue(
                    message_type=message_type,
                    payload=payload,
                    delivery=delivery,
                    idempotency_key=f"schema:{index}:{uuid4()}",
                )
                message = OutboxMessage.objects.get(pk=message_id)

                self.assertEqual(message.message_type, message_type)
                self.assertEqual(message.format_version, 1)
                self.assertEqual(message.payload, payload)
                self.assertEqual(message.state, "pending")
                self.assertEqual(message.attempts, 0)
                self.assertEqual(message.next_attempt_at, message.created_at)
                self.assertIsNone(message.claimed_at)
                self.assertIsNone(message.leased_by)
                self.assertIsNone(message.lease_expires_at)
                self.assertIsNone(message.last_safe_error)
                self.assertIsNone(message.succeeded_at)
                if delivery is None:
                    self.assertIsNone(message.encrypted_delivery)
                else:
                    ciphertext = bytes(message.encrypted_delivery)
                    self.assertLessEqual(len(ciphertext), 8192)
                    for secret_value in delivery.values():
                        self.assertNotIn(secret_value.encode("utf-8"), ciphertext)
                    self.assertEqual(self.decrypt_delivery(ciphertext), delivery)

    def test_unknown_type_version_and_payload_shape_are_rejected(self):
        InputRejected = self.errors_module().InputRejected
        message_type, payload, delivery = self.default_message()
        first_key = next(iter(payload))
        cases = (
            {"message_type": "unknown.message"},
            {"format_version": 0},
            {"format_version": 2},
            {"payload": {key: value for key, value in payload.items() if key != first_key}},
            {"payload": {**payload, "extra": "value"}},
            {"payload": {**payload, first_key: {"nested": "value"}}},
            {"payload": {**payload, first_key: ["nested"]}},
        )

        for overrides in cases:
            with self.subTest(overrides=overrides), self.assertRaises(InputRejected):
                values = {
                    "message_type": message_type,
                    "payload": payload,
                    "delivery": delivery,
                }
                values.update(overrides)
                self.enqueue(**values)

    def test_identifiers_must_be_canonical_lowercase_uuid_strings(self):
        InputRejected = self.errors_module().InputRejected
        message_type, payload, delivery = self.default_message()
        values = (str(uuid4()).upper(), "{" + str(uuid4()) + "}", "not-a-uuid", uuid4())

        for value in values:
            with self.subTest(value=value), self.assertRaises(InputRejected):
                self.enqueue(
                    message_type=message_type,
                    payload={**payload, "account_id": value},
                    delivery=delivery,
                )

    def test_closed_role_decision_change_and_seller_state_values_are_enforced(self):
        InputRejected = self.errors_module().InputRejected
        invalid_cases = (
            (
                "access.staff_invitation",
                {"invitation_id": str(uuid4()), "role": "superadmin"},
                {"recipient": "staff@example.com", "absolute_token_url": "https://example.com/i/TOKEN"},
            ),
            (
                "seller_onboarding.application_decision",
                {"application_id": str(uuid4()), "decision": "maybe"},
                {"recipient": "seller@example.com"},
            ),
            (
                "identity.protected_account_change",
                {"account_id": str(uuid4()), "change": "email_changed"},
                {"recipient": "person@example.com"},
            ),
            (
                "seller_onboarding.admission_change",
                {"seller_id": str(uuid4()), "state": "deleted"},
                None,
            ),
        )

        for message_type, payload, delivery in invalid_cases:
            with self.subTest(message_type=message_type), self.assertRaises(InputRejected):
                self.enqueue(message_type=message_type, payload=payload, delivery=delivery)

    def test_delivery_schema_recipient_and_url_are_strict(self):
        InputRejected = self.errors_module().InputRejected
        message_type, payload, valid_delivery = self.default_message()
        invalid_deliveries = (
            None,
            {"recipient": "person@example.com"},
            {**valid_delivery, "extra": "value"},
            {**valid_delivery, "recipient": "not-an-email"},
            {**valid_delivery, "recipient": "a" * 309 + "@example.com"},
            {**valid_delivery, "absolute_token_url": "/relative/TOKEN"},
            {**valid_delivery, "absolute_token_url": "ftp://example.com/TOKEN"},
            {**valid_delivery, "absolute_token_url": "https://user:pass@example.com/TOKEN"},
            {**valid_delivery, "absolute_token_url": "https://example.com:/TOKEN"},
            {**valid_delivery, "absolute_token_url": "https://example.com/TOKEN#fragment"},
            {**valid_delivery, "absolute_token_url": "https://example.com/" + "x" * 2040},
        )

        for delivery in invalid_deliveries:
            with self.subTest(delivery=delivery), self.assertRaises(InputRejected):
                self.enqueue(message_type=message_type, payload=payload, delivery=delivery)

        internal_type, internal_payload, _ = self.message_cases()[-1]
        with self.assertRaises(InputRejected):
            self.enqueue(
                message_type=internal_type,
                payload=internal_payload,
                delivery={"recipient": "person@example.com"},
            )

    def test_idempotency_key_boundaries_and_duplicate_rejection(self):
        ConcurrentConflict = self.errors_module().ConcurrentConflict
        InputRejected = self.errors_module().InputRejected

        for key in ("x", "x" * 128, f"kind:1:{uuid4()}"):
            with self.subTest(valid=key):
                self.assertIsInstance(self.enqueue(idempotency_key=key), UUID)

        for key in ("", "x" * 129, "has space", "has/slash", "кириллица"):
            with self.subTest(invalid=key), self.assertRaises(InputRejected):
                self.enqueue(idempotency_key=key)

        duplicate = f"duplicate:{uuid4()}"
        original_id = self.enqueue(idempotency_key=duplicate)
        with self.assertRaises(ConcurrentConflict):
            self.enqueue(idempotency_key=duplicate)
        self.assertEqual(self.model_class().objects.filter(idempotency_key=duplicate).count(), 1)
        self.assertTrue(self.model_class().objects.filter(pk=original_id).exists())


class OutboxStateMachineTests(OutboxTestCase):
    def test_pending_claim_and_success_use_a_short_active_lease_and_erase_ciphertext(self):
        public = self.public_module()
        OutboxMessage = self.model_class()
        now = datetime(2026, 9, 2, 12, tzinfo=UTC)
        message_id = self.enqueue()

        claimed = self.claim(worker_id="worker:alpha", now=now, lease_seconds=60, limit=1)

        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0].id, message_id)
        self.assertEqual(claimed[0].attempt_number, 1)
        self.assertIsNotNone(claimed[0].encrypted_delivery)
        message = OutboxMessage.objects.get(pk=message_id)
        self.assertEqual(message.state, "processing")
        self.assertEqual(message.attempts, 1)
        self.assertEqual(message.claimed_at, now)
        self.assertEqual(message.leased_by, "worker:alpha")
        self.assertEqual(message.lease_expires_at, now + timedelta(seconds=60))

        public.mark_message_succeeded(
            message_id=message_id,
            worker_id="worker:alpha",
            attempt_number=1,
            now=now + timedelta(seconds=30),
        )

        message.refresh_from_db()
        self.assertEqual(message.state, "succeeded")
        self.assertEqual(message.succeeded_at, now + timedelta(seconds=30))
        self.assertIsNone(message.encrypted_delivery)
        self.assertIsNone(message.next_attempt_at)
        self.assertIsNone(message.claimed_at)
        self.assertIsNone(message.leased_by)
        self.assertIsNone(message.lease_expires_at)
        self.assertEqual(self.claim(now=now + timedelta(hours=1)), [])

    def test_retry_wait_uses_exact_exponential_delay_and_becomes_ready_on_boundary(self):
        public = self.public_module()
        OutboxMessage = self.model_class()
        now = datetime(2026, 9, 2, 12, tzinfo=UTC)
        message_id = self.enqueue()
        first = self.claim(now=now, limit=1)[0]
        failure_time = now + timedelta(seconds=1)

        public.schedule_message_retry(
            message_id=message_id,
            worker_id="worker:one",
            attempt_number=first.attempt_number,
            now=failure_time,
            safe_error="smtp_timeout",
        )

        message = OutboxMessage.objects.get(pk=message_id)
        self.assertEqual(message.state, "retry_wait")
        self.assertEqual(message.next_attempt_at, failure_time + timedelta(seconds=60))
        self.assertEqual(message.last_safe_error, "smtp_timeout")
        self.assertEqual(self.claim(now=message.next_attempt_at - timedelta(microseconds=1)), [])
        second = self.claim(now=message.next_attempt_at, limit=1)[0]
        self.assertEqual(second.attempt_number, 2)

        second_failure = message.next_attempt_at + timedelta(seconds=1)
        public.schedule_message_retry(
            message_id=message_id,
            worker_id="worker:one",
            attempt_number=2,
            now=second_failure,
            safe_error="smtp_unavailable",
        )
        message.refresh_from_db()
        self.assertEqual(message.next_attempt_at, second_failure + timedelta(seconds=120))

    def test_claim_worker_lease_limit_and_time_boundaries_are_enforced(self):
        InputRejected = self.errors_module().InputRejected
        aware = datetime(2026, 9, 2, 12, tzinfo=UTC)
        invalid_cases = (
            {"worker_id": ""},
            {"worker_id": "x" * 129},
            {"worker_id": "worker with space"},
            {"worker_id": "worker/slash"},
            {"lease_seconds": 0},
            {"lease_seconds": 301},
            {"limit": 0},
            {"limit": 101},
            {"now": datetime(2026, 9, 2, 12)},
        )

        for overrides in invalid_cases:
            with self.subTest(overrides=overrides), self.assertRaises(InputRejected):
                values = {"now": aware}
                values.update(overrides)
                self.claim(**values)

        self.enqueue()
        claimed = self.claim(worker_id="w" * 128, now=aware, lease_seconds=1, limit=1)
        self.assertEqual(len(claimed), 1)
        self.enqueue()
        claimed = self.claim(worker_id="worker:max", now=aware, lease_seconds=300, limit=100)
        self.assertEqual(len(claimed), 1)

    def test_safe_error_is_a_bounded_machine_code_not_raw_exception_text(self):
        InputRejected = self.errors_module().InputRejected
        public = self.public_module()
        now = datetime(2026, 9, 2, 12, tzinfo=UTC)
        message_id = self.enqueue()
        attempt = self.claim(now=now, limit=1)[0]
        invalid_codes = ("", "SMTP_TIMEOUT", "smtp timeout", "smtp/timeout", "x" * 129)

        for code in invalid_codes:
            with self.subTest(code=code), self.assertRaises(InputRejected):
                public.schedule_message_retry(
                    message_id=message_id,
                    worker_id="worker:one",
                    attempt_number=attempt.attempt_number,
                    now=now + timedelta(seconds=1),
                    safe_error=code,
                )

        second_id = self.enqueue()
        second = self.claim(worker_id="worker:max", now=now, limit=1)[0]
        self.assertEqual(second.id, second_id)
        public.schedule_message_retry(
            message_id=second_id,
            worker_id="worker:max",
            attempt_number=second.attempt_number,
            now=now + timedelta(seconds=1),
            safe_error="x" * 128,
        )

    def test_wrong_worker_attempt_expired_lease_and_wrong_state_are_rejected(self):
        public = self.public_module()
        ConcurrentConflict = self.errors_module().ConcurrentConflict
        InvalidState = self.errors_module().InvalidState
        now = datetime(2026, 9, 2, 12, tzinfo=UTC)
        message_id = self.enqueue()
        attempt = self.claim(worker_id="worker:one", now=now, lease_seconds=60, limit=1)[0]

        invalid_claims = (
            {"worker_id": "worker:other", "attempt_number": attempt.attempt_number, "now": now + timedelta(seconds=1)},
            {"worker_id": "worker:one", "attempt_number": attempt.attempt_number + 1, "now": now + timedelta(seconds=1)},
            {"worker_id": "worker:one", "attempt_number": attempt.attempt_number, "now": now + timedelta(seconds=60)},
        )
        for values in invalid_claims:
            with self.subTest(values=values), self.assertRaises(ConcurrentConflict):
                public.mark_message_succeeded(message_id=message_id, **values)

        public.mark_message_succeeded(
            message_id=message_id,
            worker_id="worker:one",
            attempt_number=attempt.attempt_number,
            now=now + timedelta(seconds=30),
        )
        with self.assertRaises(InvalidState):
            public.mark_message_succeeded(
                message_id=message_id,
                worker_id="worker:one",
                attempt_number=attempt.attempt_number,
                now=now + timedelta(seconds=31),
            )

    def test_fifth_failed_attempt_moves_to_manual_review_and_writes_safe_audit(self):
        public = self.public_module()
        OutboxMessage = self.model_class()
        AuditEntry = import_module("open_marketplace.audit.models").AuditEntry
        InvalidState = self.errors_module().InvalidState
        now = datetime(2026, 9, 2, 12, tzinfo=UTC)
        message_id = self.enqueue()

        for expected_attempt in range(1, 6):
            claimed = self.claim(now=now, limit=1)[0]
            self.assertEqual(claimed.attempt_number, expected_attempt)
            failure_time = now + timedelta(seconds=1)
            if expected_attempt < 5:
                public.schedule_message_retry(
                    message_id=message_id,
                    worker_id="worker:one",
                    attempt_number=expected_attempt,
                    now=failure_time,
                    safe_error="smtp_timeout",
                )
                message = OutboxMessage.objects.get(pk=message_id)
                now = message.next_attempt_at
            else:
                with self.assertRaises(InvalidState):
                    public.schedule_message_retry(
                        message_id=message_id,
                        worker_id="worker:one",
                        attempt_number=expected_attempt,
                        now=failure_time,
                        safe_error="smtp_timeout",
                    )
                public.mark_message_for_manual_review(
                    message_id=message_id,
                    worker_id="worker:one",
                    attempt_number=expected_attempt,
                    now=failure_time,
                    safe_error="smtp_timeout",
                    context=self.worker_context(now=failure_time),
                )

        message = OutboxMessage.objects.get(pk=message_id)
        self.assertEqual(message.state, "manual_review")
        self.assertEqual(message.attempts, 5)
        self.assertEqual(message.last_safe_error, "smtp_timeout")
        audit = AuditEntry.objects.get(action="outbox.manual_review", object_id=str(message_id))
        self.assertEqual(audit.reason, "smtp_timeout")
        self.assertEqual(audit.before["state"], "processing")
        self.assertEqual(audit.after["state"], "manual_review")
        self.assertNotIn("encrypted_delivery", audit.before)
        self.assertNotIn("delivery", audit.after)


class OutboxManualReviewTests(OutboxTestCase):
    def test_query_requires_permission_matching_actor_and_closed_scopes(self):
        public = self.public_module()
        PermissionDenied = self.errors_module().PermissionDenied
        now = datetime(2026, 9, 2, 12, tzinfo=UTC)
        context = self.context(now=now)
        email_id = self.make_manual(now=now)
        decision_type, decision_payload, decision_delivery = self.message_cases()[3]
        decision_id = self.make_manual(
            message_type=decision_type,
            payload=decision_payload,
            delivery=decision_delivery,
            now=now + timedelta(minutes=1),
        )
        authorize, calls = self.make_authorize(
            context=context,
            scopes=(
                "outbox:state:manual_review",
                "outbox:message_type:identity.email_verification",
                "outbox:message_type:seller_onboarding.application_decision",
            ),
        )

        entries = public.query_manual_review_messages(
            query=self.make_query(),
            context=context,
            authorize=authorize,
        )

        self.assertEqual({entry.id for entry in entries}, {email_id, decision_id})
        self.assertEqual(calls, [(context, "outbox.manual_retry")])

        cases = (
            {"scopes": ()},
            {"scopes": ("",)},
            {"scopes": ("audit:state:manual_review",)},
            {"scopes": ("outbox:unknown:value",)},
            {"scopes": ("outbox:state:",)},
            {"scopes": ("outbox:state:pending",)},
            {"scopes": ("outbox:state:manual_review",), "account_id": uuid4()},
            {"scopes": ("outbox:state:manual_review",), "permission": "audit.read"},
        )
        for values in cases:
            authorize, _ = self.make_authorize(context=context, **values)
            with self.subTest(values=values), self.assertRaises(PermissionDenied):
                public.query_manual_review_messages(
                    query=self.make_query(),
                    context=context,
                    authorize=authorize,
                )

    def test_query_filters_limit_cursor_and_newest_order_are_bounded(self):
        public = self.public_module()
        OutboxMessage = self.model_class()
        InputRejected = self.errors_module().InputRejected
        base = datetime(2026, 9, 2, 12, tzinfo=UTC)
        ids = [self.make_manual(now=base + timedelta(minutes=index)) for index in range(3)]
        for index, message_id in enumerate(ids):
            OutboxMessage.objects.filter(pk=message_id).update(created_at=base + timedelta(minutes=index))
        context = self.context(now=base + timedelta(hours=1))
        scopes = ("outbox:state:manual_review",)
        authorize, _ = self.make_authorize(context=context, scopes=scopes)

        first = public.query_manual_review_messages(
            query=self.make_query(limit=2),
            context=context,
            authorize=authorize,
        )
        second = public.query_manual_review_messages(
            query=self.make_query(limit=2, cursor=first[-1].id),
            context=context,
            authorize=authorize,
        )

        self.assertEqual(tuple(entry.id for entry in first), (ids[2], ids[1]))
        self.assertEqual(tuple(entry.id for entry in second), (ids[0],))
        for invalid_query in (
            self.make_query(state="pending"),
            self.make_query(limit=0),
            self.make_query(limit=101),
            self.make_query(cursor=uuid4()),
        ):
            with self.subTest(query=invalid_query), self.assertRaises(InputRejected):
                public.query_manual_review_messages(
                    query=invalid_query,
                    context=context,
                    authorize=authorize,
                )

    def test_requested_message_type_and_id_scopes_only_narrow_results(self):
        public = self.public_module()
        base = datetime(2026, 9, 2, 12, tzinfo=UTC)
        email_id = self.make_manual(now=base)
        decision_type, decision_payload, decision_delivery = self.message_cases()[3]
        decision_id = self.make_manual(
            message_type=decision_type,
            payload=decision_payload,
            delivery=decision_delivery,
            now=base + timedelta(minutes=1),
        )
        context = self.context(now=base + timedelta(hours=1))
        authorize, _ = self.make_authorize(
            context=context,
            scopes=(
                "outbox:state:manual_review",
                f"outbox:id:{email_id}",
                f"outbox:id:{decision_id}",
            ),
        )

        narrowed = public.query_manual_review_messages(
            query=self.make_query(message_type="seller_onboarding.application_decision"),
            context=context,
            authorize=authorize,
        )
        widened = public.query_manual_review_messages(
            query=self.make_query(message_type="identity.password_reset"),
            context=context,
            authorize=authorize,
        )

        self.assertEqual(tuple(entry.id for entry in narrowed), (decision_id,))
        self.assertEqual(widened, ())

    def test_manual_retry_requires_reason_scope_and_preserves_identity_with_monotonic_attempts(self):
        public = self.public_module()
        OutboxMessage = self.model_class()
        AuditEntry = import_module("open_marketplace.audit.models").AuditEntry
        InputRejected = self.errors_module().InputRejected
        PermissionDenied = self.errors_module().PermissionDenied
        base = datetime(2026, 9, 2, 12, tzinfo=UTC)
        message_id = self.make_manual(now=base)
        before = OutboxMessage.objects.get(pk=message_id)
        original_key = before.idempotency_key
        original_attempts = before.attempts
        context = self.context(now=base + timedelta(minutes=2))

        denied, _ = self.make_authorize(
            context=context,
            scopes=("outbox:id:" + str(uuid4()),),
        )
        with self.assertRaises(PermissionDenied):
            public.retry_message_from_manual_review(
                message_id=message_id,
                reason="checked mail provider",
                context=context,
                authorize=denied,
            )

        allowed, calls = self.make_authorize(
            context=context,
            scopes=("outbox:state:manual_review", f"outbox:id:{message_id}"),
        )
        for reason in ("", "   ", "x" * 1025):
            with self.subTest(reason=reason), self.assertRaises(InputRejected):
                public.retry_message_from_manual_review(
                    message_id=message_id,
                    reason=reason,
                    context=context,
                    authorize=allowed,
                )

        public.retry_message_from_manual_review(
            message_id=message_id,
            reason="  checked mail provider  ",
            context=context,
            authorize=allowed,
        )

        message = OutboxMessage.objects.get(pk=message_id)
        self.assertEqual(message.state, "pending")
        self.assertEqual(message.next_attempt_at, context.now)
        self.assertEqual(message.idempotency_key, original_key)
        self.assertEqual(message.attempts, original_attempts)
        self.assertIsNone(message.last_safe_error)
        claimed = self.claim(worker_id="worker:manual", now=context.now, limit=1)[0]
        self.assertEqual(claimed.id, message_id)
        self.assertEqual(claimed.attempt_number, original_attempts + 1)
        self.assertTrue(calls)
        audit = AuditEntry.objects.get(action="outbox.manual_retry", object_id=str(message_id))
        self.assertEqual(audit.reason, "checked mail provider")
        self.assertNotIn("delivery", audit.before)
        self.assertNotIn("encrypted_delivery", audit.after)

    def test_manual_review_and_retry_roll_back_when_audit_append_fails(self):
        public = self.public_module()
        OutboxMessage = self.model_class()
        base = datetime(2026, 9, 2, 12, tzinfo=UTC)
        message_id = self.enqueue()
        claimed = self.claim(now=base, limit=1)[0]
        with patch(
            "open_marketplace.outbox.application.append_audit_entry",
            side_effect=RuntimeError("audit unavailable"),
        ), self.assertRaises(RuntimeError):
            public.mark_message_for_manual_review(
                message_id=message_id,
                worker_id="worker:one",
                attempt_number=claimed.attempt_number,
                now=base + timedelta(seconds=1),
                safe_error="smtp_timeout",
                context=self.worker_context(now=base + timedelta(seconds=1)),
            )
        message = OutboxMessage.objects.get(pk=message_id)
        self.assertEqual(message.state, "processing")

        public.mark_message_for_manual_review(
            message_id=message_id,
            worker_id="worker:one",
            attempt_number=claimed.attempt_number,
            now=base + timedelta(seconds=2),
            safe_error="smtp_timeout",
            context=self.worker_context(now=base + timedelta(seconds=2)),
        )
        context = self.context(now=base + timedelta(minutes=1))
        authorize, _ = self.make_authorize(
            context=context,
            scopes=("outbox:state:manual_review",),
        )
        with patch(
            "open_marketplace.outbox.application.append_audit_entry",
            side_effect=RuntimeError("audit unavailable"),
        ), self.assertRaises(RuntimeError):
            public.retry_message_from_manual_review(
                message_id=message_id,
                reason="checked provider",
                context=context,
                authorize=authorize,
            )
        message.refresh_from_db()
        self.assertEqual(message.state, "manual_review")

    def test_manual_retry_accepts_the_exact_reason_maximum(self):
        public = self.public_module()
        OutboxMessage = self.model_class()
        base = datetime(2026, 9, 2, 12, tzinfo=UTC)
        message_id = self.make_manual(now=base)
        context = self.context(now=base + timedelta(minutes=1))
        authorize, _ = self.make_authorize(
            context=context,
            scopes=("outbox:state:manual_review",),
        )

        public.retry_message_from_manual_review(
            message_id=message_id,
            reason="r" * 1024,
            context=context,
            authorize=authorize,
        )

        self.assertEqual(OutboxMessage.objects.get(pk=message_id).state, "pending")
