"""OpenAI / Azure OpenAI provider (OpenAI-compat ``/v1/chat/completions``)."""

from __future__ import annotations

import os
from typing import Any

import httpx

from ...core.errors import ProviderError
from .base import Message

DEFAULT_BASE = "https://api.openai.com/v1"


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = (base_url or os.environ.get("AZURE_OPENAI_ENDPOINT") or DEFAULT_BASE).rstrip("/")
        self.timeout = timeout

    def chat(self, messages: list[Message], *, temperature: float = 0.2, max_tokens: int = 2048) -> str:
        if not self.api_key:
            raise ProviderError("OPENAI_API_KEY not set")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        url = f"{self.base_url}/chat/completions"
        resp = httpx.post(url, json=body, headers=headers, timeout=self.timeout)
        if resp.status_code >= 400:
            raise ProviderError(f"openai http {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"openai malformed response: {data!r}") from e
