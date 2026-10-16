"""Profile facts, review, evidence, gaps, snapshots."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from nexscout.api.deps import CurrentActor, DbSession
from nexscout.api.schemas import (
    EvidenceOut,
    FactCreate,
    FactMerge,
    FactOut,
    FactReview,
    FactReviewOut,
    FactUpdate,
    GapOut,
    SnapshotCreate,
    SnapshotOut,
)
from nexscout.application import profile
from nexscout.domain.profile import ReviewState, Section
from nexscout.infrastructure.db.models import ProfileFact

router = APIRouter(tags=["profile"])


def _out(fact: ProfileFact, evidence_count: int = 0) -> FactOut:
    out = FactOut.model_validate(fact)
    out.evidence_count = evidence_count
    return out


@router.get("/cases/{case_id}/facts", response_model=list[FactOut])
async def list_facts(
    case_id: uuid.UUID,
    actor: CurrentActor,
    db: DbSession,
    section: Section | None = None,
    review_state: ReviewState | None = None,
) -> list[FactOut]:
    facts = await profile.list_facts(db, actor, case_id, section=section, review_state=review_state)
    counts = await profile.evidence_counts(db, actor, [f.id for f in facts])
    return [_out(f, counts.get(f.id, 0)) for f in facts]


@router.post("/cases/{case_id}/facts", response_model=FactOut, status_code=status.HTTP_201_CREATED)
async def create_fact(
    case_id: uuid.UUID, body: FactCreate, actor: CurrentActor, db: DbSession
) -> FactOut:
    fact = await profile.create_fact(
        db, actor, case_id, section=body.section, data=body.data, is_private=body.is_private
    )
    await db.refresh(fact)
    return _out(fact, 1)


@router.post("/cases/{case_id}/facts/review", response_model=FactReviewOut)
async def review_facts(
    case_id: uuid.UUID, body: FactReview, actor: CurrentActor, db: DbSession
) -> FactReviewOut:
    changed = await profile.review_facts(db, actor, case_id, accept=body.accept, reject=body.reject)
    return FactReviewOut(changed=changed)


@router.post("/cases/{case_id}/facts/merge", response_model=FactOut)
async def merge_facts(
    case_id: uuid.UUID, body: FactMerge, actor: CurrentActor, db: DbSession
) -> FactOut:
    fact = await profile.merge_facts(
        db, actor, case_id, keep_id=body.keep_id, merge_ids=body.merge_ids, data=body.data
    )
    counts = await profile.evidence_counts(db, actor, [fact.id])
    return _out(fact, counts.get(fact.id, 0))


@router.get("/facts/{fact_id}", response_model=FactOut)
async def get_fact(fact_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> FactOut:
    fact = await profile.get_fact(db, actor, fact_id)
    counts = await profile.evidence_counts(db, actor, [fact.id])
    return _out(fact, counts.get(fact.id, 0))


@router.patch("/facts/{fact_id}", response_model=FactOut)
async def update_fact(
    fact_id: uuid.UUID, body: FactUpdate, actor: CurrentActor, db: DbSession
) -> FactOut:
    fact = await profile.update_fact(
        db,
        actor,
        fact_id,
        expected_version=body.version,
        data=body.data,
        is_private=body.is_private,
        review_state=body.review_state,
    )
    counts = await profile.evidence_counts(db, actor, [fact.id])
    return _out(fact, counts.get(fact.id, 0))


@router.delete("/facts/{fact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fact(fact_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> Response:
    await profile.delete_fact(db, actor, fact_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/facts/{fact_id}/evidence", response_model=list[EvidenceOut])
async def fact_evidence(
    fact_id: uuid.UUID, actor: CurrentActor, db: DbSession
) -> list[EvidenceOut]:
    return [EvidenceOut.model_validate(e) for e in await profile.list_evidence(db, actor, fact_id)]


@router.get("/cases/{case_id}/profile/gaps", response_model=list[GapOut])
async def gaps(case_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> list[GapOut]:
    return [
        GapOut.model_validate(g.model_dump())
        for g in await profile.profile_gaps(db, actor, case_id)
    ]


@router.post(
    "/cases/{case_id}/snapshots", response_model=SnapshotOut, status_code=status.HTTP_201_CREATED
)
async def create_snapshot(
    case_id: uuid.UUID, body: SnapshotCreate, actor: CurrentActor, db: DbSession
) -> SnapshotOut:
    snap = await profile.create_snapshot(db, actor, case_id, reason=body.reason)
    await db.refresh(snap)
    return SnapshotOut(
        id=snap.id,
        number=snap.number,
        reason=snap.reason,
        created_at=snap.created_at,
        fact_count=len(snap.facts),
    )


@router.get("/cases/{case_id}/snapshots", response_model=list[SnapshotOut])
async def list_snapshots(
    case_id: uuid.UUID, actor: CurrentActor, db: DbSession
) -> list[SnapshotOut]:
    return [
        SnapshotOut(
            id=s.id,
            number=s.number,
            reason=s.reason,
            created_at=s.created_at,
            fact_count=len(s.facts),
        )
        for s in await profile.list_snapshots(db, actor, case_id)
    ]
