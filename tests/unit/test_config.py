"""Tests for ``core.config``."""

from __future__ import annotations

import os
from pathlib import Path

from nexscout.core.config import (
    apply_workers_dir,
    chrome_workers_dir,
    ensure_dirs,
    get_chrome_path,
    nexscout_dir,
)


def test_nexscout_dir_honours_env(tmp_path: Path) -> None:
    expected = (tmp_path / ".nexscout").resolve()
    assert nexscout_dir() == expected


def test_ensure_dirs_creates_subdirs() -> None:
    ensure_dirs()
    assert nexscout_dir().exists()
    assert chrome_workers_dir().exists()
    assert apply_workers_dir().exists()


def test_get_chrome_path_returns_string_or_none(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("CHROME_PATH", raising=False)
    out = get_chrome_path()
    assert out is None or os.path.isfile(out) or os.path.exists(out)


def test_get_chrome_path_env_override(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    fake = tmp_path / "fake-chrome"
    fake.write_text("")
    monkeypatch.setenv("CHROME_PATH", str(fake))
    assert get_chrome_path() == str(fake)
