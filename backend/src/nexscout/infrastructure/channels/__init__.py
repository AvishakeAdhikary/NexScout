"""Official messaging channel adapters and the shared HTTP client factory."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from nexscout.infrastructure.channels.base import ChannelAdapter
from nexscout.infrastructure.channels.discord import DiscordAdapter
from nexscout.infrastructure.channels.simple import EmailAdapter, SlackAdapter, WebhookAdapter
from nexscout.infrastructure.channels.telegram import TelegramAdapter
from nexscout.infrastructure.channels.whatsapp import WhatsAppAdapter

ADAPTERS: dict[str, ChannelAdapter] = {
    a.kind: a
    for a in (
        WebhookAdapter(),
        SlackAdapter(),
        EmailAdapter(),
        TelegramAdapter(),
        DiscordAdapter(),
        WhatsAppAdapter(),
    )
}


def _default_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=10.0),
        follow_redirects=False,
        headers={"User-Agent": "NexScout/2"},
    )


# Tests replace this with a factory that returns a client over a mock transport.
client_factory: Callable[[], httpx.AsyncClient] = _default_client


def new_client() -> httpx.AsyncClient:
    return client_factory()
