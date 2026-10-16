"""Document use cases: upload → validate → store → parse (isolated) → extract pending facts.

Interim (until the M4 worker): parsing runs during the upload request, in a separate,
time-limited process. The DB transaction is committed *before* parsing and re-opened after,
so no transaction or row lock is held while untrusted content is processed.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.application.actor import Actor
from nexscout.application.audit import record_audit
from nexscout.application.cases import get_case
from nexscout.application.profile import new_fact
from nexscout.domain.cv_heuristics import METHOD as HEURISTIC_METHOD
from nexscout.domain.cv_heuristics import extract_facts
from nexscout.domain.errors import NotFound, ValidationFailed
from nexscout.domain.profile import FactStatus, ReviewState
from nexscout.infrastructure.db.engine import bind_tenant
from nexscout.infrastructure.db.models import Document, FactEvidence, ProfileFact
from nexscout.infrastructure.ingestion.files import sniff
from nexscout.infrastructure.ingestion.parsers import ParsedText, parse_isolated
from nexscout.infrastructure.storage import ObjectStore


class DocumentPurpose(StrEnum):
    CV = "cv"
    RESUME = "resume"
    TRANSCRIPT = "transcript"
    DEGREE_CERTIFICATE = "degree_certificate"
    STATEMENT_OF_PURPOSE = "statement_of_purpose"
    PERSONAL_STATEMENT = "personal_statement"
    RESEARCH_STATEMENT = "research_statement"
    RESEARCH_PROPOSAL = "research_proposal"
    COVER_LETTER = "cover_letter"
    RECOMMENDATION_LETTER = "recommendation_letter"
    WRITING_SAMPLE = "writing_sample"
    PUBLICATION = "publication"
    LANGUAGE_TEST = "language_test"
    PORTFOLIO = "portfolio"
    CERTIFICATE = "certificate"
    OTHER = "other"


# Only these purposes are mined for profile facts. Transcripts or recommendation letters are
# stored as supporting documents, but their text isn't turned into claims about the candidate.
EXTRACT_FROM: frozenset[DocumentPurpose] = frozenset({DocumentPurpose.CV, DocumentPurpose.RESUME})


@dataclass(frozen=True)
class UploadResult:
    document: Document
    facts_created: int


async def upload_document(
    session: AsyncSession,
    actor: Actor,
    store: ObjectStore,
    case_id: uuid.UUID,
    *,
    data: bytes,
    filename: str | None,
    purpose: DocumentPurpose,
    max_bytes: int,
    parse_timeout_s: float = 20.0,
) -> UploadResult:
    await get_case(session, actor, case_id)
    sniffed = sniff(data, filename, max_bytes)  # rejects unsupported types before storing
    key, digest = store.put(actor.user_id, data)

    # Release the request transaction (and the session-row lock) while parsing.
    await session.commit()
    parsed: ParsedText | None = None
    parse_error: str | None = None
    try:
        parsed = await asyncio.to_thread(parse_isolated, data, sniffed.kind, parse_timeout_s)
    except ValidationFailed as exc:
        parse_error = exc.message[:500]
    await bind_tenant(session, actor.user_id)
    await get_case(session, actor, case_id)  # the case may have been deleted meanwhile

    doc = Document(
        owner_user_id=actor.user_id,
        case_id=case_id,
        purpose=purpose.value,
        file_kind=sniffed.kind.value,
        filename=sniffed.filename,
        content_type=sniffed.content_type,
        size_bytes=len(data),
        sha256=digest,
        storage_key=key,
        origin="uploaded",
        parse_status="parsed" if parsed else "failed",
        parse_error=parse_error,
        page_count=parsed.page_count if parsed else None,
        text_content=parsed.text if parsed else None,
        page_starts=parsed.page_starts if parsed else [],
    )
    session.add(doc)
    await session.flush()

    created = 0
    if parsed and purpose in EXTRACT_FROM:
        for extracted in extract_facts(parsed.text):
            fact = new_fact(
                actor,
                case_id,
                extracted.section,
                extracted.data,
                status=FactStatus.EXTRACTED,
                review_state=ReviewState.PENDING,
                meta={
                    "method": HEURISTIC_METHOD,
                    "confidence": extracted.confidence,
                    "warnings": extracted.warnings,
                    "document_id": str(doc.id),
                },
            )
            session.add(fact)
            await session.flush()
            session.add(
                FactEvidence(
                    owner_user_id=actor.user_id,
                    fact_id=fact.id,
                    document_id=doc.id,
                    kind="document",
                    method=HEURISTIC_METHOD,
                    page=parsed.page_of(extracted.start),
                    char_start=extracted.start,
                    char_end=extracted.end,
                    excerpt=extracted.excerpt,
                )
            )
            created += 1
        doc.extraction_method = HEURISTIC_METHOD
        doc.facts_extracted = created

    record_audit(
        session,
        "document.uploaded",
        actor_user_id=actor.user_id,
        target_type="document",
        target_id=doc.id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={
            "purpose": purpose.value,
            "kind": sniffed.kind.value,
            "size": len(data),
            "parsed": parsed is not None,
            "facts": created,
        },
    )
    await session.flush()
    await session.refresh(doc)
    return UploadResult(doc, created)


async def list_documents(session: AsyncSession, actor: Actor, case_id: uuid.UUID) -> list[Document]:
    await get_case(session, actor, case_id)
    return list(
        await session.scalars(
            select(Document)
            .where(Document.case_id == case_id, Document.owner_user_id == actor.user_id)
            .order_by(Document.created_at.desc())
        )
    )


async def get_document(session: AsyncSession, actor: Actor, document_id: uuid.UUID) -> Document:
    doc = await session.scalar(
        select(Document).where(Document.id == document_id, Document.owner_user_id == actor.user_id)
    )
    if doc is None:
        raise NotFound("Document not found.")
    return doc


async def read_document_bytes(
    session: AsyncSession, actor: Actor, store: ObjectStore, document_id: uuid.UUID
) -> tuple[Document, bytes]:
    doc = await get_document(session, actor, document_id)
    try:
        data = await asyncio.to_thread(store.get, doc.storage_key)
    except FileNotFoundError as exc:
        raise NotFound("The stored file is missing.") from exc
    record_audit(
        session,
        "document.downloaded",
        actor_user_id=actor.user_id,
        target_type="document",
        target_id=doc.id,
        ip=actor.ip,
        request_id=actor.request_id,
    )
    return doc, data


async def delete_document(
    session: AsyncSession,
    actor: Actor,
    store: ObjectStore,
    document_id: uuid.UUID,
    *,
    delete_pending_facts: bool,
) -> int:
    """Delete a document. Evidence rows keep their excerpt but lose the file link.

    If `delete_pending_facts`, entries extracted from this document that were never reviewed
    are removed too. Accepted entries are always kept: the user confirmed them.
    """
    doc = await get_document(session, actor, document_id)
    removed = 0
    if delete_pending_facts:
        pending = list(
            await session.scalars(
                select(ProfileFact).where(
                    ProfileFact.owner_user_id == actor.user_id,
                    ProfileFact.case_id == doc.case_id,
                    ProfileFact.review_state == ReviewState.PENDING.value,
                    ProfileFact.meta["document_id"].astext == str(doc.id),
                )
            )
        )
        for fact in pending:
            await session.delete(fact)
        removed = len(pending)
    key = doc.storage_key
    await session.delete(doc)
    await session.flush()
    still_used = await session.scalar(
        select(func.count())
        .select_from(Document)
        .where(Document.owner_user_id == actor.user_id, Document.storage_key == key)
    )
    record_audit(
        session,
        "document.deleted",
        actor_user_id=actor.user_id,
        target_type="document",
        target_id=document_id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={"pending_facts_removed": removed},
    )
    # Commit before removing the file: a rollback must never leave a row without its bytes.
    await session.commit()
    if not still_used:
        await asyncio.to_thread(store.delete, key)
    await bind_tenant(session, actor.user_id)
    return removed
