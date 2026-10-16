"""Account data rights: export and deletion."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from nexscout.api.deps import CurrentActor, DbSession, ObjectStoreDep, SettingsDep
from nexscout.api.schemas import AccountDelete
from nexscout.application import account

router = APIRouter(prefix="/me", tags=["account"])


@router.get("/export")
async def export(actor: CurrentActor, db: DbSession, store: ObjectStoreDep) -> Response:
    filename, data = await account.export_account(db, actor, store)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    body: AccountDelete,
    actor: CurrentActor,
    db: DbSession,
    store: ObjectStoreDep,
    settings: SettingsDep,
) -> Response:
    await account.delete_account(db, actor, store, password=body.password)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    return response
