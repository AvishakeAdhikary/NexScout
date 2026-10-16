import pytest
from pydantic import ValidationError

from nexscout.config import Settings


def test_production_requires_master_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXSCOUT_MASTER_KEY", raising=False)
    with pytest.raises(ValidationError, match="NEXSCOUT_MASTER_KEY"):
        Settings(env="production", master_key=None, _env_file=None)  # type: ignore[call-arg]


def test_development_allows_generated_key() -> None:
    assert Settings(env="development", master_key=None, _env_file=None).master_key is None  # type: ignore[call-arg]
