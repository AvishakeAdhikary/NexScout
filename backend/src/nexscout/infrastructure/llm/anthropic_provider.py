"""Anthropic Messages API adapter (official `anthropic` SDK, async, BYOK).

- Structured output via `output_config.format` (`json_schema`).
- `stop_reason == "refusal"` is checked before reading content.
- Server-side refusal fallback (`fallbacks="default"`, beta `server-side-fallback-2026-07-01`)
  is on by default and can be turned off per provider config.
- SDK retries are disabled (`max_retries=0`); the NexScout runtime owns retries and backoff.
"""

from __future__ import annotations

import time
from typing import Any

import anthropic

from nexscout.infrastructure.llm.base import (
    CompletionRequest,
    CompletionResult,
    ModelCapabilities,
    ProviderAuthError,
    ProviderBadRequest,
    ProviderRefusal,
    ProviderUnavailable,
    Usage,
)

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# USD per million tokens (input, output), from the Anthropic model table (2026-10).
PRICING: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}


class AnthropicProvider:
    kind = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        capabilities: ModelCapabilities,
        refusal_fallback: bool = True,
        display_name: str = "",
        base_url: str | None = None,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=0, base_url=base_url)
        self._fallback = refusal_fallback
        self.model = model
        self.capabilities = capabilities
        self.display_name = display_name or f"Anthropic {model}"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        }
        if request.system:
            params["system"] = request.system
        if request.json_schema is not None:
            params["output_config"] = {
                "format": {"type": "json_schema", "schema": request.json_schema}
            }
        started = time.perf_counter()
        client = self._client.with_options(timeout=request.timeout_s)
        try:
            if self._fallback:
                response: Any = await client.beta.messages.create(
                    **params, betas=[FALLBACK_BETA], fallbacks="default"
                )
            else:
                response = await client.messages.create(**params)
        except anthropic.AuthenticationError as exc:
            raise ProviderAuthError("Anthropic rejected the API key.") from exc
        except anthropic.PermissionDeniedError as exc:
            raise ProviderAuthError("This Anthropic key can't use that model.") from exc
        except anthropic.NotFoundError as exc:
            raise ProviderBadRequest(f"Unknown Anthropic model: {self.model}.") from exc
        except anthropic.RateLimitError as exc:
            raise ProviderUnavailable("Anthropic rate limit reached.") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise ProviderUnavailable(f"Anthropic is unavailable ({exc.status_code}).") from exc
            raise ProviderBadRequest(
                f"Anthropic rejected the request ({exc.status_code})."
            ) from exc
        except anthropic.APIConnectionError as exc:  # includes APITimeoutError
            raise ProviderUnavailable("Couldn't reach Anthropic.") from exc

        if response.stop_reason == "refusal":
            raise ProviderRefusal("The model declined this request.")
        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
        return CompletionResult(
            text=text,
            usage=Usage(
                int(response.usage.input_tokens or 0), int(response.usage.output_tokens or 0)
            ),
            model=str(response.model),
            provider_kind=self.kind,
            latency_ms=int((time.perf_counter() - started) * 1000),
            finish_reason=str(response.stop_reason),
        )
