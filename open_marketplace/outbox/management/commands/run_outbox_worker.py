import logging
import os
import re
import signal
import socket
import time
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from open_marketplace.common.errors import ConcurrentConflict, InvalidState
from open_marketplace.common.types import OperationContext
from open_marketplace.outbox.mail_delivery import (
    HANDLER_REGISTRY,
    SMTP_HANDLER_KEYS,
    InvalidMessage,
    deliver_claimed_message,
)
from open_marketplace.outbox.public import (
    claim_ready_messages,
    mark_message_for_manual_review,
    mark_message_succeeded,
    schedule_message_retry,
)

logger = logging.getLogger("open_marketplace.outbox.worker")


def _build_worker_id():
    host = re.sub(r"[^A-Za-z0-9._:-]", "-", socket.gethostname())
    return f"worker:{host}:{os.getpid()}"[:128]


def _worker_context(now):
    return OperationContext(
        actor_account_id=None,
        session_id=None,
        request_id=uuid4(),
        source="worker",
        source_address=None,
        now=now,
    )


def _mark_manual(message, *, worker_id, now, safe_error):
    mark_message_for_manual_review(
        message_id=message.id,
        worker_id=worker_id,
        attempt_number=message.attempt_number,
        now=now,
        safe_error=safe_error,
        context=_worker_context(now),
    )


def _handle_failure(message, *, worker_id, now, safe_error, terminal=False):
    if terminal or message.attempt_number >= settings.OUTBOX_MAX_ATTEMPTS:
        _mark_manual(
            message,
            worker_id=worker_id,
            now=now,
            safe_error=safe_error,
        )
    else:
        schedule_message_retry(
            message_id=message.id,
            worker_id=worker_id,
            attempt_number=message.attempt_number,
            now=now,
            safe_error=safe_error,
        )
    logger.warning(
        "outbox_delivery_failed message_id=%s error=%s",
        message.id,
        safe_error,
    )


def _process_message(message, *, worker_id):
    key = (message.message_type, message.format_version)
    if key not in HANDLER_REGISTRY:
        _handle_failure(
            message,
            worker_id=worker_id,
            now=timezone.now(),
            safe_error="unsupported_message",
            terminal=True,
        )
        return
    try:
        deliver_claimed_message(message)
    except InvalidMessage:
        _handle_failure(
            message,
            worker_id=worker_id,
            now=timezone.now(),
            safe_error="invalid_message",
            terminal=True,
        )
        return
    except Exception:
        safe_error = "smtp_failure" if key in SMTP_HANDLER_KEYS else "local_handler_failure"
        _handle_failure(
            message,
            worker_id=worker_id,
            now=timezone.now(),
            safe_error=safe_error,
        )
        return
    mark_message_succeeded(
        message_id=message.id,
        worker_id=worker_id,
        attempt_number=message.attempt_number,
        now=timezone.now(),
    )
    logger.info("outbox_delivery_succeeded message_id=%s", message.id)


class Command(BaseCommand):
    help = "Deliver ready outbox messages."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Claim one bounded batch and exit.",
        )

    def _request_stop(self, signum, frame):
        self.stop_requested = True

    def handle(self, *args, **options):
        self.stop_requested = False
        worker_id = _build_worker_id()
        previous_handler = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, self._request_stop)
        try:
            while not self.stop_requested:
                messages = claim_ready_messages(
                    worker_id=worker_id,
                    now=timezone.now(),
                    lease_seconds=settings.OUTBOX_LEASE_SECONDS,
                    limit=settings.OUTBOX_BATCH_SIZE,
                )
                for message in messages:
                    if self.stop_requested:
                        break
                    try:
                        _process_message(message, worker_id=worker_id)
                    except (ConcurrentConflict, InvalidState):
                        logger.warning(
                            "outbox_finalize_failed message_id=%s error=stale_claim",
                            message.id,
                        )
                if options["once"] or self.stop_requested:
                    break
                if not messages:
                    time.sleep(settings.OUTBOX_POLL_SECONDS)
        finally:
            signal.signal(signal.SIGTERM, previous_handler)
