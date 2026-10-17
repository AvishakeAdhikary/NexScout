"""`autopilot_cycle`: one scheduled autopilot pass for a case (M12, ADR-0014).

discover → shortlist → report
- discover: search the enabled sources (same use case as "Search"), if the policy allows it.
- shortlist: the deterministic policy (domain/policy.py) picks positions and records why every
  other one was left out. Each pick becomes an autopilot item that the worker's reconciler
  then moves through research, documents, application and submission.
- report: tells the user what was picked (on their channels), with the reasons.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from nexscout.agent_runtime.context import RunContext
from nexscout.agent_runtime.registry import WorkflowSpec, register, tracked
from nexscout.application.actor import Actor
from nexscout.application.autopilot import get_policy, shortlist_case, to_policy
from nexscout.application.notifications import notify
from nexscout.application.opportunities import sync_case
from nexscout.infrastructure.db.engine import bind_tenant


class State(TypedDict, total=False):
    found: int
    picked: list[dict[str, Any]]
    result: dict[str, Any]


def _actor(ctx: RunContext) -> Actor:
    return Actor(user_id=ctx.owner_user_id, session_id=ctx.run_id, request_id="autopilot")


async def discover(state: State, runtime: Runtime[RunContext]) -> dict[str, Any]:
    ctx = runtime.context
    step = ctx.extras.get("current_step")
    async with ctx.app_sessions() as s:
        await bind_tenant(s, ctx.owner_user_id)
        policy = to_policy(await get_policy(s, _actor(ctx), ctx.case_id))
        if not policy.enabled:
            return {"result": {"status": "off", "message": "Autopilot is off."}}
        if not policy.step("discover"):
            await ctx.note(step, "Searching is off in your settings; using positions you have.")
            return {"found": 0}
        summaries = await sync_case(s, _actor(ctx), ctx.case_id)
        await s.commit()
    found = sum(x.new_for_case for x in summaries)
    await ctx.note(step, f"Searched {len(summaries)} source(s): {found} new position(s).")
    return {"found": found}


async def shortlist(state: State, runtime: Runtime[RunContext]) -> dict[str, Any]:
    ctx = runtime.context
    step = ctx.extras.get("current_step")
    async with ctx.app_sessions() as s:
        await bind_tenant(s, ctx.owner_user_id)
        considered = await shortlist_case(s, _actor(ctx), ctx.case_id)
        await s.commit()
    picked = [asdict(c) for c in considered if c.taken]
    await ctx.note(
        step,
        f"Considered {len(considered)} position(s); picked {len(picked)}."
        + "".join(f"\n• {c.title} ({c.organization}): {c.reasons[0]}" for c in considered[:10]),
    )
    return {
        "picked": picked,
        "result": {
            "status": "ok",
            "found": state.get("found", 0),
            "picked": len(picked),
            "considered": [asdict(c) for c in considered[:50]],
        },
    }


async def report(state: State, runtime: Runtime[RunContext]) -> dict[str, Any]:
    ctx = runtime.context
    picked = state.get("picked") or []
    if picked:
        async with ctx.tenant() as s:
            await notify(
                s,
                owner=ctx.owner_user_id,
                case_id=ctx.case_id,
                kind="autopilot",
                title=f"Autopilot picked {len(picked)} position(s)",
                body="; ".join(
                    f"{p['title']} ({p['organization']}, fit {p['fit']})" for p in picked
                )[:1000],
                link=f"/cases/{ctx.case_id}/autopilot",
                key=f"autopilot-cycle:{ctx.run_id}",
            )
    return {}


def _route(state: State) -> str:
    return END if (state.get("result") or {}).get("status") == "off" else "shortlist"


def build() -> StateGraph[State, RunContext, Any, Any]:
    g: StateGraph[State, RunContext, Any, Any] = StateGraph(State, context_schema=RunContext)
    for name, fn in (("discover", discover), ("shortlist", shortlist), ("report", report)):
        g.add_node(name, cast(Any, tracked(name, fn)))
    g.add_edge(START, "discover")
    g.add_conditional_edges("discover", _route, {"shortlist": "shortlist", END: END})
    g.add_edge("shortlist", "report")
    g.add_edge("report", END)
    return g


SPEC = register(
    WorkflowSpec(
        kind="autopilot_cycle",
        title="Autopilot",
        description="Searches, picks positions within your autopilot settings, and starts work.",
        build=build,
        user_startable=False,
    )
)
