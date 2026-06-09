"""OpenClaw delivery channels (Telegram, Discord; future: Slack, ...).

Selection is driven by ``profile.openclaw.channel`` — the default ``cli``
returns ``None`` (channel-less, drops into ``~/.openclaw/inbox`` only).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..discord import DiscordChannel
from ..telegram import TelegramChannel

if TYPE_CHECKING:
    from ...core.profile import Profile

#: Union of the concrete channel implementations ``get_channel`` may return.
Channel = TelegramChannel | DiscordChannel


def get_channel(profile: Profile | None = None) -> Channel | None:
    """Return the active channel implementation, or ``None``.

    The selection rule is:

    1. ``profile.openclaw.channel == "telegram"`` → build a
       :class:`TelegramChannel` from env (``TELEGRAM_BOT_TOKEN`` +
       ``TELEGRAM_CHAT_ID``).
    2. ``profile.openclaw.channel == "discord"`` → build a
       :class:`DiscordChannel` from env (``DISCORD_WEBHOOK_URL`` or
       ``DISCORD_BOT_TOKEN`` + ``DISCORD_CHANNEL_ID``).
    3. Anything else (incl. missing credentials) → ``None`` (CLI /
       inbox-only mode).
    """
    channel = "cli"
    if profile is not None:
        channel = (profile.openclaw.channel or "cli").lower()

    if channel == "telegram":
        return TelegramChannel.from_env()
    if channel == "discord":
        return DiscordChannel.from_env()
    return None


__all__ = ["Channel", "DiscordChannel", "TelegramChannel", "get_channel"]
