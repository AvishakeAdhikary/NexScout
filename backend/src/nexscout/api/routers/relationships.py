"""Preferences, social/profile links, affiliations."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from nexscout.api.deps import CurrentActor, DbSession
from nexscout.api.schemas import (
    AffiliationFields,
    AffiliationOut,
    AffiliationUpdate,
    PreferencesOut,
    PreferencesPut,
    SocialProfileCreate,
    SocialProfileOut,
)
from nexscout.application import relationships as rel

router = APIRouter(tags=["preferences & relationships"])


@router.get("/cases/{case_id}/preferences", response_model=PreferencesOut)
async def get_preferences(case_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> PreferencesOut:
    prefs, version = await rel.get_preferences(db, actor, case_id)
    return PreferencesOut(data=prefs, version=version)


@router.put("/cases/{case_id}/preferences", response_model=PreferencesOut)
async def put_preferences(
    case_id: uuid.UUID, body: PreferencesPut, actor: CurrentActor, db: DbSession
) -> PreferencesOut:
    prefs, version = await rel.put_preferences(
        db, actor, case_id, data=body.data, expected_version=body.version
    )
    return PreferencesOut(data=prefs, version=version)


@router.get("/cases/{case_id}/social-profiles", response_model=list[SocialProfileOut])
async def list_links(
    case_id: uuid.UUID, actor: CurrentActor, db: DbSession
) -> list[SocialProfileOut]:
    return [
        SocialProfileOut.model_validate(r)
        for r in await rel.list_social_profiles(db, actor, case_id)
    ]


@router.post(
    "/cases/{case_id}/social-profiles",
    response_model=SocialProfileOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_link(
    case_id: uuid.UUID, body: SocialProfileCreate, actor: CurrentActor, db: DbSession
) -> SocialProfileOut:
    row = await rel.add_social_profile(db, actor, case_id, url=body.url, label=body.label)
    await db.refresh(row)
    return SocialProfileOut.model_validate(row)


@router.delete("/social-profiles/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_link(link_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> Response:
    await rel.delete_social_profile(db, actor, link_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/cases/{case_id}/affiliations", response_model=list[AffiliationOut])
async def list_affiliations(
    case_id: uuid.UUID, actor: CurrentActor, db: DbSession
) -> list[AffiliationOut]:
    return [
        AffiliationOut.model_validate(r) for r in await rel.list_affiliations(db, actor, case_id)
    ]


@router.post(
    "/cases/{case_id}/affiliations",
    response_model=AffiliationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_affiliation(
    case_id: uuid.UUID, body: AffiliationFields, actor: CurrentActor, db: DbSession
) -> AffiliationOut:
    values = body.model_dump(exclude_unset=True)
    row = await rel.create_affiliation(db, actor, case_id, values)
    return AffiliationOut.model_validate(row)


@router.patch("/affiliations/{affiliation_id}", response_model=AffiliationOut)
async def update_affiliation(
    affiliation_id: uuid.UUID, body: AffiliationUpdate, actor: CurrentActor, db: DbSession
) -> AffiliationOut:
    values = body.model_dump(exclude_unset=True, exclude={"version"})
    row = await rel.update_affiliation(
        db, actor, affiliation_id, expected_version=body.version, values=values
    )
    return AffiliationOut.model_validate(row)


@router.delete("/affiliations/{affiliation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_affiliation(
    affiliation_id: uuid.UUID, actor: CurrentActor, db: DbSession
) -> Response:
    await rel.delete_affiliation(db, actor, affiliation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
