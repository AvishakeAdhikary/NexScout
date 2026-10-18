import pytest
from pydantic import ValidationError

from nexscout.config import Settings


def test_production_requires_master_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXSCOUT_MASTER_KEY", raising=False)
    with pytest.raises(ValidationError, match="NEXSCOUT_MASTER_KEY"):
        Settings(env="production", master_key=None, _env_file=None)  # type: ignore[call-arg]


def test_development_allows_generated_key() -> None:
    assert Settings(env="development", master_key=None, _env_file=None).master_key is None  # type: ignore[call-arg]


KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="  # 32 bytes, test only


def test_shipped_defaults_have_no_demo_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXSCOUT_DEMO_DATA", raising=False)
    s = Settings(env="production", master_key=KEY, _env_file=None)  # type: ignore[call-arg]
    assert s.demo_data is False
    assert s.fixture_site_on is False
    # http://localhost installs must be able to sign in; https deployments get secure cookies.
    assert s.cookie_secure is False
    https = Settings(
        env="production", master_key=KEY, public_web_url="https://x.example", _env_file=None
    )  # type: ignore[call-arg]
    assert https.cookie_secure is True


def test_demo_data_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXSCOUT_DEMO_DATA", "1")
    s = Settings(env="development", _env_file=None)  # type: ignore[call-arg]
    assert s.demo_data is True
    assert s.fixture_site_on is True
