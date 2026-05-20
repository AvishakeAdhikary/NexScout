"""Shared pytest fixtures: isolate ``NEXSCOUT_DIR`` per test."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_nexscout_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    nx = tmp_path / ".nexscout"
    nx.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NEXSCOUT_DIR", str(nx))
    monkeypatch.delenv("CAPTCHA_API_KEY", raising=False)
    yield nx


@pytest.fixture
def env_var() -> Iterator[None]:
    yield None
    # noop placeholder for explicit env tweaks.
    _ = os.environ
