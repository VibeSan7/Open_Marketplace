import signal
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from importlib import import_module
from unittest.mock import patch
from uuid import uuid4

from django.core import mail
from django.core.management import call_command, load_command_class
from django.test import override_settings
from django.utils import timezone

from open_marketplace.common.types import AuthorizationDecision
from open_marketplace.outbox.tests.test_outbox import OutboxTestCase


class OutboxWorkerTests(OutboxTestCase):
    worker_now = datetime(2026, 9, 8, 12, tzinfo=UTC)

    def command_module(self):
        return import_module(
            "open_marketplace.outbox.management.commands.run_outbox_worker"
        )

    def raw_message(self, *, message_type, format_version=1):
        return self.model_class().objects.create(
            message_type=message_type,
            format_version=format_version,
            payload={"account_id": str(uuid4()), "token_id": str(uuid4())},
            encrypted_delivery=b"legacy-ciphertext",
            idempotency_key=f"legacy:{uuid4()}",
            created_at=self.worker_now,
            next_attempt_at=self.worker_now,
        )

    def authorize_manual_retry(self, context):
        return lambda received_context, permission: AuthorizationDecision(
            account_id=context.actor_account_id,
            permission=permission,
            effective_roles=("security_admin",),
            scopes=("outbox:state:manual_review",),
            reauthenticated_at=context.now,
        )

    def test_management_command_is_installed_and_exposes_once_mode(self):
        command = load_command_class("open_marketplace.outbox", "run_outbox_worker")
        parser = command.create_parser("manage.py", "run_outbox_worker")

        self.assertIn("--once", parser.format_help())

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        OUTBOX_BATCH_SIZE=1,
    )
    def test_once_claims_one_bounded_batch_and_exits(self):
        first_id = self.enqueue(
            idempotency_key=f"worker:first:{uuid4()}"
        )
        second_id = self.enqueue(
            idempotency_key=f"worker:second:{uuid4()}"
        )
        call_command("run_outbox_worker", "--once")

        states = dict(
            self.model_class()
            .objects.filter(pk__in=(first_id, second_id))
            .values_list("id", "state")
        )
        self.assertEqual(states[first_id], "succeeded")
        self.assertEqual(states[second_id], "pending")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_default_polling_honors_sigterm_between_deliveries(self):
        first_id = self.enqueue(
            delivery={
                "recipient": "first@example.com",
                "absolute_token_url": "https://example.com/first/TOKEN",
            }
        )
        second_id = self.enqueue(
            delivery={
                "recipient": "second@example.com",
                "absolute_token_url": "https://example.com/second/TOKEN",
            }
        )
        command_module = self.command_module()
        real_success = command_module.mark_message_succeeded

        def success_then_stop(**kwargs):
            result = real_success(**kwargs)
            signal.raise_signal(signal.SIGTERM)
            return result

        with patch.object(command_module, "mark_message_succeeded", side_effect=success_then_stop):
            with patch.object(command_module.time, "sleep", return_value=None):
                call_command("run_outbox_worker")

        self.assertEqual(
            self.model_class().objects.get(pk=first_id).state,
            "succeeded",
        )
        self.assertNotEqual(
            self.model_class().objects.get(pk=second_id).state,
            "succeeded",
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["first@example.com"])

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_success_updates_state_and_erases_ciphertext(self):
        message_id = self.enqueue()

        call_command("run_outbox_worker", "--once")

        message = self.model_class().objects.get(pk=message_id)
        self.assertEqual(message.state, "succeeded")
        self.assertIsNone(message.encrypted_delivery)
        self.assertIsNotNone(message.succeeded_at)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_failure_uses_existing_exponential_retry_delay(self):
        message_id = self.enqueue()
        command_module = self.command_module()
        now = timezone.now()

        with patch.object(command_module.timezone, "now", return_value=now):
            with patch(
                "django.core.mail.message.EmailMessage.send",
                side_effect=RuntimeError("smtp failure"),
            ):
                call_command("run_outbox_worker", "--once")

        message = self.model_class().objects.get(pk=message_id)
        self.assertEqual(message.state, "retry_wait")
        self.assertEqual(message.attempts, 1)
        self.assertEqual(
            message.next_attempt_at,
            now + timedelta(seconds=60),
        )
        self.assertEqual(message.last_safe_error, "smtp_failure")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_fifth_failed_claimed_attempt_moves_to_manual_review(self):
        message_id = self.enqueue()
        command_module = self.command_module()
        now = timezone.now()

        for attempt in range(1, 6):
            with self.subTest(attempt=attempt):
                with patch.object(command_module.timezone, "now", return_value=now):
                    with patch(
                        "django.core.mail.message.EmailMessage.send",
                        side_effect=RuntimeError("smtp failure"),
                    ):
                        call_command("run_outbox_worker", "--once")
                message = self.model_class().objects.get(pk=message_id)
                self.assertEqual(message.attempts, attempt)
                if attempt < 5:
                    self.assertEqual(message.state, "retry_wait")
                    self.assertIsNotNone(message.next_attempt_at)
                    now = message.next_attempt_at
                else:
                    self.assertEqual(message.state, "manual_review")

        message.refresh_from_db()
        self.assertEqual(message.attempts, 5)
        self.assertEqual(message.state, "manual_review")
        self.assertEqual(message.last_safe_error, "smtp_failure")

    def test_unknown_type_is_manual_review_with_a_bounded_safe_error(self):
        message = self.raw_message(message_type="legacy.unsupported")

        call_command("run_outbox_worker", "--once")

        message.refresh_from_db()
        self.assertEqual(message.state, "manual_review")
        self.assertRegex(message.last_safe_error, r"^[a-z0-9_.-]{1,128}$")
        self.assertNotIn("legacy.unsupported", message.last_safe_error)

    def test_unknown_version_is_manual_review_without_guessing_a_handler(self):
        message_id = self.enqueue()
        claimed = self.claim(now=timezone.now(), limit=1)[0]
        command_module = self.command_module()

        with patch.object(
            command_module,
            "_build_worker_id",
            return_value="worker:one",
        ):
            with patch.object(
                command_module,
                "claim_ready_messages",
                return_value=[replace(claimed, format_version=2)],
            ):
                call_command("run_outbox_worker", "--once")

        message = self.model_class().objects.get(pk=message_id)
        self.assertEqual(message.state, "manual_review")
        self.assertRegex(message.last_safe_error, r"^[a-z0-9_.-]{1,128}$")
        self.assertNotIn("2", message.last_safe_error)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_crash_after_send_leaves_same_row_reclaimable_after_lease_expiry(self):
        message_id = self.enqueue()
        command_module = self.command_module()
        first_now = timezone.now()
        second_now = first_now + timedelta(seconds=301)

        with patch.object(command_module.timezone, "now", return_value=first_now):
            with patch.object(command_module, "mark_message_succeeded", side_effect=SystemExit):
                with self.assertRaises(SystemExit):
                    call_command("run_outbox_worker", "--once")

        message = self.model_class().objects.get(pk=message_id)
        original_key = message.idempotency_key
        self.assertEqual(message.state, "processing")
        self.assertIsNotNone(message.encrypted_delivery)

        with patch.object(command_module.timezone, "now", return_value=second_now):
            call_command("run_outbox_worker", "--once")

        message.refresh_from_db()
        self.assertEqual(self.model_class().objects.count(), 1)
        self.assertEqual(message.idempotency_key, original_key)
        self.assertEqual(message.state, "succeeded")
        self.assertEqual(len(mail.outbox), 2)

    def test_expired_lease_is_reclaimable_with_a_new_monotonic_attempt(self):
        message_id = self.enqueue()
        first_now = timezone.now()
        first = self.claim(now=first_now, lease_seconds=1, limit=1)[0]
        second = self.claim(
            now=first_now + timedelta(seconds=1),
            lease_seconds=1,
            limit=1,
        )[0]

        self.assertEqual(first.id, message_id)
        self.assertEqual(second.id, message_id)
        self.assertEqual(first.attempt_number, 1)
        self.assertEqual(second.attempt_number, 2)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_active_lease_owned_by_another_worker_is_not_decrypted_or_delivered(self):
        message_id = self.enqueue()
        now = timezone.now()
        self.claim(worker_id="worker:other", now=now, lease_seconds=60, limit=1)

        with patch("cryptography.fernet.Fernet.decrypt") as decrypt:
            call_command("run_outbox_worker", "--once")

        decrypt.assert_not_called()
        message = self.model_class().objects.get(pk=message_id)
        self.assertEqual(message.state, "processing")
        self.assertEqual(getattr(mail, "outbox", []), [])

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_stale_success_finalization_does_not_abort_the_claimed_batch(self):
        first_id = self.enqueue(idempotency_key=f"stale:first:{uuid4()}")
        second_id = self.enqueue(idempotency_key=f"stale:second:{uuid4()}")
        command_module = self.command_module()
        real_success = command_module.mark_message_succeeded
        calls = 0

        def stale_once(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise self.errors_module().ConcurrentConflict("expired lease")
            return real_success(**kwargs)

        with patch.object(
            command_module,
            "mark_message_succeeded",
            side_effect=stale_once,
        ):
            call_command("run_outbox_worker", "--once")

        first = self.model_class().objects.get(pk=first_id)
        second = self.model_class().objects.get(pk=second_id)
        self.assertEqual(first.state, "processing")
        self.assertEqual(second.state, "succeeded")
        self.assertEqual(len(mail.outbox), 2)

    def test_corrupt_ciphertext_moves_registered_message_to_manual_review(self):
        message_id = self.enqueue()
        self.model_class().objects.filter(pk=message_id).update(
            encrypted_delivery=b"corrupt-ciphertext"
        )

        call_command("run_outbox_worker", "--once")

        message = self.model_class().objects.get(pk=message_id)
        self.assertEqual(message.state, "manual_review")
        self.assertEqual(message.last_safe_error, "invalid_message")

    def test_malformed_local_payload_moves_message_to_manual_review(self):
        message_type, payload, delivery = self.message_cases()[6]
        message_id = self.enqueue(
            message_type=message_type,
            payload=payload,
            delivery=delivery,
        )
        self.model_class().objects.filter(pk=message_id).update(
            payload={"application_id": payload["application_id"]}
        )

        call_command("run_outbox_worker", "--once")

        message = self.model_class().objects.get(pk=message_id)
        self.assertEqual(message.state, "manual_review")
        self.assertEqual(message.last_safe_error, "invalid_message")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_authorized_manual_retry_reuses_row_key_and_delivery(self):
        now = timezone.now()
        message_id = self.make_manual(now=now)
        before = self.model_class().objects.get(pk=message_id)
        context = self.context(now=now + timedelta(minutes=1))

        self.public_module().retry_message_from_manual_review(
            message_id=message_id,
            reason="provider checked",
            context=context,
            authorize=self.authorize_manual_retry(context),
        )
        with patch.object(self.command_module().timezone, "now", return_value=context.now):
            call_command("run_outbox_worker", "--once")

        after = self.model_class().objects.get(pk=message_id)
        self.assertEqual(after.id, before.id)
        self.assertEqual(after.idempotency_key, before.idempotency_key)
        self.assertEqual(self.model_class().objects.count(), 1)
        self.assertEqual(after.state, "succeeded")
