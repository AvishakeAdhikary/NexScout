"""vLLM provider (OpenAI-compat at a user-configured URL)."""

from __future__ import annotations

import os

from ...core.errors import ProviderError
from .openai import OpenAIProvider


class VLLMProvider(OpenAIProvider):
    name = "vllm"

    def __init__(self, model: str, base_url: str | None = None, timeout: float = 120.0) -> None:
        url = base_url or os.environ.get("VLLM_URL")
        if not url:
            raise ProviderError("VLLM_URL not set")
        super().__init__(model=model, api_key="vllm", base_url=url, timeout=timeout)
