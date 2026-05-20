"""Tick orchestrator — mock all stages, verify budget enforcement + summary."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from nexscout.core.database import init_db
from nexscout.core.profile import Profile
from nexscout.openclaw import tick


@pytest.fixture
def profile() -> Profile:
    return Profile.model_validate(
        {
            "me": {"legal": "X", "pref": "X", "email": "x@y", "phone": "1"},
            "captcha": {"api_key": "x"},
            "openclaw": {
                "tick_budget": {
                    "discover_per_engine": 2,
                    "enrich": 3,
                    "score": 4,
                    "tailor": 1,
                    "apply": 2,
                }
            },
        }
    )


@pytest.fixture
def conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    monkeypatch.setenv("NEXSCOUT_DIR", str(tmp_path / ".nexscout"))
    return init_db(tmp_path / ".nexscout" / "test.sqlite")


def test_tick_runs_all_stages_with_mocks(
    conn: sqlite3.Connection, profile: Profile, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tick, "_stage_discover", lambda *a, **k: 5)
    monkeypatch.setattr(tick, "_stage_enrich", lambda *a, **k: 7)
    monkeypatch.setattr(tick, "_stage_score", lambda *a, **k: 11)
    monkeypatch.setattr(tick, "_stage_tailor", lambda *a, **k: 1)
    monkeypatch.setattr(tick, "_stage_render", lambda *a, **k: 2)
    monkeypatch.setattr(tick, "_stage_apply", lambda *a, **k: 3)
    monkeypatch.setattr(tick, "_stage_surface_questions", lambda *a, **k: 0)

    summary = tick.run(profile=profile, db=conn)
    assert summary["discovered"] == 5
    assert summary["enriched"] == 7
    assert summary["scored"] == 11
    assert summary["tailored"] == 1
    assert summary["rendered"] == 2
    assert summary["applied"] == 3
    assert summary["errors"] == []
    assert summary["duration_s"] >= 0


def test_tick_catches_stage_errors(
    conn: sqlite3.Connection, profile: Profile, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*a, **k):
        raise RuntimeError("oops")

    monkeypatch.setattr(tick, "_stage_discover", boom)
    monkeypatch.setattr(tick, "_stage_enrich", lambda *a, **k: 1)
    monkeypatch.setattr(tick, "_stage_score", lambda *a, **k: 1)
    monkeypatch.setattr(tick, "_stage_tailor", lambda *a, **k: 0)
    monkeypatch.setattr(tick, "_stage_render", lambda *a, **k: 0)
    monkeypatch.setattr(tick, "_stage_apply", lambda *a, **k: 0)
    monkeypatch.setattr(tick, "_stage_surface_questions", lambda *a, **k: 0)

    summary = tick.run(profile=profile, db=conn)
    assert any("oops" in e for e in summary["errors"])
    # Other stages still ran.
    assert summary["enriched"] == 1


def test_tick_respects_wall_clock(
    conn: sqlite3.Connection, profile: Profile, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the wall clock is 0, every stage is skipped."""
    called: list[str] = []

    def fake(name: str):
        def inner(*a, **k):
            called.append(name)
            return 1

        return inner

    monkeypatch.setattr(tick, "_stage_discover", fake("discover"))
    monkeypatch.setattr(tick, "_stage_enrich", fake("enrich"))
    monkeypatch.setattr(tick, "_stage_score", fake("score"))
    monkeypatch.setattr(tick, "_stage_tailor", fake("tailor"))
    monkeypatch.setattr(tick, "_stage_render", fake("render"))
    monkeypatch.setattr(tick, "_stage_apply", fake("apply"))
    monkeypatch.setattr(tick, "_stage_surface_questions", fake("questions"))

    # Set the wall clock to a negative number — deadline already past.
    summary = tick.run(profile=profile, db=conn, wall_clock_s=-1.0)
    assert called == []
    assert summary["discovered"] == 0


def test_tick_filters_stages(
    conn: sqlite3.Connection, profile: Profile, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tick, "_stage_discover", lambda *a, **k: 5)
    monkeypatch.setattr(tick, "_stage_enrich", lambda *a, **k: 99)
    summary = tick.run(profile=profile, db=conn, stages={"discover"})
    assert summary["discovered"] == 5
    assert summary["enriched"] == 0


def test_surface_questions_writes_inbox(
    conn: sqlite3.Connection, profile: Profile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    # Ensure Path.home() reads HOME on this platform.
    if hasattr(Path, "home"):
        # On Windows Path.home() reads USERPROFILE; set both.
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
    conn.execute(
        "INSERT INTO pending_questions (job_url, question, asked_at) VALUES (?, ?, ?)",
        ("https://x.com/1", "Sponsor?", "2026-05-20T00:00:00Z"),
    )
    n = tick._stage_surface_questions(profile, conn)
    assert n == 1
    inbox = tmp_path / ".openclaw" / "inbox"
    files = list(inbox.glob("nexscout-*.md"))
    assert files, f"expected an inbox file under {inbox}"
    assert "Sponsor?" in files[0].read_text(encoding="utf-8")


def test_summary_one_liner_format(profile: Profile) -> None:
    s = tick.TickSummary(discovered=1, scored=2, applied=3, duration_s=0.5)
    line = s.to_one_liner()
    assert "discovered=1" in line
    assert "scored=2" in line
    assert "applied=3" in line
    assert "errors=0" in line
    assert "(0.5s)" in line
