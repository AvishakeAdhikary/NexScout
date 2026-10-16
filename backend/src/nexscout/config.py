"""Application configuration loaded from NEXSCOUT_* environment variables (and .env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEXSCOUT_",
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = True

    # Runtime connection uses the non-owner app role so Postgres RLS applies.
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://nexscout_app:nexscout_app_dev@localhost:5432/nexscout"
    )
    # Migrations run as the schema owner role.
    migration_database_url: SecretStr = SecretStr(
        "postgresql+psycopg://nexscout_owner:nexscout_owner_dev@localhost:5432/nexscout"
    )
    db_pool_size: int = 10
    db_max_overflow: int = 5
    db_connect_timeout_s: int = 5
    db_pool_timeout_s: int = 10

    session_idle_hours: int = 12
    session_absolute_days: int = 14
    session_cookie_name: str = "nexscout_session"
    csrf_cookie_name: str = "nexscout_csrf"
    csrf_header_name: str = "X-CSRF-Token"

    login_rate_limit_per_minute: int = Field(default=10, ge=1)

    storage_dir: Path = REPO_ROOT / "data" / "storage"
    max_upload_bytes: int = 15 * 1024 * 1024

    master_key: SecretStr | None = None

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def cookie_secure(self) -> bool:
        return self.is_production


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
