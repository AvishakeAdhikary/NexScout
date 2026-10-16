"""Candidate case use cases. Every query filters by owner; RLS is the second wall."""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.application.actor import Actor
from nexscout.application.audit import record_audit
from nexscout.domain.cases import (
    CareerPath,
    CaseStatus,
    normalize_case_name,
    normalize_description,
)
from nexscout.domain.errors import ConcurrencyConflict, Conflict, NotFound
from nexscout.infrastructure.db.models import CandidateCase

_UNSET: object = object()


async def list_cases(
    session: AsyncSession, actor: Actor, *, include_archived: bool = False
) -> list[CandidateCase]:
    stmt = select(CandidateCase).where(CandidateCase.owner_user_id == actor.user_id)
    if not include_archived:
        stmt = stmt.where(CandidateCase.status != CaseStatus.ARCHIVED.value)
    result = await session.scalars(stmt.order_by(CandidateCase.created_at))
    return list(result)


async def get_case(session: AsyncSession, actor: Actor, case_id: uuid.UUID) -> CandidateCase:
    case = await session.scalar(
        select(CandidateCase).where(
            CandidateCase.id == case_id, CandidateCase.owner_user_id == actor.user_id
        )
    )
    if case is None:
        raise NotFound("Case not found.")
    return case


async def create_case(
    session: AsyncSession,
    actor: Actor,
    *,
    name: str,
    description: str | None = None,
    career_path: CareerPath = CareerPath.UNDECIDED,
) -> CandidateCase:
    case = CandidateCase(
        owner_user_id=actor.user_id,
        name=normalize_case_name(name),
        description=normalize_description(description),
        career_path=career_path.value,
        status=CaseStatus.ACTIVE.value,
    )
    session.add(case)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:
        raise Conflict("You already have a case with this name.") from exc
    record_audit(
        session,
        "case.created",
        actor_user_id=actor.user_id,
        target_type="case",
        target_id=case.id,
        ip=actor.ip,
        request_id=actor.request_id,
    )
    return case


async def update_case(
    session: AsyncSession,
    actor: Actor,
    case_id: uuid.UUID,
    *,
    expected_version: int,
    name: str | None = None,
    description: str | object | None = _UNSET,
    career_path: CareerPath | None = None,
    status: CaseStatus | None = None,
) -> CandidateCase:
    """Optimistic concurrency: the update applies only if `expected_version` matches."""
    await get_case(session, actor, case_id)  # 404 if missing or not owned
    values: dict[str, object] = {}
    if name is not None:
        values["name"] = normalize_case_name(name)
    if description is not _UNSET:
        values["description"] = normalize_description(description)  # type: ignore[arg-type]
    if career_path is not None:
        values["career_path"] = career_path.value
    if status is not None:
        values["status"] = status.value
    if not values:
        return await get_case(session, actor, case_id)

    try:
        async with session.begin_nested():
            result = await session.execute(
                update(CandidateCase)
                .where(
                    CandidateCase.id == case_id,
                    CandidateCase.owner_user_id == actor.user_id,
                    CandidateCase.version == expected_version,
                )
                .values(**values, version=CandidateCase.version + 1)
                .returning(CandidateCase.id)
            )
            updated = result.scalar_one_or_none()
    except IntegrityError as exc:
        raise Conflict("You already have a case with this name.") from exc
    if updated is None:
        raise ConcurrencyConflict("This case was changed elsewhere. Reload and try again.")
    record_audit(
        session,
        "case.updated",
        actor_user_id=actor.user_id,
        target_type="case",
        target_id=case_id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={"fields": sorted(values)},
    )
    case = await get_case(session, actor, case_id)
    await session.refresh(case)
    return case


async def delete_case(session: AsyncSession, actor: Actor, case_id: uuid.UUID) -> None:
    case = await get_case(session, actor, case_id)
    await session.delete(case)
    record_audit(
        session,
        "case.deleted",
        actor_user_id=actor.user_id,
        target_type="case",
        target_id=case_id,
        ip=actor.ip,
        request_id=actor.request_id,
    )
