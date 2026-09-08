from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TypeAlias
from uuid import UUID

from django.core.validators import validate_email

AccountId: TypeAlias = UUID
AccountKind: TypeAlias = Literal["ordinary", "service"]
AccountState: TypeAlias = Literal[
    "pending_email_verification",
    "active",
    "blocked",
]
SessionRevocationReason: TypeAlias = Literal[
    "logout",
    "user_revoked",
    "other_sessions_revoked",
    "password_changed",
    "password_reset",
    "optional_totp_disabled",
    "mandatory_totp_recovered",
    "account_blocked",
    "role_changed",
    "compromised",
]
ThrottleScope: TypeAlias = Literal[
    "login",
    "registration_email",
    "password_reset_email",
    "staff_invitation_email",
]


def canonicalize_email(value: str) -> str:
    trimmed = value.strip()
    validate_email(trimmed)
    return trimmed.casefold()


@dataclass(frozen=True, slots=True)
class NeutralAccepted:
    accepted: Literal[True]


@dataclass(frozen=True, slots=True)
class ThrottleDecision:
    allowed: bool
    retry_after_seconds: int


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    id: AccountId
    email: str
    kind: AccountKind
    state: AccountState
    email_verified_at: datetime | None
    totp_enabled: bool


@dataclass(frozen=True, slots=True)
class AccountQuery:
    kind: AccountKind | None
    state: AccountState | None
    canonical_email: str | None
    limit: int
    cursor: UUID | None


@dataclass(frozen=True, slots=True)
class AuthenticationResult:
    account_id: AccountId
    kind: AccountKind
    authenticated_at: datetime
    session_id: UUID


@dataclass(frozen=True, slots=True)
class SessionView:
    id: UUID
    created_at: datetime
    last_activity_at: datetime
    absolute_expires_at: datetime
    device_label: str
    is_current: bool
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class SessionSecuritySnapshot:
    id: UUID
    account_id: AccountId
    revoked_at: datetime | None
    absolute_expires_at: datetime
    reauthenticated_at: datetime | None


@dataclass(frozen=True, slots=True)
class TotpSetupView:
    setup_id: UUID
    manual_secret: str
    provisioning_uri: str
    expires_at: datetime
