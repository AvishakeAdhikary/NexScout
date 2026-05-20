"""Apply agent backend selection.

Three options:

* ``native`` — :mod:`nexscout.apply.agent` ReAct loop driven by the LLM router.
* ``claude_code`` — shells out to the local ``claude`` CLI (Claude Code).
* ``openai_assistant`` — uses the OpenAI Assistants API.

The default is ``native``; the others raise :class:`ConfigError` when the
prerequisite is missing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..core.errors import ConfigError

#: Each backend resolves to a ``(job, profile, …) -> (code, reason, cost, captcha_solved)``
#: callable that mirrors :func:`apply.agent.run_agent`.
Runner = Callable[..., tuple[str, str | None, float, bool]]


def get_backend(name: str) -> Runner:
    """Return the runner callable for ``name``."""
    name = (name or "native").strip().lower()
    if name == "native":
        from .native import run as native_run

        return native_run
    if name == "claude_code":
        from .claude_code import run as cc_run

        return cc_run
    if name == "openai_assistant":
        from .openai_assistant import run as oa_run

        return oa_run
    raise ConfigError(f"unknown apply backend: {name!r}")


def known_backends() -> tuple[str, ...]:
    return ("native", "claude_code", "openai_assistant")


__all__: list[str] = ["Runner", "get_backend", "known_backends"]

# Suppress unused-Any complaint when the module is imported by ``Runner`` consumers.
_ = Any
