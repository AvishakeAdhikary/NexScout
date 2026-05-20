"""Gemini provider.

Tries the OpenAI-compat shim first at
``https://generativelanguage.googleapis.com/v1beta/openai/chat/completions``.
On HTTP 403 (typical for preview models that aren't exposed via the compat
layer), falls back to the native ``:generateContent`` endpoint. The "native
works for this model" bit is cached per-process to avoid the failed-compat
round-trip on every call.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from ...core.errors import ProviderError
from .base import Message

COMPAT_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
NATIVE_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Per-process flag: True once we know the model needs the native API.
_NATIVE_PREFERRED: dict[str, bool] = {}


def _split_system(messages: list[Message]) -> tuple[str, list[Message]]:
    system_parts: list[str] = []
    rest: list[Message] = []
    for m in messages:
        if m.get("role") == "system":
            system_parts.append(str(m.get("content", "")))
        else:
            rest.append(m)
    return "\n\n".join(system_parts), rest


def _to_native_contents(messages: list[Message]) -> list[dict[str, Any]]:
    contents: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role", "user")
        if role == "system":
            continue
        if role == "assistant":
            role = "model"
        contents.append({"role": role, "parts": [{"text": str(m.get("content", ""))}]})
    return contents


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.timeout = timeout

    def chat(self, messages: list[Message], *, temperature: float = 0.2, max_tokens: int = 2048) -> str:
        if not self.api_key:
            raise ProviderError("GEMINI_API_KEY not set")

        if _NATIVE_PREFERRED.get(self.model):
            return self._chat_native(messages, temperature=temperature, max_tokens=max_tokens)

        try:
            return self._chat_compat(messages, temperature=temperature, max_tokens=max_tokens)
        except ProviderError as e:
            # 403 — fall through to native (and remember).
            if "403" in str(e):
                _NATIVE_PREFERRED[self.model] = True
                return self._chat_native(messages, temperature=temperature, max_tokens=max_tokens)
            raise

    def _chat_compat(self, messages: list[Message], *, temperature: float, max_tokens: int) -> str:
        url = f"{COMPAT_BASE}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        resp = httpx.post(url, json=body, headers=headers, timeout=self.timeout)
        if resp.status_code >= 400:
            raise ProviderError(f"gemini compat http {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"gemini compat malformed: {data!r}") from e

    def _chat_native(self, messages: list[Message], *, temperature: float, max_tokens: int) -> str:
        system_text, rest = _split_system(messages)
        contents = _to_native_contents(rest)
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        if system_text:
            body["systemInstruction"] = {"parts": [{"text": system_text}]}
        url = f"{NATIVE_BASE}/models/{self.model}:generateContent?key={self.api_key}"
        resp = httpx.post(url, json=body, timeout=self.timeout)
        if resp.status_code >= 400:
            raise ProviderError(f"gemini native http {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        try:
            return str(data["candidates"][0]["content"]["parts"][0]["text"])
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"gemini native malformed: {data!r}") from e
