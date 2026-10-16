"""HTTP request/response schemas (the public API contract)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from nexscout.domain.cases import MAX_CASE_DESCRIPTION, MAX_CASE_NAME, CareerPath, CaseStatus
from nexscout.domain.preferences import Preferences
from nexscout.domain.profile import FactStatus, ReviewState, Section


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class RegisterRequest(ApiModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)
    display_name: str = Field(max_length=120)


class LoginRequest(ApiModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)


class UserOut(ApiModel):
    id: uuid.UUID
    email: str
    display_name: str


class SessionOut(ApiModel):
    user: UserOut
    csrf_token: str
    expires_at: datetime


class CaseCreate(ApiModel):
    name: str = Field(min_length=1, max_length=MAX_CASE_NAME)
    description: str | None = Field(default=None, max_length=MAX_CASE_DESCRIPTION)
    career_path: CareerPath = CareerPath.UNDECIDED


class CaseUpdate(ApiModel):
    version: int = Field(ge=1, description="Version you last read (optimistic concurrency).")
    name: str | None = Field(default=None, min_length=1, max_length=MAX_CASE_NAME)
    description: str | None = Field(default=None, max_length=MAX_CASE_DESCRIPTION)
    career_path: CareerPath | None = None
    status: CaseStatus | None = None


class CaseOut(ApiModel):
    id: uuid.UUID
    name: str
    description: str | None
    career_path: CareerPath
    status: CaseStatus
    version: int
    created_at: datetime
    updated_at: datetime


class HealthOut(ApiModel):
    status: str


class ReadyOut(ApiModel):
    status: str
    database: str
    migrations: str


# --------------------------------------------------------------------------- M2: profile
class FactOut(ApiModel):
    id: uuid.UUID
    case_id: uuid.UUID
    section: Section
    data: dict[str, Any]
    label: str
    status: FactStatus
    review_state: ReviewState
    is_private: bool
    meta: dict[str, Any]
    version: int
    evidence_count: int = 0
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None


class FactCreate(ApiModel):
    section: Section
    data: dict[str, Any]
    is_private: bool | None = None


class FactUpdate(ApiModel):
    version: int = Field(ge=1)
    data: dict[str, Any] | None = None
    is_private: bool | None = None
    review_state: ReviewState | None = None


class FactReview(ApiModel):
    accept: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    reject: list[uuid.UUID] = Field(default_factory=list, max_length=500)


class FactReviewOut(ApiModel):
    changed: int


class FactMerge(ApiModel):
    keep_id: uuid.UUID
    merge_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
    data: dict[str, Any] | None = None


class EvidenceOut(ApiModel):
    id: uuid.UUID
    kind: str
    method: str
    document_id: uuid.UUID | None
    page: int | None
    char_start: int | None
    char_end: int | None
    excerpt: str | None
    url: str | None
    created_at: datetime


class GapOut(ApiModel):
    code: str
    section: Section
    message: str
    fact_id: str | None = None


class SnapshotCreate(ApiModel):
    reason: str | None = Field(default=None, max_length=300)


class SnapshotOut(ApiModel):
    id: uuid.UUID
    number: int
    reason: str | None
    created_at: datetime
    fact_count: int


class DocumentOut(ApiModel):
    id: uuid.UUID
    case_id: uuid.UUID
    purpose: str
    file_kind: str
    filename: str
    content_type: str
    size_bytes: int
    origin: str
    parse_status: str
    parse_error: str | None
    page_count: int | None
    extraction_method: str | None
    facts_extracted: int
    created_at: datetime


class UploadOut(ApiModel):
    document: DocumentOut
    facts_created: int


class DocumentTextOut(ApiModel):
    id: uuid.UUID
    text: str | None
    page_starts: list[int]


class PreferencesOut(ApiModel):
    data: Preferences
    version: int


class PreferencesPut(ApiModel):
    version: int = Field(ge=0, description="0 when no preferences have been saved yet.")
    data: dict[str, Any]


class SocialProfileCreate(ApiModel):
    url: str = Field(min_length=3, max_length=2048)
    label: str | None = Field(default=None, max_length=120)


class SocialProfileOut(ApiModel):
    id: uuid.UUID
    kind: str
    url: str
    label: str | None
    created_at: datetime


class AffiliationFields(ApiModel):
    person_name: str | None = Field(default=None, max_length=200)
    organization: str | None = Field(default=None, max_length=300)
    relationship_type: str | None = Field(default=None, max_length=40)
    role: str | None = Field(default=None, max_length=200)
    start_date: str | None = Field(default=None, max_length=10)
    end_date: str | None = Field(default=None, max_length=10)
    status: str | None = Field(default=None, max_length=20)
    evidence: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=2000)
    may_use_in_applications: bool | None = None
    may_use_for_referral: bool | None = None


class AffiliationUpdate(AffiliationFields):
    version: int = Field(ge=1)


class AffiliationOut(ApiModel):
    id: uuid.UUID
    case_id: uuid.UUID
    person_name: str | None
    organization: str
    relationship_type: str
    role: str | None
    start_date: str | None
    end_date: str | None
    status: str
    evidence: str | None
    notes: str | None
    may_use_in_applications: bool
    may_use_for_referral: bool
    version: int
    created_at: datetime
    updated_at: datetime


class AccountDelete(ApiModel):
    password: str = Field(min_length=1, max_length=256)
