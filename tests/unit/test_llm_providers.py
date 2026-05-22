"""Coverage tests for LLM providers (openai / gemini / anthropic / ollama / lmstudio / vllm / llamacpp).

Each provider's ``chat`` method is exercised against a stubbed httpx response.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from nexscout.core.errors import ProviderError
from nexscout.llm.providers.anthropic import AnthropicProvider
from nexscout.llm.providers.base import Message
from nexscout.llm.providers.gemini import GeminiProvider
from nexscout.llm.providers.llamacpp import LlamaCppProvider
from nexscout.llm.providers.lmstudio import LMStudioProvider
from nexscout.llm.providers.ollama import OllamaProvider
from nexscout.llm.providers.openai import OpenAIProvider
from nexscout.llm.providers.vllm import VLLMProvider

# ---------------------------------------------------------------------------
# Helper — fake httpx.post that returns a canned response
# ---------------------------------------------------------------------------


def _fake_post_factory(
    status: int,
    payload: dict[str, Any] | None,
    *,
    text: str | None = None,
    capture: list[dict[str, Any]] | None = None,
) -> Any:
    def _fake(
        url: str,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        **kw: Any,
    ) -> httpx.Response:
        if capture is not None:
            capture.append({"url": url, "json": json, "headers": headers, "kw": kw})
        if payload is not None:
            return httpx.Response(status, json=payload, request=httpx.Request("POST", url))
        return httpx.Response(status, content=text or "", request=httpx.Request("POST", url))

    return _fake


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


class TestOpenAI:
    def test_chat_returns_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            httpx,
            "post",
            _fake_post_factory(200, {"choices": [{"message": {"content": "hello"}}]}),
        )
        p = OpenAIProvider("gpt-4o", api_key="sk-test")
        assert p.chat([Message(role="user", content="hi")]) == "hello"

    def test_chat_missing_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
            OpenAIProvider("gpt-4o", api_key=None).chat([])

    def test_chat_http_error_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(httpx, "post", _fake_post_factory(429, None, text="rate limited"))
        p = OpenAIProvider("gpt-4o", api_key="sk-test")
        with pytest.raises(ProviderError, match="429"):
            p.chat([Message(role="user", content="hi")])

    def test_chat_malformed_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(httpx, "post", _fake_post_factory(200, {"oops": True}))
        p = OpenAIProvider("gpt-4o", api_key="sk-test")
        with pytest.raises(ProviderError, match="malformed"):
            p.chat([Message(role="user", content="hi")])


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------


class TestGemini:
    def test_chat_compat_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Reset cached native-preferred flag for a fresh path.
        from nexscout.llm.providers.gemini import _NATIVE_PREFERRED

        _NATIVE_PREFERRED.clear()
        monkeypatch.setattr(
            httpx,
            "post",
            _fake_post_factory(200, {"choices": [{"message": {"content": "compat-out"}}]}),
        )
        out = GeminiProvider("gemini-2.0-flash", api_key="k").chat([Message(role="user", content="hi")])
        assert out == "compat-out"

    def test_chat_native_fallback_on_403(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from nexscout.llm.providers.gemini import _NATIVE_PREFERRED

        _NATIVE_PREFERRED.clear()
        calls: list[str] = []

        def fake_post(url: str, json: dict[str, Any] | None = None, **kw: Any) -> httpx.Response:
            calls.append(url)
            if "openai/chat/completions" in url:
                return httpx.Response(403, content=b"forbidden", request=httpx.Request("POST", url))
            return httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": "native-out"}]}}]},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx, "post", fake_post)
        out = GeminiProvider("gemini-2.5-pro-exp", api_key="k").chat(
            [Message(role="system", content="sys"), Message(role="user", content="hi")]
        )
        assert out == "native-out"
        # Both endpoints were tried.
        assert any("openai/chat/completions" in u for u in calls)
        assert any("generateContent" in u for u in calls)

    def test_missing_key(self) -> None:
        p = GeminiProvider("gemini-2.0-flash", api_key="")
        with pytest.raises(ProviderError, match="GEMINI_API_KEY"):
            p.chat([])

    def test_native_malformed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from nexscout.llm.providers.gemini import _NATIVE_PREFERRED

        _NATIVE_PREFERRED.clear()
        _NATIVE_PREFERRED["test-model"] = True
        monkeypatch.setattr(httpx, "post", _fake_post_factory(200, {"oops": True}))
        with pytest.raises(ProviderError, match="native malformed"):
            GeminiProvider("test-model", api_key="k").chat([Message(role="user", content="hi")])


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


class TestAnthropic:
    def test_chat_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: list[dict[str, Any]] = []
        monkeypatch.setattr(
            httpx,
            "post",
            _fake_post_factory(
                200,
                {"content": [{"type": "text", "text": "from claude"}]},
                capture=captured,
            ),
        )
        out = AnthropicProvider("claude-haiku-4-5", api_key="k").chat(
            [Message(role="system", content="sys"), Message(role="user", content="hi")]
        )
        assert out == "from claude"
        body = captured[0]["json"]
        # System block is converted to a `system` list with cache_control.
        assert body["system"][0]["cache_control"] == {"type": "ephemeral"}

    def test_chat_missing_key(self) -> None:
        with pytest.raises(ProviderError, match="ANTHROPIC_API_KEY"):
            AnthropicProvider("claude-haiku-4-5", api_key="").chat([])

    def test_chat_http_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(httpx, "post", _fake_post_factory(500, None, text="server fail"))
        with pytest.raises(ProviderError, match="500"):
            AnthropicProvider("claude-haiku-4-5", api_key="k").chat([Message(role="user", content="hi")])

    def test_chat_malformed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(httpx, "post", _fake_post_factory(200, {"oops": True}))
        with pytest.raises(ProviderError, match="malformed"):
            AnthropicProvider("claude-haiku-4-5", api_key="k").chat([Message(role="user", content="hi")])


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------


class TestOllama:
    def test_chat_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(httpx, "post", _fake_post_factory(200, {"message": {"content": "ollama-out"}}))
        assert OllamaProvider("llama3.1:70b").chat([Message(role="user", content="hi")]) == "ollama-out"

    def test_chat_transport_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*a: Any, **k: Any) -> Any:
            raise httpx.ConnectError("nope")

        monkeypatch.setattr(httpx, "post", boom)
        with pytest.raises(ProviderError, match="transport"):
            OllamaProvider("llama3.1:70b").chat([Message(role="user", content="hi")])

    def test_chat_malformed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(httpx, "post", _fake_post_factory(200, {"oops": True}))
        with pytest.raises(ProviderError, match="malformed"):
            OllamaProvider("llama3.1:70b").chat([Message(role="user", content="hi")])

    def test_http_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(httpx, "post", _fake_post_factory(503, None, text="busy"))
        with pytest.raises(ProviderError, match="503"):
            OllamaProvider("llama3.1:70b").chat([Message(role="user", content="hi")])


# ---------------------------------------------------------------------------
# LM Studio / vLLM / llama.cpp — all OpenAI-compat
# ---------------------------------------------------------------------------


class TestOpenAICompat:
    def test_lmstudio_chat(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(httpx, "post", _fake_post_factory(200, {"choices": [{"message": {"content": "lm"}}]}))
        assert LMStudioProvider("local-model").chat([Message(role="user", content="hi")]) == "lm"

    def test_vllm_chat(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(httpx, "post", _fake_post_factory(200, {"choices": [{"message": {"content": "v"}}]}))
        assert (
            VLLMProvider("local-model", base_url="http://example/v1").chat([Message(role="user", content="hi")]) == "v"
        )

    def test_llamacpp_chat(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(httpx, "post", _fake_post_factory(200, {"choices": [{"message": {"content": "lc"}}]}))
        assert (
            LlamaCppProvider("local-model", base_url="http://example/v1").chat([Message(role="user", content="hi")])
            == "lc"
        )
