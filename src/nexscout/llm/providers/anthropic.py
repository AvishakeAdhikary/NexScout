"""Anthropic provider — native ``/v1/messages`` with prompt-cache header."""

from __future__ import annotations

import os
from typing import Any

import httpx

from ...core.errors import ProviderError
from .base import Message

API_BASE = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
BETA_HEADER = "prompt-caching-2024-07-31"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str, api_key: str | None = None, timeout: float = 60.0) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.timeout = timeout

    def chat(self, messages: list[Message], *, temperature: float = 0.2, max_tokens: int = 2048) -> str:
        if not self.api_key:
            raise ProviderError("ANTHROPIC_API_KEY not set")

        system_parts: list[str] = []
        normalised: list[dict[str, Any]] = []
        for m in messages:
            if m.get("role") == "system":
                system_parts.append(str(m.get("content", "")))
                continue
            normalised.append({"role": m.get("role", "user"), "content": str(m.get("content", ""))})

        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": normalised,
        }
        if system_parts:
            body["system"] = [
                {
                    "type": "text",
                    "text": "\n\n".join(system_parts),
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": API_VERSION,
            "anthropic-beta": BETA_HEADER,
            "Content-Type": "application/json",
        }
        resp = httpx.post(API_BASE, json=body, headers=headers, timeout=self.timeout)
        if resp.status_code >= 400:
            raise ProviderError(f"anthropic http {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        try:
            return "".join(str(part.get("text", "")) for part in data["content"] if part.get("type") == "text") or str(
                data["content"][0]["text"]
            )
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"anthropic malformed: {data!r}") from e
