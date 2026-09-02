import re
from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction

from open_marketplace.audit.public import append_audit_entry
from open_marketplace.common.crypto import (
    generate_one_time_token,
    hash_one_time_token,
)
from open_marketplace.common.errors import InputRejected
from open_marketplace.common.types import OperationContext
from open_marketplace.identity.domain import NeutralAccepted, canonicalize_email
from open_marketplace.identity.models import Account, OneTimeToken
from open_marketplace.outbox.public import enqueue_outbox_message

_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
_OPERATION_SOURCES = frozenset({"html", "admin", "command", "worker"})
_TOKEN_REJECTED_MESSAGE = "Email verification token is invalid."
_NEUTRAL_ACCEPTED = NeutralAccepted(accepted=True)


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
