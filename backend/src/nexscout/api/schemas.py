"""HTTP request/response schemas (the public API contract)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from nexscout.domain.cases import MAX_CASE_DESCRIPTION, MAX_CASE_NAME, CareerPath, CaseStatus
from nexscout.domain.contact import ContactDetails
from nexscout.domain.preferences import Preferences
from nexscout.domain.profile import FactStatus, ReviewState, Section


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class RegisterRequest(ApiModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)
    display_name: str = Field(max_length=120)
    timezone: str | None = Field(default=None, max_length=64)  # browser's IANA zone


class LoginRequest(ApiModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)
    timezone: str | None = Field(default=None, max_length=64)


class UserOut(ApiModel):
    id: uuid.UUID
    email: str
    display_name: str
    timezone: str


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


class CaseImportOut(ApiModel):
    case_id: uuid.UUID
    case_name: str
    counts: dict[str, int]
    warnings: list[str]


class SkillsAddIn(ApiModel):
    run_id: uuid.UUID = Field(description="The `skill_discovery` run whose suggestions these are.")
    names: list[str] = Field(min_length=1, max_length=500)


class FactBulkIn(ApiModel):
    action: str = Field(pattern="^(accept|reject|delete|private|shareable)$")
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class FactBulkOut(ApiModel):
    changed: int


class RereadOut(ApiModel):
    removed: int
    created: int


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
    run_id: uuid.UUID  # reading happens in the background; follow this run


class DocumentTextOut(ApiModel):
    id: uuid.UUID
    text: str | None
    page_starts: list[int]


class PreferencesOut(ApiModel):
    data: Preferences
    version: int


class ContactOut(ApiModel):
    data: ContactDetails
    version: int
    suggested: dict[str, str] = Field(
        default_factory=dict,
        description="Details found in the newest CV that differ from the saved ones. Only "
        "suggestions: nothing is saved until the user saves them.",
    )
    suggested_from: str | None = None


class ContactPut(ApiModel):
    version: int = Field(ge=0, description="0 when no contact details have been saved yet.")
    data: dict[str, Any]


class FillOut(ApiModel):
    filled: int
    placeholders_left: int
    current_version: int


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


# ---------------------------------------------------------------- M3: mind map & opportunities
class MindNodeOut(ApiModel):
    key: str
    kind: str
    label: str
    section: str | None
    fact_id: str | None
    status: str | None
    is_private: bool
    evidence_count: int
    start: str | None
    end: str | None
    x: float | None = None
    y: float | None = None
    hidden: bool = False
    label_override: str | None = None


class MindEdgeOut(ApiModel):
    source: str
    target: str
    kind: str
    derived: bool
    basis: str | None


class MindMapOut(ApiModel):
    nodes: list[MindNodeOut]
    edges: list[MindEdgeOut]
    orphaned_overrides: list[str]


class NodeOverrideIn(ApiModel):
    x: float | None = Field(default=None, ge=-1e6, le=1e6)
    y: float | None = Field(default=None, ge=-1e6, le=1e6)
    hidden: bool = False
    label: str | None = Field(default=None, max_length=300)


class SnapshotDiffOut(ApiModel):
    added: list[dict[str, Any]]
    removed: list[dict[str, Any]]
    changed: list[dict[str, Any]]
    unchanged: int


class SourceOut(ApiModel):
    key: str
    name: str
    kinds: list[str]
    enabled: bool
    settings: dict[str, Any]
    is_demo_data: bool
    auth: str
    rate_limit: str
    terms: str
    incremental: str
    pagination: str
    limitations: list[str]
    origin: str = "demo"  # catalog | custom | demo
    provider: str = ""
    category: str = ""
    url: str = ""
    countries: list[str] = Field(default_factory=list)
    last_status: str | None = None
    last_error: str | None = None
    last_count: int | None = None
    last_fetched_at: datetime | None = None


class SourceBulkIn(ApiModel):
    keys: list[str] = Field(min_length=1, max_length=500)
    enabled: bool


class SourceAddIn(ApiModel):
    url: str = Field(min_length=8, max_length=2048)
    name: str = Field(default="", max_length=200)
    kinds: list[str] = Field(default_factory=lambda: ["job"], max_length=2)
    countries: list[str] = Field(default_factory=list, max_length=50)


class SourceAddOut(ApiModel):
    key: str
    provider: str
    name: str
    postings: int | None  # null when not read now (already in the catalog)
    already_in_catalog: bool


class SourceTestOut(ApiModel):
    ok: bool
    error: str | None
    postings: int
    sample: list[str]


class SourceImportIn(ApiModel):
    content: str = Field(min_length=1, max_length=2_000_000)


class SourceImportOut(ApiModel):
    enabled_catalog: list[str]
    added: list[str]
    unsupported: list[dict[str, str]]


class ManualSourceOut(ApiModel):
    name: str
    url: str
    reason: str


class CountryOut(ApiModel):
    code: str
    name: str
    continent: str


class CountryGroupOut(ApiModel):
    key: str
    name: str
    codes: list[str]


class GeoOut(ApiModel):
    countries: list[CountryOut]
    groups: list[CountryGroupOut]


class SourceConfigIn(ApiModel):
    enabled: bool
    settings: dict[str, Any] = Field(default_factory=dict)


class SyncIn(ApiModel):
    sources: list[str] | None = Field(default=None, max_length=20)


class SyncSummaryOut(ApiModel):
    source_key: str
    fetched: int
    new_opportunities: int
    merged_duplicates: int
    updated: int
    unchanged: int
    invalid: int
    new_for_case: int
    skipped_reason: str | None
    merges: list[dict[str, Any]]


class OpportunitySourceOut(ApiModel):
    source_key: str
    source_url: str
    retrieved_at: datetime
    dedup_score: float | None
    dedup_reasons: list[str]


class FactorOut(ApiModel):
    name: str
    weight: int
    points: float
    explanation: str
    fact_ids: list[str]


class MatchGapOut(ApiModel):
    code: str
    severity: str
    message: str


class OpportunityOut(ApiModel):
    id: uuid.UUID
    kind: str
    title: str
    organization_name: str
    status: str
    data: dict[str, Any]
    is_demo_data: bool
    first_seen_at: datetime
    last_seen_at: datetime
    sources: list[OpportunitySourceOut]
    score: int
    eligible: bool
    mode: str
    factors: list[FactorOut]
    gaps: list[MatchGapOut]
    match_status: str
    match_version: int
    matched_at: datetime
    has_description: bool = Field(
        default=True,
        description="False only in list pages, which leave the description out (fetch the "
        "opportunity to read it).",
    )


class OpportunityPageOut(ApiModel):
    items: list[OpportunityOut]
    next_cursor: str | None
    counts: dict[str, int] = Field(description="matches, not_fit, dismissed (same filters)")


class MatchStatusIn(ApiModel):
    status: str = Field(pattern="^(new|seen|shortlisted|dismissed)$")
    version: int = Field(ge=1)


class DedupReportIn(ApiModel):
    kind: str = Field(pattern="^(wrong_merge|missed_duplicate)$")
    other_opportunity_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=2000)


class RunStartedOut(ApiModel):
    run_id: uuid.UUID


class RescoreOut(ApiModel):
    rescored: int
