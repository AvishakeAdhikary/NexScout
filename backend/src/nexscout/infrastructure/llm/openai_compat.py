"""OpenAI-compatible Chat Completions adapter (OpenAI, Ollama `/v1`, LM Studio, vLLM, ...).

Plain httpx so it works against any compatible server. Schema-constrained output uses
`response_format: {type: json_schema}` only when the configured capabilities say the server
supports it; otherwise `structured()` falls back to instructions + validation.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from nexscout.domain.errors import ValidationFailed
from nexscout.infrastructure.llm.base import (
    CompletionRequest,
    CompletionResult,
    ModelCapabilities,
    ProviderAuthError,
    ProviderBadRequest,
    ProviderUnavailable,
    Usage,
)
from nexscout.infrastructure.security.urls import check_outbound_url


class OpenAICompatibleProvider:
    kind = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None,
        capabilities: ModelCapabilities,
        display_name: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
        allow_private: bool = True,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._transport = transport
        self._allow_private = allow_private
        self.model = model
        self.capabilities = capabilities
        self.display_name = display_name or f"{model} ({self._base_url})"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages += [{"role": m.role, "content": m.content} for m in request.messages]
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": request.max_tokens,
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_name[:64],
                    "schema": request.json_schema,
                    "strict": True,
                },
            }
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        if self._transport is None:  # re-validate where the name resolves *now*
            try:
                await asyncio.to_thread(
                    check_outbound_url, self._base_url, allow_private=self._allow_private
                )
            except ValidationFailed as exc:
                raise ProviderBadRequest(
                    f"Model server address not allowed: {exc.message}"
                ) from exc
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=request.timeout_s, transport=self._transport
            ) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions", json=body, headers=headers
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderUnavailable(
                f"Couldn't reach the model server ({type(exc).__name__})."
            ) from exc
        if resp.status_code in (401, 403):
            raise ProviderAuthError("The model server rejected the API key.")
        if resp.status_code == 429 or resp.status_code >= 500:
            raise ProviderUnavailable(f"The model server is busy or failing ({resp.status_code}).")
        if resp.status_code >= 400:
            raise ProviderBadRequest(
                f"The model server rejected the request ({resp.status_code}): "
                f"{_error_message(resp)}"
            )
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        usage = data.get("usage") or {}
        return CompletionResult(
            text=text,
            usage=Usage(
                int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
            ),
            model=str(data.get("model") or self.model),
            provider_kind=self.kind,
            latency_ms=int((time.perf_counter() - started) * 1000),
            finish_reason=str(choice.get("finish_reason") or "unknown"),
        )


def _error_message(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error")
        msg = err.get("message") if isinstance(err, dict) else err
        return str(msg)[:300] if msg else resp.reason_phrase
    except ValueError:
        return resp.reason_phrase
