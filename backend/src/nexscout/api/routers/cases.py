"""Candidate case endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Response, UploadFile, status

from nexscout.api.deps import CurrentActor, DbSession, ObjectStoreDep, SettingsDep
from nexscout.api.schemas import CaseCreate, CaseImportOut, CaseOut, CaseUpdate
from nexscout.application import cases, profile_bundle
from nexscout.domain.errors import ValidationFailed

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


@router.get("/{case_id}/export")
async def export_profile(
    case_id: uuid.UUID,
    actor: CurrentActor,
    db: DbSession,
    store: ObjectStoreDep,
    documents: bool = True,
) -> Response:
    """This case's profile as a `.nexscout` file (entries, evidence, mind map, snapshots,
    relationships, answers and, optionally, the original documents). No secrets."""
    filename, data = await profile_bundle.export_case(
        db, actor, store, case_id, include_documents=documents
    )
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", response_model=CaseImportOut, status_code=status.HTTP_201_CREATED)
async def import_profile(
    file: Annotated[UploadFile, File()],
    actor: CurrentActor,
    db: DbSession,
    store: ObjectStoreDep,
    settings: SettingsDep,
) -> CaseImportOut:
    """A `.nexscout` file becomes a new case (nothing existing is changed)."""
    data = await file.read(profile_bundle.MAX_BUNDLE_BYTES + 1)
    if len(data) > profile_bundle.MAX_BUNDLE_BYTES:
        raise ValidationFailed("That file is larger than 100 MB.")
    report = await profile_bundle.import_case(
        db, actor, store, data, max_document_bytes=settings.max_upload_bytes
    )
    return CaseImportOut(
        case_id=report.case_id,
        case_name=report.case_name,
        counts=report.counts,
        warnings=report.warnings,
    )
