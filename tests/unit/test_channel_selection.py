"""Tests for ``openclaw.channels.get_channel`` selecting Telegram vs Discord."""

from __future__ import annotations

import pytest

from nexscout.core.profile import Profile
from nexscout.openclaw.channels import DiscordChannel, TelegramChannel, get_channel


def _profile(channel: str) -> Profile:
    return Profile.model_validate(
        {
            "me": {"legal": "J", "pref": "J", "email": "j@x.com", "phone": "1"},
            "openclaw": {"channel": channel},
        }
    )


def _clear_channel_env(mp: pytest.MonkeyPatch) -> None:
    for var in (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "DISCORD_WEBHOOK_URL",
        "DISCORD_BOT_TOKEN",
        "DISCORD_CHANNEL_ID",
    ):
        mp.delenv(var, raising=False)


def test_cli_channel_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_channel_env(monkeypatch)
    assert get_channel(_profile("cli")) is None


def test_none_profile_returns_none() -> None:
    assert get_channel(None) is None


def test_telegram_still_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_channel_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOK")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    ch = get_channel(_profile("telegram"))
    assert isinstance(ch, TelegramChannel)
    assert ch.enabled


def test_discord_webhook_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_channel_env(monkeypatch)
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/abc")
    ch = get_channel(_profile("discord"))
    assert isinstance(ch, DiscordChannel)
    assert ch.enabled


def test_discord_bot_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_channel_env(monkeypatch)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "BOT")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "999")
    ch = get_channel(_profile("discord"))
    assert isinstance(ch, DiscordChannel)
    assert ch.enabled


def test_discord_without_env_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_channel_env(monkeypatch)
    assert get_channel(_profile("discord")) is None


def test_channel_name_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_channel_env(monkeypatch)
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/abc")
    assert isinstance(get_channel(_profile("Discord")), DiscordChannel)
