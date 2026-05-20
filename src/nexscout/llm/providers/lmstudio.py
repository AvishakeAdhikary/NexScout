"""LM Studio provider (OpenAI-compat at http://localhost:1234/v1)."""

from __future__ import annotations

import os

from .openai import OpenAIProvider


class LMStudioProvider(OpenAIProvider):
    name = "lmstudio"

    def __init__(self, model: str, base_url: str | None = None, timeout: float = 120.0) -> None:
        super().__init__(
            model=model,
            api_key="lm-studio",  # LM Studio ignores the key but the header must be present.
            base_url=base_url or os.environ.get("LMSTUDIO_URL", "http://localhost:1234/v1"),
            timeout=timeout,
        )
