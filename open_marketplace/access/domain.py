from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TypeAlias
from uuid import UUID

from open_marketplace.identity.public import TotpSetupView

StaffRole: TypeAlias = Literal["seller_reviewer", "security_admin"]
StaffAcceptanceMode: TypeAlias = Literal[
    "new_service_account", "existing_service_account"
]
PermissionCode: TypeAlias = Literal[
    "seller_application.read",
    "seller_application.review",
    "staff.invite",
    "staff.invitation_revoke",
    "staff.role_revoke",
    "account.read",
    "account.block",
    "account.unblock",
    "identity.mandatory_totp_recover",
    "seller.read",
    "seller.suspend",
    "seller.restore",
    "seller.revoke",
    "audit.read",
    "outbox.manual_retry",
]


@dataclass(frozen=True, slots=True)
class RoleAssignmentView:
    id: UUID
    account_id: UUID
    role: StaffRole
    active_from: datetime
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class StaffAcceptanceSetup:
    acceptance_id: UUID
    account_id: UUID
    mode: StaffAcceptanceMode
    totp_setup: TotpSetupView | None


@dataclass(frozen=True, slots=True)
class StaffAcceptanceResult:
    assignment_id: UUID
    recovery_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StaffInvitationView:
    id: UUID
    email: str
    role: StaffRole
    state: str
    expires_at: datetime
    accepted_at: datetime | None


@dataclass(frozen=True, slots=True)
class StaffInvitationQuery:
    state: str | None
    role: StaffRole | None
    canonical_email: str | None
    limit: int
    cursor: UUID | None
