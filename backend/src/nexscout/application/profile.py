"""Profile fact use cases: manual entry, review of extracted facts, edits, merge, snapshots.

Rules (AGENTS.md §3): extracted facts start pending; only accepted facts feed later stages;
every fact keeps its evidence; user edits are recorded, never silently replaced.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.application.actor import Actor
from nexscout.application.audit import record_audit
from nexscout.application.cases import get_case
from nexscout.domain.errors import ConcurrencyConflict, NotFound, ValidationFailed
from nexscout.domain.profile import (
    PRIVATE_BY_DEFAULT,
    FactStatus,
    Gap,
    ReviewState,
    Section,
    fact_label,
    find_gaps,
    validate_fact_data,
)
from nexscout.infrastructure.db.models import FactEvidence, ProfileFact, ProfileSnapshot

MAX_MERGE = 20


def _now() -> datetime:
    return datetime.now(UTC)


async def list_facts(
    session: AsyncSession,
    actor: Actor,
    case_id: uuid.UUID,
    *,
    section: Section | None = None,
    review_state: ReviewState | None = None,
) -> list[ProfileFact]:
    await get_case(session, actor, case_id)
    stmt = select(ProfileFact).where(
        ProfileFact.case_id == case_id, ProfileFact.owner_user_id == actor.user_id
    )
    if section is not None:
        stmt = stmt.where(ProfileFact.section == section.value)
    if review_state is not None:
        stmt = stmt.where(ProfileFact.review_state == review_state.value)
    return list(await session.scalars(stmt.order_by(ProfileFact.section, ProfileFact.created_at)))


async def get_fact(session: AsyncSession, actor: Actor, fact_id: uuid.UUID) -> ProfileFact:
    fact = await session.scalar(
        select(ProfileFact).where(
            ProfileFact.id == fact_id, ProfileFact.owner_user_id == actor.user_id
        )
    )
    if fact is None:
        raise NotFound("Profile entry not found.")
    return fact


async def list_evidence(
    session: AsyncSession, actor: Actor, fact_id: uuid.UUID
) -> list[FactEvidence]:
    await get_fact(session, actor, fact_id)
    return list(
        await session.scalars(
            select(FactEvidence)
            .where(FactEvidence.fact_id == fact_id, FactEvidence.owner_user_id == actor.user_id)
            .order_by(FactEvidence.created_at)
        )
    )


async def evidence_counts(
    session: AsyncSession, actor: Actor, fact_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not fact_ids:
        return {}
    rows = await session.execute(
        select(FactEvidence.fact_id, func.count())
        .where(FactEvidence.fact_id.in_(fact_ids), FactEvidence.owner_user_id == actor.user_id)
        .group_by(FactEvidence.fact_id)
    )
    return {fid: int(n) for fid, n in rows.all()}


def new_fact(
    owner_user_id: uuid.UUID,
    case_id: uuid.UUID,
    section: Section,
    data: dict[str, Any],
    *,
    status: FactStatus,
    review_state: ReviewState,
    is_private: bool | None = None,
    meta: dict[str, Any] | None = None,
) -> ProfileFact:
    clean = validate_fact_data(section, data)
    return ProfileFact(
        owner_user_id=owner_user_id,
        case_id=case_id,
        section=section.value,
        data=clean,
        label=fact_label(section, clean)[:300],
        status=status.value,
        review_state=review_state.value,
        is_private=section in PRIVATE_BY_DEFAULT if is_private is None else is_private,
        meta=meta or {},
        reviewed_at=_now() if review_state is not ReviewState.PENDING else None,
    )


# Entries another entry can belong to ("part of"): roles and places, not skills or projects.
LINK_TARGETS = frozenset(
    {
        Section.EMPLOYMENT,
        Section.EDUCATION,
        Section.RESEARCH,
        Section.VOLUNTEER,
        Section.LEADERSHIP,
        Section.MEMBERSHIP,
    }
)
BULK_ACTIONS = ("accept", "reject", "delete", "private", "shareable")
MAX_BULK = 500


async def check_links(
    session: AsyncSession,
    owner_user_id: uuid.UUID,
    case_id: uuid.UUID,
    data: dict[str, Any],
    *,
    self_id: uuid.UUID | None = None,
) -> None:
    """`related_fact_ids` may only name this case's role/place entries (never itself)."""
    ids = data.get("related_fact_ids") or []
    if not ids:
        return
    wanted = {uuid.UUID(x) for x in ids}
    if self_id is not None and self_id in wanted:
        raise ValidationFailed("An entry can't be part of itself.")
    rows = (
        await session.execute(
            select(ProfileFact.id, ProfileFact.section).where(
                ProfileFact.id.in_(wanted),
                ProfileFact.case_id == case_id,
                ProfileFact.owner_user_id == owner_user_id,
            )
        )
    ).all()
    found = {fid: Section(sec) for fid, sec in rows}
    if set(found) != wanted:
        raise ValidationFailed("A linked entry doesn't exist in this case.")
    if any(sec not in LINK_TARGETS for sec in found.values()):
        raise ValidationFailed(
            "Entries can only be linked to a job, study, research, volunteer, leadership or "
            "membership entry."
        )


async def _unlink(
    session: AsyncSession, owner_user_id: uuid.UUID, case_id: uuid.UUID, gone: set[str]
) -> None:
    """Remove deleted entries from other entries' links."""
    if not gone:
        return
    rows = await session.scalars(
        select(ProfileFact).where(
            ProfileFact.case_id == case_id,
            ProfileFact.owner_user_id == owner_user_id,
            ProfileFact.data.has_key("related_fact_ids"),
        )
    )
    for f in rows:
        links = [x for x in (f.data.get("related_fact_ids") or []) if x not in gone]
        if links != f.data.get("related_fact_ids"):
            data = {k: v for k, v in f.data.items() if k != "related_fact_ids"}
            if links:
                data["related_fact_ids"] = links
            f.data = data
            f.version += 1


async def create_fact(
    session: AsyncSession,
    actor: Actor,
    case_id: uuid.UUID,
    *,
    section: Section,
    data: dict[str, Any],
    is_private: bool | None = None,
) -> ProfileFact:
    """Manual entry: the user is the source, so it is accepted immediately."""
    await get_case(session, actor, case_id)
    await check_links(session, actor.user_id, case_id, data)
    fact = new_fact(
        actor.user_id,
        case_id,
        section,
        data,
        status=FactStatus.USER_ENTERED,
        review_state=ReviewState.ACCEPTED,
        is_private=is_private,
    )
    session.add(fact)
    await session.flush()
    session.add(
        FactEvidence(
            owner_user_id=actor.user_id, fact_id=fact.id, kind="user_entry", method="manual_entry"
        )
    )
    record_audit(
        session,
        "fact.created",
        actor_user_id=actor.user_id,
        target_type="fact",
        target_id=fact.id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={"section": section.value},
    )
    return fact


async def update_fact(
    session: AsyncSession,
    actor: Actor,
    fact_id: uuid.UUID,
    *,
    expected_version: int,
    data: dict[str, Any] | None = None,
    is_private: bool | None = None,
    review_state: ReviewState | None = None,
) -> ProfileFact:
    fact = await get_fact(session, actor, fact_id)
    if fact.version != expected_version:
        raise ConcurrencyConflict("This entry was changed elsewhere. Reload and try again.")
    section = Section(fact.section)
    values: dict[str, Any] = {}
    if data is not None:
        clean = validate_fact_data(section, data)
        await check_links(session, actor.user_id, fact.case_id, clean, self_id=fact.id)
        if clean != fact.data:
            values["data"] = clean
            values["label"] = fact_label(section, clean)[:300]
            values["meta"] = {
                **fact.meta,
                "edited_by_user": True,
                "original_data": fact.meta.get("original_data", fact.data),
            }
    if is_private is not None:
        values["is_private"] = is_private
    if review_state is not None and review_state.value != fact.review_state:
        values["review_state"] = review_state.value
        values["reviewed_at"] = _now()
    if not values:
        return fact
    result = await session.execute(
        update(ProfileFact)
        .where(
            ProfileFact.id == fact_id,
            ProfileFact.owner_user_id == actor.user_id,
            ProfileFact.version == expected_version,
        )
        .values(**values, version=ProfileFact.version + 1)
        .returning(ProfileFact.id)
    )
    if result.scalar_one_or_none() is None:
        raise ConcurrencyConflict("This entry was changed elsewhere. Reload and try again.")
    record_audit(
        session,
        "fact.updated",
        actor_user_id=actor.user_id,
        target_type="fact",
        target_id=fact_id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={"fields": sorted(values)},
    )
    await session.refresh(fact)
    return fact


async def review_facts(
    session: AsyncSession,
    actor: Actor,
    case_id: uuid.UUID,
    *,
    accept: list[uuid.UUID],
    reject: list[uuid.UUID],
) -> int:
    """Bulk accept/reject. Only touches this user's facts in this case."""
    await get_case(session, actor, case_id)
    if set(accept) & set(reject):
        raise ValidationFailed("An entry can't be both accepted and rejected.")
    changed = 0
    for ids, state in ((accept, ReviewState.ACCEPTED), (reject, ReviewState.REJECTED)):
        if not ids:
            continue
        result = await session.execute(
            update(ProfileFact)
            .where(
                ProfileFact.id.in_(ids),
                ProfileFact.case_id == case_id,
                ProfileFact.owner_user_id == actor.user_id,
                ProfileFact.review_state != state.value,
            )
            .values(review_state=state.value, reviewed_at=_now(), version=ProfileFact.version + 1)
        )
        changed += result.rowcount or 0  # type: ignore[attr-defined]
    record_audit(
        session,
        "fact.reviewed",
        actor_user_id=actor.user_id,
        target_type="case",
        target_id=case_id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={"accepted": len(accept), "rejected": len(reject), "changed": changed},
    )
    return changed


async def delete_fact(session: AsyncSession, actor: Actor, fact_id: uuid.UUID) -> None:
    fact = await get_fact(session, actor, fact_id)
    case_id = fact.case_id
    await session.delete(fact)
    await session.flush()
    await _unlink(session, actor.user_id, case_id, {str(fact_id)})
    record_audit(
        session,
        "fact.deleted",
        actor_user_id=actor.user_id,
        target_type="fact",
        target_id=fact_id,
        ip=actor.ip,
        request_id=actor.request_id,
    )


async def merge_facts(
    session: AsyncSession,
    actor: Actor,
    case_id: uuid.UUID,
    *,
    keep_id: uuid.UUID,
    merge_ids: list[uuid.UUID],
    data: dict[str, Any] | None = None,
) -> ProfileFact:
    """Merge duplicates into `keep_id`: evidence moves over, merged entries are deleted."""
    await get_case(session, actor, case_id)
    others = [i for i in dict.fromkeys(merge_ids) if i != keep_id]
    if not others or len(others) > MAX_MERGE:
        raise ValidationFailed(f"Choose between 1 and {MAX_MERGE} entries to merge.")
    keep = await get_fact(session, actor, keep_id)
    rows = list(
        await session.scalars(
            select(ProfileFact).where(
                ProfileFact.id.in_(others), ProfileFact.owner_user_id == actor.user_id
            )
        )
    )
    if len(rows) != len(others) or keep.case_id != case_id:
        raise NotFound("Profile entry not found.")
    if any(r.case_id != case_id or r.section != keep.section for r in rows):
        raise ValidationFailed("Only entries from the same case and section can be merged.")

    await session.execute(
        update(FactEvidence)
        .where(FactEvidence.fact_id.in_(others), FactEvidence.owner_user_id == actor.user_id)
        .values(fact_id=keep_id)
    )
    for row in rows:
        await session.delete(row)
    if data is not None:
        section = Section(keep.section)
        clean = validate_fact_data(section, data)
        keep.data = clean
        keep.label = fact_label(section, clean)[:300]
        keep.meta = {**keep.meta, "edited_by_user": True}
    keep.meta = {**keep.meta, "merged_from": [str(i) for i in others]}
    keep.version += 1
    session.add(
        FactEvidence(
            owner_user_id=actor.user_id,
            fact_id=keep_id,
            kind="merge",
            method="user_merge",
            excerpt=f"Merged {len(others)} duplicate entries.",
        )
    )
    record_audit(
        session,
        "fact.merged",
        actor_user_id=actor.user_id,
        target_type="fact",
        target_id=keep_id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={"merged": [str(i) for i in others]},
    )
    await session.flush()
    await session.refresh(keep)
    return keep


async def profile_gaps(session: AsyncSession, actor: Actor, case_id: uuid.UUID) -> list[Gap]:
    accepted = await list_facts(session, actor, case_id, review_state=ReviewState.ACCEPTED)
    return find_gaps([(str(f.id), Section(f.section), f.data) for f in accepted])


# ------------------------------------------------------------------------------ snapshots
def _snapshot_row(f: ProfileFact) -> dict[str, Any]:
    return {
        "id": str(f.id),
        "section": f.section,
        "label": f.label,
        "data": f.data,
        "status": f.status,
        "is_private": f.is_private,
    }


async def create_snapshot(
    session: AsyncSession, actor: Actor, case_id: uuid.UUID, *, reason: str | None
) -> ProfileSnapshot:
    await get_case(session, actor, case_id)
    accepted = await list_facts(session, actor, case_id, review_state=ReviewState.ACCEPTED)
    last = await session.scalar(
        select(func.max(ProfileSnapshot.number)).where(ProfileSnapshot.case_id == case_id)
    )
    snap = ProfileSnapshot(
        owner_user_id=actor.user_id,
        case_id=case_id,
        number=(last or 0) + 1,
        reason=(reason or "").strip()[:300] or None,
        facts=[_snapshot_row(f) for f in accepted],
    )
    session.add(snap)
    await session.flush()
    record_audit(
        session,
        "profile.snapshot",
        actor_user_id=actor.user_id,
        target_type="case",
        target_id=case_id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={"number": snap.number, "facts": len(accepted)},
    )
    return snap


async def bulk_facts(
    session: AsyncSession,
    actor: Actor,
    case_id: uuid.UUID,
    *,
    action: str,
    ids: list[uuid.UUID],
) -> int:
    """Accept, reject, delete or change the privacy of many entries at once (this user's, in
    this case only). Returns how many changed."""
    await get_case(session, actor, case_id)
    if action not in BULK_ACTIONS:
        raise ValidationFailed("Unknown action.")
    if not ids:
        return 0
    if len(ids) > MAX_BULK:
        raise ValidationFailed(f"At most {MAX_BULK} entries at a time.")
    if action in ("accept", "reject"):
        return await review_facts(
            session,
            actor,
            case_id,
            accept=ids if action == "accept" else [],
            reject=ids if action == "reject" else [],
        )
    owned = (
        ProfileFact.id.in_(ids),
        ProfileFact.case_id == case_id,
        ProfileFact.owner_user_id == actor.user_id,
    )
    if action == "delete":
        gone = {str(x) for x in await session.scalars(select(ProfileFact.id).where(*owned))}
        if gone:
            await session.execute(
                delete(ProfileFact).where(ProfileFact.id.in_([uuid.UUID(x) for x in gone]))
            )
            await _unlink(session, actor.user_id, case_id, gone)
        changed = len(gone)
    else:
        result = await session.execute(
            update(ProfileFact)
            .where(*owned, ProfileFact.is_private.is_(action == "shareable"))
            .values(is_private=action == "private", version=ProfileFact.version + 1)
        )
        changed = result.rowcount or 0  # type: ignore[attr-defined]
    record_audit(
        session,
        f"fact.bulk_{action}",
        actor_user_id=actor.user_id,
        target_type="case",
        target_id=case_id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={"requested": len(ids), "changed": changed},
    )
    return changed


async def delete_snapshot(
    session: AsyncSession, actor: Actor, case_id: uuid.UUID, number: int
) -> None:
    await get_case(session, actor, case_id)
    result = await session.execute(
        delete(ProfileSnapshot).where(
            ProfileSnapshot.case_id == case_id,
            ProfileSnapshot.owner_user_id == actor.user_id,
            ProfileSnapshot.number == number,
        )
    )
    if not result.rowcount:  # type: ignore[attr-defined]
        raise NotFound("Snapshot not found.")
    record_audit(
        session,
        "profile.snapshot_deleted",
        actor_user_id=actor.user_id,
        target_type="case",
        target_id=case_id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={"number": number},
    )


async def list_snapshots(
    session: AsyncSession, actor: Actor, case_id: uuid.UUID
) -> list[ProfileSnapshot]:
    await get_case(session, actor, case_id)
    return list(
        await session.scalars(
            select(ProfileSnapshot)
            .where(
                ProfileSnapshot.case_id == case_id, ProfileSnapshot.owner_user_id == actor.user_id
            )
            .order_by(ProfileSnapshot.number.desc())
        )
    )
