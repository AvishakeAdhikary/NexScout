"""Google Gemini adapter (official `google-genai` SDK, async)."""

from __future__ import annotations

import time

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from nexscout.infrastructure.llm.base import (
    CompletionRequest,
    CompletionResult,
    ModelCapabilities,
    ProviderAuthError,
    ProviderBadRequest,
    ProviderUnavailable,
    Usage,
)


class GeminiProvider:
    kind = "gemini"

    def __init__(
        self, *, api_key: str, model: str, capabilities: ModelCapabilities, display_name: str = ""
    ) -> None:
        self._client = genai.Client(api_key=api_key)
        self.model = model
        self.capabilities = capabilities
        self.display_name = display_name or f"Gemini {model}"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        contents = [
            types.Content(
                role="user" if m.role == "user" else "model", parts=[types.Part(text=m.content)]
            )
            for m in request.messages
        ]
        config = types.GenerateContentConfig(
            system_instruction=request.system or None,
            max_output_tokens=request.max_tokens,
            temperature=request.temperature,
            response_mime_type="application/json" if request.json_schema else None,
            response_json_schema=request.json_schema,
            http_options=types.HttpOptions(timeout=int(request.timeout_s * 1000)),
        )
        started = time.perf_counter()
        try:
            response = await self._client.aio.models.generate_content(
                model=self.model, contents=contents, config=config
            )
        except genai_errors.ClientError as exc:
            if exc.code in (401, 403):
                raise ProviderAuthError("Google rejected the API key.") from exc
            if exc.code == 429:
                raise ProviderUnavailable("Gemini rate limit reached.") from exc
            raise ProviderBadRequest(f"Gemini rejected the request ({exc.code}).") from exc
        except genai_errors.ServerError as exc:
            raise ProviderUnavailable(f"Gemini is unavailable ({exc.code}).") from exc
        except (TimeoutError, ConnectionError) as exc:
            raise ProviderUnavailable("Couldn't reach Gemini.") from exc
        meta = response.usage_metadata
        finish = response.candidates[0].finish_reason if response.candidates else None
        return CompletionResult(
            text=response.text or "",
            usage=Usage(
                int(meta.prompt_token_count or 0) if meta else 0,
                int(meta.candidates_token_count or 0) if meta else 0,
            ),
            model=self.model,
            provider_kind=self.kind,
            latency_ms=int((time.perf_counter() - started) * 1000),
            finish_reason=str(finish or "unknown"),
        )
