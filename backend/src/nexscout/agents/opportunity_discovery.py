"""`opportunity_discovery`: sync enabled sources for a case, dedup into the shared catalog, and
score every match. Listings are committed one at a time (resumable, idempotent)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from nexscout.agent_runtime.context import RunContext
from nexscout.agent_runtime.registry import WorkflowSpec, register, tracked
from nexscout.application.actor import Actor
from nexscout.application.opportunities import sync_case
from nexscout.infrastructure.db.engine import bind_tenant


class State(TypedDict, total=False):
    result: dict[str, Any]


async def sync(state: State, runtime: Runtime[RunContext]) -> dict[str, Any]:
    ctx = runtime.context
    actor = Actor(user_id=ctx.owner_user_id, session_id=ctx.run_id)
    sources = ctx.params.get("sources") or None
    async with ctx.app_sessions() as session:
        await bind_tenant(session, ctx.owner_user_id)
        summaries = await sync_case(session, actor, ctx.case_id, source_keys=sources)
        await session.commit()
    for s in summaries:
        msg = s.skipped_reason or (
            f"{s.source_key}: checked {s.fetched}, {s.new_for_case} new for you"
        )
        await ctx.note(ctx.extras.get("current_step"), msg)
    return {
        "result": {
            "sources": [asdict(s) for s in summaries],
            "new_for_case": sum(s.new_for_case for s in summaries),
        }
    }


def build() -> StateGraph[State, RunContext, Any, Any]:
    g: StateGraph[State, RunContext, Any, Any] = StateGraph(State, context_schema=RunContext)
    g.add_node("sync", cast(Any, tracked("sync", sync)))
    g.add_edge(START, "sync")
    g.add_edge("sync", END)
    return g


SPEC = register(
    WorkflowSpec(
        kind="opportunity_discovery",
        title="Find opportunities",
        description="Searches your enabled sources, merges duplicates, and explains each match.",
        build=build,
    )
)
