"""Tests for the OpenClaw Discord delivery channel."""

from __future__ import annotations

import json

import httpx
import pytest

from nexscout.openclaw.discord import DiscordChannel

# ---------------------------------------------------------------------------
# from_env / enabled
# ---------------------------------------------------------------------------


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_CHANNEL_ID", raising=False)


def test_from_env_returns_none_when_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    assert DiscordChannel.from_env() is None


def test_from_env_returns_none_when_bot_token_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
    assert DiscordChannel.from_env() is None


def test_from_env_returns_none_when_channel_id_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "abc")
    assert DiscordChannel.from_env() is None


def test_from_env_builds_webhook_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/abc")
    ch = DiscordChannel.from_env()
    assert ch is not None
    assert ch.enabled is True


def test_from_env_builds_bot_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "abc")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "42")
    ch = DiscordChannel.from_env()
    assert ch is not None
    assert ch.enabled is True
    assert ch.channel_id == "42"


def test_from_env_prefers_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/abc")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "abc")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "42")
    captured: list[httpx.Request] = []
    ch = DiscordChannel.from_env()
    assert ch is not None
    # Re-attach a transport to inspect which URL it posts to.
    ch._transport = _ok_transport(captured)  # type: ignore[attr-defined]
    assert ch.send("hi") is True
    assert "webhooks" in captured[0].url.path


def test_disabled_channel_returns_false() -> None:
    ch = DiscordChannel()
    assert ch.enabled is False
    assert ch.send("hi") is False


# ---------------------------------------------------------------------------
# send() — success + payload shape
# ---------------------------------------------------------------------------


def _ok_transport(captured: list[httpx.Request], status: int = 204) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if status == 204:
            return httpx.Response(204)
        return httpx.Response(status, json={"id": "1"})

    return httpx.MockTransport(handler)


def test_send_webhook_posts_content_and_treats_204_as_success() -> None:
    captured: list[httpx.Request] = []
    ch = DiscordChannel(
        webhook_url="https://discord.com/api/webhooks/1/abc",
        transport=_ok_transport(captured, status=204),
    )
    assert ch.send("hello world") is True
    assert len(captured) == 1
    req = captured[0]
    assert str(req.url) == "https://discord.com/api/webhooks/1/abc"
    payload = json.loads(req.content)
    assert payload == {"content": "hello world"}


def test_send_webhook_treats_200_as_success() -> None:
    captured: list[httpx.Request] = []
    ch = DiscordChannel(
        webhook_url="https://discord.com/api/webhooks/1/abc",
        transport=_ok_transport(captured, status=200),
    )
    assert ch.send("hi") is True


def test_send_bot_posts_to_api_with_auth_header_and_treats_200_as_success() -> None:
    captured: list[httpx.Request] = []
    ch = DiscordChannel(
        bot_token="TOK",
        channel_id="42",
        transport=_ok_transport(captured, status=200),
    )
    assert ch.send("hello world") is True
    assert len(captured) == 1
    req = captured[0]
    assert str(req.url) == "https://discord.com/api/v10/channels/42/messages"
    assert req.headers["Authorization"] == "Bot TOK"
    payload = json.loads(req.content)
    assert payload == {"content": "hello world"}


def test_send_accepts_telegram_compat_kwargs() -> None:
    captured: list[httpx.Request] = []
    ch = DiscordChannel(
        webhook_url="https://discord.com/api/webhooks/1/abc",
        transport=_ok_transport(captured, status=204),
    )
    # parse_mode / disable_web_page_preview accepted but ignored.
    assert ch.send("hi", parse_mode="HTML", disable_web_page_preview=False) is True
    payload = json.loads(captured[0].content)
    assert payload == {"content": "hi"}


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------


def test_send_retries_on_429_with_retry_after() -> None:
    """A 429 with body retry_after (seconds) schedules a sleep then succeeds."""
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, json={"retry_after": 7.5})
        return httpx.Response(204)

    ch = DiscordChannel(
        webhook_url="https://discord.com/api/webhooks/1/abc",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )
    assert ch.send("hi") is True
    assert len(calls) == 2
    assert sleeps == [7.5]


def test_send_429_uses_header_when_body_missing() -> None:
    sleeps: list[float] = []
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "3"}, text="too many")
        return httpx.Response(204)

    ch = DiscordChannel(
        webhook_url="https://discord.com/api/webhooks/1/abc",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )
    assert ch.send("hi") is True
    assert sleeps == [3.0]


def test_send_retries_on_500_then_succeeds() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(500, text="boom")
        return httpx.Response(204)

    ch = DiscordChannel(
        webhook_url="https://discord.com/api/webhooks/1/abc",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )
    assert ch.send("hi") is True
    assert len(calls) == 3
    # 2/4/8 backoff plan — first two slots used.
    assert sleeps == [2.0, 4.0]


def test_send_gives_up_after_three_attempts() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503, text="still broken")

    ch = DiscordChannel(
        webhook_url="https://discord.com/api/webhooks/1/abc",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )
    assert ch.send("hi") is False
    # 4 total attempts: initial + 3 backoffs.
    assert len(calls) == 4
    assert sleeps == [2.0, 4.0, 8.0]


def test_send_does_not_retry_on_4xx() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, text="bad")

    ch = DiscordChannel(
        webhook_url="https://discord.com/api/webhooks/1/abc",
        transport=httpx.MockTransport(handler),
    )
    assert ch.send("hi") is False
    assert len(calls) == 1


def test_send_retries_on_network_error() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("network down")
        return httpx.Response(204)

    ch = DiscordChannel(
        webhook_url="https://discord.com/api/webhooks/1/abc",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )
    assert ch.send("hi") is True
    assert len(calls) == 2
    assert sleeps == [2.0]


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _webhook_channel(captured: list[httpx.Request]) -> DiscordChannel:
    return DiscordChannel(
        webhook_url="https://discord.com/api/webhooks/1/abc",
        transport=_ok_transport(captured, status=204),
        sleep=lambda *_: None,
    )


def test_send_question_formats_content() -> None:
    captured: list[httpx.Request] = []
    ch = _webhook_channel(captured)
    assert ch.send_question(7, "Sponsor?", "https://example.com/job") is True
    content = json.loads(captured[0].content)["content"]
    assert "Q7" in content
    assert "Sponsor?" in content
    assert "https://example.com/job" in content
    assert "/answer 7" in content


def test_send_question_uses_markdown_not_html() -> None:
    captured: list[httpx.Request] = []
    ch = _webhook_channel(captured)
    ch.send_question(1, "<script>alert(1)</script>", None)
    content = json.loads(captured[0].content)["content"]
    # Discord uses markdown; we do NOT HTML-escape.
    assert "<script>alert(1)</script>" in content
    assert "&lt;" not in content


def test_send_captcha_alert_includes_title() -> None:
    captured: list[httpx.Request] = []
    ch = _webhook_channel(captured)
    ch.send_captcha_alert("https://x.example/job", "Senior Engineer")
    content = json.loads(captured[0].content)["content"]
    assert "Senior Engineer" in content
    assert "CAPTCHA" in content
    assert "https://x.example/job" in content


def test_send_captcha_alert_without_title() -> None:
    captured: list[httpx.Request] = []
    ch = _webhook_channel(captured)
    ch.send_captcha_alert("https://x.example/job")
    content = json.loads(captured[0].content)["content"]
    assert "CAPTCHA" in content
    assert "https://x.example/job" in content


def test_send_apply_summary_renders_keys() -> None:
    captured: list[httpx.Request] = []
    ch = _webhook_channel(captured)
    ch.send_apply_summary(
        {
            "discovered": 1,
            "enriched": 2,
            "scored": 3,
            "tailored": 4,
            "rendered": 5,
            "applied": 6,
            "questions_surfaced": 7,
            "errors": [],
        }
    )
    content = json.loads(captured[0].content)["content"]
    for key in (
        "discovered",
        "enriched",
        "scored",
        "tailored",
        "rendered",
        "applied",
        "questions_surfaced",
        "errors",
    ):
        assert key in content
