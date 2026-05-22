"""Tests for the ReAct loop in ``apply.agent``."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from nexscout.apply import agent
from nexscout.apply.agent import (
    MAX_ITERATIONS,
    parse_llm_reply,
    run_agent,
    transcript_lines,
)
from nexscout.core.profile import Profile


def _profile() -> Profile:
    return Profile.model_validate(
        {
            "me": {"legal": "Jane", "pref": "Jane", "email": "j@x.com", "phone": "1"},
        }
    )


# ---------------------------------------------------------------------------
# parse_llm_reply
# ---------------------------------------------------------------------------


def test_parse_llm_reply_finds_result_line() -> None:
    _tc, rl = parse_llm_reply("Thinking...\nRESULT:APPLIED:ok\n")
    assert rl is not None
    assert "APPLIED" in rl


def test_parse_llm_reply_finds_tool_call_json() -> None:
    text = 'Doing it.\n{"tool": "navigate", "args": {"url": "https://x.com"}}'
    tc, _rl = parse_llm_reply(text)
    assert tc is not None
    assert tc["tool"] == "navigate"


def test_parse_llm_reply_finds_fenced_json() -> None:
    text = '```json\n{"tool":"click","args":{"ref":"#x"}}\n```'
    tc, _rl = parse_llm_reply(text)
    assert tc is not None
    assert tc["tool"] == "click"


def test_parse_llm_reply_no_tool_no_result() -> None:
    tc, rl = parse_llm_reply("just some prose")
    assert tc is None
    assert rl is None


def test_parse_llm_reply_invalid_json_block_falls_back_to_regex() -> None:
    text = '{"tool": "navigate", "args": {}}'
    tc, _rl = parse_llm_reply(text)
    assert tc is not None
    assert tc["tool"] == "navigate"


# ---------------------------------------------------------------------------
# transcript_lines
# ---------------------------------------------------------------------------


def test_transcript_lines_missing_file(tmp_path: Path) -> None:
    assert list(transcript_lines(tmp_path)) == []


def test_transcript_lines_round_trip(tmp_path: Path) -> None:
    (tmp_path / "transcript.jsonl").write_text('{"a":1}\n\n{"b":2}\nnot json\n', encoding="utf-8")
    out = list(transcript_lines(tmp_path))
    assert out == [{"a": 1}, {"b": 2}]


# ---------------------------------------------------------------------------
# run_agent — fake router + driver
# ---------------------------------------------------------------------------


class _ScriptedRouter:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[Any] = []

    def ask(self, task: str, messages: Any, **kw: Any) -> str:
        self.calls.append(task)
        if not self.replies:
            raise RuntimeError("ran out of replies")
        return self.replies.pop(0)


def test_run_agent_immediate_result_line(tmp_path: Path) -> None:
    router = _ScriptedRouter(["RESULT:APPLIED:done"])
    code, reason, _cost, _solved = run_agent(
        job={"url": "https://x.com", "title": "Eng"},
        profile=_profile(),
        bundle_dir=tmp_path,
        driver=MagicMock(),
        solver=None,
        router=router,  # type: ignore[arg-type]
        dry_run=True,
    )
    assert code == "APPLIED"
    assert reason == "done"


def test_run_agent_done_tool_terminates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reply = '{"tool":"done","args":{"result":"RESULT:APPLIED","reason":"manual"}}'
    router = _ScriptedRouter([reply])
    code, _reason, _cost, _solved = run_agent(
        job={"url": "https://x.com", "title": "Eng"},
        profile=_profile(),
        bundle_dir=tmp_path,
        driver=MagicMock(),
        solver=None,
        router=router,  # type: ignore[arg-type]
    )
    assert code == "APPLIED"
    # The transcript was written.
    assert (tmp_path / "transcript.jsonl").exists()


def test_run_agent_unparseable_replies_then_exhaust(tmp_path: Path) -> None:
    """When parsing fails, the agent retries up to ``max_iterations`` then gives up."""
    router = _ScriptedRouter(["gibberish"] * 4)
    code, reason, _cost, _solved = run_agent(
        job={"url": "https://x.com", "title": "Eng"},
        profile=_profile(),
        bundle_dir=tmp_path,
        driver=MagicMock(),
        solver=None,
        router=router,  # type: ignore[arg-type]
        max_iterations=3,
    )
    assert code == "FAILED"
    assert reason


def test_run_agent_router_exception_marks_page_error(tmp_path: Path) -> None:
    class _Boom:
        def ask(self, *a: Any, **kw: Any) -> str:
            raise RuntimeError("provider failed")

    code, reason, _cost, _solved = run_agent(
        job={"url": "https://x.com", "title": "Eng"},
        profile=_profile(),
        bundle_dir=tmp_path,
        driver=MagicMock(),
        solver=None,
        router=_Boom(),  # type: ignore[arg-type]
    )
    assert code == "FAILED"
    assert reason == "page_error"


def test_run_agent_navigate_then_done(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    router = _ScriptedRouter(
        [
            '{"tool":"navigate","args":{"url":"https://x.com"}}',
            '{"tool":"done","args":{"result":"RESULT:APPLIED"}}',
        ]
    )
    drv = MagicMock()
    code, _, _, _ = run_agent(
        job={"url": "https://x.com", "title": "Eng"},
        profile=_profile(),
        bundle_dir=tmp_path,
        driver=drv,
        solver=None,
        router=router,  # type: ignore[arg-type]
    )
    assert code == "APPLIED"
    drv.get.assert_called_once_with("https://x.com")


def test_run_agent_dashboard_ticks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    router = _ScriptedRouter(
        [
            '{"tool":"wait","args":{"ms":0}}',
            "RESULT:APPLIED",
        ]
    )
    ticks: list[Any] = []

    class _DB:
        def tick_action(self, w: int, name: str) -> None:
            ticks.append(name)

        def start_job(self, *a: Any, **kw: Any) -> None:
            pass

        def finish_job(self, *a: Any, **kw: Any) -> None:
            pass

    run_agent(
        job={"url": "https://x.com", "title": "Eng"},
        profile=_profile(),
        bundle_dir=tmp_path,
        driver=MagicMock(),
        solver=None,
        router=router,  # type: ignore[arg-type]
        dashboard=_DB(),  # type: ignore[arg-type]
        worker_id=3,
    )
    assert "wait" in ticks


def test_run_agent_solve_captcha_marks_solved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When solve_captcha returns ok=True with injected, captcha_solved is True."""
    monkeypatch.setattr(
        "nexscout.apply.tools.detect_in_driver",
        lambda d: {"type": "recaptcha", "sitekey": "x", "url": "y"},
    )
    monkeypatch.setattr("nexscout.apply.tools.inject_token", lambda d, k, t: None)

    class _S:
        def solve(self, *a: Any, **kw: Any) -> str:
            return "tok"

    router = _ScriptedRouter(
        [
            '{"tool":"solve_captcha","args":{}}',
            "RESULT:APPLIED",
        ]
    )
    code, _reason, _cost, solved = run_agent(
        job={"url": "https://x.com", "title": "Eng"},
        profile=_profile(),
        bundle_dir=tmp_path,
        driver=MagicMock(),
        solver=_S(),  # type: ignore[arg-type]
        router=router,  # type: ignore[arg-type]
    )
    assert code == "APPLIED"
    assert solved


def test_run_agent_screenshot_indexing(tmp_path: Path) -> None:
    """Screenshots use sequential NNN_<name> naming via the agent's idx counter."""
    router = _ScriptedRouter(
        [
            '{"tool":"screenshot","args":{"name":"first"}}',
            '{"tool":"screenshot","args":{"name":"second"}}',
            "RESULT:APPLIED",
        ]
    )
    drv = MagicMock()

    def _save(path: str) -> bool:
        Path(path).write_bytes(b"png")
        return True

    drv.save_screenshot.side_effect = _save
    run_agent(
        job={"url": "https://x.com", "title": "Eng"},
        profile=_profile(),
        bundle_dir=tmp_path,
        driver=drv,
        solver=None,
        router=router,  # type: ignore[arg-type]
    )
    files = sorted((tmp_path / "screenshots").glob("*.png"))
    assert any("001_first" in str(f) for f in files)
    assert any("002_second" in str(f) for f in files)


def test_run_agent_with_tailored_resume_loaded(tmp_path: Path) -> None:
    resume = tmp_path / "resume.txt"
    resume.write_text("My Resume", encoding="utf-8")
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF")

    router = _ScriptedRouter(["RESULT:APPLIED"])
    code, _, _, _ = run_agent(
        job={
            "url": "https://x.com",
            "title": "Eng",
            "tailored_resume_path": str(resume),
            "cover_letter_path": "",
        },
        profile=_profile(),
        bundle_dir=tmp_path,
        driver=MagicMock(),
        solver=None,
        router=router,  # type: ignore[arg-type]
    )
    assert code == "APPLIED"


def test_read_text_helper() -> None:
    assert agent._read_text(None) == ""
    assert agent._read_text("/nonexistent/path") == ""


def test_read_pdf_sibling(tmp_path: Path) -> None:
    txt = tmp_path / "resume.txt"
    txt.write_text("x")
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF")
    assert agent._read_pdf_sibling(str(txt)) is not None
    assert agent._read_pdf_sibling(None) is None
    assert agent._read_pdf_sibling(str(tmp_path / "nopdf.txt")) is None


def test_kickoff_message_format() -> None:
    msg = agent._kickoff_message({"title": "Eng", "url": "https://x.com"})
    assert "Eng" in msg
    assert "https://x.com" in msg
    assert "JSON tool_call" in msg


def test_max_iterations_constant() -> None:
    assert MAX_ITERATIONS == 50
