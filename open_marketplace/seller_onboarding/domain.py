from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TypeAlias
from uuid import UUID

SellerApplicationState: TypeAlias = Literal[
    "draft",
    "submitted",
    "under_review",
    "changes_requested",
    "approved",
    "rejected",
    "withdrawn",
]

SellerState: TypeAlias = Literal[
    "awaiting_owner_totp",
    "active",
    "suspended",
    "revoked",
]

SellerReviewDecisionValue: TypeAlias = Literal[
    "request_changes",
    "approve",
    "reject",
]


@dataclass(frozen=True, slots=True)
class SellerDraftData:
    business_form: Literal["sole_proprietor", "legal_entity", "self_employed"]
    display_name: str
    official_name: str
    registration_identifier: str
    contact_email: str
    test_data_attested: bool


@dataclass(frozen=True, slots=True)
class SellerApplicationView:
    id: UUID
    applicant_id: UUID
    state: SellerApplicationState
    current_version: int
    reviewer_id: UUID | None
    decision: str | None
    reason: str | None
    created_at: datetime
    submitted_at: datetime | None


@dataclass(frozen=True, slots=True)
class SellerApplicationVersionView:
    application_id: UUID
    version_number: int
    data: SellerDraftData
    submitted_at: datetime


@dataclass(frozen=True, slots=True)
class SellerReviewQuery:
    states: tuple[SellerApplicationState, ...]
    reviewer_id: UUID | None
    limit: int
    cursor: UUID | None


@dataclass(frozen=True, slots=True)
class SellerProfileView:
    id: UUID
    owner_id: UUID
    application_id: UUID
    approved_version: int
    state: SellerState
    restriction_reason: str | None


@dataclass(frozen=True, slots=True)
class SellerProfileQuery:
    state: SellerState | None
    owner_id: UUID | None
    limit: int
    cursor: UUID | None
