import hmac
import math
import re
import unicodedata
from base64 import urlsafe_b64decode
from datetime import datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from uuid import UUID, uuid4

import pyotp
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Q

from open_marketplace.audit.public import append_audit_entry
from open_marketplace.common.crypto import (
    generate_one_time_token,
    hash_one_time_token,
)
from open_marketplace.common.errors import (
    AuthenticationDenied,
    InputRejected,
    InvalidState,
    PermissionDenied,
    RateLimited,
)
from open_marketplace.common.types import Authorize, AuthorizationDecision, OperationContext
from open_marketplace.identity.domain import (
    AccountQuery,
    AccountSnapshot,
    AuthenticationResult,
    NeutralAccepted,
    SessionRevocationReason,
    SessionSecuritySnapshot,
    SessionView,
    ThrottleDecision,
    ThrottleScope,
    TotpSetupView,
    canonicalize_email,
)
from open_marketplace.identity.models import (
    Account,
    AccountSession,
    OneTimeToken,
    RecoveryCode,
    SecurityThrottle,
    TotpCredential,
    TotpRequirement,
    TotpSetup,
)
from open_marketplace.outbox.public import enqueue_outbox_message

_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
_TOTP_CODE_PATTERN = re.compile(r"^[0-9]{6}$")
_RECOVERY_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{22}$")
_OPERATION_SOURCES = frozenset({"html", "admin", "command", "worker"})
_TOKEN_REJECTED_MESSAGE = "Email verification token is invalid."
_PASSWORD_RESET_REJECTED_MESSAGE = "Password reset token is invalid."
_NEUTRAL_ACCEPTED = NeutralAccepted(accepted=True)
_AUTHENTICATION_DENIED_MESSAGE = "Authentication failed."
_SESSION_UNAVAILABLE_MESSAGE = "Session is unavailable."
_DEVICE_LABEL_MAX_LENGTH = 200
_SESSION_KEY_MAX_LENGTH = 40
_TOTP_ISSUER = "Open Marketplace"
_DUMMY_PASSWORD_HASH = make_password(token_urlsafe(32))
_ACCOUNT_ADMIN_REASON_MAX_LENGTH = 1024
_ACCOUNT_QUERY_MAX_LIMIT = 100
_EMAIL_THROTTLE_SCOPES = frozenset(
    {"registration_email", "password_reset_email", "staff_invitation_email"}
)
_RATE_LIMITED_MESSAGE = "Too many requests. Try again later."


def _reject(message):
    raise InputRejected(message)


def _validate_utc(value, *, name):
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != timedelta(0)
    ):
        _reject(f"{name} must be a timezone-aware UTC datetime.")


def _validate_anonymous_context(context):
    if not isinstance(context, OperationContext):
        _reject("context must be an OperationContext.")
    if context.actor_account_id is not None or context.session_id is not None:
        _reject("context must be anonymous.")
    if not isinstance(context.request_id, UUID):
        _reject("context request_id must be a UUID.")
    if context.source not in _OPERATION_SOURCES:
        _reject("context source is invalid.")
    _validate_utc(context.now, name="context.now")


def _canonical_registration_email(email):
    if not isinstance(email, str):
        _reject("email is invalid.")
    try:
        canonical_email = canonicalize_email(email)
    except (AttributeError, DjangoValidationError):
        _reject("email is invalid.")
    if len(canonical_email) > 254:
        _reject("email is invalid.")
    return canonical_email


def _validated_password_hash(password, *, canonical_email):
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        _reject("password does not meet security requirements.")
    candidate = Account(email=canonical_email, kind=Account.Kind.ORDINARY)
    try:
        validate_password(password, user=candidate)
    except DjangoValidationError:
        _reject("password does not meet security requirements.")
    return make_password(password)


def _create_account(canonical_email, encoded_password):
    account = Account(
        email=canonical_email,
        kind=Account.Kind.ORDINARY.value,
        state=Account.State.PENDING_EMAIL_VERIFICATION.value,
    )
    account.password = encoded_password
    account.save(force_insert=True)
    return account


def _lock_or_create_account(canonical_email, encoded_password):
    account = (
        Account.objects.select_for_update()
        .filter(email=canonical_email)
        .first()
    )
    if account is not None:
        return account, False
    try:
        with transaction.atomic():
            account = _create_account(canonical_email, encoded_password)
        return account, True
    except IntegrityError:
        account = Account.objects.select_for_update().get(email=canonical_email)
        return account, False


def _issue_verification_token(*, account, context, action):
    active_tokens = OneTimeToken.objects.select_for_update().filter(
        account=account,
        purpose=OneTimeToken.Purpose.EMAIL_VERIFICATION,
        used_at__isnull=True,
        revoked_at__isnull=True,
        expires_at__gt=context.now,
    )
    active_tokens.update(
        revoked_at=context.now,
        revoked_reason="superseded",
    )
    raw_token, token_digest = generate_one_time_token()
    expires_at = context.now + settings.EMAIL_VERIFICATION_TTL
    token = OneTimeToken.objects.create(
        account=account,
        purpose=OneTimeToken.Purpose.EMAIL_VERIFICATION,
        token_digest=token_digest,
        created_at=context.now,
        expires_at=expires_at,
    )
    after = {
        "kind": Account.Kind.ORDINARY.value,
        "state": Account.State.PENDING_EMAIL_VERIFICATION.value,
        "email_verified": False,
        "token_purpose": OneTimeToken.Purpose.EMAIL_VERIFICATION.value,
        "expires_at": expires_at.isoformat(),
    }
    append_audit_entry(
        context=context,
        action=action,
        object_type="account",
        object_id=str(account.id),
        result="succeeded",
        reason=None,
        before={} if action == "identity.account_registered" else {
            "state": Account.State.PENDING_EMAIL_VERIFICATION.value,
            "email_verified": False,
            "token_purpose": OneTimeToken.Purpose.EMAIL_VERIFICATION.value,
        },
        after=after,
        effective_role=None,
    )
    absolute_token_url = (
        f"{settings.APP_BASE_URL}/identity/verify-email/{raw_token}/"
    )
    enqueue_outbox_message(
        message_type="identity.email_verification",
        format_version=1,
        payload={"account_id": str(account.id), "token_id": str(token.id)},
        delivery={
            "recipient": account.email,
            "absolute_token_url": absolute_token_url,
        },
        idempotency_key=f"identity.email_verification:{token.id}",
    )


def register_account(
    *,
    email: str,
    password: str,
    context: OperationContext,
) -> NeutralAccepted:
    _validate_anonymous_context(context)
    canonical_email = _canonical_registration_email(email)
    encoded_password = _validated_password_hash(
        password,
        canonical_email=canonical_email,
    )
    throttle = check_email_throttle(
        scope=SecurityThrottle.Scope.REGISTRATION_EMAIL,
        email=canonical_email,
        source_address=context.source_address,
        now=context.now,
    )
    if not throttle.allowed:
        return _NEUTRAL_ACCEPTED
    with transaction.atomic():
        account, created = _lock_or_create_account(
            canonical_email,
            encoded_password,
        )
        if created:
            _issue_verification_token(
                account=account,
                context=context,
                action="identity.account_registered",
            )
        elif (
            account.kind == Account.Kind.ORDINARY
            and account.state == Account.State.PENDING_EMAIL_VERIFICATION
        ):
            _issue_verification_token(
                account=account,
                context=context,
                action="identity.email_verification_reissued",
            )
    return _NEUTRAL_ACCEPTED


def _reject_verification_token():
    raise InputRejected(_TOKEN_REJECTED_MESSAGE)


def _validated_token_digest(raw_token):
    if not isinstance(raw_token, str) or not _TOKEN_PATTERN.fullmatch(raw_token):
        _reject_verification_token()
    return hash_one_time_token(raw_token)


def verify_email(
    *,
    raw_token: str,
    context: OperationContext,
) -> UUID:
    _validate_anonymous_context(context)
    token_digest = _validated_token_digest(raw_token)
    candidate = (
        OneTimeToken.objects.filter(
            token_digest=token_digest,
            purpose=OneTimeToken.Purpose.EMAIL_VERIFICATION,
        )
        .values("id", "account_id")
        .first()
    )
    if candidate is None:
        _reject_verification_token()

    with transaction.atomic():
        account = (
            Account.objects.select_for_update()
            .filter(pk=candidate["account_id"])
            .first()
        )
        if account is None:
            _reject_verification_token()
        token = (
            OneTimeToken.objects.select_for_update()
            .filter(
                pk=candidate["id"],
                account_id=account.id,
                token_digest=token_digest,
                purpose=OneTimeToken.Purpose.EMAIL_VERIFICATION,
            )
            .first()
        )
        if (
            token is None
            or token.used_at is not None
            or token.revoked_at is not None
            or context.now >= token.expires_at
            or account.kind != Account.Kind.ORDINARY
            or account.state != Account.State.PENDING_EMAIL_VERIFICATION
        ):
            _reject_verification_token()

        before_version = account.version
        account.state = Account.State.ACTIVE.value
        account.email_verified_at = context.now
        account.version += 1
        account.save(
            update_fields={"state", "email_verified_at", "version", "updated_at"}
        )
        token.used_at = context.now
        token.save(update_fields={"used_at"})
        OneTimeToken.objects.filter(
            account=account,
            purpose=OneTimeToken.Purpose.EMAIL_VERIFICATION,
            used_at__isnull=True,
            revoked_at__isnull=True,
        ).exclude(pk=token.id).update(
            revoked_at=context.now,
            revoked_reason="account_verified",
        )
        append_audit_entry(
            context=context,
            action="identity.email_verified",
            object_type="account",
            object_id=str(account.id),
            result="succeeded",
            reason=None,
            before={
                "state": Account.State.PENDING_EMAIL_VERIFICATION.value,
                "email_verified": False,
                "version": before_version,
                "token_purpose": OneTimeToken.Purpose.EMAIL_VERIFICATION.value,
            },
            after={
                "state": Account.State.ACTIVE.value,
                "email_verified": True,
                "version": account.version,
            },
            effective_role=None,
        )
        return account.id


def _authentication_denied():
    raise AuthenticationDenied(_AUTHENTICATION_DENIED_MESSAGE)


def _session_unavailable():
    raise AuthenticationDenied(_SESSION_UNAVAILABLE_MESSAGE)


def _canonical_login_email(email):
    if not isinstance(email, str) or len(email) > 254:
        return None
    try:
        return canonicalize_email(email)
    except (AttributeError, DjangoValidationError):
        return None


def _fingerprint(scope, value):
    if value is None:
        return None
    if not isinstance(value, str):
        value = "invalid"
    key = urlsafe_b64decode(settings.THROTTLE_HASH_KEY.encode("ascii"))
    return hmac.new(
        key,
        f"{scope}\0{value}".encode("utf-8"),
        sha256,
    ).hexdigest()


def _validated_source_address(source_address):
    if not isinstance(source_address, str) or not source_address.strip():
        _reject("context source_address is required.")
    return source_address


def _throttle_key_hash(scope, key_kind, value):
    key = urlsafe_b64decode(settings.THROTTLE_HASH_KEY.encode("ascii"))
    return hmac.new(
        key,
        f"{scope}\0{key_kind}\0{value}".encode("utf-8"),
        sha256,
    ).hexdigest()


def _validated_throttle_input(*, scope, account_key_hash, source_key_hash, now):
    if scope not in SecurityThrottle.Scope.values:
        _reject("scope is invalid.")
    for value in (account_key_hash, source_key_hash):
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            _reject("throttle key hash is invalid.")
    _validate_utc(now, name="now")


def _throttle_policy(scope):
    if scope == SecurityThrottle.Scope.LOGIN:
        return settings.LOGIN_THROTTLE_THRESHOLD, settings.LOGIN_THROTTLE_WINDOW
    return settings.EMAIL_THROTTLE_LIMIT, settings.EMAIL_THROTTLE_WINDOW


def _retry_after_seconds(rows, now):
    waits = [
        math.ceil((row.blocked_until - now).total_seconds())
        for row in rows
        if row.blocked_until is not None and row.blocked_until > now
    ]
    return max(waits, default=0)


def _reset_expired_throttle(row, *, now, window):
    if now < row.window_started_at + window:
        return
    row.window_started_at = now
    row.allowed_attempt_count = 0
    row.blocked_until = None
    row.save(
        update_fields=("window_started_at", "allowed_attempt_count", "blocked_until")
    )


def _next_blocked_until(row, *, scope, threshold, window, now):
    if row.allowed_attempt_count < threshold:
        return None
    if scope != SecurityThrottle.Scope.LOGIN:
        return row.window_started_at + window
    delay_index = min(
        row.allowed_attempt_count - threshold,
        len(settings.LOGIN_THROTTLE_DELAYS) - 1,
    )
    return now + timedelta(seconds=settings.LOGIN_THROTTLE_DELAYS[delay_index])


def _locked_throttle_rows(*, scope, account_key_hash, source_key_hash, now):
    keys = (
        (SecurityThrottle.KeyKind.ACCOUNT, account_key_hash),
        (SecurityThrottle.KeyKind.SOURCE, source_key_hash),
    )
    for _ in range(2):
        SecurityThrottle.objects.bulk_create(
            tuple(
                SecurityThrottle(
                    scope=scope,
                    key_kind=key_kind,
                    key_hash=key_hash,
                    window_started_at=now,
                )
                for key_kind, key_hash in keys
            ),
            ignore_conflicts=True,
        )
        rows = {
            (row.key_kind, row.key_hash): row
            for row in SecurityThrottle.objects.select_for_update()
            .filter(scope=scope)
            .filter(
                Q(key_kind=keys[0][0], key_hash=keys[0][1])
                | Q(key_kind=keys[1][0], key_hash=keys[1][1])
            )
            .order_by("key_kind")
        }
        if len(rows) == len(keys):
            return tuple(rows[key] for key in keys)
    raise RuntimeError("Security throttle rows could not be locked.")


def check_throttle(
    *,
    scope: ThrottleScope,
    account_key_hash: str,
    source_key_hash: str,
    now: datetime,
) -> ThrottleDecision:
    _validated_throttle_input(
        scope=scope,
        account_key_hash=account_key_hash,
        source_key_hash=source_key_hash,
        now=now,
    )
    threshold, window = _throttle_policy(scope)
    with transaction.atomic():
        rows = _locked_throttle_rows(
            scope=scope,
            account_key_hash=account_key_hash,
            source_key_hash=source_key_hash,
            now=now,
        )
        for row in rows:
            _reset_expired_throttle(row, now=now, window=window)
        retry_after_seconds = _retry_after_seconds(rows, now)
        if retry_after_seconds:
            return ThrottleDecision(
                allowed=False,
                retry_after_seconds=retry_after_seconds,
            )
        for row in rows:
            row.allowed_attempt_count += 1
            row.blocked_until = _next_blocked_until(
                row,
                scope=scope,
                threshold=threshold,
                window=window,
                now=now,
            )
            row.save(update_fields=("allowed_attempt_count", "blocked_until"))
    return ThrottleDecision(allowed=True, retry_after_seconds=0)


def _inspect_throttle(*, scope, account_key_hash, source_key_hash, now):
    _validated_throttle_input(
        scope=scope,
        account_key_hash=account_key_hash,
        source_key_hash=source_key_hash,
        now=now,
    )
    _, window = _throttle_policy(scope)
    rows = []
    with transaction.atomic():
        for key_kind, key_hash in (
            (SecurityThrottle.KeyKind.ACCOUNT, account_key_hash),
            (SecurityThrottle.KeyKind.SOURCE, source_key_hash),
        ):
            row = (
                SecurityThrottle.objects.select_for_update()
                .filter(scope=scope, key_kind=key_kind, key_hash=key_hash)
                .first()
            )
            if row is not None and now < row.window_started_at + window:
                rows.append(row)
    retry_after_seconds = _retry_after_seconds(rows, now)
    return ThrottleDecision(
        allowed=not retry_after_seconds,
        retry_after_seconds=retry_after_seconds,
    )


def check_email_throttle(*, scope, email, source_address, now):
    if scope not in _EMAIL_THROTTLE_SCOPES:
        _reject("scope is invalid.")
    canonical_email = _canonical_registration_email(email)
    source_address = _validated_source_address(source_address)
    return check_throttle(
        scope=scope,
        account_key_hash=_throttle_key_hash(scope, "account", canonical_email),
        source_key_hash=_throttle_key_hash(scope, "source", source_address),
        now=now,
    )


def _raise_rate_limited():
    raise RateLimited(_RATE_LIMITED_MESSAGE)


def _normalized_device_label(device_label):
    if not isinstance(device_label, str):
        _reject("device_label must be a string.")
    without_controls = "".join(
        character
        for character in device_label
        if not unicodedata.category(character).startswith("C")
    )
    normalized = " ".join(without_controls.split()) or "Unknown device"
    return normalized[:_DEVICE_LABEL_MAX_LENGTH]


def _validate_second_factor(second_factor):
    if second_factor is not None and (
        not isinstance(second_factor, str) or len(second_factor) > 64
    ):
        _reject("second_factor is invalid.")


def _lock_fresh_django_session(django_session_key, now):
    if (
        not isinstance(django_session_key, str)
        or not 8 <= len(django_session_key) <= _SESSION_KEY_MAX_LENGTH
    ):
        _reject("Django session key is invalid.")
    django_session = (
        Session.objects.select_for_update()
        .filter(session_key=django_session_key, expire_date__gt=now)
        .first()
    )
    if django_session is None or AccountSession.objects.filter(
        django_session_key=django_session_key
    ).exists():
        _reject("Django session key is invalid.")


def _failed_authentication_audit(*, canonical_email, context):
    append_audit_entry(
        context=context,
        action="identity.authentication_failed",
        object_type="authentication_attempt",
        object_id=str(context.request_id),
        result="failed",
        reason="authentication_failed",
        before={},
        after={
            "subject_fingerprint": _fingerprint(
                "login-subject",
                canonical_email or "invalid",
            ),
            "source_fingerprint": _fingerprint(
                "login-source",
                context.source_address,
            ),
        },
        effective_role=None,
    )


def _failed_mandatory_totp_recovery_audit(*, canonical_email, context):
    append_audit_entry(
        context=context,
        action="identity.mandatory_totp_recovery_failed",
        object_type="authentication_attempt",
        object_id=str(context.request_id),
        result="failed",
        reason="mandatory_totp_recovery_failed",
        before={},
        after={
            "subject_fingerprint": _fingerprint(
                "mandatory-totp-recovery-subject",
                canonical_email or "invalid",
            ),
            "source_fingerprint": _fingerprint(
                "mandatory-totp-recovery-source",
                context.source_address,
            ),
        },
        effective_role=None,
    )


def _authenticated_context(*, account, registry, context):
    return OperationContext(
        actor_account_id=account.id,
        session_id=registry.id,
        request_id=context.request_id,
        source=context.source,
        source_address=context.source_address,
        now=context.now,
    )


def _factor_audit_context(account, context):
    return OperationContext(
        actor_account_id=account.id,
        session_id=context.session_id,
        request_id=context.request_id,
        source=context.source,
        source_address=context.source_address,
        now=context.now,
    )


def _active_totp_credential(account):
    return (
        TotpCredential.objects.select_for_update()
        .filter(account=account, disabled_at__isnull=True)
        .first()
    )


def _has_active_totp_requirement(account):
    return TotpRequirement.objects.select_for_update().filter(
        account=account,
        removed_at__isnull=True,
    ).exists()


def _has_open_mandatory_totp_recovery(account):
    return _has_active_totp_requirement(account) and (
        OneTimeToken.objects.select_for_update().filter(
            account=account,
            purpose=OneTimeToken.Purpose.MANDATORY_TOTP_RECOVERY,
            used_at__isnull=True,
            revoked_at__isnull=True,
        ).exists()
    )


def _decrypt_totp_secret(credential):
    try:
        return Fernet(settings.TOTP_ENCRYPTION_KEY.encode("ascii")).decrypt(
            bytes(credential.encrypted_secret)
        ).decode("ascii")
    except (InvalidToken, UnicodeDecodeError):
        _authentication_denied()


def _accepted_totp_counter(*, secret, code, now, last_accepted_counter):
    if not isinstance(code, str) or not _TOTP_CODE_PATTERN.fullmatch(code):
        return None
    totp = pyotp.TOTP(secret, digits=6, interval=30)
    if not totp.verify(code, for_time=now, valid_window=1):
        return None
    base_counter = totp.timecode(now)
    matching = [
        base_counter + offset
        for offset in (-1, 0, 1)
        if pyotp.utils.strings_equal(totp.at(now, counter_offset=offset), code)
    ]
    if not matching:
        return None
    counter = max(matching)
    if last_accepted_counter is not None and counter <= last_accepted_counter:
        return None
    return counter


def _consume_second_factor(*, account, second_factor, context):
    credential = _active_totp_credential(account)
    if credential is None:
        if _has_open_mandatory_totp_recovery(account):
            _authentication_denied()
        if second_factor is not None:
            _authentication_denied()
        return None
    if not isinstance(second_factor, str):
        _authentication_denied()

    if _RECOVERY_CODE_PATTERN.fullmatch(second_factor):
        recovery = (
            RecoveryCode.objects.select_for_update()
            .filter(
                account=account,
                code_digest=hash_one_time_token(second_factor),
                used_at__isnull=True,
                revoked_at__isnull=True,
            )
            .first()
        )
        if recovery is None:
            _authentication_denied()
        recovery.used_at = context.now
        recovery.save(update_fields={"used_at"})
        append_audit_entry(
            context=_factor_audit_context(account, context),
            action="identity.recovery_code_used",
            object_type="account",
            object_id=str(account.id),
            result="succeeded",
            reason=None,
            before={},
            after={"totp_enabled": True},
            effective_role=None,
        )
        return credential

    counter = _accepted_totp_counter(
        secret=_decrypt_totp_secret(credential),
        code=second_factor,
        now=context.now,
        last_accepted_counter=credential.last_accepted_counter,
    )
    if counter is None:
        _authentication_denied()
    credential.last_accepted_counter = counter
    credential.save(update_fields={"last_accepted_counter"})
    return credential


def authenticate_account(
    *,
    email: str,
    password: str,
    second_factor: str | None,
    django_session_key: str,
    device_label: str,
    context: OperationContext,
) -> AuthenticationResult:
    _validate_anonymous_context(context)
    _validate_second_factor(second_factor)
    canonical_email = _canonical_login_email(email)
    normalized_label = _normalized_device_label(device_label)
    source_address = _validated_source_address(context.source_address)
    account_key_hash = _throttle_key_hash(
        SecurityThrottle.Scope.LOGIN,
        "account",
        canonical_email or "invalid",
    )
    source_key_hash = _throttle_key_hash(
        SecurityThrottle.Scope.LOGIN,
        "source",
        source_address,
    )
    throttle = _inspect_throttle(
        scope=SecurityThrottle.Scope.LOGIN,
        account_key_hash=account_key_hash,
        source_key_hash=source_key_hash,
        now=context.now,
    )
    if not throttle.allowed:
        _raise_rate_limited()
    password_candidate = password if isinstance(password, str) and len(password) <= 128 else ""
    result = None
    rate_limited = False

    with transaction.atomic():
        _lock_fresh_django_session(django_session_key, context.now)
        account = None
        if canonical_email is not None:
            account = (
                Account.objects.select_for_update()
                .filter(email=canonical_email)
                .first()
            )
        if account is None:
            check_password(password_candidate, _DUMMY_PASSWORD_HASH)
            password_matches = False
        else:
            password_matches = account.check_password(password_candidate)

        primary_matches = (
            account is not None
            and password_matches
            and account.state == Account.State.ACTIVE
            and account.email_verified_at is not None
        )
        factor_matches = False
        if primary_matches:
            try:
                _consume_second_factor(
                    account=account,
                    second_factor=second_factor,
                    context=context,
                )
                factor_matches = True
            except AuthenticationDenied:
                pass

        if not primary_matches or not factor_matches:
            _failed_authentication_audit(
                canonical_email=canonical_email,
                context=context,
            )
            throttle = check_throttle(
                scope=SecurityThrottle.Scope.LOGIN,
                account_key_hash=account_key_hash,
                source_key_hash=source_key_hash,
                now=context.now,
            )
            rate_limited = not throttle.allowed
        else:
            ttl = (
                settings.SERVICE_SESSION_ABSOLUTE_TTL
                if account.kind == Account.Kind.SERVICE
                else settings.ORDINARY_SESSION_ABSOLUTE_TTL
            )
            registry = AccountSession.objects.create(
                account=account,
                django_session_key=django_session_key,
                created_at=context.now,
                last_activity_at=context.now,
                absolute_expires_at=context.now + ttl,
                reauthenticated_at=context.now,
                device_label=normalized_label,
            )
            audit_context = _authenticated_context(
                account=account,
                registry=registry,
                context=context,
            )
            append_audit_entry(
                context=audit_context,
                action="identity.authentication_succeeded",
                object_type="account",
                object_id=str(account.id),
                result="succeeded",
                reason=None,
                before={},
                after={"kind": account.kind},
                effective_role=None,
            )
            append_audit_entry(
                context=audit_context,
                action="identity.session_created",
                object_type="session",
                object_id=str(registry.id),
                result="succeeded",
                reason=None,
                before={},
                after={
                    "kind": account.kind,
                    "expires_at": registry.absolute_expires_at.isoformat(),
                },
                effective_role=None,
            )
            result = AuthenticationResult(
                account_id=account.id,
                kind=account.kind,
                authenticated_at=context.now,
                session_id=registry.id,
            )

    if result is None:
        if rate_limited:
            _raise_rate_limited()
        _authentication_denied()
    return result


def _validate_authenticated_context(context):
    if not isinstance(context, OperationContext):
        _reject("context must be an OperationContext.")
    if not isinstance(context.actor_account_id, UUID):
        _reject("context actor_account_id must be a UUID.")
    if not isinstance(context.session_id, UUID):
        _reject("context session_id must be a UUID.")
    if not isinstance(context.request_id, UUID):
        _reject("context request_id must be a UUID.")
    if context.source not in _OPERATION_SOURCES:
        _reject("context source is invalid.")
    _validate_utc(context.now, name="context.now")


def _is_live_session(registry, now):
    if registry.revoked_at is not None or now >= registry.absolute_expires_at:
        return False
    if (
        registry.account.kind == Account.Kind.SERVICE
        and now >= registry.last_activity_at + settings.SERVICE_SESSION_IDLE_TTL
    ):
        return False
    return Session.objects.filter(
        session_key=registry.django_session_key,
        expire_date__gt=now,
    ).exists()


def _current_session(context, *, for_update=False):
    _validate_authenticated_context(context)
    if for_update:
        account = (
            Account.objects.select_for_update()
            .filter(pk=context.actor_account_id)
            .first()
        )
        registry = (
            AccountSession.objects.select_for_update()
            .filter(
                pk=context.session_id,
                account_id=context.actor_account_id,
            )
            .first()
        )
        if registry is not None and account is not None:
            registry.account = account
    else:
        registry = (
            AccountSession.objects.select_related("account")
            .filter(
                pk=context.session_id,
                account_id=context.actor_account_id,
            )
            .first()
        )
    if (
        registry is None
        or registry.account.state != Account.State.ACTIVE
        or not _is_live_session(registry, context.now)
    ):
        _session_unavailable()
    return registry


def _live_sessions_for_account(account, now):
    queryset = AccountSession.objects.filter(
        account=account,
        revoked_at__isnull=True,
        absolute_expires_at__gt=now,
    )
    if account.kind == Account.Kind.SERVICE:
        queryset = queryset.filter(
            last_activity_at__gt=now - settings.SERVICE_SESSION_IDLE_TTL
        )
    return queryset


def _locked_live_session_ids(queryset, now):
    candidates = queryset.select_for_update().select_related("account")
    return [
        registry.id
        for registry in candidates
        if _is_live_session(registry, now)
    ]


def _to_session_view(registry, current_session_id):
    return SessionView(
        id=registry.id,
        created_at=registry.created_at,
        last_activity_at=registry.last_activity_at,
        absolute_expires_at=registry.absolute_expires_at,
        device_label=registry.device_label,
        is_current=registry.id == current_session_id,
        revoked_at=registry.revoked_at,
    )


def list_sessions(*, context: OperationContext) -> tuple[SessionView, ...]:
    current = _current_session(context)
    candidates = _live_sessions_for_account(current.account, context.now).order_by(
        "-last_activity_at",
        "-created_at",
        "-id",
    )
    return tuple(
        _to_session_view(registry, current.id)
        for registry in candidates
        if _is_live_session(registry, context.now)
    )


def _revoke_registry(*, registry, reason, context, action):
    registry.revoked_at = context.now
    registry.revoked_reason = reason
    registry.save(update_fields={"revoked_at", "revoked_reason"})
    append_audit_entry(
        context=context,
        action=action,
        object_type="session",
        object_id=str(registry.id),
        result="succeeded",
        reason=reason,
        before={},
        after={"revoked_session_count": 1},
        effective_role=None,
    )


def revoke_session(*, session_id: UUID, context: OperationContext) -> None:
    if not isinstance(session_id, UUID):
        _reject("session_id must be a UUID.")
    with transaction.atomic():
        current = _current_session(context, for_update=True)
        registry = (
            AccountSession.objects.select_for_update()
            .select_related("account")
            .filter(pk=session_id, account_id=current.account_id)
            .first()
        )
        if registry is None or not _is_live_session(registry, context.now):
            _session_unavailable()
        _revoke_registry(
            registry=registry,
            reason=AccountSession.RevocationReason.USER_REVOKED,
            context=context,
            action="identity.session_revoked",
        )


def log_out_session(*, context: OperationContext) -> None:
    with transaction.atomic():
        current = _current_session(context, for_update=True)
        _revoke_registry(
            registry=current,
            reason=AccountSession.RevocationReason.LOGOUT,
            context=context,
            action="identity.session_logged_out",
        )


def revoke_other_sessions(*, context: OperationContext) -> int:
    with transaction.atomic():
        current = _current_session(context, for_update=True)
        queryset = _live_sessions_for_account(current.account, context.now).exclude(
            pk=current.id
        )
        session_ids = _locked_live_session_ids(queryset, context.now)
        count = AccountSession.objects.filter(pk__in=session_ids).update(
            revoked_at=context.now,
            revoked_reason=AccountSession.RevocationReason.OTHER_SESSIONS_REVOKED,
        )
        append_audit_entry(
            context=context,
            action="identity.sessions_revoked",
            object_type="account",
            object_id=str(current.account_id),
            result="succeeded",
            reason=AccountSession.RevocationReason.OTHER_SESSIONS_REVOKED,
            before={},
            after={"revoked_session_count": count},
            effective_role=None,
        )
        return count


def _revoke_sessions_for_security_event_locked(*, account, reason, context):
    if reason not in AccountSession.RevocationReason.values:
        _reject("reason is invalid.")
    queryset = _live_sessions_for_account(account, context.now)
    session_ids = _locked_live_session_ids(queryset, context.now)
    count = AccountSession.objects.filter(pk__in=session_ids).update(
        revoked_at=context.now,
        revoked_reason=reason,
    )
    append_audit_entry(
        context=context,
        action="identity.sessions_revoked_for_security_event",
        object_type="account",
        object_id=str(account.id),
        result="succeeded",
        reason=reason,
        before={},
        after={"revoked_session_count": count},
        effective_role=None,
    )
    return count


def revoke_sessions_for_security_event(
    *,
    account_id: UUID,
    reason: SessionRevocationReason,
    context: OperationContext,
) -> int:
    if not isinstance(account_id, UUID):
        _reject("account_id must be a UUID.")
    if reason not in AccountSession.RevocationReason.values:
        _reject("reason is invalid.")
    with transaction.atomic():
        _current_session(context, for_update=True)
        account = Account.objects.select_for_update().filter(pk=account_id).first()
        if account is None:
            _session_unavailable()
        return _revoke_sessions_for_security_event_locked(
            account=account,
            reason=reason,
            context=context,
        )


def get_session_security_snapshot(
    *,
    session_id: UUID,
    account_id: UUID,
) -> SessionSecuritySnapshot:
    if not isinstance(session_id, UUID) or not isinstance(account_id, UUID):
        _reject("session identifiers must be UUID values.")
    registry = AccountSession.objects.filter(
        pk=session_id,
        account_id=account_id,
    ).first()
    if registry is None:
        _session_unavailable()
    return SessionSecuritySnapshot(
        id=registry.id,
        account_id=registry.account_id,
        revoked_at=registry.revoked_at,
        absolute_expires_at=registry.absolute_expires_at,
        reauthenticated_at=registry.reauthenticated_at,
    )


def require_live_session_security_snapshot(
    *,
    session_id: UUID,
    account_id: UUID,
    now: datetime,
) -> SessionSecuritySnapshot:
    if not isinstance(session_id, UUID) or not isinstance(account_id, UUID):
        _reject("session identifiers must be UUID values.")
    _validate_utc(now, name="now")
    registry = (
        AccountSession.objects.select_related("account")
        .filter(pk=session_id, account_id=account_id)
        .first()
    )
    if (
        registry is None
        or registry.account.state != Account.State.ACTIVE
        or not _is_live_session(registry, now)
    ):
        _session_unavailable()
    return SessionSecuritySnapshot(
        id=registry.id,
        account_id=registry.account_id,
        revoked_at=registry.revoked_at,
        absolute_expires_at=registry.absolute_expires_at,
        reauthenticated_at=registry.reauthenticated_at,
    )


def _eligible_password_reset_account(account):
    return (
        account is not None
        and account.kind in (Account.Kind.ORDINARY, Account.Kind.SERVICE)
        and account.state in (Account.State.ACTIVE, Account.State.BLOCKED)
        and account.email_verified_at is not None
    )


def _revoke_active_password_reset_tokens(*, account, now, reason, exclude_id=None):
    queryset = OneTimeToken.objects.select_for_update().filter(
        account=account,
        purpose=OneTimeToken.Purpose.PASSWORD_RESET,
        used_at__isnull=True,
        revoked_at__isnull=True,
        expires_at__gt=now,
    )
    if exclude_id is not None:
        queryset = queryset.exclude(pk=exclude_id)
    return queryset.update(revoked_at=now, revoked_reason=reason)


def _enqueue_protected_account_change(*, account, change, context):
    enqueue_outbox_message(
        message_type="identity.protected_account_change",
        format_version=1,
        payload={"account_id": str(account.id), "change": change},
        delivery={"recipient": account.email},
        idempotency_key=(
            f"identity.protected_account_change:{change}:{context.request_id}"
        ),
    )


def _validated_account_admin_reason(reason):
    if not isinstance(reason, str):
        _reject("reason must be a string.")
    normalized = reason.strip()
    if not normalized or len(normalized) > _ACCOUNT_ADMIN_REASON_MAX_LENGTH:
        _reject("reason is invalid.")
    return normalized


def _authorize_security_admin(*, context, authorize, permission):
    _validate_authenticated_context(context)
    if not callable(authorize):
        raise PermissionDenied("Authorization is required.")
    decision = authorize(context=context, permission=permission)
    if (
        not isinstance(decision, AuthorizationDecision)
        or decision.account_id != context.actor_account_id
        or decision.permission != permission
        or "security_admin" not in decision.effective_roles
    ):
        raise PermissionDenied("Authorization decision does not match the request.")
    return decision


def block_account(
    *,
    account_id: UUID,
    reason: str,
    context: OperationContext,
    authorize: Authorize,
) -> None:
    if not isinstance(account_id, UUID):
        _reject("account_id must be a UUID.")
    reason = _validated_account_admin_reason(reason)
    with transaction.atomic():
        decision = _authorize_security_admin(
            context=context,
            authorize=authorize,
            permission="account.block",
        )
        account = Account.objects.select_for_update().filter(pk=account_id).first()
        if account is None or account.state != Account.State.ACTIVE:
            raise InvalidState("Account cannot be blocked from its current state.")
        if account.id == decision.account_id:
            raise InvalidState("A security administrator cannot block their own account.")

        before_version = account.version
        revoked_session_count = _revoke_sessions_for_security_event_locked(
            account=account,
            reason=AccountSession.RevocationReason.ACCOUNT_BLOCKED,
            context=context,
        )
        account.state = Account.State.BLOCKED.value
        account.blocked_at = context.now
        account.blocked_by_id = decision.account_id
        account.block_reason = reason
        account.version += 1
        account.block_audit_id = append_audit_entry(
            context=context,
            action="identity.account_blocked",
            object_type="account",
            object_id=str(account.id),
            result="succeeded",
            reason=reason,
            before={"state": Account.State.ACTIVE.value, "version": before_version},
            after={
                "state": Account.State.BLOCKED.value,
                "version": account.version,
                "revoked_session_count": revoked_session_count,
            },
            effective_role="security_admin",
        )
        account.save(
            update_fields={
                "state",
                "blocked_at",
                "blocked_by_id",
                "block_reason",
                "block_audit_id",
                "version",
                "updated_at",
            }
        )
        _enqueue_protected_account_change(
            account=account,
            change="account_blocked",
            context=context,
        )


def unblock_account(
    *,
    account_id: UUID,
    reason: str,
    context: OperationContext,
    authorize: Authorize,
) -> None:
    if not isinstance(account_id, UUID):
        _reject("account_id must be a UUID.")
    reason = _validated_account_admin_reason(reason)
    with transaction.atomic():
        _authorize_security_admin(
            context=context,
            authorize=authorize,
            permission="account.unblock",
        )
        account = Account.objects.select_for_update().filter(pk=account_id).first()
        if account is None or account.state != Account.State.BLOCKED:
            raise InvalidState("Account cannot be unblocked from its current state.")

        before_version = account.version
        account.state = Account.State.ACTIVE.value
        account.blocked_at = None
        account.blocked_by_id = None
        account.block_reason = None
        account.block_audit_id = None
        account.version += 1
        append_audit_entry(
            context=context,
            action="identity.account_unblocked",
            object_type="account",
            object_id=str(account.id),
            result="succeeded",
            reason=reason,
            before={"state": Account.State.BLOCKED.value, "version": before_version},
            after={"state": Account.State.ACTIVE.value, "version": account.version},
            effective_role="security_admin",
        )
        account.save(
            update_fields={
                "state",
                "blocked_at",
                "blocked_by_id",
                "block_reason",
                "block_audit_id",
                "version",
                "updated_at",
            }
        )
        _enqueue_protected_account_change(
            account=account,
            change="account_unblocked",
            context=context,
        )


def _validated_account_query(query):
    if not isinstance(query, AccountQuery):
        _reject("query must be an AccountQuery.")
    if query.kind is not None and query.kind not in Account.Kind.values:
        _reject("query kind is invalid.")
    if query.state is not None and query.state not in Account.State.values:
        _reject("query state is invalid.")
    if type(query.limit) is not int or not 1 <= query.limit <= _ACCOUNT_QUERY_MAX_LIMIT:
        _reject("query limit is invalid.")
    if query.cursor is not None and not isinstance(query.cursor, UUID):
        _reject("query cursor must be a UUID or None.")
    if query.canonical_email is not None:
        if not isinstance(query.canonical_email, str):
            _reject("query canonical_email is invalid.")
        try:
            canonical = canonicalize_email(query.canonical_email)
        except (AttributeError, DjangoValidationError):
            _reject("query canonical_email is invalid.")
        if canonical != query.canonical_email or len(canonical) > 254:
            _reject("query canonical_email is invalid.")


def query_accounts(
    *,
    query: AccountQuery,
    context: OperationContext,
    authorize: Authorize,
) -> tuple[AccountSnapshot, ...]:
    _validated_account_query(query)
    with transaction.atomic():
        _authorize_security_admin(
            context=context,
            authorize=authorize,
            permission="account.read",
        )
        active_credential = TotpCredential.objects.filter(
            account_id=OuterRef("pk"),
            disabled_at__isnull=True,
        )
        queryset = Account.objects.annotate(
            query_totp_enabled=Exists(active_credential)
        )
        if query.kind is not None:
            queryset = queryset.filter(kind=query.kind)
        if query.state is not None:
            queryset = queryset.filter(state=query.state)
        if query.canonical_email is not None:
            queryset = queryset.filter(email=query.canonical_email)
        if query.cursor is not None:
            queryset = queryset.filter(id__gt=query.cursor)
        accounts = queryset.order_by("id")[: query.limit]
        return tuple(
            AccountSnapshot(
                id=account.id,
                email=account.email,
                kind=account.kind,
                state=account.state,
                email_verified_at=account.email_verified_at,
                totp_enabled=account.query_totp_enabled,
            )
            for account in accounts
        )


def request_password_reset(
    *,
    email: str,
    context: OperationContext,
) -> NeutralAccepted:
    _validate_anonymous_context(context)
    canonical_email = _canonical_registration_email(email)
    throttle = check_email_throttle(
        scope=SecurityThrottle.Scope.PASSWORD_RESET_EMAIL,
        email=canonical_email,
        source_address=context.source_address,
        now=context.now,
    )
    if not throttle.allowed:
        return _NEUTRAL_ACCEPTED
    with transaction.atomic():
        account = (
            Account.objects.select_for_update()
            .filter(email=canonical_email)
            .first()
        )
        if not _eligible_password_reset_account(account):
            return _NEUTRAL_ACCEPTED

        _revoke_active_password_reset_tokens(
            account=account,
            now=context.now,
            reason="superseded",
        )
        raw_token, token_digest = generate_one_time_token()
        expires_at = context.now + settings.PASSWORD_RESET_TTL
        token = OneTimeToken.objects.create(
            account=account,
            purpose=OneTimeToken.Purpose.PASSWORD_RESET,
            token_digest=token_digest,
            created_at=context.now,
            expires_at=expires_at,
        )
        append_audit_entry(
            context=context,
            action="identity.password_reset_requested",
            object_type="account",
            object_id=str(account.id),
            result="succeeded",
            reason=None,
            before={},
            after={
                "token_purpose": OneTimeToken.Purpose.PASSWORD_RESET.value,
                "expires_at": expires_at.isoformat(),
            },
            effective_role=None,
        )
        enqueue_outbox_message(
            message_type="identity.password_reset",
            format_version=1,
            payload={"account_id": str(account.id), "token_id": str(token.id)},
            delivery={
                "recipient": account.email,
                "absolute_token_url": (
                    f"{settings.APP_BASE_URL}/identity/reset-password/{raw_token}/"
                ),
            },
            idempotency_key=f"identity.password_reset:{token.id}",
        )
    return _NEUTRAL_ACCEPTED


def _reject_password_reset_token():
    raise InputRejected(_PASSWORD_RESET_REJECTED_MESSAGE)


def _validated_password_reset_digest(raw_token):
    if not isinstance(raw_token, str) or not _TOKEN_PATTERN.fullmatch(raw_token):
        _reject_password_reset_token()
    return hash_one_time_token(raw_token)


def _validated_new_password_hash(new_password, account):
    if isinstance(new_password, str) and account.check_password(new_password):
        _reject("new password must differ from the current password.")
    return _validated_password_hash(new_password, canonical_email=account.email)


def reset_password(
    *,
    raw_token: str,
    new_password: str,
    context: OperationContext,
) -> None:
    _validate_anonymous_context(context)
    token_digest = _validated_password_reset_digest(raw_token)
    candidate = (
        OneTimeToken.objects.filter(
            token_digest=token_digest,
            purpose=OneTimeToken.Purpose.PASSWORD_RESET,
        )
        .values("id", "account_id")
        .first()
    )
    if candidate is None:
        _reject_password_reset_token()

    with transaction.atomic():
        account = (
            Account.objects.select_for_update()
            .filter(pk=candidate["account_id"])
            .first()
        )
        if not _eligible_password_reset_account(account):
            _reject_password_reset_token()
        token = (
            OneTimeToken.objects.select_for_update()
            .filter(
                pk=candidate["id"],
                account_id=account.id,
                token_digest=token_digest,
                purpose=OneTimeToken.Purpose.PASSWORD_RESET,
            )
            .first()
        )
        if (
            token is None
            or token.used_at is not None
            or token.revoked_at is not None
            or context.now >= token.expires_at
        ):
            _reject_password_reset_token()

        encoded_password = _validated_new_password_hash(new_password, account)
        before_version = account.version
        account.password = encoded_password
        account.version += 1
        account.save(update_fields={"password", "version", "updated_at"})
        token.used_at = context.now
        token.save(update_fields={"used_at"})
        _revoke_active_password_reset_tokens(
            account=account,
            now=context.now,
            reason="password_reset_completed",
            exclude_id=token.id,
        )
        revoked_session_count = _revoke_sessions_for_security_event_locked(
            account=account,
            reason=AccountSession.RevocationReason.PASSWORD_RESET,
            context=context,
        )
        append_audit_entry(
            context=context,
            action="identity.password_reset_completed",
            object_type="account",
            object_id=str(account.id),
            result="succeeded",
            reason=None,
            before={"version": before_version},
            after={
                "version": account.version,
                "token_purpose": OneTimeToken.Purpose.PASSWORD_RESET.value,
                "revoked_session_count": revoked_session_count,
            },
            effective_role=None,
        )
        _enqueue_protected_account_change(
            account=account,
            change="password_reset",
            context=context,
        )


def change_password(
    *,
    current_password: str,
    new_password: str,
    context: OperationContext,
) -> None:
    with transaction.atomic():
        current = _current_session(context, for_update=True)
        account = Account.objects.select_for_update().get(pk=current.account_id)
        password_candidate = (
            current_password
            if isinstance(current_password, str) and len(current_password) <= 128
            else ""
        )
        if not account.check_password(password_candidate):
            _authentication_denied()

        encoded_password = _validated_new_password_hash(new_password, account)
        before_version = account.version
        account.password = encoded_password
        account.version += 1
        account.save(update_fields={"password", "version", "updated_at"})
        _revoke_active_password_reset_tokens(
            account=account,
            now=context.now,
            reason="password_changed",
        )
        revoked_session_count = _revoke_sessions_for_security_event_locked(
            account=account,
            reason=AccountSession.RevocationReason.PASSWORD_CHANGED,
            context=context,
        )
        append_audit_entry(
            context=context,
            action="identity.password_changed",
            object_type="account",
            object_id=str(account.id),
            result="succeeded",
            reason=None,
            before={"version": before_version},
            after={
                "version": account.version,
                "revoked_session_count": revoked_session_count,
            },
            effective_role=None,
        )
        _enqueue_protected_account_change(
            account=account,
            change="password_changed",
            context=context,
        )


def _verify_current_password(account, password):
    candidate = password if isinstance(password, str) and len(password) <= 128 else ""
    if not account.check_password(candidate):
        _authentication_denied()


def _encrypt_totp_secret(secret):
    return Fernet(settings.TOTP_ENCRYPTION_KEY.encode("ascii")).encrypt(
        secret.encode("ascii")
    )


def _generate_recovery_code_set(*, account, now):
    set_id = uuid4()
    codes = tuple(token_urlsafe(16) for _ in range(settings.RECOVERY_CODE_COUNT))
    RecoveryCode.objects.bulk_create(
        RecoveryCode(
            account=account,
            set_id=set_id,
            code_digest=hash_one_time_token(code),
            issued_at=now,
        )
        for code in codes
    )
    return codes


def _revoke_unused_recovery_codes(*, account, now):
    return RecoveryCode.objects.select_for_update().filter(
        account=account,
        used_at__isnull=True,
        revoked_at__isnull=True,
    ).update(revoked_at=now)


def recover_mandatory_totp(
    *,
    account_id: UUID,
    reason: str,
    context: OperationContext,
    authorize: Authorize,
) -> None:
    if not isinstance(account_id, UUID):
        _reject("account_id must be a UUID.")
    reason = _validated_account_admin_reason(reason)
    with transaction.atomic():
        decision = _authorize_security_admin(
            context=context,
            authorize=authorize,
            permission="identity.mandatory_totp_recover",
        )
        account = Account.objects.select_for_update().filter(pk=account_id).first()
        if account is not None and account.id == decision.account_id:
            raise InvalidState(
                "A security administrator cannot recover their own mandatory TOTP."
            )
        if (
            account is None
            or account.state != Account.State.ACTIVE
            or account.email_verified_at is None
        ):
            raise InvalidState("Account is unavailable for mandatory TOTP recovery.")
        has_requirement = TotpRequirement.objects.select_for_update().filter(
            account=account,
            removed_at__isnull=True,
        ).exists()
        credential = _active_totp_credential(account)
        recovery_in_progress = credential is None and (
            TotpCredential.objects.select_for_update().filter(
                account=account,
                disabled_at__isnull=False,
            ).exists()
            and OneTimeToken.objects.select_for_update().filter(
                account=account,
                purpose=OneTimeToken.Purpose.MANDATORY_TOTP_RECOVERY,
                used_at__isnull=True,
            ).exists()
        )
        if not has_requirement or (credential is None and not recovery_in_progress):
            raise InvalidState("Account has no recoverable mandatory TOTP credential.")

        TotpSetup.objects.select_for_update().filter(
            account=account,
            consumed_at__isnull=True,
            invalidated_at__isnull=True,
            expires_at__gt=context.now,
        ).update(invalidated_at=context.now)
        OneTimeToken.objects.select_for_update().filter(
            account=account,
            purpose=OneTimeToken.Purpose.MANDATORY_TOTP_RECOVERY,
            used_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=context.now,
        ).update(revoked_at=context.now, revoked_reason="superseded")
        if credential is not None:
            credential.disabled_at = context.now
            credential.save(update_fields={"disabled_at"})
        _revoke_unused_recovery_codes(account=account, now=context.now)
        revoked_session_count = _revoke_sessions_for_security_event_locked(
            account=account,
            reason=AccountSession.RevocationReason.MANDATORY_TOTP_RECOVERED,
            context=context,
        )

        raw_token, token_digest = generate_one_time_token()
        expires_at = context.now + settings.MANDATORY_TOTP_RECOVERY_TTL
        token = OneTimeToken.objects.create(
            account=account,
            purpose=OneTimeToken.Purpose.MANDATORY_TOTP_RECOVERY,
            token_digest=token_digest,
            created_at=context.now,
            expires_at=expires_at,
        )
        append_audit_entry(
            context=context,
            action="identity.mandatory_totp_recovery_started",
            object_type="account",
            object_id=str(account.id),
            result="succeeded",
            reason=reason,
            before={"totp_enabled": credential is not None},
            after={
                "totp_enabled": False,
                "revoked_session_count": revoked_session_count,
                "token_purpose": OneTimeToken.Purpose.MANDATORY_TOTP_RECOVERY.value,
                "expires_at": expires_at.isoformat(),
            },
            effective_role="security_admin",
        )
        enqueue_outbox_message(
            message_type="identity.mandatory_totp_recovery",
            format_version=1,
            payload={"account_id": str(account.id), "token_id": str(token.id)},
            delivery={
                "recipient": account.email,
                "absolute_token_url": (
                    f"{settings.APP_BASE_URL}/identity/"
                    f"recover-mandatory-totp/{raw_token}/"
                ),
            },
            idempotency_key=f"identity.mandatory_totp_recovery:{token.id}",
        )


def _validated_mandatory_totp_recovery_digest(raw_token):
    if not isinstance(raw_token, str) or not _TOKEN_PATTERN.fullmatch(raw_token):
        _authentication_denied()
    return hash_one_time_token(raw_token)


def _lock_mandatory_totp_recovery_subject(token_digest):
    candidate = OneTimeToken.objects.filter(token_digest=token_digest).values(
        "id",
        "account_id",
    ).first()
    if candidate is None:
        _authentication_denied()
    account = Account.objects.select_for_update().filter(
        pk=candidate["account_id"]
    ).first()
    token = OneTimeToken.objects.select_for_update().filter(
        pk=candidate["id"],
        account=account,
    ).first()
    if account is None or token is None:
        _authentication_denied()
    return account, token


def _require_live_mandatory_totp_recovery(*, account, token, now):
    if (
        account.state != Account.State.ACTIVE
        or account.email_verified_at is None
        or token.purpose != OneTimeToken.Purpose.MANDATORY_TOTP_RECOVERY
        or token.used_at is not None
        or token.revoked_at is not None
        or now >= token.expires_at
        or TotpCredential.objects.select_for_update().filter(
            account=account,
            disabled_at__isnull=True,
        ).exists()
        or not TotpRequirement.objects.select_for_update().filter(
            account=account,
            removed_at__isnull=True,
        ).exists()
    ):
        _authentication_denied()


def _totp_setup_view(*, setup, account, secret):
    totp = pyotp.TOTP(secret, digits=6, interval=30)
    return TotpSetupView(
        setup_id=setup.id,
        manual_secret=secret,
        provisioning_uri=totp.provisioning_uri(
            name=account.email,
            issuer_name=_TOTP_ISSUER,
        ),
        expires_at=setup.expires_at,
    )


def begin_mandatory_totp_recovery(
    *,
    raw_token: str,
    current_password: str,
    context: OperationContext,
) -> TotpSetupView:
    _validate_anonymous_context(context)
    canonical_email = None
    try:
        token_digest = _validated_mandatory_totp_recovery_digest(raw_token)
        with transaction.atomic():
            account, token = _lock_mandatory_totp_recovery_subject(token_digest)
            canonical_email = account.email
            _require_live_mandatory_totp_recovery(
                account=account,
                token=token,
                now=context.now,
            )
            _verify_current_password(account, current_password)
            TotpSetup.objects.select_for_update().filter(
                account=account,
                consumed_at__isnull=True,
                invalidated_at__isnull=True,
                expires_at__gt=context.now,
            ).update(invalidated_at=context.now)
            secret = pyotp.random_base32(length=32)
            setup = TotpSetup.objects.create(
                account=account,
                session=None,
                recovery_token=token,
                encrypted_secret=_encrypt_totp_secret(secret),
                created_at=context.now,
                expires_at=min(
                    context.now + settings.TOTP_SETUP_TTL,
                    token.expires_at,
                ),
            )
            return _totp_setup_view(setup=setup, account=account, secret=secret)
    except AuthenticationDenied:
        _failed_mandatory_totp_recovery_audit(
            canonical_email=canonical_email,
            context=context,
        )
        raise


def complete_mandatory_totp_recovery(
    *,
    raw_token: str,
    setup_id: UUID,
    code: str,
    context: OperationContext,
) -> tuple[str, ...]:
    _validate_anonymous_context(context)
    canonical_email = None
    try:
        if not isinstance(setup_id, UUID):
            _authentication_denied()
        token_digest = _validated_mandatory_totp_recovery_digest(raw_token)
        with transaction.atomic():
            account, token = _lock_mandatory_totp_recovery_subject(token_digest)
            canonical_email = account.email
            _require_live_mandatory_totp_recovery(
                account=account,
                token=token,
                now=context.now,
            )
            setup = TotpSetup.objects.select_for_update().filter(
                pk=setup_id,
                account=account,
                session__isnull=True,
                recovery_token=token,
            ).first()
            if (
                setup is None
                or setup.consumed_at is not None
                or setup.invalidated_at is not None
                or context.now >= setup.expires_at
            ):
                _authentication_denied()
            counter = _accepted_totp_counter(
                secret=_decrypt_totp_secret(setup),
                code=code,
                now=context.now,
                last_accepted_counter=None,
            )
            if counter is None:
                _authentication_denied()

            TotpCredential.objects.create(
                account=account,
                encrypted_secret=setup.encrypted_secret,
                confirmed_at=context.now,
                last_accepted_counter=counter,
            )
            _revoke_unused_recovery_codes(account=account, now=context.now)
            codes = _generate_recovery_code_set(account=account, now=context.now)
            token.used_at = context.now
            token.save(update_fields={"used_at"})
            setup.consumed_at = context.now
            setup.save(update_fields={"consumed_at"})
            TotpSetup.objects.select_for_update().filter(
                account=account,
                consumed_at__isnull=True,
                invalidated_at__isnull=True,
                expires_at__gt=context.now,
            ).exclude(pk=setup.id).update(invalidated_at=context.now)
            append_audit_entry(
                context=context,
                action="identity.mandatory_totp_recovery_completed",
                object_type="account",
                object_id=str(account.id),
                result="succeeded",
                reason=None,
                before={"totp_enabled": False},
                after={"totp_enabled": True},
                effective_role=None,
            )
            _enqueue_protected_account_change(
                account=account,
                change="totp_recovered",
                context=context,
            )
            return codes
    except AuthenticationDenied:
        _failed_mandatory_totp_recovery_audit(
            canonical_email=canonical_email,
            context=context,
        )
        raise


def begin_totp_setup(
    *,
    current_password: str,
    context: OperationContext,
) -> TotpSetupView:
    with transaction.atomic():
        current = _current_session(context, for_update=True)
        account = current.account
        _verify_current_password(account, current_password)
        if _active_totp_credential(account) is not None:
            raise InvalidState("TOTP is already enabled.")
        if _has_open_mandatory_totp_recovery(account):
            _authentication_denied()

        TotpSetup.objects.select_for_update().filter(
            account=account,
            consumed_at__isnull=True,
            invalidated_at__isnull=True,
            expires_at__gt=context.now,
        ).update(invalidated_at=context.now)
        secret = pyotp.random_base32(length=32)
        expires_at = context.now + settings.TOTP_SETUP_TTL
        setup = TotpSetup.objects.create(
            account=account,
            session=current,
            encrypted_secret=_encrypt_totp_secret(secret),
            created_at=context.now,
            expires_at=expires_at,
        )
        totp = pyotp.TOTP(secret, digits=6, interval=30)
        return TotpSetupView(
            setup_id=setup.id,
            manual_secret=secret,
            provisioning_uri=totp.provisioning_uri(
                name=account.email,
                issuer_name=_TOTP_ISSUER,
            ),
            expires_at=expires_at,
        )


def enable_totp(
    *,
    setup_id: UUID,
    code: str,
    context: OperationContext,
) -> tuple[str, ...]:
    if not isinstance(setup_id, UUID):
        _reject("setup_id must be a UUID.")
    with transaction.atomic():
        current = _current_session(context, for_update=True)
        account = current.account
        if _active_totp_credential(account) is not None:
            _authentication_denied()
        if _has_open_mandatory_totp_recovery(account):
            _authentication_denied()
        setup = (
            TotpSetup.objects.select_for_update()
            .filter(
                pk=setup_id,
                account=account,
                session=current,
            )
            .first()
        )
        if (
            setup is None
            or setup.consumed_at is not None
            or setup.invalidated_at is not None
            or context.now >= setup.expires_at
        ):
            _authentication_denied()
        secret = _decrypt_totp_secret(setup)
        counter = _accepted_totp_counter(
            secret=secret,
            code=code,
            now=context.now,
            last_accepted_counter=None,
        )
        if counter is None:
            _authentication_denied()

        credential = TotpCredential.objects.create(
            account=account,
            encrypted_secret=setup.encrypted_secret,
            confirmed_at=context.now,
            last_accepted_counter=counter,
        )
        setup.consumed_at = context.now
        setup.save(update_fields={"consumed_at"})
        codes = _generate_recovery_code_set(account=account, now=context.now)
        current.reauthenticated_at = context.now
        current.save(update_fields={"reauthenticated_at"})
        append_audit_entry(
            context=context,
            action="identity.totp_enabled",
            object_type="account",
            object_id=str(account.id),
            result="succeeded",
            reason=None,
            before={"totp_enabled": False},
            after={"totp_enabled": True},
            effective_role=None,
        )
        append_audit_entry(
            context=context,
            action="identity.recovery_codes_issued",
            object_type="account",
            object_id=str(account.id),
            result="succeeded",
            reason=None,
            before={},
            after={"totp_enabled": True},
            effective_role=None,
        )
        _enqueue_protected_account_change(
            account=account,
            change="totp_enabled",
            context=context,
        )
        return codes


def reauthenticate_session(
    *,
    password: str,
    second_factor: str | None,
    context: OperationContext,
) -> datetime:
    with transaction.atomic():
        current = _current_session(context, for_update=True)
        account = current.account
        _verify_current_password(account, password)
        credential = _consume_second_factor(
            account=account,
            second_factor=second_factor,
            context=context,
        )
        current.reauthenticated_at = context.now
        current.save(update_fields={"reauthenticated_at"})
        append_audit_entry(
            context=context,
            action="identity.session_reauthenticated",
            object_type="session",
            object_id=str(current.id),
            result="succeeded",
            reason=None,
            before={},
            after={"totp_enabled": credential is not None},
            effective_role=None,
        )
        return context.now


def replace_recovery_codes(
    *,
    password: str,
    second_factor: str,
    context: OperationContext,
) -> tuple[str, ...]:
    with transaction.atomic():
        current = _current_session(context, for_update=True)
        account = current.account
        _verify_current_password(account, password)
        credential = _consume_second_factor(
            account=account,
            second_factor=second_factor,
            context=context,
        )
        if credential is None:
            raise InvalidState("TOTP is not enabled.")
        _revoke_unused_recovery_codes(account=account, now=context.now)
        codes = _generate_recovery_code_set(account=account, now=context.now)
        current.reauthenticated_at = context.now
        current.save(update_fields={"reauthenticated_at"})
        append_audit_entry(
            context=context,
            action="identity.recovery_codes_replaced",
            object_type="account",
            object_id=str(account.id),
            result="succeeded",
            reason=None,
            before={"totp_enabled": True},
            after={"totp_enabled": True},
            effective_role=None,
        )
        return codes


def _revoke_other_sessions_for_totp_disable(*, current, context):
    queryset = _live_sessions_for_account(current.account, context.now).exclude(
        pk=current.id
    )
    session_ids = _locked_live_session_ids(queryset, context.now)
    count = AccountSession.objects.filter(pk__in=session_ids).update(
        revoked_at=context.now,
        revoked_reason=AccountSession.RevocationReason.OPTIONAL_TOTP_DISABLED,
    )
    append_audit_entry(
        context=context,
        action="identity.sessions_revoked_for_security_event",
        object_type="account",
        object_id=str(current.account_id),
        result="succeeded",
        reason=AccountSession.RevocationReason.OPTIONAL_TOTP_DISABLED,
        before={},
        after={"revoked_session_count": count},
        effective_role=None,
    )
    return count


def disable_optional_totp(
    *,
    password: str,
    second_factor: str,
    context: OperationContext,
) -> None:
    with transaction.atomic():
        current = _current_session(context, for_update=True)
        account = current.account
        _verify_current_password(account, password)
        credential = _consume_second_factor(
            account=account,
            second_factor=second_factor,
            context=context,
        )
        if credential is None:
            raise InvalidState("TOTP is not enabled.")
        if TotpRequirement.objects.select_for_update().filter(
            account=account,
            removed_at__isnull=True,
        ).exists():
            raise InvalidState("TOTP is required and cannot be disabled.")

        credential.disabled_at = context.now
        credential.save(update_fields={"disabled_at"})
        _revoke_unused_recovery_codes(account=account, now=context.now)
        revoked_session_count = _revoke_other_sessions_for_totp_disable(
            current=current,
            context=context,
        )
        current.reauthenticated_at = context.now
        current.save(update_fields={"reauthenticated_at"})
        append_audit_entry(
            context=context,
            action="identity.totp_disabled",
            object_type="account",
            object_id=str(account.id),
            result="succeeded",
            reason=None,
            before={"totp_enabled": True},
            after={
                "totp_enabled": False,
                "revoked_session_count": revoked_session_count,
            },
            effective_role=None,
        )
        _enqueue_protected_account_change(
            account=account,
            change="totp_disabled",
            context=context,
        )


def _validate_totp_requirement_input(*, account_id, source_type, source_id, context):
    if not isinstance(account_id, UUID):
        _reject("account_id must be a UUID.")
    if source_type not in TotpRequirement.SourceType.values:
        _reject("source_type is invalid.")
    if not isinstance(source_id, UUID):
        _reject("source_id must be a UUID.")
    if not isinstance(context, OperationContext):
        _reject("context must be an OperationContext.")
    if not isinstance(context.request_id, UUID) or context.source not in _OPERATION_SOURCES:
        _reject("context is invalid.")
    _validate_utc(context.now, name="context.now")


def add_totp_requirement(
    *,
    account_id: UUID,
    source_type: str,
    source_id: UUID,
    context: OperationContext,
) -> None:
    _validate_totp_requirement_input(
        account_id=account_id,
        source_type=source_type,
        source_id=source_id,
        context=context,
    )
    with transaction.atomic():
        account = Account.objects.select_for_update().filter(pk=account_id).first()
        if account is None:
            raise InvalidState("Account is unavailable.")
        TotpRequirement.objects.get_or_create(
            account=account,
            source_type=source_type,
            source_id=source_id,
            defaults={"created_at": context.now},
        )


def remove_totp_requirement(
    *,
    account_id: UUID,
    source_type: str,
    source_id: UUID,
    context: OperationContext,
) -> None:
    _validate_totp_requirement_input(
        account_id=account_id,
        source_type=source_type,
        source_id=source_id,
        context=context,
    )
    with transaction.atomic():
        account = Account.objects.select_for_update().filter(pk=account_id).first()
        if account is None:
            raise InvalidState("Account is unavailable.")
        requirement = (
            TotpRequirement.objects.select_for_update()
            .filter(
                account=account,
                source_type=source_type,
                source_id=source_id,
            )
            .first()
        )
        if requirement is not None and requirement.removed_at is None:
            requirement.removed_at = context.now
            requirement.save(update_fields={"removed_at"})


def provision_service_account_for_invitation(
    *,
    email: str,
    password: str,
    invitation_id: UUID,
    context: OperationContext,
) -> tuple[UUID, TotpSetupView | None]:
    if not isinstance(invitation_id, UUID):
        _reject("invitation_id must be a UUID.")
    canonical_email = _canonical_registration_email(email)
    with transaction.atomic():
        account = Account.objects.select_for_update().filter(email=canonical_email).first()
        if account is not None:
            if account.kind != Account.Kind.SERVICE or account.state != Account.State.ACTIVE:
                raise InvalidState("The invitation email belongs to an ordinary account.")
            if account.email_verified_at is None:
                raise InvalidState("The service account is unavailable.")
            if context.actor_account_id is None or context.session_id is None:
                _authentication_denied()
            current = _current_session(context, for_update=True)
            if current.account_id != account.id:
                raise AuthenticationDenied("Authentication failed.")
            _verify_current_password(account, password)
            return account.id, None

        _validate_anonymous_context(context)
        encoded_password = _validated_password_hash(
            password,
            canonical_email=canonical_email,
        )
        account = Account(
            email=canonical_email,
            kind=Account.Kind.SERVICE,
            state=Account.State.ACTIVE,
            email_verified_at=context.now,
        )
        account.password = encoded_password
        account.save(force_insert=True)
        secret = pyotp.random_base32(length=32)
        _, setup_token_digest = generate_one_time_token()
        setup_token = OneTimeToken.objects.create(
            account=account,
            purpose=OneTimeToken.Purpose.MANDATORY_TOTP_RECOVERY,
            token_digest=setup_token_digest,
            created_at=context.now,
            expires_at=context.now + settings.TOTP_SETUP_TTL,
        )
        setup = TotpSetup.objects.create(
            account=account,
            session=None,
            recovery_token=setup_token,
            encrypted_secret=_encrypt_totp_secret(secret),
            created_at=context.now,
            expires_at=context.now + settings.TOTP_SETUP_TTL,
        )
        return account.id, _totp_setup_view(setup=setup, account=account, secret=secret)


def enable_invited_service_totp(
    *,
    account_id: UUID,
    setup_id: UUID | None,
    code: str,
    invitation_id: UUID,
    context: OperationContext,
) -> tuple[str, ...]:
    if not isinstance(account_id, UUID):
        _reject("account_id must be a UUID.")
    if setup_id is not None and not isinstance(setup_id, UUID):
        _reject("setup_id must be a UUID or None.")
    if not isinstance(invitation_id, UUID):
        _reject("invitation_id must be a UUID.")
    with transaction.atomic():
        account = Account.objects.select_for_update().filter(pk=account_id).first()
        if (
            account is None
            or account.kind != Account.Kind.SERVICE
            or account.state != Account.State.ACTIVE
            or account.email_verified_at is None
        ):
            _authentication_denied()
        if setup_id is None:
            _current_session(context, for_update=True)
            credential = _active_totp_credential(account)
            if credential is None:
                _authentication_denied()
            counter = _accepted_totp_counter(
                secret=_decrypt_totp_secret(credential),
                code=code,
                now=context.now,
                last_accepted_counter=credential.last_accepted_counter,
            )
            if counter is None:
                _authentication_denied()
            credential.last_accepted_counter = counter
            credential.save(update_fields={"last_accepted_counter"})
            return ()

        setup = TotpSetup.objects.select_for_update().filter(
            pk=setup_id,
            account_id=account.id,
            session__isnull=True,
            recovery_token__isnull=False,
        ).first()
        if (
            setup is None
            or setup.consumed_at is not None
            or setup.invalidated_at is not None
            or context.now >= setup.expires_at
            or _active_totp_credential(account) is not None
        ):
            _authentication_denied()
        counter = _accepted_totp_counter(
            secret=_decrypt_totp_secret(setup),
            code=code,
            now=context.now,
            last_accepted_counter=None,
        )
        if counter is None:
            _authentication_denied()
        TotpCredential.objects.create(
            account=account,
            encrypted_secret=setup.encrypted_secret,
            confirmed_at=context.now,
            last_accepted_counter=counter,
        )
        setup.consumed_at = context.now
        setup.save(update_fields={"consumed_at"})
        setup.recovery_token.used_at = context.now
        setup.recovery_token.save(update_fields={"used_at"})
        codes = _generate_recovery_code_set(account=account, now=context.now)
        append_audit_entry(
            context=context,
            action="identity.totp_enabled",
            object_type="account",
            object_id=str(account.id),
            result="succeeded",
            reason=None,
            before={"totp_enabled": False},
            after={"totp_enabled": True},
            effective_role=None,
        )
        append_audit_entry(
            context=context,
            action="identity.recovery_codes_issued",
            object_type="account",
            object_id=str(account.id),
            result="succeeded",
            reason=None,
            before={},
            after={"totp_enabled": True},
            effective_role=None,
        )
        _enqueue_protected_account_change(
            account=account,
            change="totp_enabled",
            context=context,
        )
        return codes
