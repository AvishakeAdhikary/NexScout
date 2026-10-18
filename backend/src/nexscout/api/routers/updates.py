"""This installation's version and whether a newer release is published."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from nexscout.api.deps import CurrentActor, SettingsDep
from nexscout.api.schemas import ApiModel
from nexscout.application.updates import version_info

router = APIRouter(tags=["updates"])


class AppVersionOut(ApiModel):
    current: str
    latest: str | None
    update_available: bool
    url: str | None
    checked_at: datetime | None


@router.get("/version", response_model=AppVersionOut)
async def get_version(_actor: CurrentActor, settings: SettingsDep) -> AppVersionOut:
    # Signed-in only, so anonymous requests can't make the server call out.
    info = await version_info(settings)
    return AppVersionOut(
        current=info.current,
        latest=info.latest,
        update_available=info.update_available,
        url=info.url,
        checked_at=info.checked_at,
    )
