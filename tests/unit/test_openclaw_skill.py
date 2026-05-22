"""Slash dispatch — mocked DB, every handler returns sane output."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from nexscout.core.database import init_db
from nexscout.openclaw import skill


@pytest.fixture(autouse=True)
def _isolate_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCLAW_MEMORY_ROOT", str(tmp_path / "memroot"))


@pytest.fixture
def conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    monkeypatch.setenv("NEXSCOUT_DIR", str(tmp_path / ".nexscout"))
    return init_db()


def test_dispatch_unknown_command(conn: sqlite3.Connection) -> None:
    _ = conn
    out = skill.dispatch("hello", "")
    assert "error" in out
    assert "available" in out


def test_status_returns_text(conn: sqlite3.Connection) -> None:
    _ = conn
    out = skill.dispatch("status", "")
    assert "text" in out
    assert "applied=" in out["text"]


def test_apply_emits_command(conn: sqlite3.Connection) -> None:
    _ = conn
    out = skill.dispatch("apply", ["https://example.com/job/1"])
    assert out["command"][0:2] == ["nexscout", "apply"]
    assert "https://example.com/job/1" in out["command"]


def test_pause_and_resume(conn: sqlite3.Connection) -> None:
    _ = conn
    p = skill.dispatch("pause", "")
    r = skill.dispatch("resume", "")
    assert p["text"] == "paused"
    assert r["text"] == "resumed"


def test_question_empty(conn: sqlite3.Connection) -> None:
    out = skill.dispatch("question", "")
    assert out["text"] == "no pending questions"


def test_question_with_pending(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO pending_questions (job_url, question, asked_at) VALUES (?, ?, ?)",
        ("https://x.com/1", "What is your work auth?", "2026-05-20T00:00:00Z"),
    )
    out = skill.dispatch("question", "")
    assert "What is your work auth?" in out["text"]
    assert out["items"]


def test_answer_persists_to_memory_and_clears_pause(conn: sqlite3.Connection, tmp_path: Path) -> None:
    conn.execute(
        "INSERT INTO pending_questions (job_url, question, asked_at) VALUES (?, ?, ?)",
        ("https://x.com/1", "Sponsor?", "2026-05-20T00:00:00Z"),
    )
    conn.execute("INSERT INTO jobs (url, apply_status) VALUES ('https://x.com/1', 'paused_for_question')")
    out = skill.dispatch("answer", ["Sponsor?", "No"])
    assert "answered" in out["text"]
    row = conn.execute("SELECT answer, answered_at FROM pending_questions").fetchone()
    assert row["answer"] == "No"
    job = conn.execute("SELECT apply_status FROM jobs WHERE url='https://x.com/1'").fetchone()
    assert job["apply_status"] is None
    learned = tmp_path / "memroot" / "learned-answers.md"
    assert learned.exists()
    assert "Sponsor?" in learned.read_text(encoding="utf-8")


def test_answer_with_no_matching_question_still_records(conn: sqlite3.Connection, tmp_path: Path) -> None:
    _ = conn
    out = skill.dispatch("answer", ["Unknown question?", "sure"])
    assert "no matching" in out["text"]
    learned = tmp_path / "memroot" / "learned-answers.md"
    assert "Unknown question?" in learned.read_text(encoding="utf-8")


def test_dispatch_splits_string_args(conn: sqlite3.Connection) -> None:
    _ = conn
    out = skill.dispatch("apply", "https://example.com/x")
    assert "https://example.com/x" in out["command"]
