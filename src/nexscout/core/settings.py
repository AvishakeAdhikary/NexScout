"""Environment-backed runtime settings (pydantic-settings)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide settings sourced from environment + ``.env`` file.

    All fields are optional; profile.yaml is the source of truth for behaviour.
    These env vars only carry secrets/keys.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # API keys
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    azure_openai_endpoint: str | None = Field(default=None, alias="AZURE_OPENAI_ENDPOINT")

    # Captcha
    captcha_api_key: str | None = Field(default=None, alias="CAPTCHA_API_KEY")

    # Search providers
    tavily_api_key: str | None = Field(default=None, alias="TAVILY_API_KEY")
    brave_api_key: str | None = Field(default=None, alias="BRAVE_API_KEY")
    google_cse_key: str | None = Field(default=None, alias="GOOGLE_CSE_KEY")
    google_cse_cx: str | None = Field(default=None, alias="GOOGLE_CSE_CX")
    searxng_url: str | None = Field(default=None, alias="SEARXNG_URL")

    # Local endpoints
    ollama_url: str = Field(default="http://localhost:11434", alias="OLLAMA_URL")
    lmstudio_url: str = Field(default="http://localhost:1234/v1", alias="LMSTUDIO_URL")
    vllm_url: str | None = Field(default=None, alias="VLLM_URL")
    llamacpp_url: str | None = Field(default=None, alias="LLAMACPP_URL")

    # Misc
    chrome_path: str | None = Field(default=None, alias="CHROME_PATH")


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return a process-wide :class:`Settings` instance (lazy init)."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
