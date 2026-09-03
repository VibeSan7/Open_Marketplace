import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from open_marketplace.audit.public import append_audit_entry
from open_marketplace.common.errors import (
    ConcurrentConflict,
    InputRejected,
    InvalidState,
    PermissionDenied,
)
from open_marketplace.common.types import Authorize, OperationContext
from open_marketplace.outbox.models import (
    IDEMPOTENCY_KEY_MAX_LENGTH,
    SAFE_ERROR_MAX_LENGTH,
    WORKER_ID_MAX_LENGTH,
    OutboxMessage,
)

OutboxState = Literal["pending", "processing", "retry_wait", "succeeded", "manual_review"]
OutboxMessageType = Literal[
    "identity.email_verification",
    "identity.password_reset",
    "identity.mandatory_totp_recovery",
    "access.staff_invitation",
    "seller_onboarding.application_submitted",
    "seller_onboarding.application_decision",
    "identity.protected_account_change",
    "seller_onboarding.admission_change",
]

MAX_AUTOMATIC_ATTEMPTS = 5
MAX_LEASE_SECONDS = 300
MAX_QUERY_LIMIT = 100
MAX_ENCRYPTED_DELIVERY_BYTES = 8192
MANUAL_REASON_MAX_LENGTH = 1024

_MESSAGE_TYPES = frozenset(
    {
        "identity.email_verification",
        "identity.password_reset",
        "identity.mandatory_totp_recovery",
        "access.staff_invitation",
        "seller_onboarding.application_submitted",
        "seller_onboarding.application_decision",
        "identity.protected_account_change",
        "seller_onboarding.admission_change",
    }
)
_PAYLOAD_SCHEMAS = {
    "identity.email_verification": {"account_id": "uuid", "token_id": "uuid"},
    "identity.password_reset": {"account_id": "uuid", "token_id": "uuid"},
    "identity.mandatory_totp_recovery": {
        "account_id": "uuid",
        "token_id": "uuid",
    },
    "access.staff_invitation": {"invitation_id": "uuid", "role": "role"},
    "seller_onboarding.application_submitted": {
        "application_id": "uuid",
        "version_id": "uuid",
    },
    "seller_onboarding.application_decision": {
        "application_id": "uuid",
        "decision": "decision",
    },
    "identity.protected_account_change": {"account_id": "uuid", "change": "change"},
    "seller_onboarding.admission_change": {"seller_id": "uuid", "state": "seller_state"},
}
_DELIVERY_SCHEMAS = {
    "identity.email_verification": frozenset({"recipient", "absolute_token_url"}),
    "identity.password_reset": frozenset({"recipient", "absolute_token_url"}),
    "identity.mandatory_totp_recovery": frozenset(
        {"recipient", "absolute_token_url"}
    ),
    "access.staff_invitation": frozenset({"recipient", "absolute_token_url"}),
    "seller_onboarding.application_submitted": None,
    "seller_onboarding.application_decision": frozenset({"recipient"}),
    "identity.protected_account_change": frozenset({"recipient"}),
    "seller_onboarding.admission_change": None,
}
_ALLOWED_VALUES = {
    "role": frozenset({"seller_reviewer", "security_admin"}),
    "decision": frozenset({"request_changes", "approve", "reject"}),
    "change": frozenset(
        {
            "password_reset",
            "password_changed",
            "totp_enabled",
            "totp_disabled",
            "totp_recovered",
            "account_blocked",
            "account_unblocked",
            "role_changed",
        }
    ),
    "seller_state": frozenset({"awaiting_owner_totp", "active", "suspended", "revoked"}),
}
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_SAFE_ERROR_PATTERN = re.compile(r"^[a-z0-9_.-]{1,128}$")
_SCOPE_FIELDS = frozenset({"state", "message_type", "id"})


@dataclass(frozen=True, slots=True)
class ClaimedMessage:
    id: UUID
    message_type: OutboxMessageType
    format_version: int
    payload: Mapping[str, object]
    encrypted_delivery: bytes | None
    idempotency_key: str
    attempt_number: int


@dataclass(frozen=True, slots=True)
class OutboxQuery:
    state: OutboxState
    message_type: OutboxMessageType | None
    limit: int
    cursor: UUID | None


@dataclass(frozen=True, slots=True)
class OutboxMessageView:
    id: UUID
    message_type: OutboxMessageType
    state: OutboxState
    attempts: int
    next_attempt_at: datetime | None
    last_safe_error: str | None
    created_at: datetime


def _reject(message):
    raise InputRejected(message)


def _validate_utc(value, *, name):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        _reject(f"{name} must be a timezone-aware UTC datetime.")


def _validate_identifier(value, *, name, max_length=128):
    if not isinstance(value, str) or not 1 <= len(value) <= max_length:
        _reject(f"{name} is invalid.")
    if not _IDENTIFIER_PATTERN.fullmatch(value):
        _reject(f"{name} is invalid.")


def _validate_safe_error(value):
    if not isinstance(value, str) or not _SAFE_ERROR_PATTERN.fullmatch(value):
        _reject("safe_error is invalid.")


def _validate_uuid_string(value, *, name):
    if not isinstance(value, str):
        _reject(f"{name} must be a canonical UUID string.")
    try:
        parsed = UUID(value)
    except ValueError:
        _reject(f"{name} must be a canonical UUID string.")
    if str(parsed) != value:
        _reject(f"{name} must be a canonical UUID string.")


def _validate_payload(message_type, payload):
    if not isinstance(payload, dict):
        _reject("payload must be a dictionary.")
    schema = _PAYLOAD_SCHEMAS[message_type]
    if set(payload) != set(schema):
        _reject("payload does not match the message schema.")
    validated = {}
    for key, kind in schema.items():
        value = payload[key]
        if kind == "uuid":
            _validate_uuid_string(value, name=f"payload.{key}")
        else:
            if not isinstance(value, str) or value not in _ALLOWED_VALUES[kind]:
                _reject(f"payload.{key} is invalid.")
        validated[key] = value
    return validated


def _validate_recipient(value):
    if not isinstance(value, str) or value.strip() != value or len(value) > 320:
        _reject("delivery.recipient is invalid.")
    try:
        validate_email(value)
    except DjangoValidationError:
        _reject("delivery.recipient is invalid.")


def _validate_absolute_token_url(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 2048 or value.strip() != value:
        _reject("delivery.absolute_token_url is invalid.")
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError:
        _reject("delivery.absolute_token_url is invalid.")
    authority_is_clean = (
        not parsed.netloc.endswith(":")
        and all(ord(character) >= 33 and character != "\\" for character in parsed.netloc)
    )
    if (
        parsed.geturl() != value
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or not authority_is_clean
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        _reject("delivery.absolute_token_url is invalid.")


def _validate_and_encrypt_delivery(message_type, delivery):
    schema = _DELIVERY_SCHEMAS[message_type]
    if schema is None:
        if delivery is not None:
            _reject("delivery must be None for this message type.")
        return None
    if not isinstance(delivery, dict) or set(delivery) != set(schema):
        _reject("delivery does not match the message schema.")
    _validate_recipient(delivery["recipient"])
    if "absolute_token_url" in schema:
        _validate_absolute_token_url(delivery["absolute_token_url"])
    if any(not isinstance(value, str) for value in delivery.values()):
        _reject("delivery values must be strings.")
    plaintext = json.dumps(
        delivery,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    ciphertext = Fernet(settings.OUTBOX_ENCRYPTION_KEY.encode("ascii")).encrypt(plaintext)
    if len(ciphertext) > MAX_ENCRYPTED_DELIVERY_BYTES:
        _reject("encrypted delivery is too large.")
    return ciphertext


def enqueue_outbox_message(
    *,
    message_type: OutboxMessageType,
    format_version: Literal[1],
    payload: dict[str, object],
    delivery: dict[str, str] | None,
    idempotency_key: str,
) -> UUID:
    if not isinstance(message_type, str) or message_type not in _MESSAGE_TYPES:
        _reject("message_type is unsupported.")
    if type(format_version) is not int or format_version != 1:
        _reject("format_version is unsupported.")
    _validate_identifier(
        idempotency_key,
        name="idempotency_key",
        max_length=IDEMPOTENCY_KEY_MAX_LENGTH,
    )
    validated_payload = _validate_payload(message_type, payload)
    encrypted_delivery = _validate_and_encrypt_delivery(message_type, delivery)
    created_at = timezone.now()
    try:
        with transaction.atomic():
            message = OutboxMessage.objects.create(
                message_type=message_type,
                format_version=format_version,
                payload=validated_payload,
                encrypted_delivery=encrypted_delivery,
                idempotency_key=idempotency_key,
                created_at=created_at,
                next_attempt_at=created_at,
            )
    except IntegrityError:
        raise ConcurrentConflict("The outbox idempotency key already exists.") from None
    return message.id


def _validate_claim_input(*, worker_id, now, lease_seconds, limit):
    _validate_identifier(worker_id, name="worker_id", max_length=WORKER_ID_MAX_LENGTH)
    _validate_utc(now, name="now")
    if type(lease_seconds) is not int or not 1 <= lease_seconds <= MAX_LEASE_SECONDS:
        _reject("lease_seconds is out of range.")
    if type(limit) is not int or not 1 <= limit <= MAX_QUERY_LIMIT:
        _reject("limit is out of range.")


def _to_claimed(message):
    return ClaimedMessage(
        id=message.id,
        message_type=message.message_type,
        format_version=message.format_version,
        payload=MappingProxyType(dict(message.payload)),
        encrypted_delivery=(
            bytes(message.encrypted_delivery)
            if message.encrypted_delivery is not None
            else None
        ),
        idempotency_key=message.idempotency_key,
        attempt_number=message.attempts,
    )


def claim_ready_messages(
    *,
    worker_id: str,
    now: datetime,
    lease_seconds: int,
    limit: int,
) -> list[ClaimedMessage]:
    _validate_claim_input(
        worker_id=worker_id,
        now=now,
        lease_seconds=lease_seconds,
        limit=limit,
    )
    ready = (
        Q(state=OutboxMessage.State.PENDING)
        | Q(
            state=OutboxMessage.State.RETRY_WAIT,
            next_attempt_at__lte=now,
        )
        | Q(
            state=OutboxMessage.State.PROCESSING,
            lease_expires_at__lte=now,
        )
    )
    with transaction.atomic():
        messages = list(
            OutboxMessage.objects.select_for_update(skip_locked=True)
            .filter(ready)
            .order_by("created_at", "id")[:limit]
        )
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        for message in messages:
            message.state = OutboxMessage.State.PROCESSING.value
            message.attempts += 1
            message.next_attempt_at = None
            message.claimed_at = now
            message.leased_by = worker_id
            message.lease_expires_at = lease_expires_at
        if messages:
            OutboxMessage.objects.bulk_update(
                messages,
                (
                    "state",
                    "attempts",
                    "next_attempt_at",
                    "claimed_at",
                    "leased_by",
                    "lease_expires_at",
                ),
            )
        return [_to_claimed(message) for message in messages]


def _validate_transition_input(*, message_id, worker_id, attempt_number, now):
    if not isinstance(message_id, UUID):
        _reject("message_id must be a UUID.")
    _validate_identifier(worker_id, name="worker_id", max_length=WORKER_ID_MAX_LENGTH)
    if type(attempt_number) is not int or attempt_number < 1:
        _reject("attempt_number is invalid.")
    _validate_utc(now, name="now")


def _lock_active_claim(*, message_id, worker_id, attempt_number, now):
    try:
        message = OutboxMessage.objects.select_for_update().get(pk=message_id)
    except OutboxMessage.DoesNotExist:
        raise InvalidState("Outbox message does not exist.") from None
    if message.state != OutboxMessage.State.PROCESSING:
        raise InvalidState("Outbox message is not processing.")
    if (
        message.leased_by != worker_id
        or message.attempts != attempt_number
        or message.lease_expires_at is None
        or message.lease_expires_at <= now
    ):
        raise ConcurrentConflict("The outbox claim is stale or expired.")
    return message


def _clear_claim(message):
    message.claimed_at = None
    message.leased_by = None
    message.lease_expires_at = None


def mark_message_succeeded(
    *,
    message_id: UUID,
    worker_id: str,
    attempt_number: int,
    now: datetime,
) -> None:
    _validate_transition_input(
        message_id=message_id,
        worker_id=worker_id,
        attempt_number=attempt_number,
        now=now,
    )
    with transaction.atomic():
        message = _lock_active_claim(
            message_id=message_id,
            worker_id=worker_id,
            attempt_number=attempt_number,
            now=now,
        )
        message.state = OutboxMessage.State.SUCCEEDED.value
        message.succeeded_at = now
        message.next_attempt_at = None
        message.last_safe_error = None
        message.encrypted_delivery = None
        _clear_claim(message)
        message.save(
            update_fields=(
                "state",
                "succeeded_at",
                "next_attempt_at",
                "last_safe_error",
                "encrypted_delivery",
                "claimed_at",
                "leased_by",
                "lease_expires_at",
            )
        )


def schedule_message_retry(
    *,
    message_id: UUID,
    worker_id: str,
    attempt_number: int,
    now: datetime,
    safe_error: str,
) -> None:
    _validate_transition_input(
        message_id=message_id,
        worker_id=worker_id,
        attempt_number=attempt_number,
        now=now,
    )
    _validate_safe_error(safe_error)
    with transaction.atomic():
        message = _lock_active_claim(
            message_id=message_id,
            worker_id=worker_id,
            attempt_number=attempt_number,
            now=now,
        )
        if attempt_number >= MAX_AUTOMATIC_ATTEMPTS:
            raise InvalidState("Automatic outbox attempts are exhausted.")
        delay_seconds = min(60 * 2 ** (attempt_number - 1), 3600)
        message.state = OutboxMessage.State.RETRY_WAIT.value
        message.next_attempt_at = now + timedelta(seconds=delay_seconds)
        message.last_safe_error = safe_error
        _clear_claim(message)
        message.save(
            update_fields=(
                "state",
                "next_attempt_at",
                "last_safe_error",
                "claimed_at",
                "leased_by",
                "lease_expires_at",
            )
        )


def _validate_context(context):
    if not isinstance(context, OperationContext):
        _reject("context must be an OperationContext.")
    _validate_utc(context.now, name="context.now")


def mark_message_for_manual_review(
    *,
    message_id: UUID,
    worker_id: str,
    attempt_number: int,
    now: datetime,
    safe_error: str,
    context: OperationContext,
) -> None:
    _validate_transition_input(
        message_id=message_id,
        worker_id=worker_id,
        attempt_number=attempt_number,
        now=now,
    )
    _validate_safe_error(safe_error)
    _validate_context(context)
    if context.now != now:
        _reject("context.now must match now.")
    with transaction.atomic():
        message = _lock_active_claim(
            message_id=message_id,
            worker_id=worker_id,
            attempt_number=attempt_number,
            now=now,
        )
        before = {
            "state": message.state,
            "message_type": message.message_type,
            "attempt_number": message.attempts,
        }
        message.state = OutboxMessage.State.MANUAL_REVIEW.value
        message.next_attempt_at = None
        message.last_safe_error = safe_error
        _clear_claim(message)
        message.save(
            update_fields=(
                "state",
                "next_attempt_at",
                "last_safe_error",
                "claimed_at",
                "leased_by",
                "lease_expires_at",
            )
        )
        append_audit_entry(
            context=context,
            action="outbox.manual_review",
            object_type="outbox_message",
            object_id=str(message.id),
            result="succeeded",
            reason=safe_error,
            before=before,
            after={
                "state": message.state,
                "message_type": message.message_type,
                "attempt_number": message.attempts,
            },
            effective_role=None,
        )


def _validate_authorization(context, authorize):
    _validate_context(context)
    decision = authorize(context, "outbox.manual_retry")
    if (
        context.actor_account_id is None
        or decision.account_id != context.actor_account_id
        or decision.permission != "outbox.manual_retry"
    ):
        raise PermissionDenied("Outbox authorization decision does not match the request.")
    return decision


def _scope_predicate(scopes):
    if not scopes:
        raise PermissionDenied("Outbox access has no scopes.")
    grouped = {}
    for scope in scopes:
        if not isinstance(scope, str):
            raise PermissionDenied("Outbox scope is malformed.")
        prefix, separator, remainder = scope.partition(":")
        field, value_separator, value = remainder.partition(":")
        if (
            prefix != "outbox"
            or not separator
            or not value_separator
            or field not in _SCOPE_FIELDS
            or not value
        ):
            raise PermissionDenied("Outbox scope is malformed.")
        if field == "state":
            if value != OutboxMessage.State.MANUAL_REVIEW:
                raise PermissionDenied("Outbox scope is malformed.")
        elif field == "message_type":
            if value not in _MESSAGE_TYPES:
                raise PermissionDenied("Outbox scope is malformed.")
        else:
            try:
                value = UUID(value)
            except ValueError as error:
                raise PermissionDenied("Outbox scope is malformed.") from error
        grouped.setdefault(field, set()).add(value)

    predicate = Q()
    for field, values in grouped.items():
        field_predicate = Q()
        for value in values:
            field_predicate |= Q(**{field: value})
        predicate &= field_predicate
    return predicate


def _validate_query(query):
    if not isinstance(query, OutboxQuery):
        _reject("query must be an OutboxQuery.")
    if query.state != OutboxMessage.State.MANUAL_REVIEW:
        _reject("query state must be manual_review.")
    if query.message_type is not None and query.message_type not in _MESSAGE_TYPES:
        _reject("query message_type is unsupported.")
    if type(query.limit) is not int or not 1 <= query.limit <= MAX_QUERY_LIMIT:
        _reject("query limit is out of range.")
    if query.cursor is not None and not isinstance(query.cursor, UUID):
        _reject("query cursor must be a UUID.")


def _to_view(message):
    return OutboxMessageView(
        id=message.id,
        message_type=message.message_type,
        state=message.state,
        attempts=message.attempts,
        next_attempt_at=message.next_attempt_at,
        last_safe_error=message.last_safe_error,
        created_at=message.created_at,
    )


def query_manual_review_messages(
    *,
    query: OutboxQuery,
    context: OperationContext,
    authorize: Authorize,
) -> tuple[OutboxMessageView, ...]:
    _validate_query(query)
    decision = _validate_authorization(context, authorize)
    queryset = OutboxMessage.objects.filter(
        _scope_predicate(decision.scopes),
        state=OutboxMessage.State.MANUAL_REVIEW,
    )
    if query.message_type is not None:
        queryset = queryset.filter(message_type=query.message_type)
    if query.cursor is not None:
        cursor_message = queryset.filter(pk=query.cursor).first()
        if cursor_message is None:
            _reject("query cursor is not in the authorized result set.")
        queryset = queryset.filter(
            Q(created_at__lt=cursor_message.created_at)
            | Q(created_at=cursor_message.created_at, id__lt=cursor_message.id)
        )
    messages = queryset.order_by("-created_at", "-id")[: query.limit]
    return tuple(_to_view(message) for message in messages)


def retry_message_from_manual_review(
    *,
    message_id: UUID,
    reason: str,
    context: OperationContext,
    authorize: Authorize,
) -> None:
    if not isinstance(message_id, UUID):
        _reject("message_id must be a UUID.")
    if not isinstance(reason, str):
        _reject("reason must be a string.")
    normalized_reason = reason.strip()
    if not 1 <= len(normalized_reason) <= MANUAL_REASON_MAX_LENGTH:
        _reject("reason is invalid.")
    decision = _validate_authorization(context, authorize)
    scope = _scope_predicate(decision.scopes)
    with transaction.atomic():
        message = (
            OutboxMessage.objects.select_for_update()
            .filter(scope, pk=message_id)
            .first()
        )
        if message is None:
            raise PermissionDenied("Outbox message is outside the authorized scope.")
        if message.state != OutboxMessage.State.MANUAL_REVIEW:
            raise InvalidState("Outbox message is not in manual review.")
        before = {
            "state": message.state,
            "message_type": message.message_type,
            "attempt_number": message.attempts,
        }
        message.state = OutboxMessage.State.PENDING.value
        message.next_attempt_at = context.now
        message.last_safe_error = None
        message.succeeded_at = None
        _clear_claim(message)
        message.save(
            update_fields=(
                "state",
                "next_attempt_at",
                "last_safe_error",
                "succeeded_at",
                "claimed_at",
                "leased_by",
                "lease_expires_at",
            )
        )
        effective_role = (
            "security_admin"
            if "security_admin" in decision.effective_roles
            else (decision.effective_roles[0] if decision.effective_roles else None)
        )
        append_audit_entry(
            context=context,
            action="outbox.manual_retry",
            object_type="outbox_message",
            object_id=str(message.id),
            result="succeeded",
            reason=normalized_reason,
            before=before,
            after={
                "state": message.state,
                "message_type": message.message_type,
                "attempt_number": message.attempts,
            },
            effective_role=effective_role,
        )
