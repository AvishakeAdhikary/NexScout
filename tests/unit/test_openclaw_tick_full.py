"""Coverage push for ``openclaw.tick`` — stage wrappers + error paths."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from nexscout.core.database import init_db
from nexscout.core.profile import Profile
from nexscout.openclaw import tick


def _profile() -> Profile:
    return Profile.model_validate(
        {
            "me": {"legal": "x", "pref": "x", "email": "e@x.com", "phone": "1"},
            "captcha": {"provider": "capsolver", "api_key": ""},
        }
    )


@pytest.fixture
def db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    conn = init_db(tmp_path / "x.sqlite")
    yield conn
    conn.close()


def test_tick_summary_to_one_liner() -> None:
    s = tick.TickSummary(discovered=3, enriched=2, scored=10, errors=["a"])
    out = s.to_one_liner()
    assert "discovered=3" in out
    assert "errors=1" in out


def test_run_stage_catches_exceptions() -> None:
    s = tick.TickSummary()

    def _boom() -> None:
        raise RuntimeError("nope")

    out = tick._run_stage("bad", _boom, summary=s)
    assert out is None
    assert s.errors and "nope" in s.errors[0]


def test_run_stage_respects_deadline() -> None:
    s = tick.TickSummary()
    called: list[int] = []

    def _ok() -> int:
        called.append(1)
        return 5

    out = tick._run_stage("x", _ok, summary=s, deadline=0.0)
    assert out is None
    assert not called


def test_run_stage_success() -> None:
    s = tick.TickSummary()
    assert tick._run_stage("ok", lambda: 7, summary=s) == 7


def test_run_full_with_mocked_stages(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive every stage with a no-op so the orchestration loop is fully covered."""
    monkeypatch.setattr(tick, "_stage_discover", lambda p, c, n: 3)
    monkeypatch.setattr(tick, "_stage_enrich", lambda p, c, n, **kw: 2)
    monkeypatch.setattr(tick, "_stage_score", lambda p, c, n, **kw: 10)
    monkeypatch.setattr(tick, "_stage_tailor", lambda p, c, n, **kw: 4)
    monkeypatch.setattr(tick, "_stage_cover", lambda p, c, n, **kw: 0)
    monkeypatch.setattr(tick, "_stage_render", lambda p, c, **kw: 1)
    monkeypatch.setattr(tick, "_stage_apply", lambda p, c, n: 0)
    monkeypatch.setattr(tick, "_stage_surface_questions", lambda p, c: 0)

    out = tick.run(profile=_profile(), db=db, wall_clock_s=10.0)
    assert out["discovered"] == 3
    assert out["scored"] == 10
    assert out["covered"] == 0
    assert out["errors"] == []


def test_run_subset_of_stages(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    def record(name: str) -> Any:
        def fn(*a: Any, **kw: Any) -> int:
            called.append(name)
            return 0

        return fn

    monkeypatch.setattr(tick, "_stage_discover", record("discover"))
    monkeypatch.setattr(tick, "_stage_enrich", record("enrich"))
    monkeypatch.setattr(tick, "_stage_score", record("score"))
    monkeypatch.setattr(tick, "_stage_tailor", record("tailor"))
    monkeypatch.setattr(tick, "_stage_render", record("render"))
    monkeypatch.setattr(tick, "_stage_apply", record("apply"))
    monkeypatch.setattr(tick, "_stage_surface_questions", record("questions"))

    tick.run(profile=_profile(), db=db, wall_clock_s=10.0, stages={"discover", "score"})
    assert called == ["discover", "score"]


def test_stage_discover_router_failure(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    """If LLMRouter fails to build, _stage_discover still runs without a router."""

    class _BadRouter:
        def __init__(self, *a: Any, **kw: Any) -> None:
            raise RuntimeError("provider broken")

    monkeypatch.setattr("nexscout.llm.router.LLMRouter", _BadRouter)
    monkeypatch.setattr("nexscout.pipeline.run_discover_stage", lambda **kw: 4)
    out = tick._stage_discover(_profile(), db, 10)
    assert out == 4


def test_stage_enrich_no_browser(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the browser factory can't be built, _stage_enrich returns 0."""

    def _boom(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("no Chrome")

    monkeypatch.setattr("nexscout.browser.driver.UndetectedFactory", _boom)
    out = tick._stage_enrich(_profile(), db, 5)
    assert out == 0


def test_stage_enrich_runs_with_factory(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    """Factory succeeds → returns the count from run_enrich_stage."""

    class _Fac:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

    monkeypatch.setattr("nexscout.browser.driver.UndetectedFactory", _Fac)

    class _Router:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

    monkeypatch.setattr("nexscout.llm.router.LLMRouter", _Router)
    monkeypatch.setattr("nexscout.pipeline.run_enrich_stage", lambda **kw: 9)
    out = tick._stage_enrich(_profile(), db, 5)
    assert out == 9


def test_stage_score_runs(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    class _Router:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

    monkeypatch.setattr("nexscout.llm.router.LLMRouter", _Router)
    monkeypatch.setattr("nexscout.pipeline.run_score_stage", lambda **kw: 11)
    out = tick._stage_score(_profile(), db, 10)
    assert out == 11


def test_stage_tailor_runs(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    class _Router:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

    monkeypatch.setattr("nexscout.llm.router.LLMRouter", _Router)
    monkeypatch.setattr("nexscout.pipeline.run_tailor_stage", lambda **kw: 6)
    out = tick._stage_tailor(_profile(), db, 5)
    assert out == 6


def test_stage_render(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nexscout.pipeline.run_render_stage", lambda **kw: 2)
    out = tick._stage_render(_profile(), db)
    assert out == 2


def test_stage_apply_no_eligible(db: sqlite3.Connection) -> None:
    """When no tailored rows exist, _stage_apply short-circuits to 0."""
    out = tick._stage_apply(_profile(), db, 3)
    assert out == 0


def test_stage_apply_runs(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    db.execute(
        "INSERT INTO jobs (url, tailored_resume_path, apply_status) VALUES (?, ?, NULL)",
        ("https://x.com/1", "/tmp/r.txt"),
    )

    class _Pool:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        def close_all(self) -> None:
            pass

    monkeypatch.setattr("nexscout.browser.pool.BrowserPool", _Pool)
    monkeypatch.setattr("nexscout.captcha.capsolver.CapSolverSolver", lambda *a, **kw: None)

    class _Router:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

    monkeypatch.setattr("nexscout.llm.router.LLMRouter", _Router)
    monkeypatch.setattr("nexscout.apply.orchestrator.worker_loop", lambda *a, **kw: 1)
    out = tick._stage_apply(_profile(), db, 3)
    assert out == 1


def test_stage_apply_router_failure(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    db.execute(
        "INSERT INTO jobs (url, tailored_resume_path, apply_status) VALUES (?, ?, NULL)",
        ("https://x.com/1", "/tmp/r.txt"),
    )

    class _Pool:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        def close_all(self) -> None:
            pass

    monkeypatch.setattr("nexscout.browser.pool.BrowserPool", _Pool)

    class _BadRouter:
        def __init__(self, *a: Any, **kw: Any) -> None:
            raise RuntimeError("provider gone")

    monkeypatch.setattr("nexscout.llm.router.LLMRouter", _BadRouter)
    out = tick._stage_apply(_profile(), db, 3)
    assert out == 0


def test_stage_apply_pool_failure(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    db.execute(
        "INSERT INTO jobs (url, tailored_resume_path, apply_status) VALUES (?, ?, NULL)",
        ("https://x.com/1", "/tmp/r.txt"),
    )

    class _BadPool:
        def __init__(self, *a: Any, **kw: Any) -> None:
            raise RuntimeError("no Chrome")

    monkeypatch.setattr("nexscout.browser.pool.BrowserPool", _BadPool)
    monkeypatch.setattr("nexscout.llm.router.LLMRouter", lambda *a, **kw: None)
    out = tick._stage_apply(_profile(), db, 3)
    assert out == 0


def test_stage_apply_worker_crash(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    db.execute(
        "INSERT INTO jobs (url, tailored_resume_path, apply_status) VALUES (?, ?, NULL)",
        ("https://x.com/1", "/tmp/r.txt"),
    )

    class _Pool:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        def close_all(self) -> None:
            pass

    monkeypatch.setattr("nexscout.browser.pool.BrowserPool", _Pool)
    monkeypatch.setattr("nexscout.llm.router.LLMRouter", lambda *a, **kw: object())

    def _crash(*a: Any, **kw: Any) -> int:
        raise RuntimeError("worker crashed")

    monkeypatch.setattr("nexscout.apply.orchestrator.worker_loop", _crash)
    out = tick._stage_apply(_profile(), db, 3)
    assert out == 0


def test_stage_surface_questions_no_rows(db: sqlite3.Connection) -> None:
    assert tick._stage_surface_questions(_profile(), db) == 0


def test_stage_surface_questions_writes_inbox(
    db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db.execute(
        "INSERT INTO pending_questions (job_url, question, asked_at) VALUES (?, ?, ?)",
        ("https://x.com/1", "Authorized?", "2025"),
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    out = tick._stage_surface_questions(_profile(), db)
    assert out == 1
    assert (tmp_path / ".openclaw" / "inbox").exists()
