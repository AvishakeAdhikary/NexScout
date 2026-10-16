"""Candidate case endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from nexscout.api.deps import CurrentActor, DbSession
from nexscout.api.schemas import CaseCreate, CaseOut, CaseUpdate
from nexscout.application import cases

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("", response_model=list[CaseOut])
async def list_cases(
    actor: CurrentActor, db: DbSession, include_archived: bool = False
) -> list[CaseOut]:
    rows = await cases.list_cases(db, actor, include_archived=include_archived)
    return [CaseOut.model_validate(r) for r in rows]


@router.post("", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
async def create_case(body: CaseCreate, actor: CurrentActor, db: DbSession) -> CaseOut:
    case = await cases.create_case(
        db, actor, name=body.name, description=body.description, career_path=body.career_path
    )
    await db.refresh(case)
    return CaseOut.model_validate(case)


@router.get("/{case_id}", response_model=CaseOut)
async def get_case(case_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> CaseOut:
    return CaseOut.model_validate(await cases.get_case(db, actor, case_id))


@router.patch("/{case_id}", response_model=CaseOut)
async def update_case(
    case_id: uuid.UUID, body: CaseUpdate, actor: CurrentActor, db: DbSession
) -> CaseOut:
    kwargs: dict[str, object] = {}
    if "description" in body.model_fields_set:
        kwargs["description"] = body.description
    case = await cases.update_case(
        db,
        actor,
        case_id,
        expected_version=body.version,
        name=body.name,
        career_path=body.career_path,
        status=body.status,
        **kwargs,
    )
    return CaseOut.model_validate(case)


@router.delete("/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_case(case_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> Response:
    await cases.delete_case(db, actor, case_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
