"""Deterministic mock provider (clearly labelled; never presented as a real model).

Answers come from registered per-purpose handlers that compute output from the structured
`mock_inputs` of the request, so tests and demos are reproducible. A `script` can be given to
return fixed raw texts or raise errors (for testing repair, retries, and failures).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from nexscout.infrastructure.llm.base import (
    CompletionRequest,
    CompletionResult,
    ModelCapabilities,
    Usage,
)

MockHandler = Callable[[CompletionRequest], dict[str, Any]]
_HANDLERS: dict[str, MockHandler] = {}

MOCK_CAPABILITIES = ModelCapabilities(
    context_window=32_768,
    max_output_tokens=4096,
    json_schema=True,
    data_leaves_device=False,
    input_cost_per_mtok=0.0,
    output_cost_per_mtok=0.0,
)


def mock_handler(purpose: str) -> Callable[[MockHandler], MockHandler]:
    def register(fn: MockHandler) -> MockHandler:
        _HANDLERS[purpose] = fn
        return fn

    return register


_HANDLERS["provider.verify"] = lambda request: {"ok": True}


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / 3.5))


class MockProvider:
    kind = "mock"
    model = "nexscout-mock-1"
    display_name = "NexScout demo model (mock, not AI)"

    def __init__(
        self,
        script: list[str | Exception] | None = None,
        capabilities: ModelCapabilities = MOCK_CAPABILITIES,
    ) -> None:
        self._script = list(script or [])
        self.capabilities = capabilities
        self.requests: list[CompletionRequest] = []

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        started = time.perf_counter()
        self.requests.append(request)
        if self._script:
            item = self._script.pop(0)
            if isinstance(item, Exception):
                raise item
            text = item
        else:
            handler = _HANDLERS.get(request.purpose)
            text = json.dumps(handler(request)) if handler else json.dumps({"echo": True})
        prompt = (request.system or "") + "".join(m.content for m in request.messages)
        return CompletionResult(
            text=text,
            usage=Usage(_estimate_tokens(prompt), _estimate_tokens(text)),
            model=self.model,
            provider_kind=self.kind,
            latency_ms=int((time.perf_counter() - started) * 1000),
            finish_reason="stop",
            is_mock=True,
        )
