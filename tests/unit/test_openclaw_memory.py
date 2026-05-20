"""Markdown roundtrip for the 4 memory files."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from nexscout.openclaw import memory


@pytest.fixture(autouse=True)
def _isolate_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCLAW_MEMORY_ROOT", str(tmp_path / "memroot"))


def test_memory_root_obeys_env(tmp_path: Path) -> None:
    os.environ["OPENCLAW_MEMORY_ROOT"] = str(tmp_path / "x")
    root = memory.memory_root()
    assert root == (tmp_path / "x").resolve() or root == tmp_path / "x"


def test_append_then_iter() -> None:
    p = memory.append_learned_answer("Are you a USC?", "Yes.", ts="2026-05-20T00:00:00Z", source="cli")
    assert p.exists()
    items = list(memory.iter_learned_answers())
    assert len(items) == 1
    assert items[0].question == "Are you a USC?"
    assert items[0].answer == "Yes."
    assert items[0].ts == "2026-05-20T00:00:00Z"
    assert items[0].source == "cli"


def test_multiple_answers_in_order() -> None:
    memory.append_learned_answer("Q1", "A1", ts="2026-05-20T00:00:00Z")
    memory.append_learned_answer("Q2", "A2", ts="2026-05-20T01:00:00Z")
    memory.append_learned_answer("Q3", "A3", ts="2026-05-20T02:00:00Z")
    items = list(memory.iter_learned_answers())
    assert [i.question for i in items] == ["Q1", "Q2", "Q3"]
    assert [i.answer for i in items] == ["A1", "A2", "A3"]


def test_iter_on_missing_file_is_empty() -> None:
    items = list(memory.iter_learned_answers("do-not-ask-again.md"))
    assert items == []


def test_unknown_file_raises() -> None:
    with pytest.raises(ValueError, match="unknown memory file"):
        memory.file_path("../etc/passwd")


def test_append_feedback() -> None:
    p = memory.append_feedback("Don't apply to Acme.", ts="2026-05-20T00:00:00Z")
    txt = p.read_text(encoding="utf-8")
    assert "Don't apply to Acme." in txt
    assert "[2026-05-20T00:00:00Z]" in txt


def test_multiline_answers_preserved() -> None:
    memory.append_learned_answer("Long?", "Line one\nLine two\nLine three", ts="2026-05-20T00:00:00Z")
    items = list(memory.iter_learned_answers())
    assert items[0].answer == "Line one\nLine two\nLine three"
