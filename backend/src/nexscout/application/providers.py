"""Model providers (BYOK): configure, verify, resolve for workflows, and record usage.

API keys are encrypted at rest, never returned by the API, never logged, and only decrypted
inside the worker/API process at the moment a provider client is built.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.application.actor import Actor
from nexscout.application.audit import record_audit
from nexscout.config import Settings
from nexscout.domain.errors import ConcurrencyConflict, NotFound, ValidationFailed
from nexscout.infrastructure.db.models import ProviderConfig, Secret, UsageRecord
from nexscout.infrastructure.llm.anthropic_provider import PRICING, AnthropicProvider
from nexscout.infrastructure.llm.base import (
    CompletionRequest,
    CompletionResult,
    LLMProvider,
    Message,
    ModelCapabilities,
    ProviderError,
    estimate_cost,
)
from nexscout.infrastructure.llm.gemini_provider import GeminiProvider
from nexscout.infrastructure.llm.mock import MockProvider
from nexscout.infrastructure.llm.openai_compat import OpenAICompatibleProvider
from nexscout.infrastructure.llm.structured import structured
from nexscout.infrastructure.security.secrets import SealedSecret, hint, load_secret_box
from nexscout.infrastructure.security.urls import check_outbound_url, is_local_address

KINDS = ("openai_compatible", "anthropic", "gemini", "mock")
SECRET_PURPOSE = "provider_api_key"  # noqa: S105 - a label, not a secret


@dataclass(frozen=True)
class ResolvedProvider:
    provider: LLMProvider
    config_id: uuid.UUID | None
    name: str


def _caps(cfg: ProviderConfig) -> ModelCapabilities:
    inp, out = cfg.input_cost_per_mtok, cfg.output_cost_per_mtok
    if cfg.kind == "anthropic" and inp is None and cfg.model in PRICING:
        inp, out = PRICING[cfg.model]
    return ModelCapabilities(
        context_window=cfg.context_window,
        max_output_tokens=cfg.max_output_tokens,
        json_schema=cfg.supports_json_schema,
        data_leaves_device=cfg.data_leaves_device,
        input_cost_per_mtok=inp,
        output_cost_per_mtok=out,
    )


def build_provider(
    cfg: ProviderConfig, api_key: str | None, *, allow_private: bool = True
) -> LLMProvider:
    caps = _caps(cfg)
    if cfg.kind == "mock":
        return MockProvider(capabilities=caps)
    if cfg.kind == "openai_compatible":
        return OpenAICompatibleProvider(
            base_url=cfg.base_url or "",
            model=cfg.model,
            api_key=api_key,
            capabilities=caps,
            display_name=cfg.name,
            allow_private=allow_private,
        )
    if not api_key:
        raise ValidationFailed(f"“{cfg.name}” needs an API key.")
    if cfg.kind == "anthropic":
        return AnthropicProvider(
            api_key=api_key,
            model=cfg.model,
            capabilities=caps,
            refusal_fallback=True,
            display_name=cfg.name,
        )
    if cfg.kind == "gemini":
        return GeminiProvider(
            api_key=api_key, model=cfg.model, capabilities=caps, display_name=cfg.name
        )
    raise ValidationFailed("Unknown provider type.")


async def _api_key(session: AsyncSession, settings: Settings, cfg: ProviderConfig) -> str | None:
    if cfg.secret_id is None:
        return None
    row = await session.get(Secret, cfg.secret_id)
    if row is None or row.owner_user_id != cfg.owner_user_id:
        return None
    box = load_secret_box(settings)
    return box.open(
        SealedSecret(row.ciphertext, row.nonce, row.key_id),
        owner_id=cfg.owner_user_id,
        purpose=SECRET_PURPOSE,
    )


class ProviderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str
    kind: str
    model: str
    base_url: str | None = None
    api_key: str | None = None
    context_window: int = 8192
    max_output_tokens: int = 1024
    supports_json_schema: bool = False
    is_default: bool = False
    input_cost_per_mtok: float | None = None
    output_cost_per_mtok: float | None = None


def _validate(data: ProviderInput, settings: Settings) -> tuple[str | None, bool]:
    if data.kind not in KINDS:
        raise ValidationFailed("Choose a supported provider type.")
    if not (1 <= len(data.name) <= 100) or not (1 <= len(data.model) <= 200):
        raise ValidationFailed("Name and model are required.")
    if not (1024 <= data.context_window <= 2_000_000) or not (
        16 <= data.max_output_tokens <= 200_000
    ):
        raise ValidationFailed("Context window or output limit is out of range.")
    base_url: str | None = None
    leaves = True
    if data.kind == "openai_compatible":
        if not data.base_url:
            raise ValidationFailed("Enter the server address, e.g. http://localhost:11434/v1.")
        # Resolve now only when private networks are disallowed; the adapter re-checks the
        # resolved addresses on every request (protects against DNS rebinding).
        base_url = check_outbound_url(
            data.base_url,
            allow_private=settings.allow_private_provider_urls,
            resolve=not settings.allow_private_provider_urls,
        )
        leaves = not is_local_address(base_url)
    elif data.kind == "mock":
        leaves = False
    if data.api_key is not None and len(data.api_key) > 500:
        raise ValidationFailed("That API key is too long.")
    return base_url, leaves


async def list_providers(session: AsyncSession, actor: Actor) -> list[ProviderConfig]:
    return list(
        await session.scalars(
            select(ProviderConfig)
            .where(ProviderConfig.owner_user_id == actor.user_id)
            .order_by(ProviderConfig.created_at)
        )
    )


async def _get(session: AsyncSession, actor: Actor, provider_id: uuid.UUID) -> ProviderConfig:
    cfg = await session.scalar(
        select(ProviderConfig).where(
            ProviderConfig.id == provider_id, ProviderConfig.owner_user_id == actor.user_id
        )
    )
    if cfg is None:
        raise NotFound("Provider not found.")
    return cfg


async def _store_key(session: AsyncSession, settings: Settings, actor: Actor, key: str) -> Secret:
    sealed = load_secret_box(settings).seal(key, owner_id=actor.user_id, purpose=SECRET_PURPOSE)
    row = Secret(
        owner_user_id=actor.user_id,
        purpose=SECRET_PURPOSE,
        ciphertext=sealed.ciphertext,
        nonce=sealed.nonce,
        key_id=sealed.key_id,
        hint=hint(key),
    )
    session.add(row)
    await session.flush()
    return row


async def create_provider(
    session: AsyncSession, settings: Settings, actor: Actor, data: ProviderInput
) -> ProviderConfig:
    base_url, leaves = _validate(data, settings)
    secret = await _store_key(session, settings, actor, data.api_key) if data.api_key else None
    if data.is_default:
        await session.execute(
            update(ProviderConfig)
            .where(ProviderConfig.owner_user_id == actor.user_id)
            .values(is_default=False)
        )
    cfg = ProviderConfig(
        owner_user_id=actor.user_id,
        name=data.name,
        kind=data.kind,
        base_url=base_url,
        model=data.model,
        secret_id=secret.id if secret else None,
        context_window=data.context_window,
        max_output_tokens=data.max_output_tokens,
        supports_json_schema=data.supports_json_schema,
        data_leaves_device=leaves,
        is_default=data.is_default,
        input_cost_per_mtok=data.input_cost_per_mtok,
        output_cost_per_mtok=data.output_cost_per_mtok,
    )
    session.add(cfg)
    await session.flush()
    record_audit(
        session,
        "provider.created",
        actor_user_id=actor.user_id,
        target_type="provider",
        target_id=cfg.id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={"kind": data.kind, "has_key": bool(secret)},
    )
    await session.refresh(cfg)
    return cfg


async def delete_provider(session: AsyncSession, actor: Actor, provider_id: uuid.UUID) -> None:
    cfg = await _get(session, actor, provider_id)
    secret_id = cfg.secret_id
    await session.delete(cfg)
    if secret_id:
        secret = await session.get(Secret, secret_id)
        if secret is not None:
            await session.delete(secret)
    record_audit(
        session,
        "provider.deleted",
        actor_user_id=actor.user_id,
        target_type="provider",
        target_id=provider_id,
        ip=actor.ip,
        request_id=actor.request_id,
    )


async def set_default(
    session: AsyncSession,
    actor: Actor,
    provider_id: uuid.UUID | None,
    expected_version: int | None = None,
) -> None:
    await session.execute(
        update(ProviderConfig)
        .where(ProviderConfig.owner_user_id == actor.user_id)
        .values(is_default=False)
    )
    if provider_id is not None:
        cfg = await _get(session, actor, provider_id)
        if expected_version is not None and cfg.version != expected_version:
            raise ConcurrencyConflict("This provider was changed elsewhere.")
        cfg.is_default = True
        cfg.version += 1


async def key_hint(session: AsyncSession, cfg: ProviderConfig) -> str | None:
    if cfg.secret_id is None:
        return None
    row = await session.get(Secret, cfg.secret_id)
    return row.hint if row else None


class _Ping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool


async def verify_provider(
    session: AsyncSession, settings: Settings, actor: Actor, provider_id: uuid.UUID
) -> dict[str, Any]:
    """Live check with a tiny prompt that contains no personal data."""
    cfg = await _get(session, actor, provider_id)
    provider = build_provider(
        cfg,
        await _api_key(session, settings, cfg),
        allow_private=settings.allow_private_provider_urls,
    )
    request = CompletionRequest(
        messages=[Message("user", 'Reply with the JSON {"ok": true}.')],
        max_tokens=64,
        timeout_s=60,
        purpose="provider.verify",
        mock_inputs={},
    )
    outcome: dict[str, Any] = {
        "checked_at": datetime.now(UTC).isoformat(),
        "schema_mode": "native" if cfg.supports_json_schema else "instructions",
    }
    try:
        res = await structured(provider, request, _Ping)
        outcome.update(
            ok=bool(res.value.ok),
            latency_ms=sum(c.latency_ms for c in res.calls),
            model_reported=res.calls[-1].model,
            repairs=len(res.calls) - 1,
        )
        for call in res.calls:
            await record_usage(
                session, actor.user_id, None, call, "provider.verify", provider.capabilities
            )
    except ProviderError as exc:
        outcome.update(ok=False, error=str(exc))
    cfg.last_verified_at = datetime.now(UTC)
    cfg.last_verification = outcome
    record_audit(
        session,
        "provider.verified",
        actor_user_id=actor.user_id,
        target_type="provider",
        target_id=cfg.id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={"ok": outcome.get("ok")},
    )
    return outcome


async def resolve_provider(
    session: AsyncSession,
    settings: Settings,
    owner_id: uuid.UUID,
    provider_id: uuid.UUID | None = None,
) -> ResolvedProvider:
    """The provider a workflow should use: explicit choice, else the user's default, else the
    built-in labelled mock."""
    stmt = select(ProviderConfig).where(ProviderConfig.owner_user_id == owner_id)
    stmt = (
        stmt.where(ProviderConfig.id == provider_id)
        if provider_id
        else stmt.where(ProviderConfig.is_default.is_(True))
    )
    cfg = await session.scalar(stmt)
    if cfg is None:
        if provider_id:
            raise NotFound("Provider not found.")
        mock = MockProvider()
        return ResolvedProvider(mock, None, mock.display_name)
    return ResolvedProvider(
        build_provider(
            cfg,
            await _api_key(session, settings, cfg),
            allow_private=settings.allow_private_provider_urls,
        ),
        cfg.id,
        cfg.name,
    )


async def record_usage(
    session: AsyncSession,
    owner_id: uuid.UUID,
    run_id: uuid.UUID | None,
    result: CompletionResult,
    purpose: str,
    caps: ModelCapabilities,
) -> None:
    session.add(
        UsageRecord(
            owner_user_id=owner_id,
            run_id=run_id,
            provider_kind=result.provider_kind,
            model=result.model[:200],
            purpose=purpose[:100],
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            latency_ms=result.latency_ms,
            estimated_cost_usd=estimate_cost(caps, result.usage),
            is_mock=result.is_mock,
        )
    )
