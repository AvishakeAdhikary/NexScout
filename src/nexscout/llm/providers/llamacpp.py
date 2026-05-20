"""llama.cpp provider (OpenAI-compat at a user-configured URL)."""

from __future__ import annotations

import os

from ...core.errors import ProviderError
from .openai import OpenAIProvider


class LlamaCppProvider(OpenAIProvider):
    name = "llamacpp"

    def __init__(self, model: str, base_url: str | None = None, timeout: float = 120.0) -> None:
        url = base_url or os.environ.get("LLAMACPP_URL")
        if not url:
            raise ProviderError("LLAMACPP_URL not set")
        super().__init__(model=model, api_key="llamacpp", base_url=url, timeout=timeout)
