"""Account data rights: export and deletion."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Response, status
from pydantic import Field

from nexscout.api.deps import CurrentActor, DbSession, ObjectStoreDep, SettingsDep
from nexscout.api.schemas import AccountDelete, ApiModel
from nexscout.application import account, tokens
from nexscout.infrastructure.db.models import PersonalAccessToken

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


class TokenIn(ApiModel):
    name: str = Field(min_length=1, max_length=100)
    expires_in_days: int | None = Field(default=90, ge=1, le=365)


class TokenOut(ApiModel):
    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked: bool


class TokenCreatedOut(TokenOut):
    token: str  # shown once


def _token(t: PersonalAccessToken) -> TokenOut:
    return TokenOut(
        id=t.id,
        name=t.name,
        prefix=t.prefix,
        scopes=list(t.scopes),
        created_at=t.created_at,
        expires_at=t.expires_at,
        last_used_at=t.last_used_at,
        revoked=t.revoked_at is not None,
    )


@router.get("/tokens", response_model=list[TokenOut])
async def list_tokens(actor: CurrentActor, db: DbSession) -> list[TokenOut]:
    return [_token(t) for t in await tokens.list_tokens(db, actor)]


@router.post("/tokens", response_model=TokenCreatedOut, status_code=status.HTTP_201_CREATED)
async def create_token(body: TokenIn, actor: CurrentActor, db: DbSession) -> TokenCreatedOut:
    row, plain = await tokens.create_token(
        db, actor, name=body.name, expires_in_days=body.expires_in_days
    )
    return TokenCreatedOut(**_token(row).model_dump(), token=plain)


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(token_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> Response:
    await tokens.revoke_token(db, actor, token_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
