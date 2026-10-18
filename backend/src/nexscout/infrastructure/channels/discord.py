"""Discord via an official bot (https://discord.com/developers/docs).

Outbound: REST — open a DM with the paired user and post a message with button components.
Inbound: the official Gateway (WebSocket): INTERACTION_CREATE for button presses and
MESSAGE_CREATE in the DM for replies. Only the non-privileged DIRECT_MESSAGES intent is used.

Pairing: the user enters their Discord user id in NexScout; the bot DMs them a code, which they
type back into NexScout. That proves the account is theirs before anything is accepted from it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from nexscout.infrastructure.channels.base import (
    ChannelError,
    OutboundMessage,
    SendResult,
    check_response,
    link_is_public,
)

API = "https://discord.com/api/v10"
INTENT_DIRECT_MESSAGES = 1 << 12
log = structlog.get_logger()


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bot {token}",
        "User-Agent": "DiscordBot (https://github.com/AvishakeAdhikary/NexScout, 2)",
    }


async def rest(
    client: httpx.AsyncClient,
    token: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        resp = await client.request(method, f"{API}{path}", json=payload, headers=_headers(token))
    except httpx.HTTPError as exc:
        raise ChannelError("Discord unreachable (network error or timeout).") from exc
    return await check_response(resp, "Discord")


class DiscordAdapter:
    kind = "discord"

    async def send(
        self,
        client: httpx.AsyncClient,
        config: dict[str, Any],
        secrets: dict[str, str],
        msg: OutboundMessage,
    ) -> SendResult:
        user_id = config.get("user_id")
        if not user_id or not config.get("paired"):
            raise ChannelError("This Discord channel isn't paired yet.", transient=False)
        return await self.send_dm(client, secrets["bot_token"], str(user_id), msg)

    async def send_dm(
        self, client: httpx.AsyncClient, token: str, user_id: str, msg: OutboundMessage
    ) -> SendResult:
        dm = await rest(client, token, "POST", "/users/@me/channels", {"recipient_id": user_id})
        content = f"**{msg.title}**"
        if msg.body:
            content += f"\n{msg.body}"
        if msg.reply_hint:
            content += f"\n_{msg.reply_hint}_"
        buttons: list[dict[str, Any]] = [
            {
                "type": 2,
                "style": 4 if a.style == "danger" else 3,
                "label": a.label[:80],
                "custom_id": a.token,
            }
            for a in msg.actions
            if a.token
        ][:4]
        if msg.link and link_is_public(msg.link):
            buttons.append({"type": 2, "style": 5, "label": "Open in NexScout", "url": msg.link})
        elif msg.link:
            content += f"\nOpen in NexScout: {msg.link}"
        payload: dict[str, Any] = {"content": content[:1990], "allowed_mentions": {"parse": []}}
        if buttons:
            payload["components"] = [{"type": 1, "components": buttons}]
        sent = await rest(client, token, "POST", f"/channels/{dm['id']}/messages", payload)
        return SendResult(str(sent.get("id")) if sent.get("id") else None)


@dataclass(frozen=True)
class DiscordEvent:
    kind: str  # "button" | "text"
    event_id: str
    user_id: str
    custom_id: str | None = None
    text: str = ""
    reply_to: str | None = None
    interaction_id: str | None = None
    interaction_token: str | None = None


def parse_dispatch(event: str, d: dict[str, Any]) -> DiscordEvent | None:
    if event == "INTERACTION_CREATE" and d.get("type") == 3:  # message component
        user = d.get("user") or (d.get("member") or {}).get("user") or {}
        return DiscordEvent(
            "button",
            str(d.get("id")),
            str(user.get("id", "")),
            custom_id=(d.get("data") or {}).get("custom_id"),
            interaction_id=str(d.get("id")),
            interaction_token=d.get("token"),
        )
    if (
        event == "MESSAGE_CREATE"
        and not d.get("guild_id")
        and not (d.get("author") or {}).get("bot")
    ):
        ref = (d.get("message_reference") or {}).get("message_id")
        return DiscordEvent(
            "text",
            str(d.get("id")),
            str((d.get("author") or {}).get("id", "")),
            text=str(d.get("content") or "")[:4000],
            reply_to=str(ref) if ref else None,
        )
    return None


async def respond_to_interaction(
    client: httpx.AsyncClient, interaction_id: str, interaction_token: str, text: str
) -> None:
    """Replace the buttons with the outcome (UPDATE_MESSAGE, type 7)."""
    try:
        resp = await client.post(
            f"{API}/interactions/{interaction_id}/{interaction_token}/callback",
            json={"type": 7, "data": {"content": text[:1990], "components": []}},
        )
    except httpx.HTTPError as exc:
        raise ChannelError("Discord unreachable (network error or timeout).") from exc
    await check_response(resp, "Discord")


class DiscordGateway:
    """Minimal, spec-following Gateway client: HELLO → IDENTIFY → heartbeats (with jitter),
    DISPATCH handling, RESUME on reconnect (op 7) and fresh IDENTIFY on invalid session (op 9)."""

    def __init__(
        self,
        token: str,
        on_event: Callable[[DiscordEvent], Awaitable[None]],
        gateway_url: str | None = None,
    ) -> None:
        self.token = token
        self.on_event = on_event
        self.gateway_url = gateway_url
        self.seq: int | None = None
        self.session_id: str | None = None
        self.resume_url: str | None = None
        self.ready = asyncio.Event()

    async def _url(self, client: httpx.AsyncClient) -> str:
        if self.gateway_url:
            return self.gateway_url
        data = await rest(client, self.token, "GET", "/gateway/bot")
        return str(data["url"])

    async def run(self, client: httpx.AsyncClient, stop: asyncio.Event) -> None:
        from websockets.asyncio.client import connect

        backoff = 1.0
        while not stop.is_set():
            base = self.resume_url or await self._url(client)
            try:
                async with connect(f"{base}/?v=10&encoding=json", open_timeout=15) as ws:
                    backoff = 1.0
                    await self._session(ws, stop)
            except (OSError, ChannelError, TimeoutError) as exc:
                log.warning("discord_gateway_reconnect", error=type(exc).__name__)
            except Exception as exc:  # noqa: BLE001 - websocket closes surface as many types
                log.warning("discord_gateway_reconnect", error=type(exc).__name__)
            if stop.is_set():
                return
            await asyncio.sleep(min(backoff, 60) * (0.5 + random.random()))  # noqa: S311
            backoff *= 2

    async def _session(self, ws: Any, stop: asyncio.Event) -> None:
        hello = json.loads(await ws.recv())
        interval = hello["d"]["heartbeat_interval"] / 1000
        if self.session_id and self.seq is not None:
            await ws.send(
                json.dumps(
                    {
                        "op": 6,
                        "d": {"token": self.token, "session_id": self.session_id, "seq": self.seq},
                    }
                )
            )
        else:
            await ws.send(
                json.dumps(
                    {
                        "op": 2,
                        "d": {
                            "token": self.token,
                            "intents": INTENT_DIRECT_MESSAGES,
                            "properties": {
                                "os": "nexscout",
                                "browser": "nexscout",
                                "device": "nexscout",
                            },
                        },
                    }
                )
            )

        async def heartbeat() -> None:
            await asyncio.sleep(interval * random.random())  # noqa: S311
            while True:
                await ws.send(json.dumps({"op": 1, "d": self.seq}))
                await asyncio.sleep(interval)

        beat = asyncio.create_task(heartbeat())
        try:
            while not stop.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except TimeoutError:
                    continue
                msg = json.loads(raw)
                op = msg.get("op")
                if msg.get("s") is not None:
                    self.seq = msg["s"]
                if op == 0:
                    t, d = msg.get("t"), msg.get("d") or {}
                    if t == "READY":
                        self.session_id = d.get("session_id")
                        self.resume_url = d.get("resume_gateway_url")
                        self.ready.set()
                    elif t == "RESUMED":
                        self.ready.set()
                    elif (ev := parse_dispatch(str(t), d)) is not None:
                        await self.on_event(ev)
                elif op == 1:
                    await ws.send(json.dumps({"op": 1, "d": self.seq}))
                elif op == 7:  # reconnect and resume
                    return
                elif op == 9:  # invalid session: start over
                    self.session_id, self.seq, self.resume_url = None, None, None
                    return
        finally:
            beat.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await beat
