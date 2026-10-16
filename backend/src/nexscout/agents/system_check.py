"""`system_check`: a harmless diagnostic workflow users can run to confirm the runtime works.

It exercises every runtime feature without touching profile data: tenant-scoped DB access,
progress notes, an optional (skippable) waiting step, an optional approval gate, and a
side effect that goes through the idempotency ledger.
"""

from __future__ import annotations

import asyncio
import operator
from pathlib import Path
from typing import Annotated, Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from sqlalchemy import select

from nexscout.agent_runtime.context import RunContext
from nexscout.agent_runtime.registry import WorkflowSpec, register, tracked
from nexscout.infrastructure.db.models import CandidateCase

MAX_WAIT_S = 120


class State(TypedDict, total=False):
    log: Annotated[list[str], operator.add]
    approved: bool
    result: dict[str, Any]


async def prepare(state: State, runtime: Runtime[RunContext]) -> dict[str, Any]:
    ctx = runtime.context
    async with ctx.tenant() as s:
        name = await s.scalar(select(CandidateCase.name).where(CandidateCase.id == ctx.case_id))
    await ctx.note(ctx.extras.get("current_step"), f"Database access OK for case “{name}”.")
    return {"log": ["prepare"]}


async def wait(state: State, runtime: Runtime[RunContext]) -> dict[str, Any]:
    ctx = runtime.context
    seconds = min(float(ctx.params.get("wait_s", 0) or 0), MAX_WAIT_S)
    elapsed = 0.0
    while elapsed < seconds:  # cancellable in small increments
        await asyncio.sleep(min(0.25, seconds - elapsed))
        elapsed += 0.25
    await ctx.note(ctx.extras.get("current_step"), f"Waited {seconds:g} s.")
    return {"log": ["wait"]}


async def approve(state: State, runtime: Runtime[RunContext]) -> dict[str, Any]:
    ctx = runtime.context
    if not ctx.params.get("require_approval"):
        return {"log": ["approve:skipped"], "approved": True}
    ok = await ctx.require_approval(
        node="approve",
        action_kind="system_check.confirm",
        title="Confirm the system check",
        summary="This test asks for your approval before its final step. Nothing is sent "
        "anywhere and no data changes.",
    )
    return {"log": [f"approve:{'yes' if ok else 'no'}"], "approved": ok}


async def effect(state: State, runtime: Runtime[RunContext]) -> dict[str, Any]:
    ctx = runtime.context
    if not state.get("approved", True):
        return {"log": ["effect:skipped (not approved)"]}
    marker = ctx.params.get("marker_file") if ctx.settings.env == "test" else None

    def append_marker(path: str) -> None:
        with Path(path).open("a", encoding="utf-8") as fh:
            fh.write(f"{ctx.run_id}\n")

    async def call() -> dict[str, Any]:
        if marker:  # test-only countable side effect, to prove at-most-once execution
            await asyncio.to_thread(append_marker, str(marker))
        return {"ok": True}

    out = await ctx.side_effect(
        tool="system_check.marker", key="final", request={"run": "x"}, call=call
    )
    return {"log": [f"effect:{out.get('ok')}"]}


async def finish(state: State, runtime: Runtime[RunContext]) -> dict[str, Any]:
    return {
        "log": ["finish"],
        "result": {
            "steps": [*state.get("log", []), "finish"],
            "approved": state.get("approved", True),
        },
    }


def build() -> StateGraph[State, RunContext, Any, Any]:
    g: StateGraph[State, RunContext, Any, Any] = StateGraph(State, context_schema=RunContext)
    for name, fn in (
        ("prepare", prepare),
        ("wait", wait),
        ("approve", approve),
        ("effect", effect),
        ("finish", finish),
    ):
        g.add_node(name, cast(Any, tracked(name, fn)))
    g.add_edge(START, "prepare")
    g.add_edge("prepare", "wait")
    g.add_edge("wait", "approve")
    g.add_edge("approve", "effect")
    g.add_edge("effect", "finish")
    g.add_edge("finish", END)
    return g


SPEC = register(
    WorkflowSpec(
        kind="system_check",
        title="System check",
        description="Confirms that background work, pausing, approvals, and recovery work.",
        build=build,
        optional_nodes=frozenset({"wait"}),
        initial_state=lambda params: {"log": []},
    )
)
