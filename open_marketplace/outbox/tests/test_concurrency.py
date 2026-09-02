from datetime import UTC, datetime, timedelta
from importlib import import_module
from importlib.util import find_spec
from threading import Barrier, Event, Thread
from time import monotonic
from uuid import uuid4

from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase


class OutboxConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def public_module(self):
        self.assertIsNotNone(find_spec("open_marketplace.outbox.public"))
        return import_module("open_marketplace.outbox.public")

    def model_class(self):
        module = import_module("open_marketplace.outbox.models")
        self.assertTrue(hasattr(module, "OutboxMessage"))
        return module.OutboxMessage

    def enqueue(self, *, idempotency_key=None):
        return self.public_module().enqueue_outbox_message(
            message_type="identity.email_verification",
            format_version=1,
            payload={"account_id": str(uuid4()), "token_id": str(uuid4())},
            delivery={
                "recipient": "person@example.com",
                "absolute_token_url": "https://example.com/verify/TOKEN",
            },
            idempotency_key=idempotency_key or f"concurrency:{uuid4()}",
        )

    def test_locked_ready_row_is_skipped_instead_of_waiting(self):
        public = self.public_module()
        OutboxMessage = self.model_class()
        message_id = self.enqueue()
        locked = Event()
        release = Event()
        thread_errors = []

        def hold_row_lock():
            close_old_connections()
            try:
                with transaction.atomic():
                    OutboxMessage.objects.select_for_update().get(pk=message_id)
                    locked.set()
                    release.wait(timeout=5)
            except Exception as error:
                thread_errors.append(error)
            finally:
                close_old_connections()

        thread = Thread(target=hold_row_lock)
        thread.start()
        self.assertTrue(locked.wait(timeout=5))
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout TO '200ms'")
            started = monotonic()
            claimed = public.claim_ready_messages(
                worker_id="worker:skip",
                now=datetime(2026, 9, 2, 12, tzinfo=UTC),
                lease_seconds=60,
                limit=1,
            )
            elapsed = monotonic() - started
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout TO DEFAULT")
            release.set()
            thread.join(timeout=5)

        self.assertEqual(thread_errors, [])
        self.assertEqual(claimed, [])
        self.assertLess(elapsed, 1)
        self.assertEqual(OutboxMessage.objects.get(pk=message_id).state, "pending")

    def test_two_workers_claim_distinct_rows(self):
        public = self.public_module()
        OutboxMessage = self.model_class()
        expected_ids = {self.enqueue(), self.enqueue()}
        barrier = Barrier(3)
        results = []
        errors = []

        def claim(worker_id):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                claimed = public.claim_ready_messages(
                    worker_id=worker_id,
                    now=datetime(2026, 9, 2, 12, tzinfo=UTC),
                    lease_seconds=60,
                    limit=1,
                )
                results.extend(claimed)
            except Exception as error:
                errors.append(error)
            finally:
                close_old_connections()

        threads = [Thread(target=claim, args=(f"worker:{index}",)) for index in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=5)

        self.assertEqual(errors, [])
        self.assertEqual({message.id for message in results}, expected_ids)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(message.attempt_number == 1 for message in results))
        self.assertEqual(OutboxMessage.objects.filter(state="processing").count(), 2)

    def test_expired_lease_reclaim_rejects_stale_attempt_with_reused_worker_id(self):
        public = self.public_module()
        ConcurrentConflict = import_module("open_marketplace.common.errors").ConcurrentConflict
        OutboxMessage = self.model_class()
        base = datetime(2026, 9, 2, 12, tzinfo=UTC)
        message_id = self.enqueue()
        first = public.claim_ready_messages(
            worker_id="worker:reused",
            now=base,
            lease_seconds=10,
            limit=1,
        )[0]

        second = public.claim_ready_messages(
            worker_id="worker:reused",
            now=base + timedelta(seconds=10),
            lease_seconds=10,
            limit=1,
        )[0]

        self.assertEqual(second.id, message_id)
        self.assertEqual(first.attempt_number, 1)
        self.assertEqual(second.attempt_number, 2)
        with self.assertRaises(ConcurrentConflict):
            public.mark_message_succeeded(
                message_id=message_id,
                worker_id="worker:reused",
                attempt_number=first.attempt_number,
                now=base + timedelta(seconds=11),
            )
        public.mark_message_succeeded(
            message_id=message_id,
            worker_id="worker:reused",
            attempt_number=second.attempt_number,
            now=base + timedelta(seconds=11),
        )
        self.assertEqual(OutboxMessage.objects.get(pk=message_id).state, "succeeded")

    def test_concurrent_duplicate_idempotency_key_creates_one_row(self):
        public = self.public_module()
        ConcurrentConflict = import_module("open_marketplace.common.errors").ConcurrentConflict
        OutboxMessage = self.model_class()
        key = f"race:{uuid4()}"
        barrier = Barrier(3)
        ids = []
        errors = []

        def enqueue_duplicate():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                ids.append(
                    public.enqueue_outbox_message(
                        message_type="identity.email_verification",
                        format_version=1,
                        payload={"account_id": str(uuid4()), "token_id": str(uuid4())},
                        delivery={
                            "recipient": "person@example.com",
                            "absolute_token_url": "https://example.com/verify/TOKEN",
                        },
                        idempotency_key=key,
                    )
                )
            except Exception as error:
                errors.append(error)
            finally:
                close_old_connections()

        threads = [Thread(target=enqueue_duplicate) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=5)

        self.assertEqual(len(ids), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ConcurrentConflict)
        self.assertEqual(OutboxMessage.objects.filter(idempotency_key=key).count(), 1)
