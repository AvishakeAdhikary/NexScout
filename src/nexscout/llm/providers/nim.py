"""NVIDIA NIM provider (OpenAI-compatible).

NVIDIA's hosted catalog at ``https://integrate.api.nvidia.com/v1`` and
self-hosted NIM microservices both speak the OpenAI chat-completions protocol,
so this is a thin :class:`OpenAIProvider` subclass with NIM-friendly defaults.

* Default ``base_url``: ``https://integrate.api.nvidia.com/v1`` (override via
  the profile ``llm.providers.nim.base_url`` or the ``NIM_BASE_URL`` env var for
  a self-hosted deployment).
* ``api_key``: a Bearer token from ``NVIDIA_API_KEY`` unless one is passed
  explicitly (from the profile providers config).

Example model ids: ``meta/llama-3.1-70b-instruct``, ``nvidia/nemotron-4-340b-instruct``.
"""

from __future__ import annotations

import os

from ...core.errors import ProviderError
from .openai import OpenAIProvider

DEFAULT_NIM_BASE = "https://integrate.api.nvidia.com/v1"


class NIMProvider(OpenAIProvider):
    """NVIDIA NIM — OpenAI-compatible, defaults to the hosted NVIDIA endpoint."""

    name = "nim"

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        key = api_key or os.environ.get("NVIDIA_API_KEY", "")
        if not key:
            raise ProviderError("NVIDIA_API_KEY not set (configure llm.providers.nim.api_key or NVIDIA_API_KEY)")
        super().__init__(
            model=model,
            api_key=key,
            base_url=base_url or os.environ.get("NIM_BASE_URL") or DEFAULT_NIM_BASE,
            timeout=timeout,
            extra_headers=extra_headers,
        )
