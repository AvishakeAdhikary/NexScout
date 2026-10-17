"""Messaging channel adapters: official provider APIs only (see AGENTS.md §4a).

Every adapter takes an `httpx.AsyncClient` so tests can inject a mock transport and the worker
can share one client. Adapters never log credentials or message bodies.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx


class ChannelError(Exception):
    """A delivery failed. `transient` errors are retried; permanent ones are not."""

    def __init__(self, message: str, *, transient: bool = True) -> None:
        super().__init__(message)
        self.transient = transient


@dataclass(frozen=True)
class ActionButton:
    label: str
    token: str | None = None  # a channel action id (approve/reject/answer), or…
    url: str | None = None  # …a plain link
    style: str = "primary"  # primary | danger | link


@dataclass(frozen=True)
class OutboundMessage:
    title: str
    body: str = ""
    link: str | None = None
    actions: list[ActionButton] = field(default_factory=list)
    reply_hint: str | None = None  # e.g. "Reply to this message with your answer."
    event: str = "info"


@dataclass(frozen=True)
class SendResult:
    provider_message_id: str | None = None


class ChannelAdapter(Protocol):
    kind: str

    async def send(
        self,
        client: httpx.AsyncClient,
        config: dict[str, Any],
        secrets: dict[str, str],
        msg: OutboundMessage,
    ) -> SendResult: ...


def link_is_public(url: str | None) -> bool:
    """Chat providers reject buttons that point at localhost; such links go into the text."""
    if not url:
        return False
    host = urlsplit(url).hostname or ""
    if host in ("localhost",) or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return urlsplit(url).scheme == "https"
    return not (ip.is_private or ip.is_loopback or ip.is_link_local)


def plain_text(msg: OutboundMessage, *, with_link: bool = True) -> str:
    parts = [msg.title]
    if msg.body:
        parts.append(msg.body)
    if msg.reply_hint:
        parts.append(msg.reply_hint)
    if with_link and msg.link:
        parts.append(f"Open in NexScout: {msg.link}")
    return "\n\n".join(parts)


async def check_response(resp: httpx.Response, provider: str) -> dict[str, Any]:
    """Map provider HTTP errors to transient (429/5xx) or permanent (other 4xx) failures."""
    if resp.status_code == 429 or resp.status_code >= 500:
        raise ChannelError(f"{provider} is busy or unavailable (HTTP {resp.status_code}).")
    if resp.status_code >= 400:
        detail = ""
        try:
            body = resp.json()
            detail = str(body.get("description") or body.get("message") or body.get("error") or "")[
                :200
            ]
        except ValueError:
            pass
        raise ChannelError(
            f"{provider} refused the message (HTTP {resp.status_code}) {detail}".strip(),
            transient=False,
        )
    if not resp.content:
        return {}
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {"result": data}
