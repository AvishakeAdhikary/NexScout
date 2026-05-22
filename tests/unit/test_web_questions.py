"""Answer flow: updates DB and writes markdown."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nexscout.core.database import init_db
from nexscout.web.app import create_app


@pytest.fixture
def db() -> sqlite3.Connection:
    # The conftest fixture sets NEXSCOUT_DIR per-test; init_db() uses the
    # default path under that env var so the route handler and this fixture
    # share state.
    conn = init_db()
    conn.execute("INSERT INTO jobs (url) VALUES ('https://x.com/1')")
    conn.execute(
        "INSERT INTO pending_questions (job_url, question, asked_at) VALUES (?, ?, ?)",
        ("https://x.com/1", "Are you authorised to work in Canada?", "2026-05-20T00:00:00Z"),
    )
    # Mark the job as paused waiting for the answer.
    conn.execute("UPDATE jobs SET apply_status='paused_for_question' WHERE url='https://x.com/1'")
    return conn


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db: sqlite3.Connection) -> TestClient:
    _ = db  # ensure the fixture seeds the DB before the client builds its app
    monkeypatch.setenv("OPENCLAW_MEMORY_ROOT", str(tmp_path / "openclaw-memory"))
    app = create_app()
    return TestClient(app)


def test_questions_page_lists_pending(client: TestClient) -> None:
    resp = client.get("/questions")
    assert resp.status_code == 200
    assert "Are you authorised to work in Canada?" in resp.text


def test_answer_updates_db_and_writes_memory(client: TestClient, db: sqlite3.Connection, tmp_path: Path) -> None:
    qid = int(db.execute("SELECT id FROM pending_questions ORDER BY id DESC LIMIT 1").fetchone()["id"])
    resp = client.post(
        "/api/answer",
        data={"question_id": str(qid), "reply": "Yes, I am a Canadian PR."},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    row = db.execute("SELECT answer, answered_at FROM pending_questions WHERE id=?", (qid,)).fetchone()
    assert row["answer"] == "Yes, I am a Canadian PR."
    assert row["answered_at"] is not None

    job_row = db.execute("SELECT apply_status FROM jobs WHERE url=?", ("https://x.com/1",)).fetchone()
    assert job_row["apply_status"] is None  # paused_for_question cleared

    memory_dir = tmp_path / "openclaw-memory"
    learned = memory_dir / "learned-answers.md"
    assert learned.exists()
    txt = learned.read_text(encoding="utf-8")
    assert "Are you authorised to work in Canada?" in txt
    assert "Yes, I am a Canadian PR." in txt


def test_answer_for_unknown_question_id_is_noop(client: TestClient) -> None:
    resp = client.post(
        "/api/answer",
        data={"question_id": "99999", "reply": "ignored"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
