"""Provider-neutral LLM contracts (ADR-0004).

Adapters translate a `CompletionRequest` into one provider's API and return a
`CompletionResult`. Workflow code never imports a provider SDK and never sees credentials.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class ModelCapabilities:
    context_window: int
    max_output_tokens: int
    json_schema: bool  # native schema-constrained output
    data_leaves_device: bool  # True for any remote/cloud endpoint
    input_cost_per_mtok: float | None = None
    output_cost_per_mtok: float | None = None


@dataclass
class CompletionRequest:
    messages: list[Message]
    system: str | None = None
    json_schema: dict[str, Any] | None = None
    schema_name: str = "result"
    max_tokens: int = 2048
    temperature: float | None = None
    timeout_s: float = 120.0
    purpose: str = "general"
    # Structured inputs the deterministic mock provider uses instead of parsing prose.
    # Real providers ignore this field.
    mock_inputs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class CompletionResult:
    text: str
    usage: Usage
    model: str
    provider_kind: str
    latency_ms: int
    finish_reason: str
    is_mock: bool = False


class LLMProvider(Protocol):
    kind: str
    model: str
    display_name: str
    capabilities: ModelCapabilities

    async def complete(self, request: CompletionRequest) -> CompletionResult: ...


# ---------------------------------------------------------------------------------- errors
class ProviderError(Exception):
    """Base class. Messages are user-safe: never include keys, headers or prompts."""


class ProviderUnavailable(ProviderError):
    """Transient: timeouts, connection failures, rate limits, 5xx. The runtime may retry."""


class ProviderAuthError(ProviderError):
    """The key is missing, wrong, or lacks access. Not retried."""


class ProviderBadRequest(ProviderError):
    """The provider rejected the request (e.g. unsupported option or model). Not retried."""


class ProviderRefusal(ProviderError):
    """The model declined to answer (safety). Not retried automatically."""


class OutputInvalid(ProviderError):
    """The model's output didn't match the required schema, even after a repair attempt."""


def estimate_cost(caps: ModelCapabilities, usage: Usage) -> float | None:
    if caps.input_cost_per_mtok is None or caps.output_cost_per_mtok is None:
        return None
    return round(
        usage.input_tokens / 1e6 * caps.input_cost_per_mtok
        + usage.output_tokens / 1e6 * caps.output_cost_per_mtok,
        6,
    )
