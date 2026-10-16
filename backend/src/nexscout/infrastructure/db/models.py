"""ORM models. Owned tables carry owner_user_id and are protected by Postgres RLS (ADR-0003)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nexscout.infrastructure.db.base import Base, IdMixin, TimestampMixin, new_id

# Tables listed here get RLS enabled+forced with the owner policy in migrations.
OWNED_TABLES: tuple[str, ...] = (
    "candidate_cases",
    "documents",
    "profile_facts",
    "fact_evidence",
    "profile_snapshots",
    "case_preferences",
    "social_profiles",
    "affiliations",
    "mindmap_overrides",
    "source_configs",
    "sync_checkpoints",
    "opportunity_matches",
    "dedup_reports",
    "workflow_runs",
    "tasks",
    "run_steps",
    "workflow_events",
    "approval_requests",
    "tool_executions",
    "usage_records",
    "secrets",
    "provider_configs",
    "research_sources",
    "research_findings",
    "generated_documents",
    "generated_document_versions",
)
# Tables the worker's system role (BYPASSRLS) needs for queue claiming, leases and recovery.
SYSTEM_TABLES: tuple[str, ...] = ("worker_heartbeats",)
# Shared, non-personal catalog tables (public opportunity data). Not RLS-protected; users reach
# them only through their own opportunity_matches rows.
CATALOG_TABLES: tuple[str, ...] = ("organizations", "opportunities", "opportunity_sources")


def case_fk() -> ForeignKeyConstraint:
    """Composite FK: a child row can only reference a case owned by the same user."""
    return ForeignKeyConstraint(
        ["case_id", "owner_user_id"],
        ["candidate_cases.id", "candidate_cases.owner_user_id"],
        ondelete="CASCADE",
    )


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)

    __table_args__ = (CheckConstraint("email = lower(email)", name="email_lowercase"),)


class AuthSession(IdMixin, Base):
    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(512))


class LoginAttempt(Base):
    """Durable login-attempt log for rate limiting across API replicas."""

    __tablename__ = "login_attempts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    email_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ip: Mapped[str | None] = mapped_column(INET)
    succeeded: Mapped[bool] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_login_attempts_email_created", "email_hash", "created_at"),
        Index("ix_login_attempts_ip_created", "ip", "created_at"),
    )


class CandidateCase(IdMixin, TimestampMixin, Base):
    __tablename__ = "candidate_cases"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    career_path: Mapped[str] = mapped_column(String(20), nullable=False, default="undecided")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("owner_user_id", "name", name="uq_candidate_cases_owner_name"),
        # Target for composite FKs so child rows can never reference another user's case.
        UniqueConstraint("id", "owner_user_id", name="uq_candidate_cases_id_owner"),
        CheckConstraint(
            "career_path IN ('undecided','phd','employment','both')", name="career_path_valid"
        ),
        CheckConstraint("status IN ('active','paused','archived')", name="status_valid"),
        Index("ix_candidate_cases_owner", "owner_user_id"),
    )


class AuditEvent(Base):
    """Append-only security audit trail (not user-facing; not RLS-filtered for inserts)."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(80))
    target_id: Mapped[uuid.UUID | None] = mapped_column()
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ip: Mapped[str | None] = mapped_column(INET)
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_audit_events_actor_created", "actor_user_id", "created_at"),)
    # The app role has INSERT but not SELECT on this table, so never use INSERT ... RETURNING.
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012


# --------------------------------------------------------------------------- M2: profile
class Document(IdMixin, TimestampMixin, Base):
    """An uploaded (or later, generated) file. The original bytes live in the ObjectStore."""

    __tablename__ = "documents"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    file_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    filename: Mapped[str] = mapped_column(String(200), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(200), nullable=False)
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded")
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    parse_error: Mapped[str | None] = mapped_column(String(500))
    page_count: Mapped[int | None] = mapped_column(Integer)
    text_content: Mapped[str | None] = mapped_column(Text)
    page_starts: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    extraction_method: Mapped[str | None] = mapped_column(String(40))
    facts_extracted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        case_fk(),
        ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        UniqueConstraint("id", "owner_user_id", name="uq_documents_id_owner"),
        CheckConstraint("origin IN ('uploaded','generated')", name="origin_valid"),
        CheckConstraint("parse_status IN ('pending','parsed','failed')", name="parse_status_valid"),
        CheckConstraint("file_kind IN ('pdf','docx','markdown','text')", name="file_kind_valid"),
        Index("ix_documents_case", "case_id", "created_at"),
    )


class ProfileFact(IdMixin, TimestampMixin, Base):
    """One structured claim about the candidate. `data` is validated per section (domain)."""

    __tablename__ = "profile_facts"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    section: Mapped[str] = mapped_column(String(30), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    review_state: Mapped[str] = mapped_column(String(20), nullable=False)
    is_private: Mapped[bool] = mapped_column(nullable=False, default=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        case_fk(),
        UniqueConstraint("id", "owner_user_id", name="uq_profile_facts_id_owner"),
        CheckConstraint(
            "status IN ('user_entered','extracted','inferred','verified','external')",
            name="status_valid",
        ),
        CheckConstraint(
            "review_state IN ('pending','accepted','rejected')", name="review_state_valid"
        ),
        Index("ix_profile_facts_case_section", "case_id", "section"),
        Index("ix_profile_facts_case_review", "case_id", "review_state"),
    )


class FactEvidence(IdMixin, Base):
    """Where a fact came from: a document span, a URL, or the user's own entry."""

    __tablename__ = "fact_evidence"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    fact_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column()
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    method: Mapped[str] = mapped_column(String(40), nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    excerpt: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["fact_id", "owner_user_id"],
            ["profile_facts.id", "profile_facts.owner_user_id"],
            ondelete="CASCADE",
        ),
        # Deleting a document keeps the evidence row (and its excerpt) but unlinks the file.
        ForeignKeyConstraint(
            ["document_id", "owner_user_id"],
            ["documents.id", "documents.owner_user_id"],
            ondelete="SET NULL (document_id)",
        ),
        CheckConstraint("kind IN ('document','url','user_entry','merge')", name="kind_valid"),
        Index("ix_fact_evidence_fact", "fact_id"),
        Index("ix_fact_evidence_document", "document_id"),
    )


class ProfileSnapshot(IdMixin, Base):
    """Frozen copy of the accepted profile, for history and comparison."""

    __tablename__ = "profile_snapshots"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300))
    facts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        case_fk(),
        UniqueConstraint("case_id", "number", name="uq_profile_snapshots_case_number"),
    )


class CasePreferences(Base):
    """Search preferences for one case (validated by domain.preferences.Preferences)."""

    __tablename__ = "case_preferences"

    case_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (case_fk(),)


class SocialProfile(IdMixin, Base):
    __tablename__ = "social_profiles"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        case_fk(),
        UniqueConstraint("case_id", "url", name="uq_social_profiles_case_url"),
    )


class Affiliation(IdMixin, TimestampMixin, Base):
    """A relationship to an organization (optionally via a named person) and how it may be used.

    A relationship is not an endorsement. Outreach may use it only when `may_use_for_referral`.
    """

    __tablename__ = "affiliations"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    person_name: Mapped[str | None] = mapped_column(String(200))  # NULL = the candidate
    organization: Mapped[str] = mapped_column(String(300), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(40), nullable=False)
    role: Mapped[str | None] = mapped_column(String(200))
    start_date: Mapped[str | None] = mapped_column(String(10))
    end_date: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="current")
    evidence: Mapped[str | None] = mapped_column(String(2000))
    notes: Mapped[str | None] = mapped_column(String(2000))
    may_use_in_applications: Mapped[bool] = mapped_column(nullable=False, default=False)
    may_use_for_referral: Mapped[bool] = mapped_column(nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        case_fk(),
        CheckConstraint("status IN ('current','former','unknown')", name="status_valid"),
        Index("ix_affiliations_case", "case_id"),
    )


# ------------------------------------------------------------------ M3: mind map & catalog
class MindmapOverride(IdMixin, Base):
    """User layout/visibility changes for one mind-map node; survives regeneration."""

    __tablename__ = "mindmap_overrides"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    node_key: Mapped[str] = mapped_column(String(200), nullable=False)
    x: Mapped[float | None] = mapped_column()
    y: Mapped[float | None] = mapped_column()
    hidden: Mapped[bool] = mapped_column(nullable=False, default=False)
    label: Mapped[str | None] = mapped_column(String(300))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        case_fk(),
        UniqueConstraint("case_id", "node_key", name="uq_mindmap_overrides_case_node"),
    )


class Organization(IdMixin, Base):
    """Shared catalog: employers and institutions resolved by a normalized key (not owned)."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_key: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    aliases: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Opportunity(IdMixin, Base):
    """Shared catalog of normalized, deduplicated public opportunities (not owned).

    Users never list the catalog directly. They see only opportunities linked to their own
    `opportunity_matches` rows.
    """

    __tablename__ = "opportunities"

    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    organization_name: Mapped[str] = mapped_column(String(300), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(300), nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(String(2048))
    requisition_id: Mapped[str | None] = mapped_column(String(300))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("status IN ('open','closed','unknown')", name="status_valid"),
        Index("ix_opportunities_org_kind", "organization_id", "kind"),
        Index("ix_opportunities_canonical_url", "canonical_url"),
    )


class OpportunitySource(IdMixin, Base):
    """Where a catalog opportunity was seen (one row per source listing)."""

    __tablename__ = "opportunity_sources"

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False
    )
    source_key: Mapped[str] = mapped_column(String(100), nullable=False)
    external_id: Mapped[str] = mapped_column(String(300), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    dedup_score: Mapped[float | None] = mapped_column()
    dedup_reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("source_key", "external_id", name="uq_opportunity_sources_listing"),
        Index("ix_opportunity_sources_opportunity", "opportunity_id"),
    )


class SourceConfig(IdMixin, Base):
    __tablename__ = "source_configs"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    adapter_key: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("owner_user_id", "adapter_key", name="uq_source_configs_owner_key"),
    )


class SyncCheckpoint(IdMixin, Base):
    __tablename__ = "sync_checkpoints"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    adapter_key: Mapped[str] = mapped_column(String(100), nullable=False)
    query_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    cursor: Mapped[str | None] = mapped_column(String(500))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        case_fk(),
        UniqueConstraint(
            "case_id", "adapter_key", "query_hash", name="uq_sync_checkpoints_case_adapter_query"
        ),
    )


class OpportunityMatch(IdMixin, Base):
    """This case's view of a catalog opportunity: explained score, gaps, and user status."""

    __tablename__ = "opportunity_matches"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    eligible: Mapped[bool] = mapped_column(nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    factors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    gaps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        case_fk(),
        UniqueConstraint("case_id", "opportunity_id", name="uq_opportunity_matches_case_opp"),
        CheckConstraint("status IN ('new','seen','shortlisted','dismissed')", name="status_valid"),
        Index("ix_opportunity_matches_case_score", "case_id", "score"),
    )


class DedupReport(IdMixin, Base):
    """A user's report that a merge or a duplicate is wrong (reviewed out of band)."""

    __tablename__ = "dedup_reports"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False
    )
    other_opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    note: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        case_fk(),
        CheckConstraint("kind IN ('wrong_merge','missed_duplicate')", name="kind_valid"),
    )


# ------------------------------------------------------------------- M4: durable runtime
class WorkflowRun(IdMixin, Base):
    """One execution of a workflow for a case. Its LangGraph thread id is this run's id."""

    __tablename__ = "workflow_runs"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    control_request: Mapped[str | None] = mapped_column(String(10))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(String(1000))
    current_node: Mapped[str | None] = mapped_column(String(100))
    steps_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    step_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=2_000_000)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        case_fk(),
        UniqueConstraint("id", "owner_user_id", name="uq_workflow_runs_id_owner"),
        CheckConstraint(
            "status IN ('pending','running','waiting_approval','pausing','paused','cancelling',"
            "'cancelled','failed','succeeded')",
            name="status_valid",
        ),
        CheckConstraint(
            "control_request IS NULL OR control_request IN ('pause','cancel')", name="control_valid"
        ),
        Index("ix_workflow_runs_case_created", "case_id", "created_at"),
    )


def run_fk() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["run_id", "owner_user_id"],
        ["workflow_runs.id", "workflow_runs.owner_user_id"],
        ondelete="CASCADE",
    )


class Task(IdMixin, Base):
    """A durable queue item that advances one run. Claimed with leases (ADR-0002)."""

    __tablename__ = "tasks"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    last_error: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        run_fk(),
        CheckConstraint(
            "status IN ('queued','running','retry_wait','succeeded','failed','cancelled')",
            name="status_valid",
        ),
        CheckConstraint("action IN ('start','resume','retry','rerun','skip')", name="action_valid"),
        Index("ix_tasks_claim", "status", "available_at", "priority"),
        Index("ix_tasks_run", "run_id"),
        Index(
            "uq_tasks_one_active_per_run",
            "run_id",
            unique=True,
            postgresql_where=text("status IN ('queued','running')"),
        ),
    )


class RunStep(IdMixin, Base):
    """User-visible record of one node execution attempt."""

    __tablename__ = "run_steps"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    node: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(String(1000))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        run_fk(),
        CheckConstraint(
            "status IN ('running','succeeded','failed','interrupted','skipped','cancelled')",
            name="status_valid",
        ),
        Index("ix_run_steps_run", "run_id", "started_at"),
    )


class WorkflowEvent(Base):
    """Append-only activity feed. `id` is a global sequence used as the SSE cursor."""

    __tablename__ = "workflow_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column()
    type: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        case_fk(),
        Index("ix_workflow_events_case_id", "case_id", "id"),
        Index("ix_workflow_events_run_id", "run_id", "id"),
    )


class ApprovalRequest(IdMixin, Base):
    """A consequential action waiting for the user. Decided only via the authenticated API."""

    __tablename__ = "approval_requests"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    node: Mapped[str] = mapped_column(String(100), nullable=False)
    action_kind: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str] = mapped_column(String(4000), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    idempotency_key: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    decision_note: Mapped[str | None] = mapped_column(String(2000))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        run_fk(),
        CheckConstraint(
            "status IN ('pending','approved','rejected','cancelled')", name="status_valid"
        ),
        Index("ix_approval_requests_case_status", "case_id", "status"),
    )


class ToolExecution(IdMixin, Base):
    """Idempotency ledger for side effects. `started` without a result after a crash is
    reported as `uncertain` and is never retried silently (ADR-0008)."""

    __tablename__ = "tool_executions"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    tool: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(String(1000))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        run_fk(),
        CheckConstraint(
            "status IN ('started','succeeded','failed','uncertain')", name="status_valid"
        ),
    )


class UsageRecord(IdMixin, Base):
    __tablename__ = "usage_records"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="SET NULL")
    )
    provider_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_usd: Mapped[float | None] = mapped_column()
    is_mock: Mapped[bool] = mapped_column(nullable=False, default=False)
    succeeded: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_usage_records_owner_created", "owner_user_id", "created_at"),)


class WorkerHeartbeat(Base):
    """Worker liveness (system table, not user data)."""

    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(200), nullable=False)
    pid: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    in_flight: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Secret(IdMixin, Base):
    """Envelope-encrypted secret (AES-GCM). Plaintext never leaves the provider adapter."""

    __tablename__ = "secrets"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(60), nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_id: Mapped[str] = mapped_column(String(40), nullable=False)
    hint: Mapped[str | None] = mapped_column(String(12))  # e.g. last 4 chars, for display
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProviderConfig(IdMixin, TimestampMixin, Base):
    """A user's model provider (BYOK). Capabilities are declared, then verified by a live test."""

    __tablename__ = "provider_configs"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500))
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    secret_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("secrets.id", ondelete="SET NULL")
    )
    context_window: Mapped[int] = mapped_column(Integer, nullable=False, default=8192)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=1024)
    supports_json_schema: Mapped[bool] = mapped_column(nullable=False, default=False)
    data_leaves_device: Mapped[bool] = mapped_column(nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(nullable=False, default=False)
    input_cost_per_mtok: Mapped[float | None] = mapped_column()
    output_cost_per_mtok: Mapped[float | None] = mapped_column()
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verification: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("owner_user_id", "name", name="uq_provider_configs_owner_name"),
        CheckConstraint(
            "kind IN ('mock','openai_compatible','anthropic','gemini')", name="kind_valid"
        ),
    )


# --- M5: research and generated application documents -------------------------------------


class ResearchSource(IdMixin, Base):
    """A page or listing read while researching an opportunity for a case.

    Owned per case: what someone researched is personal. `text` is the readable text that
    findings quote from; a finding's quote must be an exact substring of it.
    """

    __tablename__ = "research_sources"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    final_url: Mapped[str | None] = mapped_column(String(2048))
    title: Mapped[str | None] = mapped_column(String(300))
    origin: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(120))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    links: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        case_fk(),
        UniqueConstraint("case_id", "opportunity_id", "url", name="uq_research_sources_case_url"),
        CheckConstraint("origin IN ('listing','demo','web')", name="origin_valid"),
        CheckConstraint("status IN ('ok','failed','blocked','skipped')", name="status_valid"),
    )


class ResearchFinding(IdMixin, Base):
    """One requirement, deadline, supervisor, ... found in a source, with its verbatim quote."""

    __tablename__ = "research_findings"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_sources.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    field: Mapped[str] = mapped_column(String(60), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)
    method: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="current")
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        case_fk(),
        CheckConstraint(
            "kind IN ('deadline','degree','language_test','document_required','funding',"
            "'supervisor','other')",
            name="kind_valid",
        ),
        CheckConstraint("confidence IN ('high','medium','low')", name="confidence_valid"),
        CheckConstraint("status IN ('current','conflict')", name="status_valid"),
        Index("ix_research_findings_case_opp", "case_id", "opportunity_id"),
    )


class GeneratedDocument(IdMixin, TimestampMixin, Base):
    """An application document NexScout drafted (or assembled) for a case. Markdown is canonical;
    each edit or regeneration is a new immutable version."""

    __tablename__ = "generated_documents"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="SET NULL")
    )
    doc_type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="SET NULL"), unique=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        case_fk(),
        CheckConstraint(
            "doc_type IN ('sop','research_proposal','academic_cv','inquiry_email',"
            "'resume','cover_letter','referral_request')",
            name="doc_type_valid",
        ),
        Index("ix_generated_documents_case", "case_id", "created_at"),
    )


class GeneratedDocumentVersion(IdMixin, Base):
    """One immutable version: markdown, the verifier report, and rendered files (if any)."""

    __tablename__ = "generated_document_versions"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("generated_documents.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(String(20), nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    placeholders: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    artifacts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    model: Mapped[str | None] = mapped_column(String(200))
    is_mock: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("document_id", "number", name="uq_generated_document_versions_number"),
        CheckConstraint("origin IN ('generated','assembled','user_edit')", name="origin_valid"),
    )
