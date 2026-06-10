"""Tests for ``llm.router`` using a stubbed provider."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from nexscout.core.profile import Profile
from nexscout.llm.providers.base import Message
from nexscout.llm.router import LLMRouter, _parse_provider


class MockProvider:
    name = "mock"

    def __init__(self, model: str, responses: list[str] | None = None, fail_n: int = 0) -> None:
        self.model = model
        self.responses = list(responses or ["ok"])
        self.fail_n = fail_n
        self.calls: list[list[Message]] = []

    def chat(self, messages: list[Message], *, temperature: float = 0.2, max_tokens: int = 2048) -> str:
        self.calls.append(list(messages))
        if self.fail_n > 0:
            self.fail_n -= 1
            from nexscout.core.errors import ProviderError

            raise ProviderError("simulated transient failure")
        return self.responses.pop(0) if self.responses else "ok"


@pytest.fixture
def example_profile() -> Iterator[Profile]:
    # The 3-file split example; from_path auto-merges sibling settings/credentials.
    src = Path(__file__).resolve().parents[2] / "examples" / "split" / "profile.yaml"
    yield Profile.from_path(src)


def test_provider_parsing() -> None:
    assert _parse_provider("openai:gpt-4o") == ("openai", "gpt-4o")
    assert _parse_provider("anthropic:claude-haiku-4-5")[0] == "anthropic"
    assert _parse_provider("gemini-2.0-flash")[0] == "gemini"
    assert _parse_provider("ollama:llama3.1:70b") == ("ollama", "llama3.1:70b")
    assert _parse_provider("gpt-4o")[0] == "openai"
    # OpenAI-compatible schemes (model ids may themselves contain "/").
    assert _parse_provider("openai_compat:vendor/model-x") == ("openai_compat", "vendor/model-x")
    assert _parse_provider("nim:meta/llama-3.1-70b-instruct") == ("nim", "meta/llama-3.1-70b-instruct")


def test_router_uses_judge_for_judge_task(example_profile: Profile, monkeypatch: pytest.MonkeyPatch) -> None:
    router = LLMRouter(example_profile)
    judge_mock = MockProvider("judge", ["judge-out"])
    primary_mock = MockProvider("primary", ["primary-out"])

    def fake_provider(self: LLMRouter, spec: str) -> Any:
        if "claude" in spec.lower():
            return judge_mock
        return primary_mock

    monkeypatch.setattr(LLMRouter, "_provider", fake_provider)

    out = router.ask("judge", [{"role": "user", "content": "hi"}])
    assert out == "judge-out"
    assert judge_mock.calls and not primary_mock.calls


def test_router_retries_then_succeeds(example_profile: Profile, monkeypatch: pytest.MonkeyPatch) -> None:
    router = LLMRouter(example_profile)
    mock = MockProvider("primary", ["good"], fail_n=2)

    monkeypatch.setattr(LLMRouter, "_provider", lambda self, spec: mock)
    monkeypatch.setattr("nexscout.llm.router._backoff", lambda attempt: 0.0)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    out = router.ask("score", [{"role": "user", "content": "x"}])
    assert out == "good"


def test_qwen_prefix_injected(example_profile: Profile, monkeypatch: pytest.MonkeyPatch) -> None:
    example_profile.llm.primary = "ollama:qwen2.5:7b"
    router = LLMRouter(example_profile)
    mock = MockProvider("qwen", ["ok"])

    monkeypatch.setattr(LLMRouter, "_provider", lambda self, spec: mock)

    router.ask("score", [{"role": "user", "content": "hello"}])
    assert mock.calls[0][0]["content"].startswith("/no_think\n")
