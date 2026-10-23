"""Position research (sources + findings with quotes) and generated application documents."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Response, status
from pydantic import Field

from nexscout.api.deps import CurrentActor, DbSession, ObjectStoreDep
from nexscout.api.schemas import ApiModel, FillOut, RunStartedOut
from nexscout.application import contact as contact_app
from nexscout.application import generated_documents as gen
from nexscout.application import research
from nexscout.application.opportunities import get_opportunity
from nexscout.application.referrals import referrals_for
from nexscout.domain.drafting import DOC_SPECS, DocType
from nexscout.domain.formats import PROFILES, resolve_format
from nexscout.domain.research import is_stale
from nexscout.infrastructure.db.models import (
    GeneratedDocument,
    GeneratedDocumentVersion,
    ResearchSource,
)

router = APIRouter(tags=["research"])


class ResearchSourceOut(ApiModel):
    id: uuid.UUID
    url: str
    final_url: str | None
    title: str | None
    origin: str
    status: str
    error: str | None
    retrieved_at: datetime
    is_stale: bool
    is_demo_data: bool


class FindingOut(ApiModel):
    id: uuid.UUID
    source_id: uuid.UUID
    kind: str
    field: str
    summary: str
    quote: str
    value: dict[str, Any]
    confidence: str
    method: str
    status: str
    note: str | None


class ResearchOut(ApiModel):
    sources: list[ResearchSourceOut]
    findings: list[FindingOut]


def _source_out(s: ResearchSource, now: datetime) -> ResearchSourceOut:
    return ResearchSourceOut(
        id=s.id,
        url=s.url,
        final_url=s.final_url,
        title=s.title,
        origin=s.origin,
        status=s.status,
        error=s.error,
        retrieved_at=s.retrieved_at,
        is_stale=is_stale(s.retrieved_at, now),
        is_demo_data=s.origin == "demo",
    )


@router.get("/cases/{case_id}/opportunities/{opportunity_id}/research", response_model=ResearchOut)
async def get_research(
    case_id: uuid.UUID, opportunity_id: uuid.UUID, actor: CurrentActor, db: DbSession
) -> ResearchOut:
    view = await research.get_research(db, actor, case_id, opportunity_id)
    now = datetime.now(UTC)
    return ResearchOut(
        sources=[_source_out(s, now) for s in view.sources],
        findings=[FindingOut.model_validate(f) for f in view.findings],
    )


@router.post(
    "/cases/{case_id}/opportunities/{opportunity_id}/research",
    response_model=RunStartedOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_research(
    case_id: uuid.UUID, opportunity_id: uuid.UUID, actor: CurrentActor, db: DbSession
) -> RunStartedOut:
    run = await research.start_research(db, actor, case_id, opportunity_id)
    return RunStartedOut(run_id=run.id)


class ReferralOut(ApiModel):
    affiliation_id: uuid.UUID
    person_name: str
    organization: str
    relationship_type: str
    role: str | None
    reason: str


class ReferralsOut(ApiModel):
    suggestions: list[ReferralOut]
    not_permitted: int


@router.get(
    "/cases/{case_id}/opportunities/{opportunity_id}/referrals", response_model=ReferralsOut
)
async def get_referrals(
    case_id: uuid.UUID, opportunity_id: uuid.UUID, actor: CurrentActor, db: DbSession
) -> ReferralsOut:
    suggestions, hidden = await referrals_for(db, actor, case_id, opportunity_id)
    return ReferralsOut(
        suggestions=[
            ReferralOut(
                affiliation_id=uuid.UUID(x.affiliation_id),
                person_name=x.person_name,
                organization=x.organization,
                relationship_type=x.relationship_type,
                role=x.role,
                reason=x.reason,
            )
            for x in suggestions
        ],
        not_permitted=hidden,
    )


class FormatOut(ApiModel):
    key: str
    label: str
    paper: str
    reason: str | None = None
    notes: list[str]
    page_limits: dict[str, int]


@router.get("/document-formats", response_model=list[FormatOut])
async def document_formats(actor: CurrentActor) -> list[FormatOut]:
    """Regional formats NexScout can produce (conventions, not official rules)."""
    return [
        FormatOut(**{**resolve_format(None, key).as_dict(), "reason": None}) for key in PROFILES
    ]


@router.get(
    "/cases/{case_id}/opportunities/{opportunity_id}/document-format", response_model=FormatOut
)
async def opportunity_format(
    case_id: uuid.UUID, opportunity_id: uuid.UUID, actor: CurrentActor, db: DbSession
) -> FormatOut:
    """The format NexScout will use for this position, and why."""
    view = await get_opportunity(db, actor, case_id, opportunity_id)
    choice = resolve_format(view.opportunity.data.get("location_country"))
    return FormatOut(**choice.as_dict())


# --- Generated documents --------------------------------------------------------------------


class DocTypeOut(ApiModel):
    doc_type: str
    label: str
    needs_opportunity: bool
    uses_model: bool


class DraftIn(ApiModel):
    doc_type: str = Field(max_length=30)
    opportunity_id: uuid.UUID | None = None
    supervisor_finding_id: uuid.UUID | None = None
    affiliation_id: uuid.UUID | None = None
    provider_id: uuid.UUID | None = None
    format: str | None = Field(default=None, max_length=40)


class VersionSummaryOut(ApiModel):
    number: int
    origin: str
    placeholders: list[str]
    model: str | None
    is_mock: bool
    has_files: bool
    created_at: datetime


class VersionOut(VersionSummaryOut):
    markdown: str
    report: dict[str, Any]
    files: dict[str, Any]


class GeneratedDocumentOut(ApiModel):
    id: uuid.UUID
    case_id: uuid.UUID
    opportunity_id: uuid.UUID | None
    doc_type: str
    doc_label: str
    title: str
    current_version: int
    created_at: datetime
    updated_at: datetime
    latest: VersionSummaryOut


class GeneratedDocumentDetailOut(GeneratedDocumentOut):
    versions: list[VersionSummaryOut]
    current: VersionOut


class EditIn(ApiModel):
    markdown: str = Field(max_length=gen.MAX_MARKDOWN)
    base_version: int


class RenderIn(ApiModel):
    version: int | None = None


def _files(v: GeneratedDocumentVersion) -> dict[str, Any]:
    """Artifact metadata without storage keys."""
    out: dict[str, Any] = {}
    for fmt in ("pdf", "docx"):
        a = (v.artifacts or {}).get(fmt)
        if isinstance(a, dict):
            out[fmt] = {"size": a.get("size"), "sha256": a.get("sha256"), "checks": a.get("checks")}
    if v.artifacts and v.artifacts.get("rendered_at"):
        out["rendered_at"] = v.artifacts["rendered_at"]
    for key in ("compliance", "format"):
        if v.artifacts and v.artifacts.get(key):
            out[key] = v.artifacts[key]
    return out


def _summary(v: GeneratedDocumentVersion) -> VersionSummaryOut:
    return VersionSummaryOut(
        number=v.number,
        origin=v.origin,
        placeholders=list(v.placeholders or []),
        model=v.model,
        is_mock=v.is_mock,
        has_files=bool((v.artifacts or {}).get("pdf")),
        created_at=v.created_at,
    )


def _version(v: GeneratedDocumentVersion) -> VersionOut:
    return VersionOut(
        **_summary(v).model_dump(), markdown=v.markdown, report=v.report or {}, files=_files(v)
    )


def _doc_out(d: GeneratedDocument, latest: GeneratedDocumentVersion) -> GeneratedDocumentOut:
    return GeneratedDocumentOut(
        id=d.id,
        case_id=d.case_id,
        opportunity_id=d.opportunity_id,
        doc_type=d.doc_type,
        doc_label=DOC_SPECS[DocType(d.doc_type)].label if d.doc_type in DOC_SPECS else d.doc_type,
        title=d.title,
        current_version=d.current_version,
        created_at=d.created_at,
        updated_at=d.updated_at,
        latest=_summary(latest),
    )


def _detail(view: gen.DocumentView) -> GeneratedDocumentDetailOut:
    current = view.current
    return GeneratedDocumentDetailOut(
        **_doc_out(view.document, current).model_dump(),
        versions=[_summary(v) for v in view.versions],
        current=_version(current),
    )


@router.get("/document-types", response_model=list[DocTypeOut])
async def document_types(actor: CurrentActor) -> list[DocTypeOut]:
    return [
        DocTypeOut(
            doc_type=t.value,
            label=s.label,
            needs_opportunity=s.needs_opportunity,
            uses_model=s.uses_model,
        )
        for t, s in DOC_SPECS.items()
    ]


@router.post(
    "/cases/{case_id}/generated-documents",
    response_model=RunStartedOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def draft_document(
    case_id: uuid.UUID, body: DraftIn, actor: CurrentActor, db: DbSession
) -> RunStartedOut:
    run = await gen.start_draft(
        db,
        actor,
        case_id,
        doc_type=body.doc_type,
        opportunity_id=body.opportunity_id,
        supervisor_finding_id=body.supervisor_finding_id,
        affiliation_id=body.affiliation_id,
        provider_id=body.provider_id,
        format_key=body.format,
    )
    return RunStartedOut(run_id=run.id)


@router.get("/cases/{case_id}/generated-documents", response_model=list[GeneratedDocumentOut])
async def list_generated(
    case_id: uuid.UUID,
    actor: CurrentActor,
    db: DbSession,
    opportunity_id: uuid.UUID | None = None,
) -> list[GeneratedDocumentOut]:
    rows = await gen.list_documents(db, actor, case_id, opportunity_id)
    return [_doc_out(d, v) for d, v in rows]


@router.get("/generated-documents/{document_id}", response_model=GeneratedDocumentDetailOut)
async def get_generated(
    document_id: uuid.UUID, actor: CurrentActor, db: DbSession
) -> GeneratedDocumentDetailOut:
    return _detail(await gen.get_document(db, actor, document_id))


@router.get("/generated-documents/{document_id}/versions/{number}", response_model=VersionOut)
async def get_generated_version(
    document_id: uuid.UUID, number: int, actor: CurrentActor, db: DbSession
) -> VersionOut:
    return _version(await gen.get_version(db, actor, document_id, number))


@router.post(
    "/generated-documents/{document_id}/versions",
    response_model=GeneratedDocumentDetailOut,
    status_code=status.HTTP_201_CREATED,
)
async def save_generated_edit(
    document_id: uuid.UUID, body: EditIn, actor: CurrentActor, db: DbSession
) -> GeneratedDocumentDetailOut:
    view = await gen.save_edit(
        db, actor, document_id, markdown=body.markdown, base_version=body.base_version
    )
    return _detail(view)


@router.post(
    "/generated-documents/{document_id}/render",
    response_model=RunStartedOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def render_generated(
    document_id: uuid.UUID, body: RenderIn, actor: CurrentActor, db: DbSession
) -> RunStartedOut:
    run = await gen.start_render(db, actor, document_id, body.version)
    return RunStartedOut(run_id=run.id)


@router.post("/generated-documents/{document_id}/fill", response_model=FillOut)
async def fill_generated(document_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> FillOut:
    """Fill in what the user already gave NexScout (contact details, saved answers) as a new
    version. Placeholders nobody answered stay."""
    view, filled = await contact_app.fill_document(db, actor, document_id)
    return FillOut(
        filled=filled,
        placeholders_left=len(view.current.placeholders),
        current_version=view.document.current_version,
    )


@router.get("/generated-documents/{document_id}/versions/{number}/files/{fmt}")
async def download_generated(
    document_id: uuid.UUID,
    number: int,
    fmt: str,
    actor: CurrentActor,
    db: DbSession,
    store: ObjectStoreDep,
) -> Response:
    data, filename, content_type = await gen.read_artifact(
        db, actor, store, document_id, number, fmt
    )
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )


@router.delete("/generated-documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_generated(
    document_id: uuid.UUID, actor: CurrentActor, db: DbSession, store: ObjectStoreDep
) -> Response:
    await gen.delete_document(db, actor, store, document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
