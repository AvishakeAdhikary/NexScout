"""Extra router coverage — provider builder, retry-after, qwen prep, fallback."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from nexscout.core.errors import ProviderError
from nexscout.core.profile import Profile
from nexscout.llm.providers.anthropic import AnthropicProvider
from nexscout.llm.providers.base import Message
from nexscout.llm.providers.gemini import GeminiProvider
from nexscout.llm.providers.llamacpp import LlamaCppProvider
from nexscout.llm.providers.lmstudio import LMStudioProvider
from nexscout.llm.providers.ollama import OllamaProvider
from nexscout.llm.providers.openai import OpenAIProvider
from nexscout.llm.providers.vllm import VLLMProvider
from nexscout.llm.router import (
    LLMRouter,
    _backoff,
    _build_provider,
    _is_qwen,
    _parse_provider,
    _retry_after_seconds,
)


@pytest.fixture
def example_profile() -> Iterator[Profile]:
    # The 3-file split example; from_path auto-merges sibling settings/credentials.
    src = Path(__file__).resolve().parents[2] / "examples" / "split" / "profile.yaml"
    yield Profile.from_path(src)


class TestParseProvider:
    def test_inferred_schemes(self) -> None:
        assert _parse_provider("gpt-4o-mini")[0] == "openai"
        assert _parse_provider("o1-preview")[0] == "openai"
        assert _parse_provider("o3-mini")[0] == "openai"
        assert _parse_provider("claude-sonnet-4-5")[0] == "anthropic"
        assert _parse_provider("anthropic-something")[0] == "anthropic"
        assert _parse_provider("gemini-1.5-pro")[0] == "gemini"
        assert _parse_provider("llama3.1-70b")[0] == "ollama"
        assert _parse_provider("qwen2.5")[0] == "ollama"
        assert _parse_provider("mistral-large")[0] == "ollama"
        assert _parse_provider("random-model")[0] == "openai"  # fallback


class TestBuildProvider:
    def test_each_scheme_constructs_correct_class(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Stub out env so constructors don't reject missing keys.
        monkeypatch.setenv("OPENAI_API_KEY", "x")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
        monkeypatch.setenv("GEMINI_API_KEY", "x")
        monkeypatch.setenv("VLLM_URL", "http://localhost:8000/v1")
        monkeypatch.setenv("LLAMACPP_URL", "http://localhost:8080/v1")

        assert isinstance(_build_provider("openai:gpt-4o"), OpenAIProvider)
        assert isinstance(_build_provider("anthropic:claude-haiku"), AnthropicProvider)
        assert isinstance(_build_provider("gemini:gemini-2.0-flash"), GeminiProvider)
        assert isinstance(_build_provider("ollama:llama3.1:70b"), OllamaProvider)
        assert isinstance(_build_provider("lmstudio:local"), LMStudioProvider)
        assert isinstance(_build_provider("vllm:local"), VLLMProvider)
        assert isinstance(_build_provider("llamacpp:local"), LlamaCppProvider)

    def test_unknown_scheme_raises(self) -> None:
        with pytest.raises(ProviderError, match="unknown"):
            # Force the scheme branch with an unknown prefix that the parser respects.
            from nexscout.llm import router as r

            r._parse_provider = lambda _s: ("madeup", "x")  # type: ignore[attr-defined]
            try:
                _build_provider("madeup:x")
            finally:
                r._parse_provider = _parse_provider  # type: ignore[attr-defined]


class TestRetryAfterSeconds:
    def test_numeric(self) -> None:
        assert _retry_after_seconds({"retry-after": "12"}) == 12.0
        assert _retry_after_seconds({"Retry-After": "5"}) == 5.0

    def test_http_date(self) -> None:
        # Build a date 60s in the future.
        from email.utils import formatdate

        future = formatdate(time.time() + 60, usegmt=True)
        out = _retry_after_seconds({"retry-after": future})
        assert out is not None
        assert 0 < out <= 65

    def test_xratelimit_reset_requests(self) -> None:
        assert _retry_after_seconds({"x-ratelimit-reset-requests": "0.5"}) == 0.5

    def test_returns_none_when_no_headers(self) -> None:
        assert _retry_after_seconds({}) is None
        assert _retry_after_seconds({"retry-after": "not-a-date"}) is None


class TestBackoff:
    def test_growing_and_capped(self) -> None:
        # Backoff caps at BACKOFF_CAP regardless of attempt.
        a1 = _backoff(1)
        a8 = _backoff(8)
        assert 10 <= a1 <= 11  # base 10 + jitter 0..1
        assert a8 <= 61  # cap 60 + jitter 0..1


class TestQwenDetect:
    def test_qwen_in_spec(self) -> None:
        assert _is_qwen("qwen2.5-coder") is True
        assert _is_qwen("ollama:qwen2.5") is True
        assert _is_qwen("llama3.1") is False


class _RecordingProvider:
    name = "rec"

    def __init__(self) -> None:
        self.calls: list[list[Message]] = []

    def chat(self, messages: list[Message], **_: Any) -> str:
        self.calls.append(list(messages))
        return "ok"


def test_prep_messages_qwen_injects_no_think(example_profile: Profile) -> None:
    _ = LLMRouter(example_profile)
    msgs: list[Message] = [
        Message(role="system", content="sys"),
        Message(role="user", content="hello"),
        Message(role="assistant", content="hi"),
        Message(role="user", content="again"),
    ]
    prepped = LLMRouter._prep_messages("ollama:qwen2.5", msgs)
    assert prepped[0]["content"] == "sys"
    assert prepped[1]["content"].startswith("/no_think\n")
    # Only the FIRST user is rewritten.
    assert prepped[3]["content"] == "again"


def test_prep_messages_passthrough_for_non_qwen(example_profile: Profile) -> None:
    msgs: list[Message] = [Message(role="user", content="x")]
    prepped = LLMRouter._prep_messages("openai:gpt-4o", msgs)
    assert prepped == msgs
    # Returned list is a copy, not the same object.
    assert prepped is not msgs


def test_router_falls_back_after_failures(example_profile: Profile, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the primary keeps failing, attempt 2 swaps to fallback."""
    fallback = _RecordingProvider()

    class _BadFirst(_RecordingProvider):
        def chat(self, messages: list[Message], **_: Any) -> str:
            super().chat(messages)
            raise ProviderError("primary down")

    bad = _BadFirst()
    monkeypatch.setattr("nexscout.llm.router._backoff", lambda _attempt: 0.0)
    fake = {"primary": bad, "fallback": fallback}

    def fake_provider(self: LLMRouter, spec: str) -> Any:
        return fake["fallback"] if spec == example_profile.llm.fallback else fake["primary"]

    monkeypatch.setattr(LLMRouter, "_provider", fake_provider)
    router = LLMRouter(example_profile)
    out = router.ask("score", [Message(role="user", content="hi")])
    assert out == "ok"
    # Primary called at least twice before the swap.
    assert len(bad.calls) >= 2
    assert len(fallback.calls) >= 1


def test_router_budget_blocks_pushes_to_fallback(example_profile: Profile, monkeypatch: pytest.MonkeyPatch) -> None:
    fallback = _RecordingProvider()

    class _NoBudget:
        def allow(self, _spec: str, *, est_tokens: int) -> bool:
            return False

        def record(self, *a: Any, **k: Any) -> None:
            pass

    router = LLMRouter(example_profile, budget=_NoBudget())  # type: ignore[arg-type]
    monkeypatch.setattr(LLMRouter, "_provider", lambda self, spec: fallback)
    out = router.ask("tailor", [Message(role="user", content="hi")])
    assert out == "ok"
