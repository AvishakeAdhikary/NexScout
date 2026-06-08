"""OpenClaw delivery channels (Telegram, future: Slack, Discord, ...).

Selection is driven by ``profile.openclaw.channel`` — the default ``cli``
returns ``None`` (channel-less, drops into ``~/.openclaw/inbox`` only).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..telegram import TelegramChannel

if TYPE_CHECKING:
    from ...core.profile import Profile


def get_channel(profile: Profile | None = None) -> TelegramChannel | None:
    """Return the active channel implementation, or ``None``.

    The selection rule is:

    1. ``profile.openclaw.channel == "telegram"`` (or env vars set) →
       build a :class:`TelegramChannel` from env. Returns ``None`` if
       the credentials are missing.
    2. Anything else → ``None`` (CLI / inbox-only mode).
    """
    channel = "cli"
    if profile is not None:
        channel = (profile.openclaw.channel or "cli").lower()

    if channel == "telegram":
        return TelegramChannel.from_env()
    return None


__all__ = ["TelegramChannel", "get_channel"]
