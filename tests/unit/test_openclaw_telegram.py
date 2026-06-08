"""Tests for the OpenClaw Telegram delivery channel."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from nexscout.core.database import init_db
from nexscout.core.profile import Profile
from nexscout.openclaw import tick as tick_mod
from nexscout.openclaw.channels import get_channel
from nexscout.openclaw.telegram import TelegramChannel

# ---------------------------------------------------------------------------
# from_env / enabled
# ---------------------------------------------------------------------------


def test_from_env_returns_none_when_token_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    assert TelegramChannel.from_env() is None


def test_from_env_returns_none_when_chat_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert TelegramChannel.from_env() is None


def test_from_env_builds_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    ch = TelegramChannel.from_env()
    assert ch is not None
    assert ch.enabled is True
    assert ch.chat_id == "42"


def test_disabled_channel_returns_false() -> None:
    ch = TelegramChannel()
    assert ch.enabled is False
    assert ch.send("hi") is False


# ---------------------------------------------------------------------------
# send() — success + payload shape
# ---------------------------------------------------------------------------


def _ok_transport(captured: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    return httpx.MockTransport(handler)


def test_send_posts_to_telegram_api() -> None:
    captured: list[httpx.Request] = []
    ch = TelegramChannel(bot_token="TOK", chat_id="42", transport=_ok_transport(captured))
    assert ch.send("hello world") is True
    assert len(captured) == 1
    req = captured[0]
    assert req.url.path == "/botTOK/sendMessage"
    payload = json.loads(req.content)
    assert payload["chat_id"] == "42"
    assert payload["text"] == "hello world"
    assert payload["parse_mode"] == "HTML"
    assert payload["disable_web_page_preview"] is True


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------


def test_send_retries_on_429_with_retry_after() -> None:
    """A 429 with parameters.retry_after schedules a sleep then succeeds."""
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(
                429,
                json={"ok": False, "parameters": {"retry_after": 7}},
            )
        return httpx.Response(200, json={"ok": True})

    ch = TelegramChannel(
        bot_token="TOK",
        chat_id="42",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )
    assert ch.send("hi") is True
    assert len(calls) == 2
    assert sleeps == [7.0]


def test_send_retries_on_500_then_succeeds() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"ok": True})

    ch = TelegramChannel(
        bot_token="TOK",
        chat_id="42",
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

    ch = TelegramChannel(
        bot_token="TOK",
        chat_id="42",
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

    ch = TelegramChannel(bot_token="TOK", chat_id="42", transport=httpx.MockTransport(handler))
    assert ch.send("hi") is False
    assert len(calls) == 1


def test_send_retries_on_network_error() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("network down")
        return httpx.Response(200, json={"ok": True})

    ch = TelegramChannel(
        bot_token="TOK",
        chat_id="42",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )
    assert ch.send("hi") is True
    assert len(calls) == 2
    assert sleeps == [2.0]


def test_send_429_uses_header_when_body_missing() -> None:
    sleeps: list[float] = []
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "3"}, text="too many")
        return httpx.Response(200, json={"ok": True})

    ch = TelegramChannel(
        bot_token="TOK",
        chat_id="42",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )
    assert ch.send("hi") is True
    assert sleeps == [3.0]


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def test_send_question_formats_payload() -> None:
    captured: list[httpx.Request] = []
    ch = TelegramChannel(bot_token="TOK", chat_id="42", transport=_ok_transport(captured))
    assert ch.send_question(7, "Sponsor?", "https://example.com/job") is True
    text = json.loads(captured[0].content)["text"]
    assert "Q7" in text
    assert "Sponsor?" in text
    assert "https://example.com/job" in text
    assert "/answer 7" in text


def test_send_question_escapes_html() -> None:
    captured: list[httpx.Request] = []
    ch = TelegramChannel(bot_token="TOK", chat_id="42", transport=_ok_transport(captured))
    ch.send_question(1, "<script>alert(1)</script>", None)
    text = json.loads(captured[0].content)["text"]
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


def test_send_captcha_alert_includes_title() -> None:
    captured: list[httpx.Request] = []
    ch = TelegramChannel(bot_token="TOK", chat_id="42", transport=_ok_transport(captured))
    ch.send_captcha_alert("https://x.example/job", "Senior Engineer")
    text = json.loads(captured[0].content)["text"]
    assert "Senior Engineer" in text
    assert "manual CAPTCHA" in text
    assert "https://x.example/job" in text


def test_send_captcha_alert_without_title() -> None:
    captured: list[httpx.Request] = []
    ch = TelegramChannel(bot_token="TOK", chat_id="42", transport=_ok_transport(captured))
    ch.send_captcha_alert("https://x.example/job")
    text = json.loads(captured[0].content)["text"]
    assert "manual CAPTCHA" in text
    assert "https://x.example/job" in text


def test_send_apply_summary_renders_keys() -> None:
    captured: list[httpx.Request] = []
    ch = TelegramChannel(bot_token="TOK", chat_id="42", transport=_ok_transport(captured))
    ch.send_apply_summary({"discovered": 1, "applied": 2, "errors": []})
    text = json.loads(captured[0].content)["text"]
    assert "discovered" in text
    assert "applied" in text
    assert "errors" in text


# ---------------------------------------------------------------------------
# Channel factory
# ---------------------------------------------------------------------------


def test_get_channel_cli_returns_none() -> None:
    profile = _profile(channel="cli")
    assert get_channel(profile) is None


def test_get_channel_telegram_without_env_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    profile = _profile(channel="telegram")
    assert get_channel(profile) is None


def test_get_channel_telegram_with_env_returns_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    profile = _profile(channel="telegram")
    ch = get_channel(profile)
    assert isinstance(ch, TelegramChannel)
    assert ch.enabled is True


def test_get_channel_none_profile_returns_none() -> None:
    assert get_channel(None) is None


# ---------------------------------------------------------------------------
# tick wiring writes channel_delivered_at
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[sqlite3.Connection]:
    monkeypatch.setenv("NEXSCOUT_DIR", str(tmp_path / ".nexscout"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    db = init_db(tmp_path / ".nexscout" / "t.sqlite")
    yield db
    db.close()


def _profile(channel: str = "cli") -> Profile:
    return Profile.model_validate(
        {
            "me": {"legal": "X", "pref": "X", "email": "x@y", "phone": "1"},
            "openclaw": {"channel": channel},
        }
    )


def test_pending_questions_has_channel_delivered_at_column(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(pending_questions)").fetchall()}
    assert "channel_delivered_at" in cols


def test_stage_surface_questions_marks_delivered_when_channel_succeeds(
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile(channel="telegram")
    conn.execute(
        "INSERT INTO pending_questions (job_url, question, asked_at) VALUES (?, ?, ?)",
        ("https://x/1", "Sponsor?", "2025-01-01T00:00:00Z"),
    )

    sent: list[tuple[int, str, str | None]] = []

    class FakeChannel:
        enabled = True

        def send_question(self, qid: int, q: str, url: str | None) -> bool:
            sent.append((qid, q, url))
            return True

    monkeypatch.setattr("nexscout.openclaw.channels.get_channel", lambda profile: FakeChannel())
    n = tick_mod._stage_surface_questions(profile, conn)
    assert n == 1
    assert len(sent) == 1
    row = conn.execute(
        "SELECT channel_delivered_at FROM pending_questions WHERE job_url=?",
        ("https://x/1",),
    ).fetchone()
    assert row["channel_delivered_at"] is not None


def test_stage_surface_questions_no_channel_leaves_column_null(
    conn: sqlite3.Connection,
) -> None:
    profile = _profile(channel="cli")
    conn.execute(
        "INSERT INTO pending_questions (job_url, question, asked_at) VALUES (?, ?, ?)",
        ("https://x/2", "Authorized?", "2025-01-01T00:00:00Z"),
    )
    n = tick_mod._stage_surface_questions(profile, conn)
    assert n == 1
    row = conn.execute(
        "SELECT channel_delivered_at FROM pending_questions WHERE job_url=?",
        ("https://x/2",),
    ).fetchone()
    assert row["channel_delivered_at"] is None


def test_stage_surface_questions_channel_failure_keeps_null(
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile(channel="telegram")
    conn.execute(
        "INSERT INTO pending_questions (job_url, question, asked_at) VALUES (?, ?, ?)",
        ("https://x/3", "Q?", "2025-01-01T00:00:00Z"),
    )

    class FailingChannel:
        enabled = True

        def send_question(self, *a: Any, **k: Any) -> bool:
            return False

    monkeypatch.setattr("nexscout.openclaw.channels.get_channel", lambda profile: FailingChannel())
    n = tick_mod._stage_surface_questions(profile, conn)
    assert n == 1
    row = conn.execute(
        "SELECT channel_delivered_at FROM pending_questions WHERE job_url=?",
        ("https://x/3",),
    ).fetchone()
    assert row["channel_delivered_at"] is None


def test_captcha_manual_send_alert_immediately(
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``mark_result`` with CAPTCHA_MANUAL pushes through the channel immediately."""
    from nexscout.apply import orchestrator as orch
    from nexscout.apply.result_codes import RESULT_CAPTCHA_MANUAL

    conn.execute(
        "INSERT INTO jobs (url, title, site, fit_score, apply_status, tailored_resume_path) VALUES (?, ?, ?, ?, ?, ?)",
        ("https://x/100", "Eng", "greenhouse", 8, None, "/tmp/r.pdf"),
    )

    sent: list[tuple[str, str | None]] = []

    class FakeChannel:
        enabled = True

        def send_captcha_alert(self, url: str, title: str | None = None) -> bool:
            sent.append((url, title))
            return True

    # Make Profile.from_path return something sensible.
    monkeypatch.setattr(
        "nexscout.core.profile.Profile.from_path",
        classmethod(lambda cls, path=None: _profile(channel="telegram")),
    )
    monkeypatch.setattr("nexscout.openclaw.channels.get_channel", lambda profile: FakeChannel())
    # Patch the orchestrator-module callers too (they import lazily).
    monkeypatch.setattr(orch, "_emit_captcha_alert", orch._emit_captcha_alert)

    orch.mark_result("https://x/100", RESULT_CAPTCHA_MANUAL, None, conn)
    assert sent == [("https://x/100", "Eng")]
    row = conn.execute(
        "SELECT channel_delivered_at FROM pending_questions WHERE job_url=?",
        ("https://x/100",),
    ).fetchone()
    assert row["channel_delivered_at"] is not None
