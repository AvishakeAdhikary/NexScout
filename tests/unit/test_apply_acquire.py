"""SQLite-backed test of the atomic acquire query (§5)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nexscout.apply.orchestrator import acquire_job, mark_result, release_lock
from nexscout.core.database import init_db
from nexscout.core.profile import Profile


def _profile() -> Profile:
    return Profile.model_validate(
        {
            "me": {"legal": "Jane", "pref": "Jane", "email": "j@x.com", "phone": "1"},
            "auth": {"authorized": True, "sponsor": False, "permit": "USC"},
            "search": {"min_score": 7},
            "apply": {"max_attempts": 3},
            "captcha": {"provider": "capsolver", "api_key": "x"},
        }
    )


def _insert_job(
    conn: sqlite3.Connection,
    url: str,
    *,
    title: str = "Engineer",
    site: str = "greenhouse",
    fit_score: int = 8,
    tailored_resume_path: str | None = "/tmp/resume.txt",
    apply_status: str | None = None,
    apply_attempts: int = 0,
) -> None:
    conn.execute(
        "INSERT INTO jobs (url, title, site, fit_score, tailored_resume_path, apply_status, apply_attempts) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (url, title, site, fit_score, tailored_resume_path, apply_status, apply_attempts),
    )


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    return init_db(tmp_path / "test.sqlite")


class TestAcquireJob:
    def test_returns_highest_score(self, db: sqlite3.Connection) -> None:
        _insert_job(db, "https://a.com/1", fit_score=7)
        _insert_job(db, "https://b.com/2", fit_score=9)
        _insert_job(db, "https://c.com/3", fit_score=8)
        got = acquire_job(_profile(), db, agent_id="worker-0")
        assert got is not None
        assert got["url"] == "https://b.com/2"
        assert got["fit_score"] == 9

    def test_skips_without_tailored_resume(self, db: sqlite3.Connection) -> None:
        _insert_job(db, "https://a.com/1", tailored_resume_path=None)
        assert acquire_job(_profile(), db, agent_id="worker-0") is None

    def test_skips_below_min_score(self, db: sqlite3.Connection) -> None:
        _insert_job(db, "https://a.com/1", fit_score=5)
        assert acquire_job(_profile(), db, agent_id="worker-0") is None

    def test_skips_in_progress(self, db: sqlite3.Connection) -> None:
        _insert_job(db, "https://a.com/1", apply_status="in_progress")
        assert acquire_job(_profile(), db, agent_id="worker-0") is None

    def test_picks_up_failed(self, db: sqlite3.Connection) -> None:
        _insert_job(db, "https://a.com/1", apply_status="failed", apply_attempts=1)
        got = acquire_job(_profile(), db, agent_id="worker-0")
        assert got is not None
        assert got["url"] == "https://a.com/1"

    def test_respects_max_attempts(self, db: sqlite3.Connection) -> None:
        _insert_job(db, "https://a.com/1", apply_status="failed", apply_attempts=3)
        assert acquire_job(_profile(), db, agent_id="worker-0") is None

    def test_marks_in_progress(self, db: sqlite3.Connection) -> None:
        _insert_job(db, "https://a.com/1")
        got = acquire_job(_profile(), db, agent_id="worker-7")
        assert got is not None
        row = db.execute(
            "SELECT apply_status, agent_id FROM jobs WHERE url=?", (got["url"],)
        ).fetchone()
        assert row["apply_status"] == "in_progress"
        assert row["agent_id"] == "worker-7"

    def test_concurrency_disjoint(self, db: sqlite3.Connection) -> None:
        """Two consecutive acquires return different rows (atomic update prevents duplication)."""
        _insert_job(db, "https://a.com/1", fit_score=9)
        _insert_job(db, "https://b.com/2", fit_score=8)
        first = acquire_job(_profile(), db, agent_id="worker-0")
        second = acquire_job(_profile(), db, agent_id="worker-1")
        assert first is not None and second is not None
        assert first["url"] != second["url"]


class TestMarkResult:
    def test_applied(self, db: sqlite3.Connection) -> None:
        _insert_job(db, "https://a.com/1", apply_status="in_progress")
        mark_result("https://a.com/1", "APPLIED", None, db)
        row = db.execute("SELECT apply_status, applied_at FROM jobs WHERE url=?", ("https://a.com/1",)).fetchone()
        assert row["apply_status"] == "applied"
        assert row["applied_at"] is not None

    def test_permanent_failure_freezes_at_99(self, db: sqlite3.Connection) -> None:
        _insert_job(db, "https://a.com/1", apply_status="in_progress")
        mark_result("https://a.com/1", "FAILED", "sso_required", db)
        row = db.execute("SELECT apply_status, apply_attempts FROM jobs WHERE url=?", ("https://a.com/1",)).fetchone()
        assert row["apply_status"] == "failed"
        assert row["apply_attempts"] == 99

    def test_transient_failure_bumps_attempts(self, db: sqlite3.Connection) -> None:
        _insert_job(db, "https://a.com/1", apply_status="in_progress", apply_attempts=1)
        mark_result("https://a.com/1", "FAILED", "page_error", db)
        row = db.execute("SELECT apply_attempts FROM jobs WHERE url=?", ("https://a.com/1",)).fetchone()
        assert row["apply_attempts"] == 2

    def test_captcha_is_permanent(self, db: sqlite3.Connection) -> None:
        _insert_job(db, "https://a.com/1", apply_status="in_progress")
        mark_result("https://a.com/1", "CAPTCHA", None, db)
        row = db.execute("SELECT apply_status, apply_attempts FROM jobs WHERE url=?", ("https://a.com/1",)).fetchone()
        assert row["apply_status"] == "captcha"
        assert row["apply_attempts"] == 99


class TestReleaseLock:
    def test_releases_in_progress_for_matching_agent(self, db: sqlite3.Connection) -> None:
        _insert_job(db, "https://a.com/1", apply_status="in_progress")
        db.execute("UPDATE jobs SET agent_id='worker-3' WHERE url='https://a.com/1'")
        release_lock("https://a.com/1", db, agent_id="worker-3")
        row = db.execute("SELECT apply_status FROM jobs WHERE url=?", ("https://a.com/1",)).fetchone()
        assert row["apply_status"] is None

    def test_no_op_when_agent_mismatches(self, db: sqlite3.Connection) -> None:
        _insert_job(db, "https://a.com/1", apply_status="in_progress")
        db.execute("UPDATE jobs SET agent_id='worker-3' WHERE url='https://a.com/1'")
        release_lock("https://a.com/1", db, agent_id="worker-9")
        row = db.execute("SELECT apply_status FROM jobs WHERE url=?", ("https://a.com/1",)).fetchone()
        assert row["apply_status"] == "in_progress"


def test_acquire_then_mark_then_acquire_again(db: sqlite3.Connection) -> None:
    _insert_job(db, "https://a.com/1")
    profile = _profile()
    first = acquire_job(profile, db, agent_id="worker-0")
    assert first is not None
    # Mark transient failure → eligible again on next call.
    mark_result(first["url"], "FAILED", "page_error", db)
    second = acquire_job(profile, db, agent_id="worker-1")
    assert second is not None
    assert second["url"] == first["url"]


def test_acquire_iso_timestamp(db: sqlite3.Connection) -> None:
    """The acquire query stamps ``last_attempted_at`` with a parseable ISO date."""
    _insert_job(db, "https://a.com/1")
    acquire_job(_profile(), db, agent_id="worker-0")
    row = db.execute("SELECT last_attempted_at FROM jobs WHERE url='https://a.com/1'").fetchone()
    assert row["last_attempted_at"] is not None
    dt = datetime.fromisoformat(row["last_attempted_at"])
    assert dt.tzinfo == UTC
