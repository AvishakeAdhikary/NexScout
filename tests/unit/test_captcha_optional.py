"""CAPTCHA is now OPTIONAL (Task-4 spec).

Covers:

* ``nexscout doctor`` reports CAPTCHA as WARN (not MISSING) when no key,
  still exits 0 when prereqs are healthy.
* ``solve_captcha`` returns ``captcha_manual_required`` when a CAPTCHA is
  detected but no solver is wired.
* ``mark_result`` inserts a ``pending_questions`` row for CAPTCHA_MANUAL.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from nexscout.apply.orchestrator import mark_result
from nexscout.apply.result_codes import (
    PERMANENT_FAILURE_REASONS,
    RESULT_CAPTCHA_MANUAL,
    is_permanent_failure,
)
from nexscout.apply.tools import solve_captcha
from nexscout.core.database import init_db
from nexscout.core.profile import Profile

# ---------------------------------------------------------------------------
# solve_captcha — no solver wired
# ---------------------------------------------------------------------------


class _FakeDriverWithCaptcha:
    """Driver that pretends the page has an hCaptcha."""

    def execute_script(self, script: str) -> Any:
        _ = script
        return {"type": "hcaptcha", "sitekey": "abc", "url": "https://x.com/job"}


class _FakeDriverNoCaptcha:
    def execute_script(self, script: str) -> Any:
        _ = script
        return None


def test_solve_captcha_no_solver_detects_returns_manual(tmp_path: Path) -> None:
    out = solve_captcha(_FakeDriverWithCaptcha(), {}, tmp_path, solver=None)
    assert not out.ok
    assert out.error == "captcha_manual_required"
    assert out.data and out.data.get("manual") is True
    assert out.data.get("detected", {}).get("type") == "hcaptcha"


def test_solve_captcha_no_solver_no_detection_is_noop(tmp_path: Path) -> None:
    out = solve_captcha(_FakeDriverNoCaptcha(), {}, tmp_path, solver=None)
    assert out.ok
    assert out.data == {"detected": None}


# ---------------------------------------------------------------------------
# Result codes
# ---------------------------------------------------------------------------


def test_captcha_manual_is_permanent() -> None:
    assert RESULT_CAPTCHA_MANUAL == "CAPTCHA_MANUAL"
    assert "captcha_manual" in PERMANENT_FAILURE_REASONS
    assert is_permanent_failure("captcha_manual")


# ---------------------------------------------------------------------------
# mark_result writes a pending_questions row
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    monkeypatch.setenv("NEXSCOUT_DIR", str(tmp_path / ".nexscout"))
    return init_db(tmp_path / ".nexscout" / "captcha.sqlite")


def test_mark_result_captcha_manual_inserts_pending_question(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO jobs (url, title, tailored_resume_path) VALUES (?, ?, ?)",
        ("https://x.com/job/1", "Engineer", "/tmp/resume.txt"),
    )
    mark_result(
        "https://x.com/job/1",
        RESULT_CAPTCHA_MANUAL,
        reason="hcaptcha visible at submit",
        conn=conn,
    )

    row = conn.execute("SELECT apply_status, apply_attempts FROM jobs WHERE url=?", ("https://x.com/job/1",)).fetchone()
    assert row["apply_status"] == "captcha_manual"
    # permanent → bumped to 99 so the acquire query never returns it again
    assert row["apply_attempts"] == 99

    questions = conn.execute(
        "SELECT job_url, question, channel, answered_at FROM pending_questions WHERE job_url=?",
        ("https://x.com/job/1",),
    ).fetchall()
    assert len(questions) == 1
    assert "manual CAPTCHA solving" in questions[0]["question"]
    assert questions[0]["channel"] == "cli"
    assert questions[0]["answered_at"] is None


def test_mark_result_captcha_manual_idempotent(conn: sqlite3.Connection) -> None:
    """Two consecutive CAPTCHA_MANUAL marks must not create duplicate questions."""
    conn.execute(
        "INSERT INTO jobs (url, title, tailored_resume_path) VALUES (?, ?, ?)",
        ("https://x.com/job/2", "Engineer", "/tmp/resume.txt"),
    )
    mark_result("https://x.com/job/2", RESULT_CAPTCHA_MANUAL, None, conn)
    mark_result("https://x.com/job/2", RESULT_CAPTCHA_MANUAL, None, conn)

    count = conn.execute(
        "SELECT COUNT(*) AS n FROM pending_questions WHERE job_url=? AND answered_at IS NULL",
        ("https://x.com/job/2",),
    ).fetchone()["n"]
    assert count == 1


# ---------------------------------------------------------------------------
# CLI doctor — reports WARN, not failure
# ---------------------------------------------------------------------------


def test_doctor_reports_captcha_warn_when_no_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NEXSCOUT_DIR", str(tmp_path / ".nexscout"))
    profile = Profile.model_validate(
        {
            "me": {"legal": "Jane", "pref": "Jane", "email": "j@e.com", "phone": "1"},
            "llm": {"primary": "gemini-2.0-flash"},
            "captcha": {"api_key": ""},
        }
    )
    (tmp_path / ".nexscout").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".nexscout" / "profile.yaml").write_text(profile.to_yaml(), encoding="utf-8")

    # The CLI uses a rich Console bound to stderr; invoke the doctor command
    # directly so capsys can pick it up regardless of CliRunner buffering.
    from contextlib import suppress

    from nexscout.cli import doctor

    with suppress(SystemExit):
        doctor(quiet=False)
    out = capsys.readouterr()
    combined = out.out + out.err
    assert "WARN" in combined or "manual user review" in combined
    # Never reported as a hard issue/MISSING for CAPTCHA.
    assert "captcha_missing" not in combined.lower()


def test_doctor_quiet_exits_zero_when_t2_healthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--quiet should exit 0 when tier == T2 even without CAPTCHA key."""
    monkeypatch.setenv("NEXSCOUT_DIR", str(tmp_path / ".nexscout"))
    monkeypatch.setattr("nexscout.cli.get_chrome_path", lambda: "/usr/bin/chromium")
    monkeypatch.setattr("nexscout.cli._has_latex_engine", lambda: "tectonic")
    profile = Profile.model_validate(
        {
            "me": {"legal": "Jane", "pref": "Jane", "email": "j@e.com", "phone": "1"},
            "llm": {"primary": "gemini-2.0-flash"},
            "captcha": {"api_key": ""},
        }
    )
    (tmp_path / ".nexscout").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".nexscout" / "profile.yaml").write_text(profile.to_yaml(), encoding="utf-8")

    import typer

    from nexscout.cli import doctor

    with pytest.raises(typer.Exit) as exc_info:
        doctor(quiet=True)
    assert exc_info.value.exit_code == 0


_ = CliRunner  # keep imported for downstream test extensions
