"""Hermetic tests for the NexScout MCP server.

These tests never launch the HTTP listener, a browser, or an LLM. They build an
isolated :class:`FastMCP` instance via :func:`build_server`, reach the
registered tools through the FastMCP tool manager, and call each tool's
underlying function directly against a temp ``NEXSCOUT_DIR`` (set by the autouse
``_isolate_nexscout_dir`` conftest fixture). Heavy pipeline stages are
monkeypatched so we exercise the tool wrappers, not the real work.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nexscout.core.config import database_path
from nexscout.core.database import init_db
from nexscout.mcp import server as mcp_server

#: The tools the server is contractually expected to expose.
EXPECTED_TOOLS = {
    "get_profile",
    "get_resume_text",
    "pipeline_status",
    "discover_jobs",
    "score_jobs",
    "tailor_jobs",
    "apply_to_job",
    "list_open_questions",
    "answer_question",
    "run_once",
}

_MIN_PROFILE = """\
meta: {v: 1}
me:
  legal: "Ada Lovelace"
  pref: "Ada"
  email: "ada@example.com"
  phone: "+1-555-0100"
  city: "London"
exp:
  years: 7
  current_title: "Staff Engineer"
  target_titles: ["Principal Engineer"]
skills:
  lang: ["Python", "Rust"]
facts:
  companies: ["Analytical Engines Inc"]
  projects: ["Note G"]
"""


@pytest.fixture
def nexscout_dir(_isolate_nexscout_dir: Path) -> Path:
    """Write a minimal profile.yaml into the isolated NEXSCOUT_DIR and init the DB."""
    (_isolate_nexscout_dir / "profile.yaml").write_text(_MIN_PROFILE, encoding="utf-8")
    init_db(database_path())
    return _isolate_nexscout_dir


def _tools(server: Any) -> dict[str, Any]:
    """Map tool-name -> Tool object from a FastMCP instance."""
    return {t.name: t for t in server._tool_manager.list_tools()}


def _call(server: Any, name: str, **kwargs: Any) -> Any:
    """Invoke a registered tool's underlying function directly (no transport)."""
    return _tools(server)[name].fn(**kwargs)


# ---------------------------------------------------------------------------
# Module import + registration
# ---------------------------------------------------------------------------


def test_module_imports_and_constants() -> None:
    assert mcp_server.DEFAULT_PORT == 8770
    assert mcp_server.MCP_PATH == "/mcp"
    assert callable(mcp_server.build_server)
    assert callable(mcp_server.main)


def test_build_server_registers_expected_tools() -> None:
    server = mcp_server.build_server()
    names = set(_tools(server))
    assert names == EXPECTED_TOOLS, f"unexpected tool set: {names ^ EXPECTED_TOOLS}"


def test_tools_have_descriptions() -> None:
    server = mcp_server.build_server()
    for name, tool in _tools(server).items():
        assert tool.description and tool.description.strip(), f"tool {name} has no description"


def test_server_binds_host_and_port_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXSCOUT_MCP_HOST", "0.0.0.0")
    monkeypatch.setenv("NEXSCOUT_MCP_PORT", "9999")
    server = mcp_server.build_server()
    assert server.settings.host == "0.0.0.0"
    assert server.settings.port == 9999


# ---------------------------------------------------------------------------
# Tool behaviour against a temp NEXSCOUT_DIR
# ---------------------------------------------------------------------------


def test_get_profile_returns_candidate_fields(nexscout_dir: Path) -> None:
    server = mcp_server.build_server()
    out = _call(server, "get_profile")
    assert out["ok"] is True
    assert out["name"] == "Ada Lovelace"
    assert out["current_title"] == "Staff Engineer"
    assert "Python" in out["skills"]


def test_get_resume_text_returns_plain_text(nexscout_dir: Path) -> None:
    server = mcp_server.build_server()
    out = _call(server, "get_resume_text")
    assert out["ok"] is True
    assert "Ada Lovelace" in out["resume_text"]
    assert "TECHNICAL SKILLS" in out["resume_text"]


def test_pipeline_status_returns_stats(nexscout_dir: Path) -> None:
    server = mcp_server.build_server()
    out = _call(server, "pipeline_status")
    assert out["ok"] is True
    assert out["stats"]["total"] == 0
    # All the headline counters the agent reports on must be present.
    for key in ("scored", "tailored", "applied", "ready_to_apply"):
        assert key in out["stats"]


def test_list_open_questions_round_trips_with_answer(nexscout_dir: Path) -> None:
    conn = init_db(database_path())
    conn.execute(
        "INSERT INTO pending_questions (id, job_url, question, asked_at) VALUES (?, ?, ?, ?)",
        (1, "https://jobs.example.com/42", "Are you authorized to work in the US?", "2026-06-11T00:00:00Z"),
    )
    server = mcp_server.build_server()

    listed = _call(server, "list_open_questions")
    assert listed["ok"] is True
    assert len(listed["questions"]) == 1
    assert listed["questions"][0]["id"] == 1

    answered = _call(server, "answer_question", question_id=1, answer="Yes, US citizen")
    assert answered == {"ok": True, "answered_id": 1}

    # Now there are no open questions.
    assert _call(server, "list_open_questions")["questions"] == []
    row = conn.execute("SELECT answer, answered_at FROM pending_questions WHERE id=1").fetchone()
    assert row["answer"] == "Yes, US citizen"
    assert row["answered_at"]


def test_answer_question_rejects_unknown_id(nexscout_dir: Path) -> None:
    server = mcp_server.build_server()
    out = _call(server, "answer_question", question_id=999, answer="whatever")
    assert out["ok"] is False
    assert "999" in out["error"]


def test_answer_question_rejects_empty_answer(nexscout_dir: Path) -> None:
    server = mcp_server.build_server()
    out = _call(server, "answer_question", question_id=1, answer="   ")
    assert out["ok"] is False
    assert "empty" in out["error"].lower()


# ---------------------------------------------------------------------------
# Heavy stages: mocked so we test the wrapper, not the work.
# ---------------------------------------------------------------------------


def test_discover_jobs_wraps_pipeline_stage(nexscout_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nexscout import pipeline

    monkeypatch.setattr(pipeline, "run_discover_stage", lambda **kw: 4)
    # The router build may fail without an LLM backend; the tool must tolerate it.
    monkeypatch.setattr(mcp_server, "_router", lambda profile: (_ for _ in ()).throw(RuntimeError("no llm")))
    server = mcp_server.build_server()
    out = _call(server, "discover_jobs", limit_per_engine=3)
    assert out == {"ok": True, "new_jobs": 4}


def test_score_jobs_wraps_pipeline_stage(nexscout_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nexscout import pipeline

    monkeypatch.setattr(mcp_server, "_router", lambda profile: object())
    monkeypatch.setattr(pipeline, "run_score_stage", lambda **kw: 9)
    server = mcp_server.build_server()
    out = _call(server, "score_jobs", limit=10)
    assert out == {"ok": True, "scored": 9}


def test_tailor_jobs_wraps_pipeline_stage(nexscout_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nexscout import pipeline

    monkeypatch.setattr(mcp_server, "_router", lambda profile: object())
    monkeypatch.setattr(pipeline, "run_tailor_stage", lambda **kw: 2)
    server = mcp_server.build_server()
    out = _call(server, "tailor_jobs", limit=5)
    assert out == {"ok": True, "tailored": 2}


def test_run_once_wraps_tick(nexscout_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nexscout.openclaw import tick

    monkeypatch.setattr(tick, "run", lambda **kw: {"discovered": 1, "applied": 0, "errors": []})
    server = mcp_server.build_server()
    out = _call(server, "run_once", wall_clock_s=1.0)
    assert out["ok"] is True
    assert out["summary"]["discovered"] == 1


def test_apply_to_job_no_eligible_job_is_graceful(nexscout_dir: Path) -> None:
    """A URL not in the pipeline yields a clean 'no attempt ran' result, not a crash."""
    server = mcp_server.build_server()
    out = _call(server, "apply_to_job", url="https://jobs.example.com/never-seen")
    # apply_to_job builds a real BrowserPool; on hosts without Chrome this raises
    # and is caught into an error envelope. Either way the server must not crash
    # and the result is a well-formed dict.
    assert isinstance(out, dict)
    assert out["ok"] in (True, False)
    if out["ok"]:
        assert out["attempts_run"] == 0
        assert "discover_jobs" in out["note"]


def test_apply_to_job_rejects_empty_url(nexscout_dir: Path) -> None:
    server = mcp_server.build_server()
    out = _call(server, "apply_to_job", url="   ")
    assert out["ok"] is False
    assert "url" in out["error"].lower()


# ---------------------------------------------------------------------------
# Robustness: tools never raise — they return an error envelope.
# ---------------------------------------------------------------------------


def test_tool_failure_returns_error_envelope_not_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    # No profile.yaml on disk: Profile.from_path() raises ConfigError; the tool
    # must convert that into {"ok": False, "error": ...} rather than propagate.
    server = mcp_server.build_server()
    out = _call(server, "get_profile")
    assert out["ok"] is False
    assert out["action"] == "get_profile"
    assert out["error"]
