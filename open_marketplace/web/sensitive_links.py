import json
from datetime import timedelta

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.utils import timezone

_INITIAL_TTL = timedelta(minutes=10)
_CONTINUATION_TTL = timedelta(minutes=5)
_SESSION_KEY = "_sensitive_link_exchange"
_ALLOWED_PURPOSES = {
    "email_verification",
    "password_reset",
    "mandatory_totp_recovery",
    "staff_invitation",
}


class SensitiveLinkRejected(Exception):
    pass


def _ensure_session_key(request):
    if request.session.session_key is None:
        request.session.create()
    return request.session.session_key


def _encrypt(request, *, purpose, raw_token, kind, identifier, ttl):
    if purpose not in _ALLOWED_PURPOSES:
        raise ValueError("Unknown sensitive-link purpose.")
    if not isinstance(raw_token, str) or not raw_token or len(raw_token) > 512:
        raise SensitiveLinkRejected()
    session_key = _ensure_session_key(request)
    payload = {
        "purpose": purpose,
        "raw_token": raw_token,
        "kind": kind,
        "identifier": identifier,
        "session_key": session_key,
        "expires_at": (timezone.now() + ttl).timestamp(),
    }
    plaintext = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    request.session[_SESSION_KEY] = Fernet(
        settings.LINK_EXCHANGE_ENCRYPTION_KEY.encode("ascii")
    ).encrypt(plaintext).decode("ascii")


def store_initial(request, *, purpose, raw_token):
    _encrypt(
        request,
        purpose=purpose,
        raw_token=raw_token,
        kind="initial",
        identifier=None,
        ttl=_INITIAL_TTL,
    )


def store_continuation(request, *, purpose, raw_token, identifier):
    _encrypt(
        request,
        purpose=purpose,
        raw_token=raw_token,
        kind="continuation",
        identifier=str(identifier),
        ttl=_CONTINUATION_TTL,
    )


def _consume(request, *, purpose, kind):
    encrypted = request.session.pop(_SESSION_KEY, None)
    if not isinstance(encrypted, str):
        raise SensitiveLinkRejected()
    try:
        plaintext = Fernet(
            settings.LINK_EXCHANGE_ENCRYPTION_KEY.encode("ascii")
        ).decrypt(encrypted.encode("ascii"))
        payload = json.loads(plaintext)
    except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        raise SensitiveLinkRejected() from None
    if (
        not isinstance(payload, dict)
        or payload.get("purpose") != purpose
        or payload.get("kind") != kind
        or payload.get("session_key") != request.session.session_key
        or not isinstance(payload.get("raw_token"), str)
        or not isinstance(payload.get("expires_at"), (int, float))
        or timezone.now().timestamp() >= payload["expires_at"]
    ):
        raise SensitiveLinkRejected()
    return payload


def consume_initial(request, *, purpose):
    payload = _consume(request, purpose=purpose, kind="initial")
    return payload["raw_token"]


def consume_continuation(request, *, purpose):
    payload = _consume(request, purpose=purpose, kind="continuation")
    identifier = payload.get("identifier")
    if not isinstance(identifier, str):
        raise SensitiveLinkRejected()
    return payload["raw_token"], identifier
