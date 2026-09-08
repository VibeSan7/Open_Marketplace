import json

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.mail import EmailMessage

from open_marketplace.common.errors import InputRejected
from open_marketplace.outbox.application import (
    _DELIVERY_SCHEMAS,
    _validate_absolute_token_url,
    _validate_payload,
    _validate_recipient,
)


class UnsupportedMessage(Exception):
    pass


class InvalidMessage(Exception):
    pass


class DeliveryFailed(Exception):
    pass


SMTP_HANDLER_KEYS = frozenset(
    {
        ("identity.email_verification", 1),
        ("identity.password_reset", 1),
        ("identity.mandatory_totp_recovery", 1),
        ("access.staff_invitation", 1),
        ("seller_onboarding.application_decision", 1),
        ("identity.protected_account_change", 1),
    }
)

_SUBJECTS = {
    "identity.email_verification": "Confirm your Open Marketplace email",
    "identity.password_reset": "Reset your Open Marketplace password",
    "identity.mandatory_totp_recovery": "Recover your Open Marketplace TOTP",
    "access.staff_invitation": "Open Marketplace staff invitation",
    "seller_onboarding.application_decision": "Open Marketplace seller application decision",
    "identity.protected_account_change": "Open Marketplace protected account change",
}

_LINK_INTRODUCTIONS = {
    "identity.email_verification": "Confirm your email using this link:",
    "identity.password_reset": "Reset your password using this link:",
    "identity.mandatory_totp_recovery": "Recover your authenticator using this link:",
    "access.staff_invitation": "Accept your staff invitation using this link:",
}


def _validated_payload(message):
    try:
        return _validate_payload(message.message_type, dict(message.payload))
    except (InputRejected, KeyError, TypeError, ValueError):
        raise InvalidMessage from None


def _decrypt_delivery(message):
    schema = _DELIVERY_SCHEMAS[message.message_type]
    if schema is None:
        if message.encrypted_delivery is not None:
            raise InvalidMessage
        return None
    if message.encrypted_delivery is None:
        raise InvalidMessage
    try:
        plaintext = Fernet(settings.OUTBOX_ENCRYPTION_KEY.encode("ascii")).decrypt(
            bytes(message.encrypted_delivery)
        )
        delivery = json.loads(plaintext.decode("utf-8"))
        if not isinstance(delivery, dict) or set(delivery) != set(schema):
            raise InvalidMessage
        if any(not isinstance(value, str) for value in delivery.values()):
            raise InvalidMessage
        _validate_recipient(delivery["recipient"])
        if "absolute_token_url" in schema:
            _validate_absolute_token_url(delivery["absolute_token_url"])
    except (InputRejected, InvalidToken, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        raise InvalidMessage from None
    return delivery


def _email_body(message_type, payload, delivery):
    if "absolute_token_url" in delivery:
        return f"{_LINK_INTRODUCTIONS[message_type]}\n{delivery['absolute_token_url']}\n"
    if message_type == "seller_onboarding.application_decision":
        return f"Your seller application decision is: {payload['decision']}.\n"
    return f"A protected account change was recorded: {payload['change']}.\n"


def _handle_smtp(message):
    payload = _validated_payload(message)
    delivery = _decrypt_delivery(message)
    email = EmailMessage(
        subject=_SUBJECTS[message.message_type],
        body=_email_body(message.message_type, payload, delivery),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[delivery["recipient"]],
        headers={"X-Open-Marketplace-Message-Type": message.message_type},
    )
    if email.send(fail_silently=False) != 1:
        raise DeliveryFailed


def _handle_local(message):
    _validated_payload(message)
    _decrypt_delivery(message)


HANDLER_REGISTRY = {
    ("identity.email_verification", 1): _handle_smtp,
    ("identity.password_reset", 1): _handle_smtp,
    ("identity.mandatory_totp_recovery", 1): _handle_smtp,
    ("access.staff_invitation", 1): _handle_smtp,
    ("seller_onboarding.application_submitted", 1): _handle_local,
    ("seller_onboarding.application_decision", 1): _handle_smtp,
    ("identity.protected_account_change", 1): _handle_smtp,
    ("seller_onboarding.admission_change", 1): _handle_local,
}


def deliver_claimed_message(message):
    handler = HANDLER_REGISTRY.get((message.message_type, message.format_version))
    if handler is None:
        raise UnsupportedMessage
    handler(message)
