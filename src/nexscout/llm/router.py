"""Task-aware LLM router with retry, budget enforcement and Qwen optimisation.

Provider strings are encoded as ``"<scheme>:<model>"`` or just ``"<model>"``
in which case the scheme is inferred from the model name:

* ``openai:gpt-4o`` / ``gpt-4o``               → OpenAI
* ``anthropic:claude-...``                     → Anthropic
* ``gemini-2.0-flash`` / ``gemini:...``        → Gemini
* ``ollama:llama3.1:70b``                      → Ollama
* ``lmstudio:...`` / ``vllm:...`` / ``llamacpp:...``
"""

from __future__ import annotations

import logging
import random
import time
from email.utils import parsedate_to_datetime
from typing import Any, Literal

import httpx

from ..core.errors import ProviderError
from ..core.profile import Profile
from .budget import BudgetLedger
from .providers.anthropic import AnthropicProvider
from .providers.base import Message, Provider
from .providers.gemini import GeminiProvider
from .providers.llamacpp import LlamaCppProvider
from .providers.lmstudio import LMStudioProvider
from .providers.ollama import OllamaProvider
from .providers.openai import OpenAIProvider
from .providers.vllm import VLLMProvider

log = logging.getLogger(__name__)

Task = Literal["discover", "enrich", "score", "tailor", "judge", "cover", "apply"]
MAX_ATTEMPTS = 5
BACKOFF_BASE = 10.0
BACKOFF_CAP = 60.0


def _parse_provider(spec: str) -> tuple[str, str]:
    """Split ``scheme:model`` (or infer scheme from a bare model name)."""
    if ":" in spec:
        first, rest = spec.split(":", 1)
        known = {"openai", "anthropic", "gemini", "ollama", "lmstudio", "vllm", "llamacpp"}
        if first.lower() in known:
            return first.lower(), rest
    s = spec.lower()
    if s.startswith("gpt") or s.startswith("o1") or s.startswith("o3"):
        return "openai", spec
    if "claude" in s or s.startswith("anthropic"):
        return "anthropic", spec
    if s.startswith("gemini"):
        return "gemini", spec
    if s.startswith("llama") or s.startswith("qwen") or s.startswith("mistral"):
        return "ollama", spec
    return "openai", spec


def _build_provider(spec: str) -> Provider:
    scheme, model = _parse_provider(spec)
    if scheme == "openai":
        return OpenAIProvider(model=model)
    if scheme == "anthropic":
        return AnthropicProvider(model=model)
    if scheme == "gemini":
        return GeminiProvider(model=model)
    if scheme == "ollama":
        return OllamaProvider(model=model)
    if scheme == "lmstudio":
        return LMStudioProvider(model=model)
    if scheme == "vllm":
        return VLLMProvider(model=model)
    if scheme == "llamacpp":
        return LlamaCppProvider(model=model)
    raise ProviderError(f"unknown provider scheme {scheme!r}")


def _is_qwen(spec: str) -> bool:
    return "qwen" in spec.lower()


def _retry_after_seconds(headers: dict[str, str]) -> float | None:
    for key in ("retry-after", "Retry-After"):
        if key in headers:
            v = headers[key]
            if v.isdigit():
                return float(v)
            try:
                dt = parsedate_to_datetime(v)
                return max(0.0, (dt.timestamp() - time.time()))
            except (TypeError, ValueError):
                pass
    for key in ("x-ratelimit-reset-requests", "X-RateLimit-Reset-Requests"):
        if key in headers:
            v = headers[key]
            if v.replace(".", "", 1).isdigit():
                return float(v)
    return None


def _backoff(attempt: int) -> float:
    return min(BACKOFF_CAP, BACKOFF_BASE * (2 ** (attempt - 1))) + random.uniform(0, 1.0)


class LLMRouter:
    """Task-aware dispatch with budget gating and retry."""

    def __init__(self, profile: Profile, budget: BudgetLedger | None = None) -> None:
        self.profile = profile
        self.budget = budget or BudgetLedger(
            monthly_usd=profile.llm.budgets.monthly_usd,
            daily_calls=profile.llm.budgets.daily_calls,
        )
        # Per-spec provider cache.
        self._provider_cache: dict[str, Provider] = {}

    # ---- selection ----
    def _select_spec(self, task: Task) -> str:
        if task == "judge":
            return self.profile.llm.judge or self.profile.llm.primary
        return self.profile.llm.primary

    def _fallback_spec(self, task: Task) -> str:
        if task == "judge":
            return self.profile.llm.primary
        return self.profile.llm.fallback

    def _provider(self, spec: str) -> Provider:
        if spec not in self._provider_cache:
            self._provider_cache[spec] = _build_provider(spec)
        return self._provider_cache[spec]

    # ---- main entry ----
    def ask(
        self,
        task: Task,
        messages: list[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
        spec = self._select_spec(task)
        if not self.budget.allow(spec, est_tokens=max_tokens):
            log.warning("budget blocks %s for task=%s, falling back", spec, task)
            spec = self._fallback_spec(task)

        # Qwen optimisation: suppress <think> tokens.
        prepared: list[Message] = self._prep_messages(spec, messages)

        last_err: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                provider = self._provider(spec)
                out = provider.chat(prepared, temperature=temperature, max_tokens=max_tokens)
                self.budget.record(spec, in_tokens=_rough_tokens(prepared), out_tokens=_rough_tokens_str(out))
                return out
            except ProviderError as e:
                last_err = e
                wait = self._wait_for(e, attempt)
                log.warning("provider %s attempt %d failed: %s; sleeping %.1fs", spec, attempt, e, wait)
                time.sleep(wait)
            except httpx.HTTPError as e:
                last_err = e
                wait = _backoff(attempt)
                log.warning("transport %s attempt %d failed: %s; sleeping %.1fs", spec, attempt, e, wait)
                time.sleep(wait)
            if attempt == 2 and spec != self._fallback_spec(task):
                # Switch to fallback after a couple of attempts.
                new_spec = self._fallback_spec(task)
                if new_spec and new_spec != spec:
                    log.warning("switching from %s to %s", spec, new_spec)
                    spec = new_spec
                    prepared = self._prep_messages(spec, messages)
        raise ProviderError(f"all attempts failed for task={task}: {last_err}") from last_err

    @staticmethod
    def _prep_messages(spec: str, messages: list[Message]) -> list[Message]:
        if not _is_qwen(spec):
            return list(messages)
        out: list[Message] = []
        seen_user = False
        for m in messages:
            if not seen_user and m.get("role") == "user":
                out.append({"role": "user", "content": "/no_think\n" + str(m.get("content", ""))})
                seen_user = True
            else:
                out.append(m)
        return out

    @staticmethod
    def _wait_for(err: Exception, attempt: int) -> float:
        # Honour Retry-After when ProviderError carries the response in args.
        for arg in getattr(err, "args", ()):
            if isinstance(arg, dict):
                ra = _retry_after_seconds(arg)
                if ra is not None:
                    return ra
        return _backoff(attempt)


def _rough_tokens(messages: list[Message]) -> int:
    chars = sum(len(str(m.get("content", ""))) for m in messages)
    return max(1, chars // 4)


def _rough_tokens_str(s: str | Any) -> int:
    return max(1, len(str(s)) // 4)
