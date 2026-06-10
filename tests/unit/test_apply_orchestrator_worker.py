"""Coverage tests for the worker loop, mark_result optional kwargs, and the
result_codes branches in ``apply.orchestrator``."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from nexscout.apply import orchestrator
from nexscout.apply.orchestrator import (
    acquire_job,
    mark_result,
    release_lock,
    worker_loop,
)
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


def _insert(conn: sqlite3.Connection, url: str, *, score: int = 8) -> None:
    conn.execute(
        "INSERT INTO jobs (url, title, site, fit_score, tailored_resume_path) VALUES (?, ?, ?, ?, ?)",
        (url, "Engineer", "greenhouse", score, "/tmp/resume.txt"),
    )


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    return init_db(tmp_path / "test.sqlite")


# ---------------------------------------------------------------------------
# mark_result branches
# ---------------------------------------------------------------------------


class TestMarkResultKwargs:
    def test_records_duration_cost_captcha_bundle(self, db: sqlite3.Connection) -> None:
        _insert(db, "https://a.com/1")
        mark_result(
            "https://a.com/1",
            "APPLIED",
            None,
            db,
            duration_ms=4321,
            cost_usd=0.42,
            captcha_solved=True,
            bundle_dir="/tmp/bundle",
        )
        row = db.execute(
            "SELECT apply_duration_ms, cost_usd, captcha_solved, bundle_dir FROM jobs WHERE url=?",
            ("https://a.com/1",),
        ).fetchone()
        assert row["apply_duration_ms"] == 4321
        assert abs(row["cost_usd"] - 0.42) < 1e-9
        assert row["captcha_solved"] == 1
        assert row["bundle_dir"] == "/tmp/bundle"

    def test_captcha_false_persists_zero(self, db: sqlite3.Connection) -> None:
        _insert(db, "https://a.com/1")
        mark_result("https://a.com/1", "APPLIED", None, db, captcha_solved=False)
        row = db.execute("SELECT captcha_solved FROM jobs WHERE url=?", ("https://a.com/1",)).fetchone()
        assert row["captcha_solved"] == 0

    def test_cost_accumulates(self, db: sqlite3.Connection) -> None:
        _insert(db, "https://a.com/1")
        mark_result("https://a.com/1", "FAILED", "page_error", db, cost_usd=0.10)
        mark_result("https://a.com/1", "FAILED", "page_error", db, cost_usd=0.30)
        row = db.execute("SELECT cost_usd FROM jobs WHERE url=?", ("https://a.com/1",)).fetchone()
        assert abs(row["cost_usd"] - 0.40) < 1e-9

    def test_expired_is_permanent(self, db: sqlite3.Connection) -> None:
        _insert(db, "https://a.com/1")
        mark_result("https://a.com/1", "EXPIRED", None, db)
        row = db.execute("SELECT apply_status, apply_attempts FROM jobs WHERE url=?", ("https://a.com/1",)).fetchone()
        assert row["apply_status"] == "expired"
        assert row["apply_attempts"] == 99

    def test_login_issue_is_permanent(self, db: sqlite3.Connection) -> None:
        _insert(db, "https://a.com/1")
        mark_result("https://a.com/1", "LOGIN_ISSUE", None, db)
        row = db.execute("SELECT apply_status, apply_attempts FROM jobs WHERE url=?", ("https://a.com/1",)).fetchone()
        assert row["apply_status"] == "login_issue"
        assert row["apply_attempts"] == 99


# ---------------------------------------------------------------------------
# worker_loop
# ---------------------------------------------------------------------------


class _FakeRunner:
    """Pluggable runner so the worker loop can be exercised without LLM/browser."""

    def __init__(self, codes: list[tuple[str, str | None, float, bool]]) -> None:
        self.codes = codes
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> tuple[str, str | None, float, bool]:
        self.calls.append(kwargs)
        return self.codes.pop(0) if self.codes else ("FAILED", "page_error", 0.0, False)


class _NoOpDashboard:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def start_job(self, worker_id: int, job: dict[str, Any]) -> None:
        self.events.append(("start", {"worker": worker_id, "url": job["url"]}))

    def finish_job(self, worker_id: int, code: str, *, reason: str | None = None) -> None:
        self.events.append(("finish", {"worker": worker_id, "code": code, "reason": reason}))

    def tick_action(self, worker_id: int, action: str) -> None:
        self.events.append(("action", {"worker": worker_id, "action": action}))


def _ensure_bundle(tmp_path: Path) -> Any:
    def make(_id: int) -> Path:
        d = tmp_path / f"{_id:06d}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    return make


def test_worker_loop_processes_then_exits(
    db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Loop acquires both jobs, calls runner, then exits (non-continuous, no limit)."""
    monkeypatch.setattr("nexscout.apply.orchestrator.bundle_dir_for", _ensure_bundle(tmp_path))
    _insert(db, "https://a.com/1", score=9)
    _insert(db, "https://b.com/2", score=8)

    runner = _FakeRunner(
        [
            ("APPLIED", None, 0.05, False),
            ("APPLIED", None, 0.07, True),
        ]
    )
    dashboard = _NoOpDashboard()
    count = worker_loop(
        worker_id=0,
        profile=_profile(),
        db_conn=db,
        solver=None,
        llm_router=object(),  # type: ignore[arg-type]
        runner=runner,
        dashboard=dashboard,
        continuous=False,
    )
    assert count == 2
    assert len(runner.calls) == 2

    # Both rows are now `applied`.
    rows = list(db.execute("SELECT url, apply_status, cost_usd FROM jobs ORDER BY url").fetchall())
    assert all(r["apply_status"] == "applied" for r in rows)
    # cost was recorded for both
    assert any(r["cost_usd"] for r in rows)

    # `result.json` was written into the bundle dir.
    assert (tmp_path / "000001" / "result.json").exists()
    payload = json.loads((tmp_path / "000001" / "result.json").read_text())
    assert payload["code"] == "APPLIED"
    assert payload["agent_id"] == "worker-0"
    assert payload["backend"] == "native"


def test_worker_loop_respects_limit(db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nexscout.apply.orchestrator.bundle_dir_for", _ensure_bundle(tmp_path))
    _insert(db, "https://a.com/1", score=9)
    _insert(db, "https://b.com/2", score=8)
    runner = _FakeRunner(
        [
            ("APPLIED", None, 0.0, False),
            ("APPLIED", None, 0.0, False),
        ]
    )
    count = worker_loop(
        worker_id=0,
        profile=_profile(),
        db_conn=db,
        solver=None,
        llm_router=object(),  # type: ignore[arg-type]
        runner=runner,
        limit=1,
        continuous=False,
    )
    assert count == 1


def test_worker_loop_catches_runner_exception(
    db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crashing runner is caught, marked a real fault, and the loop continues.

    The job is marked ``failed`` with ``worker_crashed`` (so apply_attempts
    bumps and it can't spin forever) — never re-acquired endlessly, never a
    bubbled traceback.
    """
    monkeypatch.setattr("nexscout.apply.orchestrator.bundle_dir_for", _ensure_bundle(tmp_path))
    _insert(db, "https://a.com/1", score=9)

    def boom(**_: Any) -> tuple[str, str | None, float, bool]:
        raise RuntimeError("kaboom")

    count = worker_loop(
        worker_id=0,
        profile=_profile(),
        db_conn=db,
        solver=None,
        llm_router=object(),  # type: ignore[arg-type]
        runner=boom,
        limit=1,  # process exactly one pass so we can inspect the first mark
        continuous=False,
    )
    # The job was processed (not abandoned) and the loop returned cleanly.
    assert count == 1
    row = db.execute(
        "SELECT apply_status, apply_error, apply_attempts FROM jobs WHERE url=?",
        ("https://a.com/1",),
    ).fetchone()
    # A genuine fault status with a bumped attempt count (bounded retry, NOT a
    # permanent freeze and NOT an endless re-acquire).
    assert row["apply_status"] == "failed"
    assert row["apply_error"] == "worker_crashed"
    assert row["apply_attempts"] == 1


def test_worker_loop_driver_acquire_failure_backs_off(
    db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A browser/driver launch failure releases the lock and backs off.

    It is an environment-level infra problem, NOT a posting fault, so the job
    is NOT marked an error (apply_status stays NULL / eligible) and the worker
    stops churning. No traceback escapes.
    """
    monkeypatch.setattr("nexscout.apply.orchestrator.bundle_dir_for", _ensure_bundle(tmp_path))
    _insert(db, "https://a.com/1", score=9)

    class _BadPool:
        def acquire(self, _worker_id: int) -> Any:
            raise RuntimeError("chromedriver not found")

        def release(self, _worker_id: int, _driver: Any) -> None:  # pragma: no cover
            pass

    count = worker_loop(
        worker_id=0,
        profile=_profile(),
        db_conn=db,
        solver=None,
        llm_router=object(),  # type: ignore[arg-type]
        runner=_FakeRunner([("APPLIED", None, 0.0, False)]),
        pool=_BadPool(),
        continuous=False,
    )
    # Backed off before completing any job; nothing marked as an error.
    assert count == 0
    row = db.execute(
        "SELECT apply_status, apply_error, apply_attempts FROM jobs WHERE url=?",
        ("https://a.com/1",),
    ).fetchone()
    assert row["apply_status"] is None  # lock released, still eligible
    assert row["apply_error"] is None
    assert row["apply_attempts"] == 0


def test_worker_loop_default_runner_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_default_runner`` returns the apply.agent.run_agent callable."""
    runner = orchestrator._default_runner()  # type: ignore[attr-defined]
    from nexscout.apply.agent import run_agent

    assert runner is run_agent


# ---------------------------------------------------------------------------
# Release lock — additional path
# ---------------------------------------------------------------------------


def test_release_lock_no_op_on_other_status(db: sqlite3.Connection) -> None:
    _insert(db, "https://a.com/1")
    # apply_status is NULL — release should be a no-op.
    release_lock("https://a.com/1", db, agent_id="worker-0")
    row = db.execute("SELECT apply_status FROM jobs WHERE url=?", ("https://a.com/1",)).fetchone()
    assert row["apply_status"] is None


# ---------------------------------------------------------------------------
# Acquire policy plumbing
# ---------------------------------------------------------------------------


def test_acquire_excludes_blocked_sites(
    db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _insert(db, "https://a.com/1", score=9)
    db.execute("UPDATE jobs SET site='glassdoor' WHERE url='https://a.com/1'")

    from nexscout.apply.policy import ApplyPolicy

    def _fake_policy() -> ApplyPolicy:
        return ApplyPolicy(
            blocked_sites=["glassdoor"],
            blocked_url_patterns=[],
            blocked_sso=[],
            manual_ats=[],
        )

    monkeypatch.setattr("nexscout.apply.orchestrator.load_policy", _fake_policy)
    assert acquire_job(_profile(), db, agent_id="worker-0") is None


def test_acquire_excludes_blocked_url_patterns(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    _insert(db, "https://glassdoor.com/job/1", score=9)
    from nexscout.apply.policy import ApplyPolicy

    def _fake_policy() -> ApplyPolicy:
        return ApplyPolicy(
            blocked_sites=[],
            blocked_url_patterns=["%glassdoor%"],
            blocked_sso=[],
            manual_ats=[],
        )

    monkeypatch.setattr("nexscout.apply.orchestrator.load_policy", _fake_policy)
    assert acquire_job(_profile(), db, agent_id="worker-0") is None
