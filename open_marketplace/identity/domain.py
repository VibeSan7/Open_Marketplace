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


def canonicalize_email(value: str) -> str:
    trimmed = value.strip()
    validate_email(trimmed)
    return trimmed.casefold()


@dataclass(frozen=True, slots=True)
class NeutralAccepted:
    accepted: Literal[True]


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    id: AccountId
    email: str
    kind: AccountKind
    state: AccountState
    email_verified_at: datetime | None
    totp_enabled: bool
