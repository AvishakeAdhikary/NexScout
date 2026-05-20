"""Markdown reader/writer for the four §2 memory files.

Files live under ``~/.openclaw/memory/nexscout/`` and are append-only with a
structured Q/A block format. Each block looks like::

    ## Q: <question text>
    - asked_at: 2026-05-21T12:34:56Z
    - source: <free text, e.g. agent / channel name>
    A: <answer text>

This module exposes a reader (:func:`iter_learned_answers`) that yields
``(question, answer, ts)`` tuples and a writer
(:func:`append_learned_answer`) used by the web ``/api/answer`` route.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

#: Default memory root — override with the ``OPENCLAW_MEMORY_ROOT`` env var
#: (e.g. tests, NemoClaw sandbox).
_DEFAULT_ROOT_ENV = "OPENCLAW_MEMORY_ROOT"

FILES = (
    "learned-answers.md",
    "learned-employers.md",
    "do-not-ask-again.md",
    "feedback.md",
)


def memory_root() -> Path:
    """Return the OpenClaw memory directory for NexScout (created if missing)."""
    override = os.environ.get(_DEFAULT_ROOT_ENV)
    root = Path(override).expanduser() if override else Path.home() / ".openclaw" / "memory" / "nexscout"
    root.mkdir(parents=True, exist_ok=True)
    return root


def file_path(name: str) -> Path:
    """Return the absolute path of one of the four memory files."""
    if name not in FILES:
        raise ValueError(f"unknown memory file: {name!r}")
    return memory_root() / name


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@dataclass
class LearnedAnswer:
    """A single Q/A block harvested from learned-answers.md."""

    question: str
    answer: str
    ts: str | None = None
    source: str | None = None


_BLOCK_HEADER_RE = re.compile(r"^## Q:\s*(.+?)\s*$")
_FIELD_ASKED_RE = re.compile(r"^-\s*asked_at:\s*(.+?)\s*$")
_FIELD_SOURCE_RE = re.compile(r"^-\s*source:\s*(.+?)\s*$")
_ANSWER_RE = re.compile(r"^A:\s*(.*)$", re.DOTALL)


def iter_learned_answers(name: str = "learned-answers.md") -> Iterator[LearnedAnswer]:
    """Yield every Q/A block from one of the memory files."""
    path = file_path(name) if name in FILES else memory_root() / name
    if not path.exists():
        return
    current: LearnedAnswer | None = None
    answer_lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        header = _BLOCK_HEADER_RE.match(line)
        if header:
            if current is not None:
                current.answer = "\n".join(answer_lines).strip()
                yield current
            current = LearnedAnswer(question=header.group(1).strip(), answer="")
            answer_lines = []
            continue
        if current is None:
            continue
        asked = _FIELD_ASKED_RE.match(line)
        if asked:
            current.ts = asked.group(1).strip()
            continue
        source = _FIELD_SOURCE_RE.match(line)
        if source:
            current.source = source.group(1).strip()
            continue
        ans = _ANSWER_RE.match(line)
        if ans:
            answer_lines.append(ans.group(1))
            continue
        if answer_lines:
            answer_lines.append(line)
    if current is not None:
        current.answer = "\n".join(answer_lines).strip()
        yield current


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def append_learned_answer(
    question: str,
    answer: str,
    *,
    name: str = "learned-answers.md",
    source: str | None = "web",
    ts: str | None = None,
) -> Path:
    """Append a Q/A block to the named memory file. Returns the file path."""
    path = file_path(name) if name in FILES else memory_root() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = ts or datetime.now(UTC).isoformat()
    block = ["## Q: " + question.strip().replace("\n", " "), f"- asked_at: {stamp}"]
    if source:
        block.append(f"- source: {source}")
    block.append("A: " + answer.strip())
    block.append("")
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    separator = "\n" if (existing and not existing.endswith("\n")) else ""
    path.write_text(existing + separator + "\n".join(block) + "\n", encoding="utf-8")
    return path


def append_feedback(text: str, *, ts: str | None = None) -> Path:
    """Append a free-form note to feedback.md."""
    path = file_path("feedback.md")
    stamp = ts or datetime.now(UTC).isoformat()
    line = f"- [{stamp}] {text.strip()}\n"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(existing + line, encoding="utf-8")
    return path


__all__ = [
    "FILES",
    "LearnedAnswer",
    "append_feedback",
    "append_learned_answer",
    "file_path",
    "iter_learned_answers",
    "memory_root",
]
