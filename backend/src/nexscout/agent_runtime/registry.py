"""Workflow registry: each workflow is a LangGraph graph plus metadata the runtime enforces."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langgraph.errors import GraphBubbleUp
from langgraph.graph import StateGraph
from langgraph.runtime import Runtime

from nexscout.agent_runtime.context import RunContext

NodeFn = Callable[[Any, Runtime[RunContext]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class WorkflowSpec:
    kind: str
    title: str
    description: str
    build: Callable[[], StateGraph[Any, RunContext, Any, Any]]
    optional_nodes: frozenset[str] = frozenset()
    user_startable: bool = True
    initial_state: Callable[[dict[str, Any]], dict[str, Any]] = field(default=lambda p: {})


def tracked(node: str, fn: NodeFn) -> NodeFn:
    """Wrap a node so every execution attempt is recorded as a user-visible step."""

    async def wrapper(state: Any, runtime: Runtime[RunContext]) -> dict[str, Any]:
        ctx = runtime.context
        step_id = await ctx.step_started(node)
        ctx.extras["current_step"] = step_id
        try:
            update = await fn(state, runtime)
        except GraphBubbleUp:  # approval interrupt or drain: not a failure
            await asyncio.shield(ctx.step_finished(step_id, node, "interrupted"))
            raise
        except asyncio.CancelledError:
            await asyncio.shield(ctx.step_finished(step_id, node, "cancelled"))
            raise
        except Exception as exc:
            await ctx.step_finished(step_id, node, "failed", error=_safe_error(exc))
            raise
        await ctx.step_finished(
            step_id, node, "succeeded", summary={"updated": sorted((update or {}).keys())}
        )
        return update

    wrapper.__name__ = node
    return wrapper


def _safe_error(exc: BaseException) -> str:
    """User-facing error text. Never includes secrets or stack traces."""
    return f"{type(exc).__name__}: {exc}"[:500]


_REGISTRY: dict[str, WorkflowSpec] = {}


def register(spec: WorkflowSpec) -> WorkflowSpec:
    _REGISTRY[spec.kind] = spec
    return spec


def get_workflow(kind: str) -> WorkflowSpec | None:
    _load_builtin()
    return _REGISTRY.get(kind)


def workflows() -> dict[str, WorkflowSpec]:
    _load_builtin()
    return dict(_REGISTRY)


def _load_builtin() -> None:
    # Import for registration side effects (kept lazy to avoid import cycles).
    from nexscout.agents import profile_summary, system_check  # noqa: F401
