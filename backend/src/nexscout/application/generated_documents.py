"""Generated application documents: start drafting, edit (new version), render, download."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.application.actor import Actor
from nexscout.application.audit import record_audit
from nexscout.application.cases import get_case
from nexscout.application.opportunities import get_opportunity
from nexscout.application.runs import start_run
from nexscout.domain.drafting import (
    AVAILABLE_DOC_TYPES,
    DOC_SPECS,
    DocType,
    find_placeholders,
)
from nexscout.domain.errors import (
    ConcurrencyConflict,
    NotFound,
    PermissionDenied,
    ValidationFailed,
)
from nexscout.infrastructure.db.models import (
    Affiliation,
    GeneratedDocument,
    GeneratedDocumentVersion,
    ResearchFinding,
    WorkflowRun,
)
from nexscout.infrastructure.storage import ObjectStore

MAX_MARKDOWN = 100_000
FORMATS = {
    "pdf": ("application/pdf", ".pdf"),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
}


@dataclass
class DocumentView:
    document: GeneratedDocument
    versions: list[GeneratedDocumentVersion]

    @property
    def current(self) -> GeneratedDocumentVersion:
        return next(v for v in self.versions if v.number == self.document.current_version)


async def start_draft(
    session: AsyncSession,
    actor: Actor,
    case_id: uuid.UUID,
    *,
    doc_type: str,
    opportunity_id: uuid.UUID | None,
    supervisor_finding_id: uuid.UUID | None = None,
    affiliation_id: uuid.UUID | None = None,
    provider_id: uuid.UUID | None = None,
) -> WorkflowRun:
    try:
        kind = DocType(doc_type)
    except ValueError as exc:
        raise ValidationFailed("Unknown document type.") from exc
    if kind not in AVAILABLE_DOC_TYPES:
        raise ValidationFailed("This document type isn't available yet.")
    spec = DOC_SPECS[kind]
    await get_case(session, actor, case_id)
    if spec.needs_opportunity and opportunity_id is None:
        raise ValidationFailed(f"Choose the position this {spec.label.lower()} is for.")
    if opportunity_id is not None:
        await get_opportunity(session, actor, case_id, opportunity_id)
    if supervisor_finding_id is not None:
        finding = await session.scalar(
            select(ResearchFinding).where(
                ResearchFinding.id == supervisor_finding_id,
                ResearchFinding.owner_user_id == actor.user_id,
                ResearchFinding.case_id == case_id,
                ResearchFinding.kind == "supervisor",
            )
        )
        if finding is None or finding.opportunity_id != opportunity_id:
            raise NotFound("Supervisor not found for this position.")
    if kind is DocType.REFERRAL_REQUEST:
        if affiliation_id is None:
            raise ValidationFailed("Choose who you want to ask for a referral.")
        aff = await session.scalar(
            select(Affiliation).where(
                Affiliation.id == affiliation_id,
                Affiliation.owner_user_id == actor.user_id,
                Affiliation.case_id == case_id,
            )
        )
        if aff is None:
            raise NotFound("Relationship not found.")
        if not aff.may_use_for_referral or not aff.person_name:
            raise PermissionDenied(
                "You haven't allowed NexScout to suggest a referral request to this person."
            )
    params: dict[str, Any] = {"doc_type": kind.value}
    if opportunity_id:
        params["opportunity_id"] = str(opportunity_id)
    if supervisor_finding_id:
        params["supervisor_finding_id"] = str(supervisor_finding_id)
    if affiliation_id:
        params["affiliation_id"] = str(affiliation_id)
    if provider_id:
        params["provider_id"] = str(provider_id)
    return await start_run(
        session, actor, case_id, kind="draft_document", params=params, internal=True
    )


async def list_documents(
    session: AsyncSession,
    actor: Actor,
    case_id: uuid.UUID,
    opportunity_id: uuid.UUID | None = None,
) -> list[tuple[GeneratedDocument, GeneratedDocumentVersion]]:
    await get_case(session, actor, case_id)
    stmt = (
        select(GeneratedDocument, GeneratedDocumentVersion)
        .join(
            GeneratedDocumentVersion,
            (GeneratedDocumentVersion.document_id == GeneratedDocument.id)
            & (GeneratedDocumentVersion.number == GeneratedDocument.current_version),
        )
        .where(
            GeneratedDocument.owner_user_id == actor.user_id,
            GeneratedDocument.case_id == case_id,
        )
        .order_by(GeneratedDocument.created_at.desc())
    )
    if opportunity_id is not None:
        stmt = stmt.where(GeneratedDocument.opportunity_id == opportunity_id)
    return [(d, v) for d, v in (await session.execute(stmt)).all()]


async def _document(
    session: AsyncSession, actor: Actor, document_id: uuid.UUID, *, lock: bool = False
) -> GeneratedDocument:
    stmt = select(GeneratedDocument).where(
        GeneratedDocument.id == document_id, GeneratedDocument.owner_user_id == actor.user_id
    )
    if lock:
        stmt = stmt.with_for_update()
    doc = await session.scalar(stmt)
    if doc is None:
        raise NotFound("Document not found.")
    return doc


async def get_document(session: AsyncSession, actor: Actor, document_id: uuid.UUID) -> DocumentView:
    doc = await _document(session, actor, document_id)
    versions = list(
        await session.scalars(
            select(GeneratedDocumentVersion)
            .where(
                GeneratedDocumentVersion.document_id == doc.id,
                GeneratedDocumentVersion.owner_user_id == actor.user_id,
            )
            .order_by(GeneratedDocumentVersion.number)
        )
    )
    return DocumentView(doc, versions)


async def get_version(
    session: AsyncSession, actor: Actor, document_id: uuid.UUID, number: int
) -> GeneratedDocumentVersion:
    doc = await _document(session, actor, document_id)
    version = await session.scalar(
        select(GeneratedDocumentVersion).where(
            GeneratedDocumentVersion.document_id == doc.id,
            GeneratedDocumentVersion.owner_user_id == actor.user_id,
            GeneratedDocumentVersion.number == number,
        )
    )
    if version is None:
        raise NotFound("Version not found.")
    return version


async def save_edit(
    session: AsyncSession,
    actor: Actor,
    document_id: uuid.UUID,
    *,
    markdown: str,
    base_version: int,
) -> DocumentView:
    """The user's text becomes a new version. It isn't re-verified: it's theirs. Placeholders
    are recounted so an unfinished document stays visibly unfinished."""
    if len(markdown) > MAX_MARKDOWN:
        raise ValidationFailed("The document is too long.")
    if not markdown.strip():
        raise ValidationFailed("The document is empty.")
    doc = await _document(session, actor, document_id, lock=True)
    if doc.current_version != base_version:
        raise ConcurrencyConflict(
            "This document changed since you opened it. Reload to see the latest version."
        )
    last = await session.scalar(
        select(func.max(GeneratedDocumentVersion.number)).where(
            GeneratedDocumentVersion.document_id == doc.id
        )
    )
    number = int(last or 0) + 1
    session.add(
        GeneratedDocumentVersion(
            owner_user_id=actor.user_id,
            document_id=doc.id,
            number=number,
            markdown=markdown.replace("\r\n", "\n"),
            origin="user_edit",
            report={"edited_from": base_version},
            placeholders=find_placeholders(markdown),
            artifacts={},
        )
    )
    doc.current_version = number
    doc.version += 1
    record_audit(
        session,
        "generated_document.edited",
        actor_user_id=actor.user_id,
        target_type="generated_document",
        target_id=doc.id,
        meta={"version": number},
    )
    await session.flush()
    return await get_document(session, actor, document_id)


async def start_render(
    session: AsyncSession, actor: Actor, document_id: uuid.UUID, number: int | None
) -> WorkflowRun:
    doc = await _document(session, actor, document_id)
    version = await get_version(session, actor, document_id, number or doc.current_version)
    return await start_run(
        session,
        actor,
        doc.case_id,
        kind="render_document",
        params={"document_id": str(doc.id), "version": version.number},
        internal=True,
    )


async def read_artifact(
    session: AsyncSession,
    actor: Actor,
    store: ObjectStore,
    document_id: uuid.UUID,
    number: int,
    fmt: str,
) -> tuple[bytes, str, str]:
    if fmt not in FORMATS:
        raise NotFound("Unknown format.")
    doc = await _document(session, actor, document_id)
    version = await get_version(session, actor, document_id, number)
    artifact = (version.artifacts or {}).get(fmt)
    if not artifact or not artifact.get("key"):
        raise NotFound("This version hasn't been turned into that file yet.")
    content_type, ext = FORMATS[fmt]
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in doc.title)[:80].strip()
    return store.get(artifact["key"]), f"{safe or 'document'} v{number}{ext}", content_type


async def delete_document(
    session: AsyncSession, actor: Actor, store: ObjectStore, document_id: uuid.UUID
) -> None:
    view = await get_document(session, actor, document_id)
    keys = {
        a["key"]
        for v in view.versions
        for a in (v.artifacts or {}).values()
        if isinstance(a, dict) and a.get("key")
    }
    await session.delete(view.document)
    record_audit(
        session,
        "generated_document.deleted",
        actor_user_id=actor.user_id,
        target_type="generated_document",
        target_id=document_id,
    )
    await session.flush()
    for key in keys:
        store.delete(key)
