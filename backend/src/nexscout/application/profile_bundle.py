"""Profile export/import: one case's profile as a portable `.nexscout` file (ADR-0018).

A bundle is a zip with `profile.json` (format `nexscout-profile/1`) and, optionally, the original
documents under `documents/`. It holds what took the user time to build: the case, preferences,
every profile entry with its evidence, relationships, links, the mind map's saved layout, profile
snapshots and the answer bank. It never holds secrets, AI providers, applications, runs,
notifications or sources.

Import always creates a **new** case, so nothing existing is overwritten. Every id is remapped
(entries, documents, mind-map node keys, snapshot rows, links), every value goes through the same
validation as when the user types it, and the archive is checked before anything is read (size,
file count, paths). Unknown fields from a newer version are reported, never trusted.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout import __version__
from nexscout.application import answers as answers_app
from nexscout.application import contact as contact_app
from nexscout.application import mindmap as mindmap_app
from nexscout.application import relationships as rel_app
from nexscout.application.actor import Actor
from nexscout.application.audit import record_audit
from nexscout.application.cases import create_case, get_case
from nexscout.domain.cases import CareerPath
from nexscout.domain.errors import Conflict, DomainError, ValidationFailed
from nexscout.domain.profile import FactStatus, ReviewState, Section, fact_label, validate_fact_data
from nexscout.infrastructure.db.models import (
    Affiliation,
    CandidateCase,
    CaseAnswer,
    CaseContact,
    CasePreferences,
    Document,
    FactEvidence,
    MindmapOverride,
    ProfileFact,
    ProfileSnapshot,
    SocialProfile,
)
from nexscout.infrastructure.ingestion.files import sniff
from nexscout.infrastructure.storage import ObjectStore

FORMAT = "nexscout-profile/1"
MAX_BUNDLE_BYTES = 100 * 1024 * 1024
MAX_UNCOMPRESSED = 300 * 1024 * 1024
MAX_FILES = 500
MAX_JSON_BYTES = 50 * 1024 * 1024
MAX_FACTS = 10_000
# Meta keys an imported entry may carry (anything else is dropped).
_META_KEYS = frozenset(
    {
        "method",
        "confidence",
        "warnings",
        "document_id",
        "edited_by_user",
        "original_data",
        "relationship_quote",
        "source",
    }
)


@dataclass
class ImportReport:
    case_id: uuid.UUID
    case_name: str
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _safe_filename(name: str) -> str:
    base = re.sub(r"[^\w.() -]+", "_", name).strip(" .") or "file"
    return base[:120]


# ---------------------------------------------------------------------------------- export
async def export_case(
    session: AsyncSession,
    actor: Actor,
    store: ObjectStore,
    case_id: uuid.UUID,
    *,
    include_documents: bool = True,
) -> tuple[str, bytes]:
    case = await get_case(session, actor, case_id)

    def owned(model: Any) -> Any:
        return select(model).where(model.owner_user_id == actor.user_id, model.case_id == case_id)

    facts = list(await session.scalars(owned(ProfileFact).order_by(ProfileFact.created_at)))
    fact_ids = [f.id for f in facts]
    evidence = (
        list(
            await session.scalars(
                select(FactEvidence).where(
                    FactEvidence.owner_user_id == actor.user_id, FactEvidence.fact_id.in_(fact_ids)
                )
            )
        )
        if fact_ids
        else []
    )
    docs = list(await session.scalars(owned(Document).order_by(Document.created_at)))
    prefs = await session.get(CasePreferences, case_id)
    contact = await session.get(CaseContact, case_id)
    payload: dict[str, Any] = {
        "format": FORMAT,
        "app_version": __version__,
        "exported_at": datetime.now(UTC).isoformat(),
        "case": {
            "name": case.name,
            "description": case.description,
            "career_path": case.career_path,
        },
        "preferences": prefs.data if prefs and prefs.owner_user_id == actor.user_id else None,
        # Added in v2.10 (same format number: older files simply don't have it).
        "contact": contact.data if contact and contact.owner_user_id == actor.user_id else None,
        "facts": [
            {
                "id": str(f.id),
                "section": f.section,
                "data": f.data,
                "status": f.status,
                "review_state": f.review_state,
                "is_private": f.is_private,
                "meta": {k: v for k, v in f.meta.items() if k in _META_KEYS},
                "created_at": _iso(f.created_at),
                "reviewed_at": _iso(f.reviewed_at),
            }
            for f in facts
        ],
        "evidence": [
            {
                "fact_id": str(e.fact_id),
                "document_id": str(e.document_id) if e.document_id else None,
                "kind": e.kind,
                "method": e.method,
                "page": e.page,
                "char_start": e.char_start,
                "char_end": e.char_end,
                "excerpt": e.excerpt,
                "url": e.url,
            }
            for e in evidence
        ],
        "documents": [],
        "affiliations": [
            {k: getattr(a, k) for k in rel_app.AFFILIATION_FIELDS}
            for a in await session.scalars(owned(Affiliation))
        ],
        "social_profiles": [
            {"url": s.url, "label": s.label} for s in await session.scalars(owned(SocialProfile))
        ],
        "mindmap_overrides": [
            {"node_key": o.node_key, "x": o.x, "y": o.y, "hidden": o.hidden, "label": o.label}
            for o in await session.scalars(owned(MindmapOverride))
        ],
        "snapshots": [
            {
                "number": s.number,
                "reason": s.reason,
                "facts": s.facts,
                "created_at": _iso(s.created_at),
            }
            for s in await session.scalars(owned(ProfileSnapshot).order_by(ProfileSnapshot.number))
        ],
        "answers": [
            {"question": a.question, "answer": a.answer, "source": a.source}
            for a in await session.scalars(owned(CaseAnswer))
        ],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for n, d in enumerate(docs, start=1):
            entry: dict[str, Any] = {
                "id": str(d.id),
                "purpose": d.purpose,
                "filename": d.filename,
                "parse_status": d.parse_status,
                "text_content": d.text_content,
                "page_starts": d.page_starts,
                "extraction_method": d.extraction_method,
                "facts_extracted": d.facts_extracted,
                "file": None,
            }
            if include_documents:
                blob: bytes | None
                try:
                    blob = await asyncio.to_thread(store.get, d.storage_key)
                except FileNotFoundError:
                    blob = None
                if blob is not None:
                    path = f"documents/{n}/{_safe_filename(d.filename)}"
                    zf.writestr(path, blob)
                    entry["file"] = path
            payload["documents"].append(entry)
        payload["manifest"] = {
            key: len(payload[key])
            for key in (
                "facts",
                "evidence",
                "documents",
                "affiliations",
                "social_profiles",
                "mindmap_overrides",
                "snapshots",
                "answers",
            )
        }
        zf.writestr("profile.json", json.dumps(payload, ensure_ascii=False, indent=1))
    record_audit(
        session,
        "case.exported",
        actor_user_id=actor.user_id,
        target_type="case",
        target_id=case_id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={**payload["manifest"], "documents_included": include_documents},
    )
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    slug = re.sub(r"[^a-z0-9]+", "-", case.name.lower()).strip("-")[:60] or "profile"
    return f"{slug}-{stamp}.nexscout", buf.getvalue()


# ---------------------------------------------------------------------------------- import
def _open(data: bytes) -> tuple[zipfile.ZipFile, dict[str, Any]]:
    """Check the archive before reading anything from it."""
    if len(data) > MAX_BUNDLE_BYTES:
        raise ValidationFailed("That file is larger than 100 MB.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except (zipfile.BadZipFile, ValueError) as exc:
        raise ValidationFailed("That isn't a NexScout profile file.") from exc
    if len(infos) > MAX_FILES:
        raise ValidationFailed("That file has too many parts.")
    if sum(i.file_size for i in infos) > MAX_UNCOMPRESSED:
        raise ValidationFailed("That file unpacks to more than 300 MB.")
    for i in infos:
        name = i.filename
        if name.startswith(("/", "\\")) or ".." in name.split("/") or ":" in name:
            raise ValidationFailed("That file contains unsafe paths.")
    try:
        info = zf.getinfo("profile.json")
    except KeyError as exc:
        raise ValidationFailed("That isn't a NexScout profile file (no profile.json).") from exc
    if info.file_size > MAX_JSON_BYTES:
        raise ValidationFailed("The profile data is too large.")
    try:
        payload = json.loads(zf.read(info))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationFailed("The profile data is damaged.") from exc
    if not isinstance(payload, dict) or not str(payload.get("format", "")).startswith(
        "nexscout-profile/"
    ):
        raise ValidationFailed("That isn't a NexScout profile file.")
    if payload["format"] != FORMAT:
        raise ValidationFailed(
            "This profile was exported by a newer NexScout. Update NexScout, then import it."
        )
    return zf, payload


def _list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key) or []
    if not isinstance(value, list):
        raise ValidationFailed(f"The profile data is damaged ({key}).")
    return [v for v in value if isinstance(v, dict)]


async def _new_case(session: AsyncSession, actor: Actor, case: dict[str, Any]) -> Any:
    """A new case named like the exported one ("X", else "X (imported)", "X (imported 2)")."""
    name = str(case.get("name") or "Imported profile").strip()[:100] or "Imported profile"
    try:
        path = CareerPath(case.get("career_path") or CareerPath.UNDECIDED.value)
    except ValueError:
        path = CareerPath.UNDECIDED
    taken = {
        n.lower()
        for n in await session.scalars(
            select(CandidateCase.name).where(CandidateCase.owner_user_id == actor.user_id)
        )
    }
    candidate = name
    for attempt in range(2, 1000):
        if candidate.lower() not in taken:
            break
        suffix = " (imported)" if attempt == 2 else f" (imported {attempt - 1})"
        candidate = f"{name[: 100 - len(suffix)]}{suffix}"
    return await create_case(
        session, actor, name=candidate, description=case.get("description"), career_path=path
    )


async def import_case(
    session: AsyncSession,
    actor: Actor,
    store: ObjectStore,
    data: bytes,
    *,
    max_document_bytes: int,
) -> ImportReport:
    zf, payload = _open(data)
    facts_in = _list(payload, "facts")
    if len(facts_in) > MAX_FACTS:
        raise ValidationFailed("That profile has too many entries.")
    known = {
        "format",
        "app_version",
        "exported_at",
        "case",
        "preferences",
        "contact",
        "facts",
        "evidence",
        "documents",
        "affiliations",
        "social_profiles",
        "mindmap_overrides",
        "snapshots",
        "answers",
        "manifest",
    }
    case = await _new_case(session, actor, payload.get("case") or {})
    report = ImportReport(case.id, case.name)
    if extra := sorted(set(payload) - known):
        report.warnings.append(f"Ignored parts this version doesn't know: {', '.join(extra)}.")

    # Preferences go through the same validation as the Preferences page.
    if isinstance(payload.get("preferences"), dict):
        try:
            await rel_app.put_preferences(
                session, actor, case.id, data=payload["preferences"], expected_version=0
            )
            report.counts["preferences"] = 1
        except ValidationFailed as exc:
            report.warnings.append(f"Preferences skipped: {exc}")
    if isinstance(payload.get("contact"), dict):
        try:
            await contact_app.put_contact(
                session, actor, case.id, data=payload["contact"], expected_version=0
            )
            report.counts["contact"] = 1
        except ValidationFailed as exc:
            report.warnings.append(f"Contact details skipped: {exc}")

    # Documents: the original file is checked like an upload before it is stored.
    doc_map: dict[str, uuid.UUID] = {}
    for d in _list(payload, "documents"):
        path = d.get("file")
        if not isinstance(path, str) or path not in zf.namelist():
            continue
        try:
            blob = zf.read(path)
            sniffed = sniff(blob, str(d.get("filename") or "document"), max_document_bytes)
        except (ValidationFailed, DomainError, KeyError, ValueError) as exc:
            report.warnings.append(f"Document {d.get('filename')!s} skipped: {exc}")
            continue
        from nexscout.application.documents import DocumentPurpose

        try:
            purpose = DocumentPurpose(str(d.get("purpose")))
        except ValueError:
            purpose = DocumentPurpose.OTHER
        key, digest = store.put(actor.user_id, blob)
        text = d.get("text_content") if isinstance(d.get("text_content"), str) else None
        starts = [int(x) for x in d.get("page_starts") or [] if isinstance(x, int)]
        doc = Document(
            owner_user_id=actor.user_id,
            case_id=case.id,
            purpose=purpose.value,
            file_kind=sniffed.kind.value,
            filename=sniffed.filename,
            content_type=sniffed.content_type,
            size_bytes=len(blob),
            sha256=digest,
            storage_key=key,
            origin="uploaded",  # the user uploaded it originally; the audit log records the import
            parse_status="parsed" if text else "failed",
            parse_error=None if text else "Imported without its text; upload it again to read it.",
            text_content=text,
            page_starts=starts,
            page_count=len(starts) or None,
            extraction_method=str(d.get("extraction_method") or "")[:40] or None,
            facts_extracted=int(d.get("facts_extracted") or 0),
        )
        session.add(doc)
        await session.flush()
        doc_map[str(d.get("id"))] = doc.id
    report.counts["documents"] = len(doc_map)

    # Entries: new ids first, so links and snapshots can be remapped.
    fact_map = {str(f.get("id")): uuid.uuid4() for f in facts_in}
    made = 0
    for f in facts_in:
        old = str(f.get("id"))
        try:
            section = Section(str(f.get("section")))
            status = FactStatus(str(f.get("status") or FactStatus.USER_ENTERED.value))
            review = ReviewState(str(f.get("review_state") or ReviewState.PENDING.value))
            raw = dict(f.get("data") or {})
            links = [str(fact_map[x]) for x in raw.get("related_fact_ids") or [] if x in fact_map]
            raw.pop("related_fact_ids", None)
            if links:
                raw["related_fact_ids"] = links
            clean = validate_fact_data(section, raw)
        except (ValueError, ValidationFailed) as exc:
            report.warnings.append(f"An entry was skipped ({exc}).")
            fact_map.pop(old, None)
            continue
        meta = {k: v for k, v in dict(f.get("meta") or {}).items() if k in _META_KEYS}
        if meta.get("document_id") is not None:
            new_doc = doc_map.get(str(meta["document_id"]))
            meta["document_id"] = str(new_doc) if new_doc else None
            if new_doc is None:
                meta.pop("document_id")
        session.add(
            ProfileFact(
                id=fact_map[old],
                owner_user_id=actor.user_id,
                case_id=case.id,
                section=section.value,
                data=clean,
                label=fact_label(section, clean)[:300],
                status=status.value,
                review_state=review.value,
                is_private=bool(f.get("is_private")),
                meta=meta,
                reviewed_at=datetime.now(UTC) if review is not ReviewState.PENDING else None,
            )
        )
        made += 1
    await session.flush()
    report.counts["facts"] = made

    ev = 0
    for e in _list(payload, "evidence"):
        new_fact = fact_map.get(str(e.get("fact_id")))
        if new_fact is None:
            continue
        doc_id = doc_map.get(str(e.get("document_id"))) if e.get("document_id") else None

        def _int(v: Any) -> int | None:
            return v if isinstance(v, int) and v >= 0 else None

        session.add(
            FactEvidence(
                owner_user_id=actor.user_id,
                fact_id=new_fact,
                document_id=doc_id,
                kind=str(e.get("kind") or "document")[:30],
                method=str(e.get("method") or "imported")[:40],
                page=_int(e.get("page")),
                char_start=_int(e.get("char_start")) if doc_id else None,
                char_end=_int(e.get("char_end")) if doc_id else None,
                excerpt=str(e["excerpt"])[:1000] if e.get("excerpt") else None,
                url=str(e["url"])[:2048] if e.get("url") else None,
            )
        )
        ev += 1
    report.counts["evidence"] = ev

    n = 0
    for a in _list(payload, "affiliations"):
        try:
            await rel_app.create_affiliation(
                session, actor, case.id, {k: a.get(k) for k in rel_app.AFFILIATION_FIELDS}
            )
            n += 1
        except ValidationFailed as exc:
            report.warnings.append(f"A relationship was skipped ({exc}).")
    report.counts["affiliations"] = n

    n = 0
    for s in _list(payload, "social_profiles"):
        try:
            await rel_app.add_social_profile(
                session, actor, case.id, url=str(s.get("url") or ""), label=s.get("label")
            )
            n += 1
        except (ValidationFailed, Conflict) as exc:
            report.warnings.append(f"A link was skipped ({exc}).")
    report.counts["social_profiles"] = n

    n = 0
    for o in _list(payload, "mindmap_overrides"):
        key = str(o.get("node_key") or "")
        if key.startswith("fact:"):
            new = fact_map.get(key.removeprefix("fact:"))
            if new is None:
                continue
            key = f"fact:{new}"
        x, y = o.get("x"), o.get("y")
        try:
            await mindmap_app.set_override(
                session,
                actor,
                case.id,
                key,
                x=float(x) if isinstance(x, int | float) else None,
                y=float(y) if isinstance(y, int | float) else None,
                hidden=bool(o.get("hidden")),
                label=o.get("label") if isinstance(o.get("label"), str) else None,
            )
            n += 1
        except ValidationFailed:
            continue
    report.counts["mindmap_overrides"] = n

    n = 0
    for s in _list(payload, "snapshots"):
        rows = []
        for r in s.get("facts") or []:
            if not isinstance(r, dict):
                continue
            row = dict(r)
            if str(row.get("id")) in fact_map:
                row["id"] = str(fact_map[str(row["id"])])
            row_data = row.get("data")
            if isinstance(row_data, dict) and row_data.get("related_fact_ids"):
                row["data"] = {
                    **row_data,
                    "related_fact_ids": [
                        str(fact_map[x]) for x in row_data["related_fact_ids"] if x in fact_map
                    ],
                }
            rows.append(row)
        number = s.get("number")
        session.add(
            ProfileSnapshot(
                owner_user_id=actor.user_id,
                case_id=case.id,
                number=number if isinstance(number, int) and number > 0 else n + 1,
                reason=str(s["reason"])[:300] if s.get("reason") else None,
                facts=rows,
            )
        )
        n += 1
    await session.flush()
    report.counts["snapshots"] = n

    n = 0
    for a in _list(payload, "answers"):
        try:
            await answers_app.save_answer(
                session,
                actor,
                case.id,
                str(a.get("question") or ""),
                str(a.get("answer") or ""),
                source=str(a.get("source") or "user")[:40],
            )
            n += 1
        except ValidationFailed:
            continue
    report.counts["answers"] = n

    record_audit(
        session,
        "case.imported",
        actor_user_id=actor.user_id,
        target_type="case",
        target_id=case.id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={**report.counts, "warnings": len(report.warnings)},
    )
    return report
