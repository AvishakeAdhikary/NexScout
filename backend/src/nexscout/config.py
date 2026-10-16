"""Application configuration loaded from NEXSCOUT_* environment variables (and .env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
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
        "postgresql+psycopg://nexscout_app:nexscout_app_dev@127.0.0.1:5432/nexscout"
    )
    # Migrations run as the schema owner role.
    migration_database_url: SecretStr = SecretStr(
        "postgresql+psycopg://nexscout_owner:nexscout_owner_dev@127.0.0.1:5432/nexscout"
    )
    # Worker-only role (BYPASSRLS) for queue claiming, leases, recovery and checkpoints.
    system_database_url: SecretStr = SecretStr(
        "postgresql+psycopg://nexscout_system:nexscout_system_dev@127.0.0.1:5432/nexscout"
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

    # Durable worker (ADR-0002, ADR-0008)
    worker_concurrency: int = Field(default=4, ge=1, le=64)
    worker_per_user_limit: int = Field(default=2, ge=1, le=64)
    worker_lease_s: int = Field(default=60, ge=5)
    worker_poll_s: float = Field(default=2.0, gt=0)
    worker_shutdown_grace_s: int = Field(default=30, ge=1)
    task_max_attempts: int = Field(default=3, ge=1, le=20)

    # Providers: allow base URLs on private/loopback networks (needed for Ollama/LM Studio on
    # this machine). Disable on multi-user servers to prevent SSRF into internal services.
    allow_private_provider_urls: bool = True

    # Research: read public pages linked from listings (SSRF-safe, robots.txt respected).
    research_fetch_enabled: bool = True

    @model_validator(mode="after")
    def _production_requirements(self) -> Settings:
        # Fail at startup, not at the first saved API key.
        if self.env == "production" and not (
            self.master_key and self.master_key.get_secret_value()
        ):
            raise ValueError("NEXSCOUT_MASTER_KEY must be set when NEXSCOUT_ENV=production.")
        return self

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def cookie_secure(self) -> bool:
        return self.is_production


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
