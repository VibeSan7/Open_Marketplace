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
