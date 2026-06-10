"""Unit tests for the OpenAI-compatible + NVIDIA NIM providers and their
router resolution (``openai_compat:`` / ``nim:`` schemes)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from nexscout.core.errors import ProviderError
from nexscout.core.profile import LLMProviderEndpoint
from nexscout.llm.providers.base import Message
from nexscout.llm.providers.nim import DEFAULT_NIM_BASE, NIMProvider
from nexscout.llm.providers.openai_compat import OpenAICompatProvider
from nexscout.llm.router import _build_provider


class _Capture:
    """Records the last httpx.post call so we can assert URL/headers/body."""

    def __init__(self, content: str = "hi") -> None:
        self.content = content
        self.url: str | None = None
        self.headers: dict[str, str] | None = None
        self.body: dict[str, Any] | None = None

    def __call__(self, url: str, *, json: dict[str, Any], headers: dict[str, str], timeout: float) -> Any:
        self.url = url
        self.headers = headers
        self.body = json
        return httpx.Response(200, json={"choices": [{"message": {"content": self.content}}]})


# --------------------------------------------------------------------------
# openai_compat provider
# --------------------------------------------------------------------------


def test_openai_compat_explicit_config(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _Capture("compat-ok")
    monkeypatch.setattr(httpx, "post", cap)
    prov = OpenAICompatProvider(
        model="my-model",
        api_key="sk-compat",
        base_url="https://my-endpoint/v1",
        extra_headers={"X-Route": "fast"},
    )
    out = prov.chat([Message(role="user", content="hello")])
    assert out == "compat-ok"
    assert cap.url == "https://my-endpoint/v1/chat/completions"
    assert cap.headers is not None
    assert cap.headers["Authorization"] == "Bearer sk-compat"
    assert cap.headers["X-Route"] == "fast"
    assert cap.body is not None
    assert cap.body["model"] == "my-model"


def test_openai_compat_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_COMPAT_BASE_URL", "https://env-endpoint/v1")
    monkeypatch.setenv("OPENAI_COMPAT_API_KEY", "sk-env")
    prov = OpenAICompatProvider(model="m")
    assert prov.base_url == "https://env-endpoint/v1"
    assert prov.api_key == "sk-env"


def test_openai_compat_missing_base_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_COMPAT_BASE_URL", raising=False)
    with pytest.raises(ProviderError, match="base_url not set"):
        OpenAICompatProvider(model="m", api_key="x")


# --------------------------------------------------------------------------
# NIM provider
# --------------------------------------------------------------------------


def test_nim_defaults_to_nvidia_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NIM_BASE_URL", raising=False)
    prov = NIMProvider(model="meta/llama-3.1-70b-instruct", api_key="nvapi-x")
    assert prov.base_url == DEFAULT_NIM_BASE
    assert prov.api_key == "nvapi-x"


def test_nim_self_hosted_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIM_BASE_URL", "http://my-nim:8000/v1")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-env")
    prov = NIMProvider(model="meta/llama-3.1-8b-instruct")
    assert prov.base_url == "http://my-nim:8000/v1"
    assert prov.api_key == "nvapi-env"


def test_nim_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="NVIDIA_API_KEY not set"):
        NIMProvider(model="meta/llama-3.1-70b-instruct")


def test_nim_sends_bearer_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _Capture("nim-ok")
    monkeypatch.setattr(httpx, "post", cap)
    prov = NIMProvider(model="meta/llama-3.1-70b-instruct", api_key="nvapi-key")
    out = prov.chat([Message(role="user", content="hi")])
    assert out == "nim-ok"
    assert cap.url == f"{DEFAULT_NIM_BASE}/chat/completions"
    assert cap.headers is not None
    assert cap.headers["Authorization"] == "Bearer nvapi-key"
    assert cap.body is not None
    assert cap.body["model"] == "meta/llama-3.1-70b-instruct"


# --------------------------------------------------------------------------
# router resolution
# --------------------------------------------------------------------------


def test_router_builds_nim_from_providers_config() -> None:
    providers = {
        "nim": LLMProviderEndpoint(base_url="https://integrate.api.nvidia.com/v1", api_key="nvapi-cfg"),
    }
    prov = _build_provider("nim:meta/llama-3.1-70b-instruct", providers)
    assert isinstance(prov, NIMProvider)
    assert prov.model == "meta/llama-3.1-70b-instruct"
    assert prov.base_url == "https://integrate.api.nvidia.com/v1"
    assert prov.api_key == "nvapi-cfg"


def test_router_builds_openai_compat_from_providers_config() -> None:
    providers = {
        "openai_compat": LLMProviderEndpoint(
            base_url="https://my-endpoint/v1",
            api_key="sk-cfg",
            extra_headers={"X-Tag": "1"},
        ),
    }
    prov = _build_provider("openai_compat:vendor/model-x", providers)
    assert isinstance(prov, OpenAICompatProvider)
    assert prov.model == "vendor/model-x"
    assert prov.base_url == "https://my-endpoint/v1"
    assert prov.api_key == "sk-cfg"
    assert prov.extra_headers == {"X-Tag": "1"}


def test_router_nim_env_fallback_when_no_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-env")
    monkeypatch.delenv("NIM_BASE_URL", raising=False)
    prov = _build_provider("nim:meta/llama-3.1-70b-instruct")  # no providers arg
    assert isinstance(prov, NIMProvider)
    assert prov.api_key == "nvapi-env"
    assert prov.base_url == DEFAULT_NIM_BASE


def test_router_openai_compat_env_fallback_when_no_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_COMPAT_BASE_URL", "https://env-endpoint/v1")
    monkeypatch.setenv("OPENAI_COMPAT_API_KEY", "sk-env")
    prov = _build_provider("openai_compat:vendor/model")
    assert isinstance(prov, OpenAICompatProvider)
    assert prov.base_url == "https://env-endpoint/v1"
    assert prov.api_key == "sk-env"


def test_router_uses_providers_default_model_for_bare_spec() -> None:
    providers = {
        "nim": LLMProviderEndpoint(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key="nvapi-cfg",
            model="meta/llama-3.1-8b-instruct",
        ),
    }
    prov = _build_provider("nim:", providers)
    assert isinstance(prov, NIMProvider)
    assert prov.model == "meta/llama-3.1-8b-instruct"


def test_router_bare_spec_without_model_raises() -> None:
    providers = {"nim": LLMProviderEndpoint(base_url="https://x/v1", api_key="k")}
    with pytest.raises(ProviderError, match="no model id"):
        _build_provider("nim:", providers)
