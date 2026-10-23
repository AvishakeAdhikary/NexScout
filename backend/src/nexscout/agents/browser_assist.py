"""`browser_assist`: hand a blocked application to the person, in a visible browser (M12).

Used when a site shows a CAPTCHA or a sign-in, which NexScout never solves or bypasses. A
browser window opens on the user's own computer with the form filled from what NexScout knows;
the person solves the challenge, checks everything, ticks any declarations and submits. NexScout
only watches for the site's confirmation, and records it as the person's own submission.
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from nexscout.agent_runtime.context import RunContext
from nexscout.agent_runtime.registry import WorkflowSpec, register, tracked
from nexscout.agents.browser_apply import (
    Inputs,
    _app_id,
    _applicant,
    _guard,
    _prepare_documents,
)
from nexscout.application.answers import answers_for
from nexscout.application.applications import event, move
from nexscout.domain.state_machines import ApplicationStatus
from nexscout.infrastructure.browser import assist_form
from nexscout.infrastructure.db.models import Application

S = ApplicationStatus
ASSIST_FROM = frozenset({S.NEEDS_USER_ACTION, S.PREPARING, S.FAILED})


class State(TypedDict, total=False):
    result: dict[str, Any]


async def assist(state: State, runtime: Runtime[RunContext]) -> dict[str, Any]:
    ctx = runtime.context
    step = ctx.extras.get("current_step")
    async with ctx.tenant() as s:
        app = await s.get(Application, _app_id(ctx))
        if app is None:
            raise LookupError("The application was deleted.")
        if S(app.status) not in ASSIST_FROM:
            return {"result": {"status": "skipped", "message": f"Application is {app.status}."}}
        url = str(app.apply_url)
        snapshot = Inputs.of(app, await answers_for(s, app.owner_user_id, app.case_id))
    # You are at the keyboard here, so unfinished documents don't stop the window opening; they
    # just aren't uploaded for you.
    for problem in await _prepare_documents(ctx, step, snapshot.document_ids):
        await ctx.note(step, f"Not uploaded: {problem}.")
    await ctx.note(step, "A browser window is open on your computer. Finish and submit there.")
    workdir = Path(tempfile.mkdtemp(prefix="nexscout-assist-"))
    try:
        who = await _applicant(ctx, snapshot, workdir)
        out = await assist_form(
            url,
            who,
            _guard(ctx),
            headless=ctx.settings.assist_headless,
            timeout_s=ctx.settings.assist_timeout_s,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    key = ctx.store.put(ctx.owner_user_id, out.screenshot)[0] if out.screenshot else None
    async with ctx.tenant() as s:
        app = await s.get(Application, _app_id(ctx), with_for_update=True)
        assert app is not None
        if out.status == "confirmed" and S(app.status) in ASSIST_FROM:
            payload = {
                "final_url": out.final_url,
                "reference": out.reference,
                "excerpt": out.excerpt,
                "screenshot_key": key,
            }
            app.submitted_at = datetime.now(UTC)
            app.evidence = {"source": "observed", "assisted": True, **payload}
            app.blocker = None
            event(
                s,
                app,
                "submitted",
                actor="user",
                run_id=ctx.run_id,
                payload=payload,
                message="You submitted in the assisted browser; the site confirmed it "
                f"(reference {out.reference or 'not shown'}).",
            )
            move(s, app, S.SUBMITTED, actor="user", run_id=ctx.run_id)
            await ctx.note(step, "Submitted by you. The site confirmed it.")
            return {"result": {"status": "submitted", "reference": out.reference}}
        message = {
            "timeout": "The assisted window timed out before the site confirmed a submission.",
            "closed": "The assisted window was closed before the site confirmed a submission.",
        }.get(out.status, f"The assisted window stopped: {out.error or out.status}.")
        event(
            s,
            app,
            "assist_ended",
            actor="agent",
            run_id=ctx.run_id,
            message=message,
            payload={"status": out.status},
        )
    await ctx.note(step, message)
    return {"result": {"status": out.status, "message": message}}


def build() -> StateGraph[State, RunContext, Any, Any]:
    g: StateGraph[State, RunContext, Any, Any] = StateGraph(State, context_schema=RunContext)
    g.add_node("assist", cast(Any, tracked("assist", assist)))
    g.add_edge(START, "assist")
    g.add_edge("assist", END)
    return g


SPEC = register(
    WorkflowSpec(
        kind="browser_assist",
        title="Finish an application yourself (assisted)",
        description="Opens the form in a browser window on your computer; you submit it.",
        build=build,
        user_startable=False,
    )
)
