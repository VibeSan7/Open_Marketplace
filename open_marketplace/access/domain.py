from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TypeAlias
from uuid import UUID

StaffRole: TypeAlias = Literal["seller_reviewer", "security_admin"]
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
