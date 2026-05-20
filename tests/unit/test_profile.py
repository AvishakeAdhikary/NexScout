"""Tests for ``core.profile``."""

from __future__ import annotations

from pathlib import Path

import pytest

from nexscout.core.errors import ConfigError
from nexscout.core.profile import Profile


def _example_yaml() -> str:
    example = Path(__file__).resolve().parents[2] / "examples" / "profile.example.yaml"
    return example.read_text(encoding="utf-8")


def test_load_example_profile_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "profile.yaml"
    p.write_text(_example_yaml(), encoding="utf-8")
    profile = Profile.from_path(p)
    assert profile.me.legal == "Jane Q. Public"
    assert "Python" in profile.skills.lang
    assert profile.search.min_score == 7
    assert profile.llm.budgets.monthly_usd == 30
    text = profile.to_resume_text()
    assert "SUMMARY" in text
    assert "TECHNICAL SKILLS" in text
    assert "EDUCATION" in text


def test_env_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAPTCHA_API_KEY", "TEST123")
    p = tmp_path / "profile.yaml"
    p.write_text(_example_yaml(), encoding="utf-8")
    profile = Profile.from_path(p)
    assert profile.captcha.api_key == "TEST123"


def test_missing_profile_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        Profile.from_path(tmp_path / "does-not-exist.yaml")


def test_invalid_yaml_raises(tmp_path: Path) -> None:
    p = tmp_path / "profile.yaml"
    p.write_text("not a mapping\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        Profile.from_path(p)


def test_save_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "profile.yaml"
    p.write_text(_example_yaml(), encoding="utf-8")
    profile = Profile.from_path(p)
    out = tmp_path / "out.yaml"
    profile.save(out)
    reloaded = Profile.from_path(out)
    assert reloaded.me.email == profile.me.email
