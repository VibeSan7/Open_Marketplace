from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, TypeAlias
from uuid import UUID

OperationSource: TypeAlias = Literal["html", "admin", "command", "worker"]


@dataclass(frozen=True, slots=True)
class OperationContext:
    actor_account_id: UUID | None
    session_id: UUID | None
    request_id: UUID
    source: OperationSource
    source_address: str | None
    now: datetime


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    account_id: UUID
    permission: str
    effective_roles: tuple[str, ...]
    scopes: tuple[str, ...]
    reauthenticated_at: datetime | None


class Authorize(Protocol):
    def __call__(
        self,
        context: OperationContext,
        permission: str,
    ) -> AuthorizationDecision: ...
