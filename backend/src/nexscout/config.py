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
    maintenance_interval_s: float = Field(default=60.0, ge=1.0)

    # Providers: allow base URLs on private/loopback networks (needed for Ollama/LM Studio on
    # this machine). Disable on multi-user servers to prevent SSRF into internal services.
    allow_private_provider_urls: bool = True

    # Research: read public pages linked from listings (SSRF-safe, robots.txt respected).
    research_fetch_enabled: bool = True

    # Demo data (labelled demo sources and the demo application site at /fixture-site) is for
    # tests, E2E and developer demos only. It is OFF unless NEXSCOUT_DEMO_DATA=1, so a shipped
    # install never shows demo listings.
    demo_data: bool = False

    # Browser automation. The demo site (only with demo data on) is reached by the worker at
    # `fixture_site_origin`.
    browser_headless: bool = True
    fixture_site_enabled: bool | None = None
    fixture_site_origin: str = "http://127.0.0.1:8000"

    # Notification channels (M11). Links in messages point here; set it to the address you
    # open NexScout at (a public HTTPS address makes chat apps show an "Open" button).
    public_web_url: str = "http://localhost:3000"
    channels_enabled: bool = True
    secure_cookies: bool | None = None  # None: secure exactly when public_web_url is https
    channel_poll_interval_s: float = Field(default=2.0, gt=0)

    # Assisted mode (M12): a visible browser window on this computer where the person solves
    # a CAPTCHA or signs in and submits. Only meaningful where the worker runs on the user's own
    # machine (desktop app, local install); the desktop app turns it on.
    assisted_browser: bool = False
    assist_timeout_s: float = Field(default=900.0, ge=10)
    assist_headless: bool = False  # tests only: the window must be visible for a person
    # Autopilot pacing: at most one browser session per site in this many seconds.
    autopilot_site_spacing_s: float = Field(default=600.0, ge=0)

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
    def fixture_site_on(self) -> bool:
        if not self.demo_data:
            return False
        return True if self.fixture_site_enabled is None else self.fixture_site_enabled

    @property
    def cookie_secure(self) -> bool:
        # Secure cookies need HTTPS. A local install (http://localhost) in production mode must
        # still be able to sign in, so the default follows the public address.
        if self.secure_cookies is not None:
            return self.secure_cookies
        return self.is_production and self.public_web_url.lower().startswith("https://")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
