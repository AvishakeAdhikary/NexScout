"""Tests for ``nexscout.cli`` — every Typer command driven via CliRunner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from nexscout import cli
from nexscout.core.profile import Profile

runner = CliRunner()


def _make_profile_yaml(path: Path) -> None:
    profile = Profile.model_validate(
        {
            "me": {"legal": "Jane Q. Public", "pref": "Jane", "email": "j@x.com", "phone": "1"},
            "captcha": {"provider": "capsolver", "api_key": "x"},
        }
    )
    profile.save(path)


def test_version_flag() -> None:
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert "nexscout" in result.output


def test_init_invokes_wizard(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, Any] = {}

    def _fake_wizard(force: bool = False) -> Path:
        called["force"] = force
        return Path("/tmp/profile.yaml")

    monkeypatch.setattr("nexscout.wizard.run_wizard", _fake_wizard)
    result = runner.invoke(cli.app, ["init", "--force"])
    assert result.exit_code == 0
    assert called["force"] is True


def test_doctor_no_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "get_chrome_path", lambda: "/usr/bin/chrome")
    monkeypatch.setattr(cli, "_has_latex_engine", lambda: None)
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 1
    assert "MISSING" in result.output or "profile" in result.output


def test_doctor_full_table(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _make_profile_yaml(tmp_path / ".nexscout" / "profile.yaml")
    monkeypatch.setattr(cli, "profile_path", lambda: tmp_path / ".nexscout" / "profile.yaml")
    monkeypatch.setattr(cli, "nexscout_dir", lambda: tmp_path / ".nexscout")
    monkeypatch.setattr(cli, "get_chrome_path", lambda: "/usr/bin/chrome")
    monkeypatch.setattr(cli, "_has_latex_engine", lambda: "pdflatex")
    result = runner.invoke(cli.app, ["doctor"])
    assert "Tier" in result.output


def test_doctor_quiet_healthy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _make_profile_yaml(tmp_path / ".nexscout" / "profile.yaml")
    monkeypatch.setattr(cli, "profile_path", lambda: tmp_path / ".nexscout" / "profile.yaml")
    monkeypatch.setattr(cli, "nexscout_dir", lambda: tmp_path / ".nexscout")
    monkeypatch.setattr(cli, "get_chrome_path", lambda: "/usr/bin/chrome")
    monkeypatch.setattr(cli, "_has_latex_engine", lambda: "pdflatex")
    result = runner.invoke(cli.app, ["doctor", "--quiet"])
    assert result.exit_code == 0


def test_doctor_quiet_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "get_chrome_path", lambda: None)
    result = runner.invoke(cli.app, ["doctor", "--quiet"])
    assert result.exit_code == 1


def test_run_no_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "profile_path", lambda: tmp_path / "missing.yaml")
    result = runner.invoke(cli.app, ["run"])
    assert result.exit_code == 1


def test_run_with_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _make_profile_yaml(tmp_path / "p.yaml")
    monkeypatch.setattr(cli, "profile_path", lambda: tmp_path / "p.yaml")
    result = runner.invoke(cli.app, ["run", "discover"])
    assert result.exit_code == 0


def test_tick_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _make_profile_yaml(tmp_path / "p.yaml")
    monkeypatch.setattr(cli, "profile_path", lambda: tmp_path / "p.yaml")
    monkeypatch.setattr("nexscout.openclaw.tick.run", lambda **kw: {"applied": 0})
    result = runner.invoke(cli.app, ["tick"])
    assert result.exit_code == 0


def test_tick_no_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "profile_path", lambda: tmp_path / "missing.yaml")
    result = runner.invoke(cli.app, ["tick"])
    assert result.exit_code == 1


def test_question_list_text_empty() -> None:
    result = runner.invoke(cli.app, ["question", "list"])
    assert result.exit_code == 0


def test_question_list_json_empty() -> None:
    result = runner.invoke(cli.app, ["question", "list", "--format", "json"])
    assert result.exit_code == 0
    assert "[" in result.output


def test_question_list_openclaw_no_items() -> None:
    result = runner.invoke(cli.app, ["question", "list", "--format", "openclaw"])
    assert "no pending questions" in result.output


def test_question_list_with_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    from nexscout.core.database import init_db

    def _fake_init_db() -> Any:
        conn = init_db()
        conn.execute(
            "INSERT INTO pending_questions (job_url, question, asked_at) VALUES (?, ?, ?)",
            ("https://x.com", "Are you sure?", "2025"),
        )
        return conn

    monkeypatch.setattr("nexscout.core.database.init_db", _fake_init_db)
    result = runner.invoke(cli.app, ["question", "list"])
    assert "Are you sure?" in result.output


def test_question_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nexscout.openclaw.skill.handle_answer", lambda q, a: {"text": "stored"})
    result = runner.invoke(cli.app, ["question", "answer", "-q", "x", "-a", "y"])
    assert "stored" in result.output


def test_status_text() -> None:
    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 0


def test_status_json() -> None:
    result = runner.invoke(cli.app, ["status", "--format", "json"])
    assert result.exit_code == 0
    assert "total" in result.output


def test_status_openclaw() -> None:
    result = runner.invoke(cli.app, ["status", "--format", "openclaw"])
    assert result.exit_code == 0
    assert "nexscout:" in result.output


def test_controls_pause_resume(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("nexscout.core.config.nexscout_dir", lambda: tmp_path)
    result = runner.invoke(cli.app, ["controls", "pause"])
    assert result.exit_code == 0
    result2 = runner.invoke(cli.app, ["controls", "resume"])
    assert result2.exit_code == 0


def test_apply_unknown_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _make_profile_yaml(tmp_path / "p.yaml")
    monkeypatch.setattr(cli, "profile_path", lambda: tmp_path / "p.yaml")
    result = runner.invoke(cli.app, ["apply", "--backend", "nope"])
    assert result.exit_code == 1


def test_apply_no_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "profile_path", lambda: tmp_path / "missing.yaml")
    result = runner.invoke(cli.app, ["apply"])
    assert result.exit_code == 1


def test_apply_runs_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _make_profile_yaml(tmp_path / "p.yaml")
    monkeypatch.setattr(cli, "profile_path", lambda: tmp_path / "p.yaml")

    monkeypatch.setattr(
        "nexscout.agent_backends.get_backend",
        lambda name: lambda **kw: ("APPLIED", None, 0.0, False),
    )

    class _FakePool:
        def __init__(self, **kw: Any) -> None:
            pass

        def close_all(self) -> None:
            pass

    monkeypatch.setattr("nexscout.browser.pool.BrowserPool", _FakePool)
    monkeypatch.setattr("nexscout.apply.orchestrator.worker_loop", lambda *a, **kw: 0)

    class _FakeRouter:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

    monkeypatch.setattr("nexscout.llm.router.LLMRouter", _FakeRouter)
    monkeypatch.setattr("nexscout.captcha.capsolver.CapSolverSolver", lambda *a, **kw: None)

    result = runner.invoke(cli.app, ["apply", "--workers", "1"])
    assert result.exit_code == 0


def test_web_init_pw(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("getpass.getpass", lambda prompt: "secret123")
    called: dict[str, Any] = {}
    monkeypatch.setattr("nexscout.web.auth.set_password", lambda pw: called.update(pw=pw))
    result = runner.invoke(cli.app, ["web", "--init-pw"])
    assert result.exit_code == 0
    assert called["pw"] == "secret123"


def test_web_init_pw_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("getpass.getpass", lambda prompt: "")
    result = runner.invoke(cli.app, ["web", "--init-pw"])
    assert result.exit_code == 1


def test_has_latex_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/pdflatex" if name == "pdflatex" else None)
    assert cli._has_latex_engine() == "pdflatex"


def test_has_latex_engine_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert cli._has_latex_engine() is None


def test_detect_tier_branches() -> None:
    profile = Profile.model_validate({"me": {"legal": "x", "pref": "x", "email": "e@x.com", "phone": "1"}})
    assert cli._detect_tier(None, None, None) == "T0"
    assert cli._detect_tier(None, "/chrome", None) == "T1"
    assert cli._detect_tier(profile, "/chrome", None) == "T2"
    assert cli._detect_tier(profile, "/chrome", "/pdflatex") == "T3"


def test_dashboard_export_writes_html(tmp_path: Path) -> None:
    """`nexscout dashboard --export <file>` writes a self-contained HTML file."""
    out = tmp_path / "out.html"
    result = runner.invoke(cli.app, ["dashboard", "--export", str(out)])
    assert result.exit_code == 0, result.output
    text = out.read_text(encoding="utf-8")
    assert "<!doctype html>" in text
    assert "NexScout" in text
    assert "<style>" in text


def test_dashboard_requires_export_flag() -> None:
    result = runner.invoke(cli.app, ["dashboard"])
    assert result.exit_code == 1
    assert "required" in result.output
