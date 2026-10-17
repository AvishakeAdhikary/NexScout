"""Notification channels: setup and pairing (user), the delivery outbox and inbound actions
(worker). See AGENTS.md §4a and ADR-0013.

Security model:
- Credentials are sealed secrets bound to the owner and a per-kind purpose; never returned.
- A channel acts only for its **paired identity** (chat id / user id / phone), proven by a
  one-time code. Button tokens are single-use, expire, and are bound to one channel.
- Delivery is a transactional outbox with retries, backoff with jitter and a dead-letter state;
  repeated permanent failures pause the channel (circuit breaker).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import random
import re
import secrets as pysecrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexscout.application.actor import Actor
from nexscout.application.audit import record_audit
from nexscout.config import Settings
from nexscout.domain.errors import DomainError, NotFound, ValidationFailed
from nexscout.infrastructure.channels import ADAPTERS, new_client
from nexscout.infrastructure.channels.base import (
    ActionButton,
    ChannelError,
    OutboundMessage,
)
from nexscout.infrastructure.db.engine import bind_tenant
from nexscout.infrastructure.db.models import (
    ChannelAction,
    ChannelInboundEvent,
    Notification,
    NotificationChannel,
    NotificationDelivery,
    Secret,
)
from nexscout.infrastructure.security.secrets import SealedSecret, load_secret_box
from nexscout.infrastructure.security.urls import check_outbound_url

log = structlog.get_logger()

KINDS = ("webhook", "slack", "email", "telegram", "discord", "whatsapp")
EVENTS = (
    "approval",
    "question",
    "application",
    "reminder",
    "submitted",
    "autopilot",
    "digest",
    "test",
)
URGENT = frozenset({"approval", "question"})  # still respect quiet hours, but deliver first
MAX_ATTEMPTS = 8
BREAKER_FAILURES = 5
PAIRING_TTL = timedelta(minutes=30)
ACTION_TTL = timedelta(days=7)

# Required fields per kind: (config keys, secret keys).
FIELDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "webhook": ((), ("url",)),
    "slack": ((), ("webhook_url",)),
    "email": (("smtp_host", "from_address", "to_address"), ()),
    "telegram": ((), ("bot_token",)),
    "discord": (("user_id",), ("bot_token",)),
    "whatsapp": (("phone_number_id",), ("access_token", "app_secret")),
}


# --- small helpers -------------------------------------------------------------------------


def _purpose(kind: str) -> str:
    return f"channel:{kind}"


def _hash(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


def new_pairing_code() -> str:
    return pysecrets.token_hex(4).upper()


def whatsapp_verify_token(settings: Settings, channel_id: uuid.UUID) -> str:
    """Deterministic per-channel webhook verify token (derived from the master key), so the
    API can answer Meta's verification request without reading user data."""
    return load_secret_box(settings).derive(f"whatsapp-verify:{channel_id}")


def _seal(settings: Settings, owner: uuid.UUID, kind: str, data: dict[str, str]) -> Secret:
    sealed = load_secret_box(settings).seal(
        json.dumps(data), owner_id=owner, purpose=_purpose(kind)
    )
    return Secret(
        owner_user_id=owner,
        purpose=_purpose(kind),
        ciphertext=sealed.ciphertext,
        nonce=sealed.nonce,
        key_id=sealed.key_id,
        hint=None,
    )


async def channel_secrets(
    s: AsyncSession, settings: Settings, ch: NotificationChannel
) -> dict[str, str]:
    if ch.secret_id is None:
        return {}
    row = await s.get(Secret, ch.secret_id)
    if row is None or row.owner_user_id != ch.owner_user_id:
        return {}
    plain = load_secret_box(settings).open(
        SealedSecret(row.ciphertext, row.nonce, row.key_id),
        owner_id=ch.owner_user_id,
        purpose=_purpose(ch.kind),
    )
    data: dict[str, str] = json.loads(plain)
    return data


def _check_quiet(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(value)):
        raise ValidationFailed("Quiet hours use HH:MM, e.g. 22:00.")
    return str(value)


def in_quiet_hours(ch: NotificationChannel, now: datetime) -> datetime | None:
    """When quiet hours are on, the time they end (else None)."""
    if not ch.quiet_start or not ch.quiet_end:
        return None
    try:
        tz = ZoneInfo(ch.timezone or "UTC")
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    local = now.astimezone(tz)
    start = time.fromisoformat(ch.quiet_start)
    end = time.fromisoformat(ch.quiet_end)
    t = local.time()
    quiet = (start <= t < end) if start < end else (t >= start or t < end)
    if not quiet:
        return None
    end_dt = local.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if end_dt <= local:
        end_dt += timedelta(days=1)
    return end_dt.astimezone(UTC)


# --- user-facing use cases -----------------------------------------------------------------


@dataclass
class CreatedChannel:
    channel: NotificationChannel
    pairing_code: str | None
    instructions: str
    signing_secret: str | None = None  # webhook only; shown once


async def create_channel(
    s: AsyncSession,
    settings: Settings,
    actor: Actor,
    *,
    kind: str,
    name: str,
    config: dict[str, Any],
    secret_values: dict[str, str],
    events: list[str],
    quiet_start: str | None,
    quiet_end: str | None,
    timezone: str,
) -> CreatedChannel:
    if kind not in KINDS:
        raise ValidationFailed("Unknown channel type.")
    need_cfg, need_secret = FIELDS[kind]
    config = {k: str(v).strip() for k, v in (config or {}).items() if v not in (None, "")}
    secret_values = {k: str(v).strip() for k, v in (secret_values or {}).items() if v}
    missing = [k for k in need_cfg if not config.get(k)] + [
        k for k in need_secret if not secret_values.get(k)
    ]
    if missing:
        raise ValidationFailed(f"Missing: {', '.join(missing)}.")
    bad_events = [e for e in events if e not in EVENTS]
    if bad_events:
        raise ValidationFailed(f"Unknown events: {', '.join(bad_events)}.")
    try:
        ZoneInfo(timezone or "UTC")
    except ZoneInfoNotFoundError as exc:
        raise ValidationFailed("Unknown time zone.") from exc

    instructions = ""
    code: str | None = None
    status = "active"
    if kind == "webhook":
        secret_values["url"] = check_outbound_url(
            secret_values["url"], allow_private=settings.allow_private_provider_urls
        )
        secret_values.setdefault("signing_secret", pysecrets.token_urlsafe(32))
        instructions = (
            "Verify each request with the X-NexScout-Signature header: "
            "HMAC-SHA256 of '<X-NexScout-Timestamp>.<body>' with your signing secret."
        )
    elif kind == "slack":
        if not secret_values["webhook_url"].startswith("https://hooks.slack.com/"):
            raise ValidationFailed(
                "Use a Slack incoming-webhook address (https://hooks.slack.com/...)."
            )
    elif kind == "email":
        if "@" not in config["to_address"] or "@" not in config["from_address"]:
            raise ValidationFailed("Check the email addresses.")
        if config.get("security", "starttls") not in ("starttls", "ssl", "none"):
            raise ValidationFailed("Security must be starttls, ssl or none.")
    elif kind == "telegram":
        from nexscout.infrastructure.channels.telegram import get_me

        async with new_client() as client:
            try:
                me = await get_me(client, secret_values["bot_token"])
            except ChannelError as exc:
                raise ValidationFailed(f"Telegram didn't accept the bot token: {exc}") from exc
        config["bot_username"] = str(me.get("username", ""))
        code, status = new_pairing_code(), "pending_pairing"
        instructions = (
            f"Open Telegram, find @{config['bot_username']} and send: /start {code} "
            "(the code is valid for 30 minutes)."
        )
    elif kind == "discord":
        if not re.fullmatch(r"\d{15,22}", config["user_id"]):
            raise ValidationFailed(
                "A Discord user id is a 17-20 digit number (Developer Mode → "
                "right-click your name → Copy User ID)."
            )
        code, status = new_pairing_code(), "pending_pairing"
        instructions = (
            "NexScout's bot sent you a Discord direct message with a code. Enter it "
            "here to finish pairing. (Share a server with the bot first so it can DM you.)"
        )
    elif kind == "whatsapp":
        if not re.fullmatch(r"\d{6,20}", config["phone_number_id"]):
            raise ValidationFailed(
                "The phone number id is the numeric id from Meta's WhatsApp setup."
            )
        code, status = new_pairing_code(), "pending_pairing"
        instructions = (
            f"Send 'PAIR {code}' from your WhatsApp to your business number. Webhook "
            "callback URL and verify token are shown on the channel."
        )

    secret_row = _seal(settings, actor.user_id, kind, secret_values)
    s.add(secret_row)
    await s.flush()
    ch = NotificationChannel(
        owner_user_id=actor.user_id,
        kind=kind,
        name=name.strip()[:100],
        status=status,
        config=config,
        secret_id=secret_row.id,
        events=list(events),
        quiet_start=_check_quiet(quiet_start),
        quiet_end=_check_quiet(quiet_end),
        timezone=timezone or "UTC",
        pairing_code_hash=_hash(code) if code else None,
        pairing_expires_at=datetime.now(UTC) + PAIRING_TTL if code else None,
    )
    s.add(ch)
    await s.flush()
    if kind == "discord" and code:
        from nexscout.infrastructure.channels.discord import DiscordAdapter

        async with new_client() as client:
            try:
                await DiscordAdapter().send_dm(
                    client,
                    secret_values["bot_token"],
                    config["user_id"],
                    OutboundMessage(
                        f"Your NexScout pairing code: {code}",
                        "Enter it in NexScout to connect this Discord account.",
                    ),
                )
            except ChannelError as exc:
                raise ValidationFailed(f"Discord couldn't send the pairing message: {exc}") from exc
    record_audit(
        s,
        "channel.created",
        actor_user_id=actor.user_id,
        target_type="channel",
        target_id=ch.id,
        meta={"kind": kind},
    )
    return CreatedChannel(
        ch, code, instructions, secret_values.get("signing_secret") if kind == "webhook" else None
    )


async def _get(
    s: AsyncSession, actor: Actor, channel_id: uuid.UUID, *, lock: bool = False
) -> NotificationChannel:
    stmt = select(NotificationChannel).where(
        NotificationChannel.id == channel_id, NotificationChannel.owner_user_id == actor.user_id
    )
    if lock:
        stmt = stmt.with_for_update()
    ch = await s.scalar(stmt)
    if ch is None:
        raise NotFound("Channel not found.")
    return ch


async def list_channels(s: AsyncSession, actor: Actor) -> list[NotificationChannel]:
    return list(
        await s.scalars(
            select(NotificationChannel)
            .where(NotificationChannel.owner_user_id == actor.user_id)
            .order_by(NotificationChannel.created_at)
        )
    )


async def confirm_pairing(
    s: AsyncSession, actor: Actor, channel_id: uuid.UUID, code: str
) -> NotificationChannel:
    """Discord: the user types the code the bot sent them."""
    ch = await _get(s, actor, channel_id, lock=True)
    if ch.status != "pending_pairing" or ch.kind != "discord":
        raise ValidationFailed("This channel isn't waiting for a code.")
    if not _pairing_ok(ch, code):
        raise ValidationFailed(
            "That code is wrong or expired. Remove the channel and add it again."
        )
    _activate(ch, str(ch.config["user_id"]), {"paired": True})
    record_audit(
        s, "channel.paired", actor_user_id=actor.user_id, target_type="channel", target_id=ch.id
    )
    return ch


def _pairing_ok(ch: NotificationChannel, code: str) -> bool:
    if not ch.pairing_code_hash or not ch.pairing_expires_at:
        return False
    if ch.pairing_expires_at < datetime.now(UTC):
        return False
    return hmac.compare_digest(ch.pairing_code_hash, _hash(code))


def _activate(ch: NotificationChannel, identity: str, extra: dict[str, Any]) -> None:
    ch.status = "active"
    ch.paired_identity = identity
    ch.config = {**ch.config, **extra}
    ch.pairing_code_hash = None
    ch.pairing_expires_at = None
    ch.consecutive_failures = 0
    ch.version += 1


async def update_channel(
    s: AsyncSession, actor: Actor, channel_id: uuid.UUID, *, version: int, changes: dict[str, Any]
) -> NotificationChannel:
    ch = await _get(s, actor, channel_id, lock=True)
    if ch.version != version:
        raise ValidationFailed("This channel changed. Reload and try again.")
    if "paused" in changes and changes["paused"] is not None:
        if changes["paused"]:
            ch.status = "paused" if ch.status in ("active", "error") else ch.status
        elif ch.status in ("paused", "error"):
            ch.status = (
                "active"
                if ch.paired_identity or ch.kind in ("webhook", "slack", "email")
                else "pending_pairing"
            )
            ch.consecutive_failures = 0
    if changes.get("events") is not None:
        bad = [e for e in changes["events"] if e not in EVENTS]
        if bad:
            raise ValidationFailed(f"Unknown events: {', '.join(bad)}.")
        ch.events = list(changes["events"])
    if "quiet_start" in changes:
        ch.quiet_start = _check_quiet(changes["quiet_start"])
    if "quiet_end" in changes:
        ch.quiet_end = _check_quiet(changes["quiet_end"])
    if changes.get("name"):
        ch.name = str(changes["name"])[:100]
    ch.version += 1
    return ch


async def delete_channel(s: AsyncSession, actor: Actor, channel_id: uuid.UUID) -> None:
    ch = await _get(s, actor, channel_id)
    secret_id = ch.secret_id
    await s.delete(ch)
    if secret_id:
        sec = await s.get(Secret, secret_id)
        if sec is not None:
            await s.delete(sec)
    record_audit(
        s,
        "channel.deleted",
        actor_user_id=actor.user_id,
        target_type="channel",
        target_id=channel_id,
    )


async def send_test(
    s: AsyncSession, settings: Settings, actor: Actor, channel_id: uuid.UUID
) -> dict[str, Any]:
    """Send a test message right away (not through the outbox) and report the result."""
    ch = await _get(s, actor, channel_id)
    if ch.status not in ("active", "error"):
        raise ValidationFailed("Pair the channel first.")
    msg = OutboundMessage(
        "NexScout test message",
        "If you can read this, notifications reach you here.",
        link=settings.public_web_url,
        event="test",
    )
    sec = await channel_secrets(s, settings, ch)
    async with new_client() as client:
        try:
            await ADAPTERS[ch.kind].send(client, ch.config, sec, msg)
        except ChannelError as exc:
            ch.last_error = str(exc)[:500]
            return {"ok": False, "error": str(exc)}
    ch.last_error = None
    ch.last_delivery_at = datetime.now(UTC)
    return {"ok": True, "error": None}


async def list_deliveries(
    s: AsyncSession, actor: Actor, channel_id: uuid.UUID
) -> list[tuple[NotificationDelivery, Notification]]:
    await _get(s, actor, channel_id)
    rows = await s.execute(
        select(NotificationDelivery, Notification)
        .join(Notification, Notification.id == NotificationDelivery.notification_id)
        .where(
            NotificationDelivery.channel_id == channel_id,
            NotificationDelivery.owner_user_id == actor.user_id,
        )
        .order_by(NotificationDelivery.created_at.desc())
        .limit(50)
    )
    return [(d, n) for d, n in rows.all()]


# --- outbox (system role, worker) -------------------------------------------------------------


async def enqueue_deliveries(
    s: AsyncSession, *, owner: uuid.UUID, notification_id: uuid.UUID, kind: str
) -> int:
    """Called in the same transaction that created the notification (transactional outbox)."""
    channels = await s.scalars(
        select(NotificationChannel).where(
            NotificationChannel.owner_user_id == owner, NotificationChannel.status == "active"
        )
    )
    n = 0
    for ch in channels:
        if ch.events and kind not in ch.events:
            continue
        res = await s.execute(
            insert(NotificationDelivery)
            .values(
                id=uuid.uuid4(),
                owner_user_id=owner,
                notification_id=notification_id,
                channel_id=ch.id,
                status="pending",
            )
            .on_conflict_do_nothing(constraint="uq_deliveries_notification_channel")
            .returning(NotificationDelivery.id)
        )
        n += int(res.scalar() is not None)
    return n


async def claim_due(
    s: AsyncSession, now: datetime, limit: int = 20
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Lease due rows (SKIP LOCKED, so several workers can share the outbox)."""
    rows = list(
        await s.scalars(
            select(NotificationDelivery)
            .where(
                or_(
                    (NotificationDelivery.status == "pending")
                    & (NotificationDelivery.next_attempt_at <= now),
                    (NotificationDelivery.status == "sending")
                    & (NotificationDelivery.locked_until < now),
                )
            )
            .order_by(NotificationDelivery.next_attempt_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    for d in rows:
        d.status = "sending"
        d.locked_until = now + timedelta(seconds=90)
        d.attempts += 1
    return [(d.id, d.channel_id) for d in rows]


def _backoff(attempt: int) -> timedelta:
    return timedelta(seconds=min(3600, 15 * 2 ** (attempt - 1)) * (0.75 + random.random() / 2))  # noqa: S311


async def _build_message(
    s: AsyncSession, settings: Settings, ch: NotificationChannel, n: Notification
) -> OutboundMessage:
    base = settings.public_web_url.rstrip("/")
    link = f"{base}{n.link}" if n.link and n.link.startswith("/") else (n.link or base)
    actions: list[ActionButton] = []
    reply_hint = None
    data = n.data or {}
    interactive = ch.kind in ("telegram", "discord", "whatsapp")
    if interactive and n.kind == "approval" and data.get("approval_id"):
        for action, label, style in (
            ("approve", "Approve", "primary"),
            ("reject", "Reject", "danger"),
        ):
            token = pysecrets.token_urlsafe(18)[:24]
            s.add(
                ChannelAction(
                    id=token,
                    owner_user_id=n.owner_user_id,
                    channel_id=ch.id,
                    notification_id=n.id,
                    action=action,
                    target={"approval_id": data["approval_id"]},
                    expires_at=datetime.now(UTC) + ACTION_TTL,
                )
            )
            actions.append(ActionButton(label, token=token, style=style))
    if interactive and n.kind == "question" and data.get("question"):
        reply_hint = "Reply to this message with your answer. NexScout will reuse it next time."
    return OutboundMessage(
        n.title, n.body or "", link=link, actions=actions, reply_hint=reply_hint, event=n.kind
    )


async def deliver_one(
    sessions: async_sessionmaker[AsyncSession], settings: Settings, delivery_id: uuid.UUID
) -> str:
    """Deliver one claimed row. Returns the final status."""
    now = datetime.now(UTC)
    async with sessions() as s, s.begin():
        d = await s.get(NotificationDelivery, delivery_id, with_for_update=True)
        if d is None or d.status != "sending":
            return "gone"
        ch = await s.get(NotificationChannel, d.channel_id)
        n = await s.get(Notification, d.notification_id)
        if ch is None or n is None or ch.status not in ("active",):
            d.status, d.last_error = "skipped", "Channel paused or removed."
            return d.status
        if (until := in_quiet_hours(ch, now)) is not None:
            d.status, d.next_attempt_at, d.attempts = "pending", until, max(0, d.attempts - 1)
            d.locked_until = None
            return "deferred"
        msg = await _build_message(s, settings, ch, n)
        sec = await channel_secrets(s, settings, ch)
        kind, config, attempts = ch.kind, dict(ch.config), d.attempts
    try:
        if kind == "webhook":  # re-check at send time (DNS may have changed since setup)
            try:
                await asyncio.to_thread(
                    check_outbound_url,
                    sec.get("url", ""),
                    allow_private=settings.allow_private_provider_urls,
                )
            except DomainError as exc:
                raise ChannelError(f"Webhook address not allowed: {exc}", transient=False) from exc
        async with new_client() as client:
            result = await ADAPTERS[kind].send(client, config, sec, msg)
        error: ChannelError | None = None
    except ChannelError as exc:
        error, result = exc, None
    async with sessions() as s, s.begin():
        d = await s.get(NotificationDelivery, delivery_id, with_for_update=True)
        ch = await s.get(NotificationChannel, d.channel_id, with_for_update=True) if d else None
        if d is None or ch is None:
            return "gone"
        if error is None:
            d.status, d.sent_at, d.last_error = "sent", datetime.now(UTC), None
            d.provider_message_id = result.provider_message_id if result else None
            ch.consecutive_failures, ch.last_error, ch.last_delivery_at = 0, None, d.sent_at
        else:
            d.last_error = str(error)[:500]
            ch.last_error = d.last_error
            if error.transient and attempts < MAX_ATTEMPTS:
                d.status, d.next_attempt_at = "pending", datetime.now(UTC) + _backoff(attempts)
            else:
                d.status = "dead"
                ch.consecutive_failures += 1
                if ch.consecutive_failures >= BREAKER_FAILURES:
                    ch.status = "error"  # circuit open: the user sees it in Settings
        d.locked_until = None
        log.info("notification_delivery", status=d.status, kind=kind, attempts=attempts)
        return d.status


# --- inbound (worker) ---------------------------------------------------------------------


async def record_inbound(
    s: AsyncSession, channel_id: uuid.UUID, event_id: str, payload: dict[str, Any]
) -> bool:
    """False when this provider event was already processed (idempotency)."""
    res = await s.execute(
        insert(ChannelInboundEvent)
        .values(
            channel_id=channel_id,
            provider_event_id=event_id[:200],
            payload=payload,
            status="processed",
            processed_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing()
        .returning(ChannelInboundEvent.provider_event_id)
    )
    return res.scalar() is not None


_PAIR = re.compile(r"^(?:/start|pair)\s+([0-9A-Fa-f]{8})\s*$", re.I)


async def handle_text(
    system: async_sessionmaker[AsyncSession],
    app: async_sessionmaker[AsyncSession],
    channel_id: uuid.UUID,
    identity: str,
    text: str,
    reply_to: str | None,
    extra: dict[str, Any],
) -> str | None:
    """Pairing messages and answers. Returns a reply to send back, or None."""
    async with system() as s, s.begin():
        ch = await s.get(NotificationChannel, channel_id, with_for_update=True)
        if ch is None:
            return None
        m = _PAIR.match(text.strip())
        if ch.status == "pending_pairing":
            if ch.kind == "discord" and identity != str(ch.config.get("user_id")):
                return None
            if m and _pairing_ok(ch, m.group(1)):
                _activate(ch, identity, extra)
                return "Paired. NexScout will send your notifications here."
            return None  # unpaired senders get nothing back (no oracle)
        if ch.status != "active" or identity != ch.paired_identity:
            return None
        stop_owner = ch.owner_user_id if text.strip().upper() in ("STOP", "/STOP") else None
    if stop_owner is not None:
        return await _stop_from_chat(app, stop_owner, channel_id)
    async with system() as s, s.begin():
        ch = await s.get(NotificationChannel, channel_id)
        if ch is None:
            return None
        if not reply_to:
            return "Reply to a NexScout question to answer it, or use the buttons on a message."
        row = await s.execute(
            select(Notification)
            .join(NotificationDelivery, NotificationDelivery.notification_id == Notification.id)
            .where(
                NotificationDelivery.channel_id == ch.id,
                NotificationDelivery.provider_message_id == reply_to,
            )
        )
        n = row.scalars().first()
        owner = ch.owner_user_id
    if n is None or n.kind != "question":
        return "That message doesn't need an answer."
    from nexscout.application.answers import record_answer

    async with app() as s, s.begin():
        await bind_tenant(s, owner)
        try:
            await record_answer(
                s,
                Actor(user_id=owner, session_id=uuid.uuid4()),
                n.data or {},
                text.strip()[:5000],
                source=f"chat:{channel_id}",
            )
            record_audit(
                s,
                "answer.recorded_via_channel",
                actor_user_id=owner,
                target_type="notification",
                target_id=n.id,
                meta={"channel_id": str(channel_id)},
            )
        except DomainError as exc:
            return f"Couldn't save that answer: {exc}"
    return "Thanks. Saved; NexScout will reuse this answer and continue."


async def handle_action(
    system: async_sessionmaker[AsyncSession],
    app: async_sessionmaker[AsyncSession],
    channel_id: uuid.UUID,
    identity: str,
    token: str,
) -> str:
    """A button press. Only the paired identity of the same channel can use its tokens."""
    from nexscout.application import runs

    async with system() as s, s.begin():
        ch = await s.get(NotificationChannel, channel_id)
        act = await s.get(ChannelAction, token, with_for_update=True)
        if (
            ch is None
            or act is None
            or act.channel_id != channel_id
            or ch.status != "active"
            or identity != ch.paired_identity
        ):
            return "This button isn't valid for you."
        if act.used_at is not None:
            return f"Already handled: {act.result or 'done'}."
        if act.expires_at < datetime.now(UTC):
            return "This button has expired. Open NexScout to decide."
        owner, action, target = act.owner_user_id, act.action, dict(act.target)
        # Siblings (approve/reject on the same message) become unusable too.
        await s.execute(
            update(ChannelAction)
            .where(
                ChannelAction.notification_id == act.notification_id,
                ChannelAction.channel_id == channel_id,
                ChannelAction.used_at.is_(None),
            )
            .values(used_at=datetime.now(UTC))
        )
    approve = action == "approve"
    async with app() as s, s.begin():
        await bind_tenant(s, owner)
        actor = Actor(user_id=owner, session_id=uuid.uuid4())
        try:
            await runs.decide(
                s,
                actor,
                uuid.UUID(target["approval_id"]),
                approve=approve,
                note=f"Decided from a paired chat channel ({channel_id}).",
            )
            result = (
                "Approved. NexScout will continue." if approve else "Rejected. Nothing was sent."
            )
        except DomainError as exc:
            result = f"Couldn't apply: {exc}"
        record_audit(
            s,
            "approval.decided_via_channel",
            actor_user_id=owner,
            target_type="approval",
            target_id=uuid.UUID(target["approval_id"]),
            meta={"channel_id": str(channel_id), "approve": approve},
        )
    async with system() as s, s.begin():
        await s.execute(
            update(ChannelAction).where(ChannelAction.id == token).values(result=result[:300])
        )
    return result


async def _stop_from_chat(
    app: async_sessionmaker[AsyncSession], owner: uuid.UUID, channel_id: uuid.UUID
) -> str:
    """ "STOP" from the paired identity: the autopilot kill switch, from anywhere."""
    from nexscout.application.autopilot import stop_all

    async with app() as s, s.begin():
        await bind_tenant(s, owner)
        done = await stop_all(
            s, Actor(user_id=owner, session_id=uuid.uuid4()), reason="STOP sent from chat"
        )
    return (
        f"Autopilot stopped: {done['policies']} setting(s) turned off, "
        f"{done['runs_cancelled']} task(s) cancelled. Turn it back on in NexScout."
    )
