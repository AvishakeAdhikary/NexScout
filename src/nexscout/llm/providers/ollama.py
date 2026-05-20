"""Ollama provider — POST localhost:11434/api/chat."""

from __future__ import annotations

import os
from typing import Any

import httpx

from ...core.errors import ProviderError
from .base import Message


class OllamaProvider:
    name = "ollama"

    def __init__(self, model: str, base_url: str | None = None, timeout: float = 300.0) -> None:
        self.model = model
        self.base_url = (base_url or os.environ.get("OLLAMA_URL", "http://localhost:11434")).rstrip("/")
        self.timeout = timeout

    def chat(self, messages: list[Message], *, temperature: float = 0.2, max_tokens: int = 2048) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        try:
            resp = httpx.post(f"{self.base_url}/api/chat", json=body, timeout=self.timeout)
        except httpx.HTTPError as e:
            raise ProviderError(f"ollama transport: {e}") from e
        if resp.status_code >= 400:
            raise ProviderError(f"ollama http {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        try:
            return str(data["message"]["content"])
        except (KeyError, TypeError) as e:
            raise ProviderError(f"ollama malformed: {data!r}") from e
