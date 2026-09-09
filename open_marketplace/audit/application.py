import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.db.models import Q

from open_marketplace.audit.models import (
    ACTION_MAX_LENGTH,
    EFFECTIVE_ROLE_MAX_LENGTH,
    OBJECT_ID_MAX_LENGTH,
    OBJECT_TYPE_MAX_LENGTH,
    RESULT_MAX_LENGTH,
    AuditEntry,
)
from open_marketplace.common.errors import InputRejected, PermissionDenied
from open_marketplace.common.types import Authorize, OperationContext

AUDIT_REASON_MAX_LENGTH = 1024
AUDIT_VALUE_STRING_MAX_LENGTH = 256
AUDIT_VALUE_INT_MAX = 2**63 - 1
AUDIT_QUERY_MAX_LIMIT = 100

_ALLOWED_PAYLOAD_KEYS = frozenset(
    {
        "kind",
        "state",
        "email_verified",
        "totp_enabled",
        "role",
        "requirement_source",
        "version",
        "decision",
        "session_count",
        "revoked_session_count",
        "message_type",
        "format_version",
        "attempt_number",
        "next_attempt_at",
        "token_purpose",
        "subject_fingerprint",
        "source_fingerprint",
        "expires_at",
    }
)
_SENSITIVE_KEYS = frozenset({"password", "token", "secret", "totp", "recovery_code"})
_FINGERPRINT_KEYS = frozenset({"subject_fingerprint", "source_fingerprint"})
_DATETIME_KEYS = frozenset({"next_attempt_at", "expires_at"})
_SCOPE_FIELDS = frozenset({"actor_id", "action", "object_type", "object_id", "result"})
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class AuditQuery:
    from_at: datetime | None
    to_at: datetime | None
    actor_id: UUID | None
    action: str | None
    object_type: str | None
    object_id: str | None
    result: str | None
    limit: int
    cursor: UUID | None


@dataclass(frozen=True, slots=True)
class AuditEntryView:
    id: UUID
    occurred_at: datetime
    actor_id: UUID | None
    effective_role: str | None
    action: str
    object_type: str
    object_id: str
    result: str
    reason: str | None
    request_id: UUID
    before: dict[str, object]
    after: dict[str, object]
    source: str


def _reject(message):
    raise InputRejected(message)


def _validate_text(value, *, name, max_length, nullable=False):
    if value is None and nullable:
        return
    if not isinstance(value, str):
        _reject(f"{name} must be a string.")
    if len(value) > max_length:
        _reject(f"{name} exceeds its maximum length.")


def _validate_utc_datetime(value, *, name):
    if not isinstance(value, datetime):
        _reject(f"{name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        _reject(f"{name} must be timezone-aware UTC.")


def _validate_iso_utc(value, *, name):
    if not isinstance(value, str):
        _reject(f"{name} must be a UTC ISO-8601 string.")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        _reject(f"{name} must be a UTC ISO-8601 string.")
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        _reject(f"{name} must be a UTC ISO-8601 string.")


def _contains_sensitive_key(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            if isinstance(key, str) and key.casefold() in _SENSITIVE_KEYS:
                return True
            if _contains_sensitive_key(nested):
                return True
    elif isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def _validate_payload(payload, *, name):
    if _contains_sensitive_key(payload):
        _reject(f"{name} contains a sensitive key.")
    if not isinstance(payload, dict):
        _reject(f"{name} must be a dictionary.")

    validated = {}
    for key, value in payload.items():
        if key not in _ALLOWED_PAYLOAD_KEYS:
            _reject(f"{name} contains an unknown key.")
        if value is None or type(value) is bool:
            pass
        elif type(value) is int:
            if not 0 <= value <= AUDIT_VALUE_INT_MAX:
                _reject(f"{name}.{key} integer is out of range.")
        elif type(value) is str:
            if len(value) > AUDIT_VALUE_STRING_MAX_LENGTH:
                _reject(f"{name}.{key} string is too long.")
        else:
            _reject(f"{name}.{key} must be a scalar value.")

        if key in _FINGERPRINT_KEYS and value is not None:
            if not isinstance(value, str) or not _FINGERPRINT_PATTERN.fullmatch(value):
                _reject(f"{name}.{key} must be a lowercase SHA-256 fingerprint.")
        if key in _DATETIME_KEYS and value is not None:
            _validate_iso_utc(value, name=f"{name}.{key}")
        validated[key] = value
    return validated


def _validate_append_input(
    *,
    context,
    action,
    object_type,
    object_id,
    result,
    reason,
    before,
    after,
    effective_role,
):
    if not isinstance(context, OperationContext):
        _reject("context must be an OperationContext.")
    if context.actor_account_id is not None and not isinstance(context.actor_account_id, UUID):
        _reject("context actor must be a UUID or None.")
    if not isinstance(context.request_id, UUID):
        _reject("context request_id must be a UUID.")
    if context.source not in AuditEntry.Source.values:
        _reject("context source is invalid.")
    _validate_utc_datetime(context.now, name="context.now")
    _validate_text(action, name="action", max_length=ACTION_MAX_LENGTH)
    _validate_text(object_type, name="object_type", max_length=OBJECT_TYPE_MAX_LENGTH)
    _validate_text(object_id, name="object_id", max_length=OBJECT_ID_MAX_LENGTH)
    _validate_text(result, name="result", max_length=RESULT_MAX_LENGTH)
    _validate_text(reason, name="reason", max_length=AUDIT_REASON_MAX_LENGTH, nullable=True)
    _validate_text(
        effective_role,
        name="effective_role",
        max_length=EFFECTIVE_ROLE_MAX_LENGTH,
        nullable=True,
    )
    return _validate_payload(before, name="before"), _validate_payload(after, name="after")


def append_audit_entry(
    *,
    context: OperationContext,
    action: str,
    object_type: str,
    object_id: str,
    result: str,
    reason: str | None,
    before: dict[str, object],
    after: dict[str, object],
    effective_role: str | None,
) -> UUID:
    validated_before, validated_after = _validate_append_input(
        context=context,
        action=action,
        object_type=object_type,
        object_id=object_id,
        result=result,
        reason=reason,
        before=before,
        after=after,
        effective_role=effective_role,
    )
    entry = AuditEntry.objects.append(
        occurred_at=context.now,
        actor_id=context.actor_account_id,
        effective_role=effective_role,
        action=action,
        object_type=object_type,
        object_id=object_id,
        result=result,
        reason=reason,
        request_id=context.request_id,
        before=validated_before,
        after=validated_after,
        source=context.source,
    )
    return entry.id


def audit_entry_exists(*, request_id: UUID, action: str) -> bool:
    if not isinstance(request_id, UUID):
        _reject("request_id must be a UUID.")
    _validate_text(action, name="action", max_length=ACTION_MAX_LENGTH)
    return AuditEntry.objects.filter(request_id=request_id, action=action).exists()


def _validate_query(query):
    if not isinstance(query, AuditQuery):
        _reject("query must be an AuditQuery.")
    if type(query.limit) is not int or not 1 <= query.limit <= AUDIT_QUERY_MAX_LIMIT:
        _reject("query limit is out of range.")
    for name in ("from_at", "to_at"):
        value = getattr(query, name)
        if value is not None:
            _validate_utc_datetime(value, name=f"query.{name}")
    if query.from_at is not None and query.to_at is not None and query.from_at > query.to_at:
        _reject("query time range is invalid.")
    if query.actor_id is not None and not isinstance(query.actor_id, UUID):
        _reject("query actor_id must be a UUID.")
    if query.cursor is not None and not isinstance(query.cursor, UUID):
        _reject("query cursor must be a UUID.")
    _validate_text(query.action, name="query.action", max_length=ACTION_MAX_LENGTH, nullable=True)
    _validate_text(
        query.object_type,
        name="query.object_type",
        max_length=OBJECT_TYPE_MAX_LENGTH,
        nullable=True,
    )
    _validate_text(
        query.object_id,
        name="query.object_id",
        max_length=OBJECT_ID_MAX_LENGTH,
        nullable=True,
    )
    _validate_text(query.result, name="query.result", max_length=RESULT_MAX_LENGTH, nullable=True)


def _scope_predicate(scopes):
    if not scopes:
        raise PermissionDenied("Audit access has no scopes.")
    grouped = {}
    for scope in scopes:
        if not isinstance(scope, str):
            raise PermissionDenied("Audit scope is malformed.")
        prefix, separator, remainder = scope.partition(":")
        field, value_separator, value = remainder.partition(":")
        if prefix != "audit" or not separator or not value_separator:
            raise PermissionDenied("Audit scope is malformed.")
        if field not in _SCOPE_FIELDS or not value:
            raise PermissionDenied("Audit scope is malformed.")
        if field == "actor_id":
            try:
                value = UUID(value)
            except ValueError as error:
                raise PermissionDenied("Audit scope is malformed.") from error
        else:
            max_lengths = {
                "action": ACTION_MAX_LENGTH,
                "object_type": OBJECT_TYPE_MAX_LENGTH,
                "object_id": OBJECT_ID_MAX_LENGTH,
                "result": RESULT_MAX_LENGTH,
            }
            if len(value) > max_lengths[field]:
                raise PermissionDenied("Audit scope is malformed.")
        grouped.setdefault(field, set()).add(value)

    predicate = Q()
    for field, values in grouped.items():
        field_predicate = Q()
        for value in values:
            field_predicate |= Q(**{field: value})
        predicate &= field_predicate
    return predicate


def _apply_requested_filters(query, queryset):
    filters = {}
    for field in ("actor_id", "action", "object_type", "object_id", "result"):
        value = getattr(query, field)
        if value is not None:
            filters[field] = value
    if query.from_at is not None:
        filters["occurred_at__gte"] = query.from_at
    if query.to_at is not None:
        filters["occurred_at__lte"] = query.to_at
    return queryset.filter(**filters)


def _to_view(entry):
    return AuditEntryView(
        id=entry.id,
        occurred_at=entry.occurred_at,
        actor_id=entry.actor_id,
        effective_role=entry.effective_role,
        action=entry.action,
        object_type=entry.object_type,
        object_id=entry.object_id,
        result=entry.result,
        reason=entry.reason,
        request_id=entry.request_id,
        before=dict(entry.before),
        after=dict(entry.after),
        source=entry.source,
    )


def query_audit_entries(
    *,
    query: AuditQuery,
    context: OperationContext,
    authorize: Authorize,
) -> tuple[AuditEntryView, ...]:
    _validate_query(query)
    decision = authorize(context, "audit.read")
    if (
        context.actor_account_id is None
        or decision.account_id != context.actor_account_id
        or decision.permission != "audit.read"
    ):
        raise PermissionDenied("Audit authorization decision does not match the request.")

    queryset = AuditEntry.objects.filter(_scope_predicate(decision.scopes))
    queryset = _apply_requested_filters(query, queryset)
    if query.cursor is not None:
        cursor_entry = queryset.filter(pk=query.cursor).first()
        if cursor_entry is None:
            _reject("query cursor is not in the authorized result set.")
        queryset = queryset.filter(
            Q(occurred_at__lt=cursor_entry.occurred_at)
            | Q(occurred_at=cursor_entry.occurred_at, id__lt=cursor_entry.id)
        )

    entries = queryset.order_by("-occurred_at", "-id")[: query.limit]
    return tuple(_to_view(entry) for entry in entries)
