"""Mind map use cases: build from accepted facts, apply user overrides, compare snapshots."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.application.actor import Actor
from nexscout.application.cases import get_case
from nexscout.application.profile import evidence_counts, list_facts
from nexscout.domain.errors import NotFound, ValidationFailed
from nexscout.domain.mindmap import FactInput, MindMap, SnapshotDiff, build_mindmap, diff_snapshots
from nexscout.domain.profile import ReviewState, Section
from nexscout.infrastructure.db.models import MindmapOverride, ProfileSnapshot, User

NODE_KEY = re.compile(r"^(candidate|section:[a-z_]{1,30}|fact:[0-9a-f-]{36}|org:[\w ]{1,200})$")


@dataclass
class MindMapView:
    map: MindMap
    overrides: dict[str, MindmapOverride]
    orphaned: list[str]  # overrides whose node no longer exists (kept, not applied)


async def get_mindmap(session: AsyncSession, actor: Actor, case_id: uuid.UUID) -> MindMapView:
    await get_case(session, actor, case_id)
    user = await session.get(User, actor.user_id)
    facts = await list_facts(session, actor, case_id, review_state=ReviewState.ACCEPTED)
    counts = await evidence_counts(session, actor, [f.id for f in facts])
    mm = build_mindmap(
        [
            FactInput(
                id=str(f.id),
                section=Section(f.section),
                label=f.label,
                data=f.data,
                status=f.status,
                is_private=f.is_private,
                evidence_count=counts.get(f.id, 0),
            )
            for f in facts
        ],
        candidate_label=user.display_name if user else "You",
    )
    rows = list(
        await session.scalars(
            select(MindmapOverride).where(
                MindmapOverride.case_id == case_id, MindmapOverride.owner_user_id == actor.user_id
            )
        )
    )
    keys = {n.key for n in mm.nodes}
    overrides = {r.node_key: r for r in rows if r.node_key in keys}
    orphaned = sorted(r.node_key for r in rows if r.node_key not in keys)
    return MindMapView(mm, overrides, orphaned)


async def set_override(
    session: AsyncSession,
    actor: Actor,
    case_id: uuid.UUID,
    node_key: str,
    *,
    x: float | None,
    y: float | None,
    hidden: bool,
    label: str | None,
) -> MindmapOverride:
    await get_case(session, actor, case_id)
    if not NODE_KEY.match(node_key):
        raise ValidationFailed("Invalid node key.")
    clean_label = (label or "").strip()[:300] or None
    stmt = (
        insert(MindmapOverride)
        .values(
            id=uuid.uuid4(),
            owner_user_id=actor.user_id,
            case_id=case_id,
            node_key=node_key,
            x=x,
            y=y,
            hidden=hidden,
            label=clean_label,
        )
        .on_conflict_do_update(
            constraint="uq_mindmap_overrides_case_node",
            set_={"x": x, "y": y, "hidden": hidden, "label": clean_label},
        )
        .returning(MindmapOverride.id)
    )
    row_id = (await session.execute(stmt)).scalar_one()
    row = await session.get(MindmapOverride, row_id)
    assert row is not None
    await session.refresh(row)
    return row


async def clear_overrides(
    session: AsyncSession, actor: Actor, case_id: uuid.UUID, node_key: str | None = None
) -> int:
    await get_case(session, actor, case_id)
    stmt = delete(MindmapOverride).where(
        MindmapOverride.case_id == case_id, MindmapOverride.owner_user_id == actor.user_id
    )
    if node_key is not None:
        stmt = stmt.where(MindmapOverride.node_key == node_key)
    result = await session.execute(stmt)
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def reset_positions(session: AsyncSession, actor: Actor, case_id: uuid.UUID) -> int:
    """Auto-arrange: forget saved node positions so the layout engine places every node.
    Renamed and hidden nodes stay renamed and hidden; overrides left with nothing are removed."""
    await get_case(session, actor, case_id)
    owned = (MindmapOverride.case_id == case_id, MindmapOverride.owner_user_id == actor.user_id)
    moved = await session.execute(
        update(MindmapOverride)
        .where(*owned, MindmapOverride.x.is_not(None) | MindmapOverride.y.is_not(None))
        .values(x=None, y=None)
    )
    await session.execute(
        delete(MindmapOverride).where(
            *owned, MindmapOverride.label.is_(None), MindmapOverride.hidden.is_(False)
        )
    )
    return int(moved.rowcount or 0)  # type: ignore[attr-defined]


async def compare_snapshots(
    session: AsyncSession, actor: Actor, case_id: uuid.UUID, from_number: int, to_number: int
) -> SnapshotDiff:
    await get_case(session, actor, case_id)
    rows = {
        s.number: s
        for s in await session.scalars(
            select(ProfileSnapshot).where(
                ProfileSnapshot.case_id == case_id,
                ProfileSnapshot.owner_user_id == actor.user_id,
                ProfileSnapshot.number.in_([from_number, to_number]),
            )
        )
    }
    if from_number not in rows or to_number not in rows:
        raise NotFound("Snapshot not found.")
    return diff_snapshots(rows[from_number].facts, rows[to_number].facts)
