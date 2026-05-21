"""Tests for ``agent_backends`` — native, claude_code, openai_assistant."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from nexscout.agent_backends import claude_code, get_backend, known_backends
from nexscout.core.errors import ConfigError


def test_known_backends() -> None:
    assert known_backends() == ("native", "claude_code", "openai_assistant")


def test_get_backend_native() -> None:
    from nexscout.apply.agent import run_agent

    assert get_backend("native") is run_agent


def test_get_backend_default() -> None:
    from nexscout.apply.agent import run_agent

    assert get_backend("") is run_agent


def test_get_backend_claude_code() -> None:
    out = get_backend("claude_code")
    assert callable(out)


def test_get_backend_openai_assistant() -> None:
    out = get_backend("openai_assistant")
    assert callable(out)


def test_get_backend_unknown() -> None:
    with pytest.raises(ConfigError):
        get_backend("nope")


# ---------------------------------------------------------------------------
# claude_code
# ---------------------------------------------------------------------------


def test_claude_code_missing_binary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(claude_code, "_claude_path", lambda: None)
    with pytest.raises(ConfigError):
        claude_code.run(
            job={"url": "x"},
            profile=SimpleNamespace(
                me=SimpleNamespace(
                    legal="x", pref="x", email="e@x.com", phone="1",
                    city="", region="", country="", postcode="",
                    links=SimpleNamespace(li="", gh="", web="", portfolio=""),
                    address="",
                ),
                auth=SimpleNamespace(authorized=True, sponsor=False, permit="USC"),
                pay=SimpleNamespace(expect=0, currency="USD"),
                exp=SimpleNamespace(years=0, edu="", current_title=""),
                avail=SimpleNamespace(start="Immediately"),
                eeo=SimpleNamespace(gender="decline", race="decline", veteran="not-protected", disability="decline"),
            ),
            bundle_dir=tmp_path,
            driver=None,
            solver=None,
            router=None,
        )


def test_claude_code_run_parses_result(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(claude_code, "_claude_path", lambda: "/usr/bin/claude")
    monkeypatch.setattr(
        claude_code.subprocess, "run",
        lambda *a, **kw: SimpleNamespace(stdout="thinking\nRESULT:APPLIED:done", stderr=""),
    )
    from nexscout.core.profile import Profile

    p = Profile.model_validate({"me": {"legal": "x", "pref": "x", "email": "e@x.com", "phone": "1"}})
    code, _reason, _cost, _solved = claude_code.run(
        job={"url": "x", "title": "Eng"}, profile=p, bundle_dir=tmp_path,
        driver=None, solver=None, router=None,
    )
    assert code == "APPLIED"


def test_claude_code_run_no_result_line(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(claude_code, "_claude_path", lambda: "/usr/bin/claude")
    monkeypatch.setattr(
        claude_code.subprocess, "run",
        lambda *a, **kw: SimpleNamespace(stdout="no result line here", stderr=""),
    )
    from nexscout.core.profile import Profile

    p = Profile.model_validate({"me": {"legal": "x", "pref": "x", "email": "e@x.com", "phone": "1"}})
    code, _reason, _cost, _solved = claude_code.run(
        job={"url": "x", "title": "Eng"}, profile=p, bundle_dir=tmp_path,
        driver=None, solver=None, router=None,
    )
    assert code == "FAILED"


def test_claude_code_subprocess_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import subprocess

    monkeypatch.setattr(claude_code, "_claude_path", lambda: "/usr/bin/claude")

    def _boom(*a: Any, **kw: Any) -> Any:
        raise subprocess.SubprocessError("crashed")

    monkeypatch.setattr(claude_code.subprocess, "run", _boom)
    from nexscout.core.profile import Profile

    p = Profile.model_validate({"me": {"legal": "x", "pref": "x", "email": "e@x.com", "phone": "1"}})
    code, _reason, _cost, _solved = claude_code.run(
        job={"url": "x", "title": "Eng"}, profile=p, bundle_dir=tmp_path,
        driver=None, solver=None, router=None,
    )
    assert code == "FAILED"


def test_claude_code_reads_resume_and_cover(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    resume = tmp_path / "r.txt"
    resume.write_text("Resume body")
    cover = tmp_path / "c.txt"
    cover.write_text("Cover body")
    monkeypatch.setattr(claude_code, "_claude_path", lambda: "/usr/bin/claude")
    monkeypatch.setattr(
        claude_code.subprocess, "run",
        lambda *a, **kw: SimpleNamespace(stdout="RESULT:APPLIED", stderr=""),
    )
    from nexscout.core.profile import Profile

    p = Profile.model_validate({"me": {"legal": "x", "pref": "x", "email": "e@x.com", "phone": "1"}})
    code, *_ = claude_code.run(
        job={
            "url": "x",
            "title": "Eng",
            "tailored_resume_path": str(resume),
            "cover_letter_path": str(cover),
        },
        profile=p, bundle_dir=tmp_path, driver=None, solver=None, router=None,
    )
    assert code == "APPLIED"


# ---------------------------------------------------------------------------
# openai_assistant
# ---------------------------------------------------------------------------


def test_openai_assistant_no_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from nexscout.agent_backends import openai_assistant

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        openai_assistant.run(
            job={"url": "x"}, profile=MagicMock(), bundle_dir=tmp_path,
            driver=None, solver=None, router=None,
        )


def test_openai_assistant_no_sdk(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from nexscout.agent_backends import openai_assistant

    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setitem(sys.modules, "openai", None)  # type: ignore[arg-type]
    with pytest.raises(ConfigError):
        openai_assistant.run(
            job={"url": "x"}, profile=MagicMock(), bundle_dir=tmp_path,
            driver=None, solver=None, router=None,
        )


def test_openai_assistant_full_flow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from nexscout.agent_backends import openai_assistant
    from nexscout.core.profile import Profile

    monkeypatch.setenv("OPENAI_API_KEY", "k")

    fake_client = MagicMock()
    fake_client.beta.assistants.create.return_value = SimpleNamespace(id="a1")
    fake_client.beta.threads.create.return_value = SimpleNamespace(id="t1")
    fake_client.beta.threads.runs.create_and_poll.return_value = SimpleNamespace(status="completed")

    msg_text = SimpleNamespace(value="RESULT:APPLIED")
    msg_content = SimpleNamespace(type="text", text=msg_text)
    fake_client.beta.threads.messages.list.return_value = SimpleNamespace(
        data=[SimpleNamespace(content=[msg_content])]
    )

    fake_openai = ModuleType("openai")
    fake_openai.OpenAI = lambda: fake_client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    p = Profile.model_validate({"me": {"legal": "x", "pref": "x", "email": "e@x.com", "phone": "1"}})
    code, *_ = openai_assistant.run(
        job={"url": "x", "title": "Eng"}, profile=p, bundle_dir=tmp_path,
        driver=None, solver=None, router=None,
    )
    assert code == "APPLIED"


def test_openai_assistant_exception_during_call(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from nexscout.agent_backends import openai_assistant
    from nexscout.core.profile import Profile

    monkeypatch.setenv("OPENAI_API_KEY", "k")

    class _BadClient:
        @property
        def beta(self) -> Any:
            raise RuntimeError("api down")

    fake_openai = ModuleType("openai")
    fake_openai.OpenAI = _BadClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    p = Profile.model_validate({"me": {"legal": "x", "pref": "x", "email": "e@x.com", "phone": "1"}})
    code, _reason, *_ = openai_assistant.run(
        job={"url": "x"}, profile=p, bundle_dir=tmp_path,
        driver=None, solver=None, router=None,
    )
    assert code == "FAILED"


def test_openai_assistant_run_status_non_completed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from nexscout.agent_backends import openai_assistant
    from nexscout.core.profile import Profile

    monkeypatch.setenv("OPENAI_API_KEY", "k")

    fake_client = MagicMock()
    fake_client.beta.assistants.create.return_value = SimpleNamespace(id="a1")
    fake_client.beta.threads.create.return_value = SimpleNamespace(id="t1")
    fake_client.beta.threads.runs.create_and_poll.return_value = SimpleNamespace(status="failed")

    fake_openai = ModuleType("openai")
    fake_openai.OpenAI = lambda: fake_client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    p = Profile.model_validate({"me": {"legal": "x", "pref": "x", "email": "e@x.com", "phone": "1"}})
    code, reason, *_ = openai_assistant.run(
        job={"url": "x", "title": "Eng"}, profile=p, bundle_dir=tmp_path,
        driver=None, solver=None, router=None,
    )
    assert code == "FAILED"
    assert "assistant_status_failed" in (reason or "")


# ---------------------------------------------------------------------------
# __main__
# ---------------------------------------------------------------------------


def test_main_module_imports() -> None:
    """Trigger import of ``nexscout.__main__`` so it's covered."""
    import importlib

    import nexscout.__main__ as main_mod

    importlib.reload(main_mod)
    assert hasattr(main_mod, "app")
