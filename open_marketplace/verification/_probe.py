"""Shared helpers for the restore probe management commands.

Only Django framework APIs and module ``public.py`` interfaces are used here;
project models are never imported statically or via ``apps.get_model``.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Callable
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.utils import timezone

from open_marketplace.access.public import (
    accept_staff_invitation,
    authorize,
    authorize_read_only,
    begin_staff_invitation_acceptance,
    bootstrap_security_admin,
    invite_staff_member,
)
from open_marketplace.common.types import AuthorizationDecision, OperationContext
from open_marketplace.identity.public import (
    authenticate_account,
    register_account,
    verify_email,
)
from open_marketplace.outbox.public import claim_ready_messages

MARKER_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_EMAIL_DOMAIN = "example.test"


def require_marker(marker: str) -> str:
    if not isinstance(marker, str) or not MARKER_PATTERN.fullmatch(marker):
        raise ValueError("marker must match [A-Za-z0-9_-]{1,64}.")
    return marker


def probe_email(marker: str, kind: str) -> str:
    require_marker(marker)
    return f"{kind}-{marker}@{_EMAIL_DOMAIN}"


def command_context(*, actor_account_id=None, session_id=None, now=None) -> OperationContext:
    return OperationContext(
        actor_account_id=actor_account_id,
        session_id=session_id,
        request_id=uuid4(),
        source="command",
        source_address="127.0.0.1",
        now=now or timezone.now(),
    )


def now_utc() -> datetime:
    return timezone.now().astimezone(UTC)


def claim_token(*, marker: str, expected_type: str) -> str:
    """Claim ready outbox rows and return the raw one-time token from delivery."""
    require_marker(marker)
    claimed = claim_ready_messages(
        worker_id=f"restore-probe:{marker}:{uuid4().hex}",
        now=now_utc(),
        lease_seconds=300,
        limit=100,
    )
    for message in claimed:
        if message.message_type != expected_type or message.encrypted_delivery is None:
            continue
        plaintext = Fernet(settings.OUTBOX_ENCRYPTION_KEY.encode("ascii")).decrypt(
            bytes(message.encrypted_delivery)
        )
        delivery = json.loads(plaintext.decode("utf-8"))
        raw_token = str(delivery["absolute_token_url"]).rstrip("/").rsplit("/", 1)[-1]
        if raw_token:
            return raw_token
    raise RuntimeError(f"restore probe token not found for {expected_type}.")


def create_verified_ordinary_account(*, marker: str) -> UUID:
    """Register and email-verify an ordinary account through public interfaces."""
    email = probe_email(marker, "owner")
    password = f"T3st!{uuid4().hex}"
    anonymous = command_context()
    register_account(email=email, password=password, context=anonymous)
    raw_token = claim_token(marker=marker, expected_type="identity.email_verification")
    return verify_email(raw_token=raw_token, context=command_context())


def accept_staff_invitation_flow(*, marker: str, kind: str, role: str, created_by=None) -> dict[str, UUID]:
    """Bootstrap or invite a staff member and accept the invitation.

    Returns account, role-assignment and authenticated-session identifiers.
    The newly created Django session carries the probe marker so that the
    read-only verify command can locate the restored staff session.
    """
    import pyotp

    email = probe_email(marker, kind)
    password = f"T3st!{uuid4().hex}"
    anonymous = command_context()
    if created_by is None:
        bootstrap_security_admin(email=email, context=anonymous)
    else:
        invite_staff_member(email=email, role=role, context=created_by["context"])
    raw_token = claim_token(marker=marker, expected_type="access.staff_invitation")
    setup = begin_staff_invitation_acceptance(
        raw_token=raw_token,
        password=password,
        context=anonymous,
    )
    totp_code = pyotp.TOTP(setup.totp_setup.manual_secret).now()
    accepted = accept_staff_invitation(
        acceptance_id=setup.acceptance_id,
        raw_token=raw_token,
        totp_code=totp_code,
        context=anonymous,
    )
    session_store = SessionStore()
    session_store.create()
    authentication = authenticate_account(
        email=email,
        password=password,
        second_factor=accepted.recovery_codes[0],
        django_session_key=session_store.session_key,
        device_label="restore-probe",
        context=anonymous,
    )
    session_store["probe_marker"] = marker
    session_store["probe_role"] = role
    session_store["account_id"] = str(authentication.account_id)
    session_store["session_id"] = str(authentication.session_id)
    session_store.save()
    return {
        "account_id": authentication.account_id,
        "session_id": authentication.session_id,
        "context": command_context(
            actor_account_id=authentication.account_id,
            session_id=authentication.session_id,
        ),
    }


def find_probe_session(marker: str, role: str) -> dict[str, UUID]:
    """Find a live restored staff Django session carrying the probe marker.

    Django sessions are framework rows, not project domain models; decoding
    them is the only read-only way for the restore probe to recover the
    authenticated staff session created by the seed command.
    """
    require_marker(marker)
    now = now_utc()
    for django_session in Session.objects.filter(expire_date__gt=now).only(
        "session_key", "session_data"
    ):
        try:
            data = SessionStore().decode(django_session.session_data)
        except Exception:  # noqa: BLE001 - malformed framework rows are skipped
            continue
        if not isinstance(data, dict):
            continue
        if data.get("probe_marker") != marker or data.get("probe_role") != role:
            continue
        account_id = data.get("account_id")
        session_id = data.get("session_id")
        if isinstance(account_id, str) and isinstance(session_id, str):
            return {
                "account_id": UUID(account_id),
                "session_id": UUID(session_id),
            }
    raise RuntimeError("restore probe staff session not found.")


def make_service_authorize(*, read_only: bool = False) -> Callable:
    """Return an authorize callback wired to the selected access check.

    The callback forwards the exact OperationContext it receives, so the
    decision account matches the requesting context as the subject modules
    require. Only restored live staff sessions can pass the access check.
    """

    authorization = authorize_read_only if read_only else authorize

    def authorize_callback(context: OperationContext, permission: str) -> AuthorizationDecision:
        return authorization(context=context, permission=permission)

    return authorize_callback
