"""Document use cases: upload → validate → store → (worker) parse in isolation → extract.

Interim (until the M4 worker): parsing runs during the upload request, in a separate,
time-limited process. The DB transaction is committed *before* parsing and re-opened after,
so no transaction or row lock is held while untrusted content is processed.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.application.actor import Actor
from nexscout.application.audit import record_audit
from nexscout.application.cases import get_case
from nexscout.application.profile import new_fact
from nexscout.domain.cv_heuristics import METHOD as HEURISTIC_METHOD
from nexscout.domain.cv_heuristics import ExtractedFact, extract_facts
from nexscout.domain.errors import NotFound, ValidationFailed
from nexscout.domain.letters import METHOD as LETTER_METHOD
from nexscout.domain.letters import read_reference
from nexscout.domain.profile import FactStatus, ReviewState, Section, identity_keys
from nexscout.infrastructure.db.engine import bind_tenant
from nexscout.infrastructure.db.models import Document, FactEvidence, ProfileFact
from nexscout.infrastructure.ingestion.files import FileKind, sniff
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


# Only these purposes are mined for profile entries. A recommendation letter yields one
# reference entry (who recommends you, domain/letters.py); its praise is never turned into claims
# about the candidate. Transcripts and the rest are stored as supporting documents.
EXTRACT_FROM: frozenset[DocumentPurpose] = frozenset(
    {DocumentPurpose.CV, DocumentPurpose.RESUME, DocumentPurpose.RECOMMENDATION_LETTER}
)


@dataclass(frozen=True)
class UploadResult:
    document: Document
    run_id: uuid.UUID


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
) -> UploadResult:
    """Validate and store the file, then hand reading/extraction to the durable worker."""
    from nexscout.application.runs import start_run

    await get_case(session, actor, case_id)
    sniffed = sniff(data, filename, max_bytes)  # rejects unsupported types before storing
    key, digest = store.put(actor.user_id, data)
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
        parse_status="pending",
    )
    session.add(doc)
    await session.flush()
    run = await start_run(
        session,
        actor,
        case_id,
        kind="document_ingestion",
        params={"document_id": str(doc.id)},
        internal=True,
    )
    record_audit(
        session,
        "document.uploaded",
        actor_user_id=actor.user_id,
        target_type="document",
        target_id=doc.id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={"purpose": purpose.value, "kind": sniffed.kind.value, "size": len(data)},
    )
    await session.refresh(doc)
    return UploadResult(doc, run.id)


async def read_document_text(
    store: ObjectStore, doc: Document, timeout_s: float = 20.0
) -> tuple[ParsedText | None, str | None]:
    """Parse in an isolated, killable subprocess. Call outside any DB transaction."""
    data = await asyncio.to_thread(store.get, doc.storage_key)
    try:
        return await asyncio.to_thread(
            parse_isolated, data, FileKind(doc.file_kind), timeout_s
        ), None
    except ValidationFailed as exc:
        return None, exc.message[:500]


async def save_extraction(
    session: AsyncSession,
    owner_id: uuid.UUID,
    doc: Document,
    parsed: ParsedText | None,
    parse_error: str | None,
) -> int:
    """Persist parse results and pending facts. Idempotent: re-running after a crash never
    duplicates entries for the same document."""
    doc.parse_status = "parsed" if parsed else "failed"
    doc.parse_error = parse_error
    doc.page_count = parsed.page_count if parsed else None
    doc.text_content = parsed.text if parsed else None
    doc.page_starts = parsed.page_starts if parsed else []
    already = await session.scalar(
        select(func.count())
        .select_from(ProfileFact)
        .where(
            ProfileFact.owner_user_id == owner_id,
            ProfileFact.meta["document_id"].astext == str(doc.id),
        )
    )
    created = int(already or 0)
    if parsed and DocumentPurpose(doc.purpose) in EXTRACT_FROM and not already:
        created = await _extract_into(session, owner_id, doc, parsed.text, parsed.page_of)
    if parsed and DocumentPurpose(doc.purpose) in EXTRACT_FROM:
        doc.extraction_method = (
            LETTER_METHOD
            if doc.purpose == DocumentPurpose.RECOMMENDATION_LETTER
            else HEURISTIC_METHOD
        )
        doc.facts_extracted = created
    return created


async def _extract_into(
    session: AsyncSession,
    owner_id: uuid.UUID,
    doc: Document,
    text: str,
    page_of: Callable[[int], int | None],
) -> int:
    """Turn a document's text into pending entries with evidence. Entries the case already has
    (any review state, so rejected ones aren't brought back) are skipped."""
    # What the case already has, including the wording a user edited away (meta.original_data):
    # identity key -> (that entry's id, its review state).
    existing: dict[tuple[str, ...], tuple[uuid.UUID, str]] = {}
    for fact_id, sec, data, fact_meta, state in (
        await session.execute(
            select(
                ProfileFact.id,
                ProfileFact.section,
                ProfileFact.data,
                ProfileFact.meta,
                ProfileFact.review_state,
            ).where(ProfileFact.owner_user_id == owner_id, ProfileFact.case_id == doc.case_id)
        )
    ).all():
        section = Section(sec)
        keys = identity_keys(section, data)
        if isinstance(fact_meta.get("original_data"), dict):
            keys |= identity_keys(section, fact_meta["original_data"])
        for key in keys:
            existing.setdefault(key, (fact_id, state))
    # (entry, method, relationship quote) for each candidate entry.
    rows: list[tuple[ExtractedFact, str, str | None]]
    if doc.purpose == DocumentPurpose.RECOMMENDATION_LETTER:
        ref = read_reference(text)
        if ref is None:
            return 0
        letter = ExtractedFact(
            Section.REFERENCE, dict(ref.data), ref.start, ref.end, ref.excerpt, ref.warnings
        )
        rows = [(letter, LETTER_METHOD, ref.relationship_quote)]
    else:
        rows = [(f, HEURISTIC_METHOD, None) for f in extract_facts(text)]
    made: dict[int, ProfileFact] = {}
    # Each candidate's entry: the new one, or the one the case already has (so a project still
    # links to the job the user accepted and edited). Rejected entries are never link targets.
    entry_of: dict[int, uuid.UUID] = {}
    for i, (extracted, method, quote) in enumerate(rows):
        keys = identity_keys(extracted.section, extracted.data)
        if hit := next((existing[k] for k in keys if k in existing), None):
            if hit[1] != ReviewState.REJECTED.value:
                entry_of[i] = hit[0]
            continue
        meta: dict[str, object] = {
            "method": method,
            "confidence": extracted.confidence,
            "warnings": extracted.warnings,
            "document_id": str(doc.id),
        }
        if quote:
            meta["relationship_quote"] = quote
        fact = new_fact(
            owner_id,
            doc.case_id,
            extracted.section,
            extracted.data,
            status=FactStatus.EXTRACTED,
            review_state=ReviewState.PENDING,
            meta=meta,
        )
        session.add(fact)
        await session.flush()
        session.add(
            FactEvidence(
                owner_user_id=owner_id,
                fact_id=fact.id,
                document_id=doc.id,
                kind="document",
                method=method,
                page=page_of(extracted.start),
                char_start=extracted.start,
                char_end=extracted.end,
                excerpt=extracted.excerpt,
            )
        )
        for key in keys:
            existing.setdefault(key, (fact.id, ReviewState.PENDING.value))
        made[i] = fact
        entry_of[i] = fact.id
    # Links ("this project was done in that job"), on new entries only, still pending review.
    for i, fact in made.items():
        targets = [str(entry_of[j]) for j in rows[i][0].related if j in entry_of]
        if targets:
            fact.data = {**fact.data, "related_fact_ids": targets}
    return len(made)


async def reread_document(
    session: AsyncSession, actor: Actor, document_id: uuid.UUID
) -> dict[str, int]:
    """Read a document again with the current reader. Only its pending, unedited entries are
    replaced; anything the user accepted, rejected or edited stays exactly as it is."""
    doc = await get_document(session, actor, document_id)
    if not doc.text_content:
        raise ValidationFailed("This document has no readable text to read again.")
    if DocumentPurpose(doc.purpose) not in EXTRACT_FROM:
        raise ValidationFailed(
            "Entries are only read from CVs, résumés and recommendation letters."
        )
    pending = [
        f
        for f in await session.scalars(
            select(ProfileFact).where(
                ProfileFact.owner_user_id == actor.user_id,
                ProfileFact.case_id == doc.case_id,
                ProfileFact.review_state == ReviewState.PENDING.value,
                ProfileFact.meta["document_id"].astext == str(doc.id),
            )
        )
        if not f.meta.get("edited_by_user")
    ]
    for fact in pending:
        await session.delete(fact)
    await session.flush()
    stored = ParsedText(doc.text_content, list(doc.page_starts or []))
    created = await _extract_into(session, actor.user_id, doc, stored.text, stored.page_of)
    doc.extraction_method = (
        LETTER_METHOD if doc.purpose == DocumentPurpose.RECOMMENDATION_LETTER else HEURISTIC_METHOD
    )
    doc.facts_extracted = created
    record_audit(
        session,
        "document.reread",
        actor_user_id=actor.user_id,
        target_type="document",
        target_id=doc.id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={"removed": len(pending), "created": created},
    )
    return {"removed": len(pending), "created": created}


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
