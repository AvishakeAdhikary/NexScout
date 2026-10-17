"""Worker loops for notification channels (AGENTS.md §4a).

- delivery: claims due outbox rows and sends them (bounded concurrency).
- telegram: one long-poll (`getUpdates`) task per channel. No public URL needed.
- discord: one Gateway connection per channel (button presses and DM replies).
- whatsapp: verifies and processes webhook bodies the API stored in the inbox.

The supervisors re-read the channel list periodically, so adding, pausing or removing a channel
takes effect without restarting the worker. Everything a loop does is keyed by a provider event
id (idempotent), and every action is checked against the channel's paired identity.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexscout.application import channels as svc
from nexscout.config import Settings
from nexscout.infrastructure.channels import new_client
from nexscout.infrastructure.channels.base import ChannelError, OutboundMessage
from nexscout.infrastructure.db.models import ChannelInboundEvent, NotificationChannel

log = structlog.get_logger()
Sessions = async_sessionmaker[AsyncSession]
LIVE = ("active", "pending_pairing")


@dataclass
class ChannelLoops:
    settings: Settings
    system: Sessions
    app: Sessions
    stop: asyncio.Event

    # ------------------------------------------------------------------ delivery
    async def deliver_due(self) -> int:
        """Channels in parallel; messages within a channel in order and one at a time (so the
        circuit breaker sees every failure)."""
        async with self.system() as s, s.begin():
            claimed = await svc.claim_due(s, datetime.now(UTC))
        by_channel: dict[uuid.UUID, list[uuid.UUID]] = {}
        for delivery_id, channel_id in claimed:
            by_channel.setdefault(channel_id, []).append(delivery_id)
        sem = asyncio.Semaphore(5)

        async def channel(ids: list[uuid.UUID]) -> None:
            async with sem:
                for i in ids:
                    try:
                        await svc.deliver_one(self.system, self.settings, i)
                    except Exception:  # one bad row must not stop the loop
                        log.exception("delivery_crashed")

        await asyncio.gather(*(channel(ids) for ids in by_channel.values()))
        return len(claimed)

    async def delivery_loop(self) -> None:
        while not self.stop.is_set():
            n = 0
            with contextlib.suppress(Exception):
                n = await self.deliver_due()
            if not n:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self.stop.wait(), self.settings.channel_poll_interval_s)

    # ------------------------------------------------------------------ telegram
    async def telegram_poll_once(self, channel_id: uuid.UUID, wait_s: int = 20) -> int:
        from nexscout.infrastructure.channels import telegram as tg

        async with self.system() as s:
            ch = await s.get(NotificationChannel, channel_id)
            if ch is None or ch.status not in LIVE:
                return 0
            token = (await svc.channel_secrets(s, self.settings, ch))["bot_token"]
            offset = ch.poll_offset
        async with new_client() as client:
            updates = await tg.get_updates(client, token, offset, wait_s)
            for u in updates:
                await self._telegram_update(client, token, channel_id, u)
                async with self.system() as s, s.begin():
                    await s.execute(
                        update(NotificationChannel)
                        .where(NotificationChannel.id == channel_id)
                        .values(poll_offset=u.update_id + 1)
                    )
        return len(updates)

    async def _telegram_update(
        self, client: Any, token: str, channel_id: uuid.UUID, u: Any
    ) -> None:
        from nexscout.infrastructure.channels import telegram as tg

        async with self.system() as s, s.begin():
            fresh = await svc.record_inbound(
                s, channel_id, f"tg:{u.update_id}", {"kind": u.kind, "from": u.user_id}
            )
        if not fresh:
            return
        if u.kind == "callback" and u.data:
            result = await svc.handle_action(self.system, self.app, channel_id, u.user_id, u.data)
            with contextlib.suppress(ChannelError):
                await tg.answer_callback(client, token, str(u.callback_id), result)
                if u.message_id:
                    await tg.clear_buttons(client, token, u.chat_id, u.message_id)
                await tg.TelegramAdapter().send_to(
                    client, token, u.chat_id, OutboundMessage(result, "")
                )
            return
        reply = await svc.handle_text(
            self.system, self.app, channel_id, u.user_id, u.text, u.reply_to, {"chat_id": u.chat_id}
        )
        if reply:
            with contextlib.suppress(ChannelError):
                await tg.TelegramAdapter().send_to(
                    client, token, u.chat_id, OutboundMessage(reply, "")
                )

    # ------------------------------------------------------------------ discord
    async def discord_event(self, client: Any, token: str, channel_id: uuid.UUID, ev: Any) -> None:
        from nexscout.infrastructure.channels import discord as dc

        async with self.system() as s, s.begin():
            fresh = await svc.record_inbound(
                s, channel_id, f"dc:{ev.event_id}", {"kind": ev.kind, "from": ev.user_id}
            )
        if not fresh:
            return
        if ev.kind == "button" and ev.custom_id:
            result = await svc.handle_action(
                self.system, self.app, channel_id, ev.user_id, ev.custom_id
            )
            try:
                await dc.respond_to_interaction(
                    client, str(ev.interaction_id), str(ev.interaction_token), result
                )
            except ChannelError:
                with contextlib.suppress(ChannelError):
                    await dc.DiscordAdapter().send_dm(
                        client, token, ev.user_id, OutboundMessage(result, "")
                    )
            return
        reply = await svc.handle_text(
            self.system, self.app, channel_id, ev.user_id, ev.text, ev.reply_to, {"paired": True}
        )
        if reply:
            with contextlib.suppress(ChannelError):
                await dc.DiscordAdapter().send_dm(
                    client, token, ev.user_id, OutboundMessage(reply, "")
                )

    async def _discord_session(self, channel_id: uuid.UUID, stop: asyncio.Event) -> None:
        from nexscout.infrastructure.channels.discord import DiscordGateway

        async with self.system() as s:
            ch = await s.get(NotificationChannel, channel_id)
            if ch is None:
                return
            token = (await svc.channel_secrets(s, self.settings, ch))["bot_token"]
            gateway_url = ch.config.get("gateway_url")  # tests point this at a fake gateway
        async with new_client() as client:

            async def on_event(ev: Any) -> None:
                try:
                    await self.discord_event(client, token, channel_id, ev)
                except Exception:
                    log.exception("discord_event_failed")

            await DiscordGateway(token, on_event, gateway_url).run(client, stop)

    # ------------------------------------------------------------------ whatsapp
    async def whatsapp_inbox_once(self) -> int:
        from nexscout.infrastructure.channels import whatsapp as wa

        async with self.system() as s, s.begin():
            rows = list(
                await s.scalars(
                    select(ChannelInboundEvent)
                    .where(ChannelInboundEvent.status == "received")
                    .order_by(ChannelInboundEvent.received_at)
                    .limit(20)
                    .with_for_update(skip_locked=True)
                )
            )
            work: list[tuple[ChannelInboundEvent, NotificationChannel | None, dict[str, str]]] = []
            for row in rows:
                ch = await s.get(NotificationChannel, row.channel_id)
                sec = await svc.channel_secrets(s, self.settings, ch) if ch else {}
                ok = (
                    ch is not None
                    and ch.kind == "whatsapp"
                    and ch.status in LIVE
                    and wa.verify_signature(
                        sec.get("app_secret", ""), row.raw_body or b"", row.signature
                    )
                )
                row.raw_body = None  # data minimization: the parsed payload is enough
                row.processed_at = datetime.now(UTC)
                if not ok:
                    row.status, row.note = "rejected", "signature check failed"
                    continue
                row.status = "processed"
                work.append((row, ch, sec))
            batch = [
                (r.channel_id, dict(r.payload), dict(c.config) if c else {}, sec)
                for r, c, sec in work
            ]
        for channel_id, payload, config, sec in batch:
            async with new_client() as client:
                for m in wa.parse_webhook(payload):
                    await self._whatsapp_message(client, channel_id, config, sec, m)
        return len(rows)

    async def _whatsapp_message(
        self,
        client: Any,
        channel_id: uuid.UUID,
        config: dict[str, Any],
        sec: dict[str, str],
        m: Any,
    ) -> None:
        from nexscout.infrastructure.channels import whatsapp as wa

        async with self.system() as s, s.begin():
            fresh = await svc.record_inbound(
                s, channel_id, f"wa:{m.event_id}", {"kind": m.kind, "from": m.from_id}
            )
        if not fresh:
            return
        if m.kind == "button" and m.button_id:
            reply: str | None = await svc.handle_action(
                self.system, self.app, channel_id, m.from_id, m.button_id
            )
        else:
            reply = await svc.handle_text(
                self.system,
                self.app,
                channel_id,
                m.from_id,
                m.text,
                m.reply_to,
                {"wa_id": m.from_id},
            )
        if reply:
            with contextlib.suppress(ChannelError):
                await wa.WhatsAppAdapter().send_to(
                    client, config, sec, m.from_id, OutboundMessage(reply, "")
                )

    async def whatsapp_loop(self) -> None:
        while not self.stop.is_set():
            n = 0
            with contextlib.suppress(Exception):
                n = await self.whatsapp_inbox_once()
            if not n:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self.stop.wait(), self.settings.channel_poll_interval_s)

    # ------------------------------------------------------------------ supervisor
    async def supervisor_loop(self, refresh_s: float = 10.0) -> None:
        """Keeps one Telegram poller / Discord gateway per live channel."""
        tasks: dict[uuid.UUID, tuple[str, asyncio.Task[None], asyncio.Event]] = {}
        try:
            while not self.stop.is_set():
                with contextlib.suppress(Exception):
                    async with self.system() as s:
                        rows = (
                            await s.execute(
                                select(
                                    NotificationChannel.id,
                                    NotificationChannel.kind,
                                    NotificationChannel.secret_id,
                                ).where(
                                    NotificationChannel.kind.in_(("telegram", "discord")),
                                    NotificationChannel.status.in_(LIVE),
                                )
                            )
                        ).all()
                    wanted = {cid: f"{kind}:{sid}" for cid, kind, sid in rows}
                    kinds = {cid: kind for cid, kind, _ in rows}
                    for cid, (sig, task, ev) in list(tasks.items()):
                        if wanted.get(cid) != sig or task.done():
                            ev.set()
                            task.cancel()
                            del tasks[cid]
                    for cid, sig in wanted.items():
                        if cid not in tasks:
                            ev = asyncio.Event()
                            runner = (
                                self._telegram_runner
                                if kinds[cid] == "telegram"
                                else self._discord_session
                            )
                            tasks[cid] = (
                                sig,
                                asyncio.create_task(self._guarded(runner, cid, ev)),
                                ev,
                            )
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self.stop.wait(), refresh_s)
        finally:
            for _, task, ev in tasks.values():
                ev.set()
                task.cancel()
            await asyncio.gather(*(t for _, t, _ in tasks.values()), return_exceptions=True)

    async def _telegram_runner(self, channel_id: uuid.UUID, stop: asyncio.Event) -> None:
        backoff = 1.0
        while not stop.is_set() and not self.stop.is_set():
            try:
                await self.telegram_poll_once(channel_id)
                backoff = 1.0
            except ChannelError as exc:
                log.warning("telegram_poll_failed", error=str(exc)[:200])
                await asyncio.sleep(min(backoff, 60))
                backoff *= 2

    async def _guarded(
        self,
        runner: Callable[[uuid.UUID, asyncio.Event], Awaitable[None]],
        channel_id: uuid.UUID,
        stop: asyncio.Event,
    ) -> None:
        try:
            await runner(channel_id, stop)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("channel_runner_crashed")
            await asyncio.sleep(5)

    def loops(self) -> list[Coroutine[Any, Any, None]]:
        return [self.delivery_loop(), self.supervisor_loop(), self.whatsapp_loop()]
