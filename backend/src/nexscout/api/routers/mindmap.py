"""Mind map: generated graph + user overrides, and snapshot comparison."""

from __future__ import annotations

import uuid
from dataclasses import asdict

from fastapi import APIRouter, Response, status

from nexscout.api.deps import CurrentActor, DbSession
from nexscout.api.schemas import (
    MindEdgeOut,
    MindMapOut,
    MindNodeOut,
    NodeOverrideIn,
    SnapshotDiffOut,
)
from nexscout.application import mindmap

router = APIRouter(tags=["mind map"])


@router.get("/cases/{case_id}/mindmap", response_model=MindMapOut)
async def get_mindmap(case_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> MindMapOut:
    view = await mindmap.get_mindmap(db, actor, case_id)
    nodes = []
    for n in view.map.nodes:
        o = view.overrides.get(n.key)
        nodes.append(
            MindNodeOut(
                **asdict(n),
                x=o.x if o else None,
                y=o.y if o else None,
                hidden=o.hidden if o else False,
                label_override=o.label if o else None,
            )
        )
    return MindMapOut(
        nodes=nodes,
        edges=[MindEdgeOut(**asdict(e)) for e in view.map.edges],
        orphaned_overrides=view.orphaned,
    )


@router.put("/cases/{case_id}/mindmap/nodes/{node_key}", status_code=status.HTTP_204_NO_CONTENT)
async def set_override(
    case_id: uuid.UUID, node_key: str, body: NodeOverrideIn, actor: CurrentActor, db: DbSession
) -> Response:
    await mindmap.set_override(
        db, actor, case_id, node_key, x=body.x, y=body.y, hidden=body.hidden, label=body.label
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/cases/{case_id}/mindmap/nodes/{node_key}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_override(
    case_id: uuid.UUID, node_key: str, actor: CurrentActor, db: DbSession
) -> Response:
    await mindmap.clear_overrides(db, actor, case_id, node_key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/cases/{case_id}/mindmap/overrides", status_code=status.HTTP_204_NO_CONTENT)
async def clear_all(case_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> Response:
    await mindmap.clear_overrides(db, actor, case_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/cases/{case_id}/mindmap/layout/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_layout(case_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> Response:
    """Auto-arrange: clears saved positions only (names and hidden nodes are kept)."""
    await mindmap.reset_positions(db, actor, case_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/cases/{case_id}/snapshots/compare", response_model=SnapshotDiffOut)
async def compare(
    case_id: uuid.UUID, actor: CurrentActor, db: DbSession, from_number: int, to_number: int
) -> SnapshotDiffOut:
    diff = await mindmap.compare_snapshots(db, actor, case_id, from_number, to_number)
    return SnapshotDiffOut(**asdict(diff))
