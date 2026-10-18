"""AI model providers (BYOK). API keys are write-only: never returned, only a short hint."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Response, status
from pydantic import Field

from nexscout.api.deps import CurrentActor, DbSession, SettingsDep
from nexscout.api.schemas import ApiModel
from nexscout.application import providers as prov
from nexscout.infrastructure.db.models import ProviderConfig

router = APIRouter(prefix="/providers", tags=["providers"])


class ProviderIn(ApiModel):
    name: str = Field(min_length=1, max_length=100)
    kind: str = Field(pattern="^(openai_compatible|anthropic|gemini|mock)$")
    model: str = Field(min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)
    context_window: int = 8192
    max_output_tokens: int = 1024
    supports_json_schema: bool = False
    is_default: bool = False
    input_cost_per_mtok: float | None = Field(default=None, ge=0)
    output_cost_per_mtok: float | None = Field(default=None, ge=0)


class ProviderOut(ApiModel):
    id: uuid.UUID
    name: str
    kind: str
    model: str
    base_url: str | None
    has_api_key: bool
    api_key_hint: str | None
    context_window: int
    max_output_tokens: int
    supports_json_schema: bool
    data_leaves_device: bool
    is_default: bool
    input_cost_per_mtok: float | None
    output_cost_per_mtok: float | None
    last_verified_at: datetime | None
    last_verification: dict[str, Any]
    version: int


class ProviderPatch(ApiModel):
    """Only the fields sent are changed. The key is write-only: send `api_key` to replace it,
    `clear_api_key` to remove it, or neither to keep it."""

    version: int
    name: str | None = Field(default=None, min_length=1, max_length=100)
    kind: str | None = Field(default=None, pattern="^(openai_compatible|anthropic|gemini|mock)$")
    model: str | None = Field(default=None, min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)
    clear_api_key: bool = False
    context_window: int | None = None
    max_output_tokens: int | None = None
    supports_json_schema: bool | None = None
    is_default: bool | None = None
    input_cost_per_mtok: float | None = Field(default=None, ge=0)
    output_cost_per_mtok: float | None = Field(default=None, ge=0)


class DefaultIn(ApiModel):
    provider_id: uuid.UUID | None


async def _out(db: DbSession, cfg: ProviderConfig) -> ProviderOut:
    return ProviderOut(
        id=cfg.id,
        name=cfg.name,
        kind=cfg.kind,
        model=cfg.model,
        base_url=cfg.base_url,
        has_api_key=cfg.secret_id is not None,
        api_key_hint=await prov.key_hint(db, cfg),
        context_window=cfg.context_window,
        max_output_tokens=cfg.max_output_tokens,
        supports_json_schema=cfg.supports_json_schema,
        data_leaves_device=cfg.data_leaves_device,
        is_default=cfg.is_default,
        input_cost_per_mtok=cfg.input_cost_per_mtok,
        output_cost_per_mtok=cfg.output_cost_per_mtok,
        last_verified_at=cfg.last_verified_at,
        last_verification=cfg.last_verification,
        version=cfg.version,
    )


@router.get("", response_model=list[ProviderOut])
async def list_providers(actor: CurrentActor, db: DbSession) -> list[ProviderOut]:
    return [await _out(db, c) for c in await prov.list_providers(db, actor)]


@router.post("", response_model=ProviderOut, status_code=status.HTTP_201_CREATED)
async def create_provider(
    body: ProviderIn, actor: CurrentActor, db: DbSession, settings: SettingsDep
) -> ProviderOut:
    cfg = await prov.create_provider(db, settings, actor, prov.ProviderInput(**body.model_dump()))
    return await _out(db, cfg)


@router.put("/default", status_code=status.HTTP_204_NO_CONTENT)
async def set_default(body: DefaultIn, actor: CurrentActor, db: DbSession) -> Response:
    await prov.set_default(db, actor, body.provider_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id: uuid.UUID,
    body: ProviderPatch,
    actor: CurrentActor,
    db: DbSession,
    settings: SettingsDep,
) -> ProviderOut:
    data = prov.ProviderUpdate(**body.model_dump(exclude_unset=True))
    cfg = await prov.update_provider(db, settings, actor, provider_id, data)
    return await _out(db, cfg)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(provider_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> Response:
    await prov.delete_provider(db, actor, provider_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{provider_id}/verify")
async def verify(
    provider_id: uuid.UUID, actor: CurrentActor, db: DbSession, settings: SettingsDep
) -> dict[str, Any]:
    return await prov.verify_provider(db, settings, actor, provider_id)
