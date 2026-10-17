"""Notification channels (M11): set up, pair, test, pause and remove the user's own channels,
plus the WhatsApp Cloud API webhook (unauthenticated by design; bodies are verified by the
worker with the channel's app secret before anything is acted on)."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, Request, Response, status
from pydantic import Field
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from nexscout.api.deps import CurrentActor, DbSession, SettingsDep
from nexscout.api.schemas import ApiModel
from nexscout.application import channels
from nexscout.config import Settings
from nexscout.domain.errors import NotFound, ValidationFailed
from nexscout.infrastructure.db.models import ChannelInboundEvent, NotificationChannel

router = APIRouter(tags=["channels"])
MAX_WEBHOOK_BYTES = 256 * 1024
DEFAULT_EVENTS = [
    "approval",
    "question",
    "application",
    "reminder",
    "submitted",
    "autopilot",
    "digest",
]


class ChannelIn(ApiModel):
    kind: str = Field(max_length=20)
    name: str = Field(min_length=1, max_length=100)
    config: dict[str, str] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)
    events: list[str] = Field(default_factory=lambda: list(DEFAULT_EVENTS), max_length=20)
    quiet_start: str | None = Field(default=None, max_length=5)
    quiet_end: str | None = Field(default=None, max_length=5)
    timezone: str = Field(default="UTC", max_length=64)


class ChannelPatch(ApiModel):
    version: int
    name: str | None = Field(default=None, max_length=100)
    paused: bool | None = None
    events: list[str] | None = Field(default=None, max_length=20)
    quiet_start: str | None = Field(default=None, max_length=5)
    quiet_end: str | None = Field(default=None, max_length=5)


class WebhookInfo(ApiModel):
    callback_url: str
    verify_token: str


class ChannelOut(ApiModel):
    id: uuid.UUID
    kind: str
    name: str
    status: str
    config: dict[str, Any]
    paired: bool
    events: list[str]
    quiet_start: str | None
    quiet_end: str | None
    timezone: str
    last_error: str | None
    last_delivery_at: datetime | None
    consecutive_failures: int
    created_at: datetime
    version: int
    webhook: WebhookInfo | None = None


class ChannelCreatedOut(ApiModel):
    channel: ChannelOut
    pairing_code: str | None
    instructions: str
    signing_secret: str | None = None  # webhook channels: shown once, store it now


class PairIn(ApiModel):
    code: str = Field(min_length=4, max_length=20)


class TestOut(ApiModel):
    ok: bool
    error: str | None


class DeliveryOut(ApiModel):
    id: uuid.UUID
    status: str
    attempts: int
    last_error: str | None
    sent_at: datetime | None
    created_at: datetime
    title: str
    kind: str


# Config keys that may be shown back (never secrets; those live sealed in `secrets`).
SHOWN_CONFIG = frozenset(
    {
        "bot_username",
        "user_id",
        "chat_id",
        "phone_number_id",
        "wa_id",
        "template_name",
        "template_language",
        "smtp_host",
        "smtp_port",
        "security",
        "username",
        "from_address",
        "to_address",
        "paired",
    }
)


def _out(ch: NotificationChannel, settings: Settings) -> ChannelOut:
    webhook = None
    if ch.kind == "whatsapp":
        webhook = WebhookInfo(
            callback_url=f"{settings.public_web_url.rstrip('/')}/api/v1/channels/{ch.id}/whatsapp",
            verify_token=channels.whatsapp_verify_token(settings, ch.id),
        )
    return ChannelOut(
        id=ch.id,
        kind=ch.kind,
        name=ch.name,
        status=ch.status,
        config={k: v for k, v in ch.config.items() if k in SHOWN_CONFIG},
        paired=bool(ch.paired_identity) or ch.kind in ("webhook", "slack", "email"),
        events=list(ch.events),
        quiet_start=ch.quiet_start,
        quiet_end=ch.quiet_end,
        timezone=ch.timezone,
        last_error=ch.last_error,
        last_delivery_at=ch.last_delivery_at,
        consecutive_failures=ch.consecutive_failures,
        created_at=ch.created_at,
        version=ch.version,
        webhook=webhook,
    )


@router.get("/channels", response_model=list[ChannelOut])
async def list_channels(
    actor: CurrentActor, db: DbSession, settings: SettingsDep
) -> list[ChannelOut]:
    return [_out(c, settings) for c in await channels.list_channels(db, actor)]


@router.post("/channels", response_model=ChannelCreatedOut, status_code=status.HTTP_201_CREATED)
async def create_channel(
    body: ChannelIn, actor: CurrentActor, db: DbSession, settings: SettingsDep
) -> ChannelCreatedOut:
    try:
        created = await channels.create_channel(
            db,
            settings,
            actor,
            kind=body.kind,
            name=body.name,
            config=body.config,
            secret_values=body.secrets,
            events=body.events,
            quiet_start=body.quiet_start,
            quiet_end=body.quiet_end,
            timezone=body.timezone,
        )
        await db.flush()
    except IntegrityError as exc:
        raise ValidationFailed("You already have a channel with that name.") from exc
    await db.refresh(created.channel)
    return ChannelCreatedOut(
        channel=_out(created.channel, settings),
        pairing_code=created.pairing_code,
        signing_secret=created.signing_secret,
        instructions=created.instructions,
    )


@router.patch("/channels/{channel_id}", response_model=ChannelOut)
async def update_channel(
    channel_id: uuid.UUID,
    body: ChannelPatch,
    actor: CurrentActor,
    db: DbSession,
    settings: SettingsDep,
) -> ChannelOut:
    changes = body.model_dump(exclude={"version"}, exclude_unset=True)
    ch = await channels.update_channel(db, actor, channel_id, version=body.version, changes=changes)
    await db.flush()
    await db.refresh(ch)
    return _out(ch, settings)


@router.post("/channels/{channel_id}/pair", response_model=ChannelOut)
async def pair(
    channel_id: uuid.UUID, body: PairIn, actor: CurrentActor, db: DbSession, settings: SettingsDep
) -> ChannelOut:
    ch = await channels.confirm_pairing(db, actor, channel_id, body.code)
    await db.flush()
    await db.refresh(ch)
    return _out(ch, settings)


@router.post("/channels/{channel_id}/test", response_model=TestOut)
async def test(
    channel_id: uuid.UUID, actor: CurrentActor, db: DbSession, settings: SettingsDep
) -> TestOut:
    return TestOut(**await channels.send_test(db, settings, actor, channel_id))


@router.get("/channels/{channel_id}/deliveries", response_model=list[DeliveryOut])
async def deliveries(
    channel_id: uuid.UUID, actor: CurrentActor, db: DbSession
) -> list[DeliveryOut]:
    return [
        DeliveryOut(
            id=d.id,
            status=d.status,
            attempts=d.attempts,
            last_error=d.last_error,
            sent_at=d.sent_at,
            created_at=d.created_at,
            title=n.title,
            kind=n.kind,
        )
        for d, n in await channels.list_deliveries(db, actor, channel_id)
    ]


@router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(channel_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> Response:
    await channels.delete_channel(db, actor, channel_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- WhatsApp Cloud API webhook --------------------------------------------------------------


@router.get("/channels/{channel_id}/whatsapp", include_in_schema=False)
async def whatsapp_verify(
    channel_id: uuid.UUID,
    settings: SettingsDep,
    mode: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge", max_length=200),
) -> Response:
    expected = channels.whatsapp_verify_token(settings, channel_id)
    if mode == "subscribe" and hmac.compare_digest(token, expected):
        return Response(challenge, media_type="text/plain")
    return Response(status_code=status.HTTP_403_FORBIDDEN)


@router.post("/channels/{channel_id}/whatsapp", include_in_schema=False)
async def whatsapp_inbound(channel_id: uuid.UUID, request: Request, db: DbSession) -> Response:
    """Store the raw body for the worker (which verifies X-Hub-Signature-256). Nothing is acted
    on here, so a forged request can at most add a row that is then rejected."""
    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BYTES:
        return Response(status_code=status.HTTP_413_CONTENT_TOO_LARGE)
    try:
        payload = await request.json()
    except ValueError:
        return Response(status_code=status.HTTP_400_BAD_REQUEST)
    if not isinstance(payload, dict):
        return Response(status_code=status.HTTP_400_BAD_REQUEST)
    try:
        await db.execute(
            insert(ChannelInboundEvent)
            .values(
                channel_id=channel_id,
                provider_event_id="body:" + hashlib.sha256(raw).hexdigest(),
                payload=payload,
                raw_body=raw,
                signature=(request.headers.get("x-hub-signature-256") or "")[:200],
                status="received",
            )
            .on_conflict_do_nothing()
        )
        await db.flush()
    except IntegrityError as exc:  # unknown channel id
        raise NotFound("Not found.") from exc
    return Response(status_code=status.HTTP_200_OK)
