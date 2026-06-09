"""Tests for the 3-file profile split (profile / settings / credentials).

The on-disk layout may be split into a résumé file plus optional
``settings.yaml`` and ``credentials.yaml`` sidecars that deep-merge into the
single :class:`Profile` model (priority profile < settings < credentials).
A monolithic ``profile.yaml`` must still load unchanged (backward compatible).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nexscout.core.errors import ConfigError
from nexscout.core.profile import Profile

_ME = 'me:\n  legal: Jane Q. Public\n  pref: Jane\n  email: jane@example.com\n  phone: "+1-415-555-0100"\n'


def _write(p: Path, text: str) -> None:
    p.write_text(text, encoding="utf-8")


def test_three_files_deep_merge(tmp_path: Path) -> None:
    _write(tmp_path / "profile.yaml", _ME + "skills:\n  lang: [Python, Go]\n")
    _write(
        tmp_path / "settings.yaml",
        "search:\n  min_score: 9\nllm:\n  primary: lmstudio:gemma\nopenclaw:\n  channel: discord\n",
    )
    _write(tmp_path / "credentials.yaml", "captcha:\n  api_key: SECRET123\ngmail_password: hunter2\n")

    profile = Profile.from_path(tmp_path / "profile.yaml")
    assert profile.me.legal == "Jane Q. Public"
    assert "Python" in profile.skills.lang
    assert profile.search.min_score == 9
    assert profile.llm.primary == "lmstudio:gemma"
    assert profile.openclaw.channel == "discord"
    assert profile.captcha.api_key == "SECRET123"
    assert profile.gmail_password == "hunter2"


def test_credentials_merge_into_settings_section(tmp_path: Path) -> None:
    """``captcha`` is split across settings (provider) + credentials (api_key)."""
    _write(tmp_path / "profile.yaml", _ME)
    _write(tmp_path / "settings.yaml", "captcha:\n  provider: capsolver\n")
    _write(tmp_path / "credentials.yaml", "captcha:\n  api_key: K\n")

    profile = Profile.from_path(tmp_path / "profile.yaml")
    assert profile.captcha.provider == "capsolver"
    assert profile.captcha.api_key == "K"


def test_credentials_win_over_settings(tmp_path: Path) -> None:
    _write(tmp_path / "profile.yaml", _ME)
    _write(tmp_path / "settings.yaml", "password: from-settings\n")
    _write(tmp_path / "credentials.yaml", "password: from-credentials\n")
    profile = Profile.from_path(tmp_path / "profile.yaml")
    assert profile.password == "from-credentials"


def test_monolithic_still_loads(tmp_path: Path) -> None:
    """A single profile.yaml with everything inline loads with no sidecars."""
    _write(
        tmp_path / "profile.yaml",
        _ME + "search:\n  min_score: 5\ncaptcha:\n  provider: capsolver\n  api_key: INLINE\n",
    )
    profile = Profile.from_path(tmp_path / "profile.yaml")
    assert profile.search.min_score == 5
    assert profile.captcha.api_key == "INLINE"


def test_env_resolution_in_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAPTCHA_API_KEY", "ENVVAL")
    _write(tmp_path / "profile.yaml", _ME)
    _write(tmp_path / "credentials.yaml", 'captcha:\n  api_key: "${env:CAPTCHA_API_KEY}"\n')
    profile = Profile.from_path(tmp_path / "profile.yaml")
    assert profile.captcha.api_key == "ENVVAL"


def test_non_mapping_sidecar_raises(tmp_path: Path) -> None:
    _write(tmp_path / "profile.yaml", _ME)
    _write(tmp_path / "settings.yaml", "just a string\n")
    with pytest.raises(ConfigError):
        Profile.from_path(tmp_path / "profile.yaml")


def test_empty_sidecar_is_ignored(tmp_path: Path) -> None:
    _write(tmp_path / "profile.yaml", _ME)
    _write(tmp_path / "settings.yaml", "")
    _write(tmp_path / "credentials.yaml", "\n")
    profile = Profile.from_path(tmp_path / "profile.yaml")
    assert profile.me.email == "jane@example.com"


def test_save_split_roundtrip(tmp_path: Path) -> None:
    profile = Profile.model_validate(
        {
            "me": {"legal": "Jane", "pref": "Jane", "email": "j@x.com", "phone": "1"},
            "search": {"min_score": 8},
            "captcha": {"provider": "capsolver", "api_key": "TOPSECRET"},
            "smtp": {"host": "smtp.example.com", "password": "pw"},
            "gmail_password": "gpw",
            "openclaw": {"channel": "discord"},
        }
    )
    paths = profile.save_split(tmp_path)
    assert paths["profile"].exists()
    assert paths["settings"].exists()
    assert paths["credentials"].exists()

    # Secrets must live only in credentials.yaml, not settings.yaml.
    settings_text = paths["settings"].read_text(encoding="utf-8")
    creds_text = paths["credentials"].read_text(encoding="utf-8")
    assert "TOPSECRET" not in settings_text
    assert "TOPSECRET" in creds_text
    assert "gpw" in creds_text
    assert "provider: capsolver" in settings_text
    assert "smtp.example.com" in settings_text

    reloaded = Profile.from_path(paths["profile"])
    assert reloaded.captcha.api_key == "TOPSECRET"
    assert reloaded.captcha.provider == "capsolver"
    assert reloaded.smtp.host == "smtp.example.com"
    assert reloaded.smtp.password == "pw"
    assert reloaded.gmail_password == "gpw"
    assert reloaded.search.min_score == 8
    assert reloaded.openclaw.channel == "discord"


def test_save_split_default_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXSCOUT_DIR", str(tmp_path))
    profile = Profile.model_validate({"me": {"legal": "J", "pref": "J", "email": "e@x.com", "phone": "1"}})
    paths = profile.save_split()
    assert paths["profile"] == tmp_path / "profile.yaml"
    assert (tmp_path / "settings.yaml").exists()
    assert Profile.from_path().me.email == "e@x.com"
