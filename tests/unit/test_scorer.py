"""Tests for ``scoring.scorer`` using a stubbed router."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from nexscout.core.profile import Profile
from nexscout.scoring.scorer import _parse_score, score_job


class StubRouter:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, list[Any]]] = []

    def ask(self, task: str, messages: list[Any], **kwargs: Any) -> str:
        self.calls.append((task, messages))
        return self.response


@pytest.fixture
def example_profile(tmp_path: Path) -> Iterator[Profile]:
    src = Path(__file__).resolve().parents[2] / "examples" / "profile.example.yaml"
    dest = tmp_path / "profile.yaml"
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    yield Profile.from_path(dest)


def test_parse_score_extracts_fields() -> None:
    text = "SCORE: 8\nKEYWORDS: python, fastapi, postgres\nREASONING: strong match\n"
    score, combined = _parse_score(text)
    assert score == 8
    assert "python" in combined.lower()
    assert "strong match" in combined.lower()


def test_parse_score_clamps() -> None:
    assert _parse_score("SCORE: 11\nREASONING: x")[0] == 10
    assert _parse_score("SCORE: 0\nREASONING: x")[0] == 1
    assert _parse_score("no score here")[0] == 0


def test_score_job_uses_router(example_profile: Profile) -> None:
    stub = StubRouter("SCORE: 7\nKEYWORDS: python\nREASONING: good fit.\n")
    job = {
        "url": "https://example.com/1",
        "title": "Senior Backend Engineer",
        "site": "Example",
        "location": "Remote",
        "full_description": "Python, FastAPI, Postgres backend at a high-traffic SaaS.",
    }
    score, reasoning = score_job(stub, example_profile, job)  # type: ignore[arg-type]
    assert score == 7
    assert "python" in reasoning.lower()
    assert stub.calls and stub.calls[0][0] == "score"
