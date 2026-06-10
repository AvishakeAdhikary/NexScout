"""Generic OpenAI-compatible provider (any ``/v1/chat/completions`` endpoint).

Many vendors and self-hosted runtimes expose the OpenAI chat-completions API
verbatim (NVIDIA NIM, OpenRouter, Together, Fireworks, Groq, DeepInfra,
LiteLLM proxies, ...). This provider lets a user point NexScout at any such
endpoint with just a ``base_url`` + ``model`` + ``api_key``, reusing the
:class:`OpenAIProvider` request/response machinery.

The endpoint is normally supplied via the profile's ``llm.providers`` block
(see :class:`nexscout.core.profile.LLMProviderEndpoint`); when that is absent
the router falls back to the ``OPENAI_COMPAT_BASE_URL`` / ``OPENAI_COMPAT_API_KEY``
environment variables.
"""

from __future__ import annotations

import os

from ...core.errors import ProviderError
from .openai import OpenAIProvider


class OpenAICompatProvider(OpenAIProvider):
    """Any OpenAI-compatible endpoint configured by base_url + model + api_key."""

    name = "openai_compat"

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        url = base_url or os.environ.get("OPENAI_COMPAT_BASE_URL")
        if not url:
            raise ProviderError(
                "openai_compat base_url not set (set providers.openai_compat.base_url or OPENAI_COMPAT_BASE_URL)"
            )
        super().__init__(
            model=model,
            api_key=api_key or os.environ.get("OPENAI_COMPAT_API_KEY", ""),
            base_url=url,
            timeout=timeout,
            extra_headers=extra_headers,
        )
