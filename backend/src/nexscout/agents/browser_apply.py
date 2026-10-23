"""`browser_apply`: fill an application form, ask the user, then submit at most once.

fill → (blocked / missing → needs_user_action) | approve → submit
- fill: open the page, plan from the user's account, answers and chosen documents, fill without
  submitting, screenshot. CAPTCHA or login → stop: NexScout never bypasses them.
- approve: the user sees every field, file and declaration plus a screenshot. Rejecting goes
  back to preparing.
- submit: application APPROVED → SUBMITTING is committed *before* the click. The page is filled
  again and must produce exactly the approved plan, or nothing is submitted. Declarations are
  ticked only now. `submitted` needs an observed confirmation; otherwise `submission_uncertain`
  until the user confirms. A crash during submit (status still SUBMITTING) is never retried.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from sqlalchemy import func, select

from nexscout.agent_runtime.context import RunContext, UncertainOutcome
from nexscout.agent_runtime.registry import WorkflowSpec, register, tracked
from nexscout.agents.draft_document import render_version
from nexscout.application.actor import Actor
from nexscout.application.answers import answers_for
from nexscout.application.applications import (
    BROWSER_START,
    CV_TYPES,
    LETTER_TYPES,
    event,
    fixture_origin,
    move,
)
from nexscout.application.contact import applicant_details, fill_document
from nexscout.application.notifications import notify
from nexscout.domain.forms import Applicant, normalize_question
from nexscout.domain.state_machines import ApplicationStatus
from nexscout.infrastructure.browser import FillOutcome, Guard, fill_form, submit_form
from nexscout.infrastructure.db.models import (
    Application,
    ApplicationEvent,
    AutopilotPolicy,
    GeneratedDocument,
    GeneratedDocumentVersion,
)

S = ApplicationStatus


class State(TypedDict, total=False):
    digest: str
    url: str
    result: dict[str, Any]


def _app_id(ctx: RunContext) -> uuid.UUID:
    return uuid.UUID(str(ctx.params["application_id"]))


def _guard(ctx: RunContext) -> Guard:
    origin = fixture_origin(ctx.settings)
    return Guard(frozenset({origin.lower()}) if origin else frozenset())


@dataclass(frozen=True)
class Inputs:
    """What the applicant data is built from (read inside a transaction, used outside)."""

    document_ids: list[str]
    answers: dict[str, str]
    phone: str | None

    @classmethod
    def of(cls, app: Application, bank: dict[str, str] | None = None) -> Inputs:
        # The case answer bank first; answers given on this application win.
        return cls(list(app.document_ids), {**(bank or {}), **(app.answers or {})}, app.phone)


async def _applicant(ctx: RunContext, app: Inputs, workdir: Path) -> Applicant:
    """Who is applying: the case's contact details (else the account's name and email), profile
    links, the user's answers and their chosen documents."""
    async with ctx.tenant() as s:
        who = await applicant_details(s, ctx.owner_user_id, ctx.case_id)
        rows = (
            await s.execute(
                select(GeneratedDocument, GeneratedDocumentVersion)
                .join(
                    GeneratedDocumentVersion,
                    (GeneratedDocumentVersion.document_id == GeneratedDocument.id)
                    & (GeneratedDocumentVersion.number == GeneratedDocument.current_version),
                )
                .where(GeneratedDocument.id.in_([uuid.UUID(x) for x in app.document_ids]))
            )
        ).all()
    files: dict[str, dict[str, str]] = {}
    for doc, version in rows:
        role = (
            "cv"
            if doc.doc_type in CV_TYPES
            else "cover_letter"
            if doc.doc_type in LETTER_TYPES
            else None
        )
        pdf = (version.artifacts or {}).get("pdf")
        if role is None or role in files or not pdf:
            continue
        path = workdir / f"{role}.pdf"
        path.write_bytes(ctx.store.get(pdf["key"]))
        files[role] = {"path": str(path), "title": f"{doc.title} (v{version.number}, PDF)"}
    c = who.contact
    return Applicant(
        full_name=who.name,
        email=who.email,
        phone=app.phone or c.phone,
        answers=dict(app.answers or {}),
        files=files,
        given_name=c.given_name,
        family_name=c.family_name,
        address=c.address,
        postal_code=c.postal_code,
        city=c.city,
        region=c.region,
        country=c.country,
        location=c.location,
        links=who.links,
    )


async def _prepare_documents(ctx: RunContext, step: Any, document_ids: list[str]) -> list[str]:
    """Make the chosen documents ready before the form is opened: fill in what the user
    already told NexScout (contact details, saved answers) and create the PDF of any version
    that has none. Returns what still needs the user (placeholders nobody has answered)."""
    actor = Actor(user_id=ctx.owner_user_id, session_id=ctx.run_id, request_id="browser_apply")
    problems: list[str] = []
    to_render: list[tuple[uuid.UUID, int, str]] = []
    async with ctx.tenant() as s:
        for raw in document_ids:
            doc = await s.get(GeneratedDocument, uuid.UUID(raw))
            if doc is None:
                continue
            version = await s.scalar(
                select(GeneratedDocumentVersion).where(
                    GeneratedDocumentVersion.document_id == doc.id,
                    GeneratedDocumentVersion.number == doc.current_version,
                )
            )
            if version is None:
                continue
            if version.placeholders:
                version = (await fill_document(s, actor, doc.id))[0].current
            if version.placeholders:
                problems.append(f"“{doc.title}” still needs {'; '.join(version.placeholders)}")
            elif not (version.artifacts or {}).get("pdf"):
                to_render.append((doc.id, version.number, doc.title))
    for doc_id, number, title in to_render:
        await ctx.note(step, f"Creating the PDF of “{title}”.")
        artifacts = await render_version(ctx, doc_id, number)
        compliance = artifacts.get("compliance") or {}
        if compliance.get("status") == "blocking":  # the same rule as before starting a run
            failed = [
                c["rule"]
                for c in compliance.get("checks", [])
                if not c["ok"] and c["severity"] == "blocking"
            ]
            problems.append(
                f"“{title}” doesn't meet the posting's requirements: {'; '.join(failed)}"
            )
    return problems


async def fill(state: State, runtime: Runtime[RunContext]) -> dict[str, Any]:
    ctx = runtime.context
    step = ctx.extras.get("current_step")
    async with ctx.tenant() as s:
        app = await s.get(Application, _app_id(ctx), with_for_update=True)
        if app is None:
            raise LookupError("The application was deleted.")
        if S(app.status) not in BROWSER_START:
            return {"result": {"status": "skipped", "message": f"Application is {app.status}."}}
        if app.status == S.APPROVED:
            move(s, app, S.AWAITING_REVIEW, actor="agent", run_id=ctx.run_id)
        if app.status != S.PREPARING:
            move(
                s,
                app,
                S.PREPARING,
                actor="agent",
                run_id=ctx.run_id,
                message="Filling in the form again.",
            )
        url = str(app.apply_url)
        snapshot = Inputs.of(app, await answers_for(s, app.owner_user_id, app.case_id))
    problems = await _prepare_documents(ctx, step, snapshot.document_ids)
    if problems:
        out = FillOutcome(status="documents", url=url, error="; ".join(problems))
    else:
        await ctx.note(step, f"Opening {url}")
        workdir = Path(tempfile.mkdtemp(prefix="nexscout-apply-"))
        try:
            who = await _applicant(ctx, snapshot, workdir)
            out = await fill_form(url, who, _guard(ctx), headless=ctx.settings.browser_headless)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    shot_key = ctx.store.put(ctx.owner_user_id, out.screenshot)[0] if out.screenshot else None
    async with ctx.tenant() as s:
        app = await s.get(Application, _app_id(ctx), with_for_update=True)
        assert app is not None
        payload: dict[str, Any] = {"url": out.url, "screenshot_key": shot_key}
        if out.status == "filled" and out.plan is not None:
            payload.update(
                fields=out.plan.summary(),
                digest=out.plan.digest(),
                declarations=out.plan.attestations,
            )
            event(
                s,
                app,
                "form_filled",
                actor="agent",
                run_id=ctx.run_id,
                message="Form filled in. Nothing was submitted.",
                payload=payload,
            )
            app.blocker = None
            move(s, app, S.AWAITING_REVIEW, actor="agent", run_id=ctx.run_id)
            await ctx.note(
                step,
                f"Filled {sum(f.action != 'skip' for f in out.plan.fields)} "
                "field(s). Waiting for your approval to submit.",
            )
            return {"digest": out.plan.digest(), "url": out.url}
        if out.status == "blocked":
            reason = (
                "This site shows a CAPTCHA. NexScout doesn't solve CAPTCHAs: open the page, "
                "apply yourself, then mark the application as submitted."
                if out.blocker == "captcha"
                else "This site asks you to sign in. NexScout never signs in for you: open the "
                "page, apply yourself, then mark the application as submitted."
            )
        elif out.status == "missing" and out.plan is not None:
            payload["missing"] = out.plan.missing
            reason = (
                "The form asks for things NexScout has no answer for: "
                + "; ".join(out.plan.missing)
                + ". Add your answers, then try again."
            )
        elif out.status == "documents":
            reason = (
                f"Your documents aren't ready: {out.error}. Fill that in on the document's "
                "page (or save it as an answer), then try again."
            )
        else:
            reason = f"Couldn't open or fill the form: {out.error}"
        app.blocker = reason[:500]
        event(
            s,
            app,
            "needs_user_action",
            actor="agent",
            run_id=ctx.run_id,
            message=reason,
            payload=payload,
        )
        target = S.FAILED if out.status == "error" else S.NEEDS_USER_ACTION
        move(s, app, target, actor="agent", run_id=ctx.run_id, message=reason)
        # Ask once per question, on the user's own channels. NexScout never guesses; the answer
        # is stored and reused (domain/forms.plan_form reads `answers`).
        for question in out.plan.missing if out.status == "missing" and out.plan else []:
            await notify(
                s,
                owner=app.owner_user_id,
                case_id=app.case_id,
                kind="question",
                title=f"{app.organization} asks: {question}",
                body=f"NexScout has no answer for this on “{app.title}”. Your reply is saved "
                "and reused; nothing is guessed.",
                link=f"/cases/{app.case_id}/applications/{app.id}",
                key=f"question:{app.id}:{normalize_question(question)}",
                data={"application_id": str(app.id), "question": question},
            )
        if out.status == "blocked":
            await notify(
                s,
                owner=app.owner_user_id,
                case_id=app.case_id,
                kind="application",
                title=f"{app.organization} needs you: "
                + ("a CAPTCHA" if out.blocker == "captcha" else "a sign-in"),
                body=reason,
                link=f"/cases/{app.case_id}/applications/{app.id}",
                key=f"blocked:{app.id}:{app.version}",
                data={"application_id": str(app.id), "blocker": out.blocker},
            )
    await ctx.note(step, reason)
    return {
        "result": {
            "status": target.value,
            "reason": reason,
            "blocker": out.blocker,
            "missing": out.plan.missing if out.plan else [],
        }
    }


def _route_after_fill(state: State) -> str:
    return "approve" if state.get("digest") and not state.get("result") else END


async def approve(state: State, runtime: Runtime[RunContext]) -> dict[str, Any]:
    ctx = runtime.context
    async with ctx.tenant() as s:
        app = await s.get(Application, _app_id(ctx))
        assert app is not None
        ev = await s.scalar(
            select(ApplicationEvent)
            .where(
                ApplicationEvent.application_id == app.id, ApplicationEvent.type == "form_filled"
            )
            .order_by(ApplicationEvent.seq.desc())
            .limit(1)
        )
        org, title = app.organization, app.title
        fields = (ev.payload or {}).get("fields", []) if ev else []
        declarations = (ev.payload or {}).get("declarations", []) if ev else []
        event_id = str(ev.id) if ev else None
        page_fallback = (ev.payload or {}).get("url") if ev else None
        page_fallback = str(page_fallback or app.apply_url or "")
    shown = [f"{f['label']}: {f['value']}" for f in fields if f["action"] in ("fill", "upload")]
    gate_note = ""
    if ctx.params.get("autopilot"):
        allowed, reasons = await _autopilot_gate(
            ctx, bool(declarations), str(state.get("url") or page_fallback)
        )
        if allowed:
            await ctx.record_policy_approval(
                node="approve",
                action_kind="submit_application",
                title=f"Submit your application to {org}?",
                summary=f"Approved by your autopilot settings: {' '.join(reasons)}",
                details={
                    "application_id": str(_app_id(ctx)),
                    "fields": shown,
                    "declarations": declarations,
                    "screenshot_event_id": event_id,
                },
            )
        else:
            gate_note = " Autopilot asks you because: " + " ".join(reasons)
    ok = await ctx.require_approval(
        node="approve",
        action_kind="submit_application",
        title=f"Submit your application to {org}?",
        summary=(
            f"NexScout filled in the application form for “{title}”. If you approve, it will "
            "submit it once"
            + (", confirming: " + "; ".join(declarations) if declarations else "")
            + ". Check every value and the screenshot first."
            + gate_note
        ),
        details={
            "page": state.get("url"),
            "fields": shown,
            "declarations": declarations,
            "application_id": str(_app_id(ctx)),
            "screenshot_event_id": event_id,
        },
    )
    if ok:
        return {}
    async with ctx.tenant() as s:
        app = await s.get(Application, _app_id(ctx), with_for_update=True)
        assert app is not None
        if app.status == S.AWAITING_REVIEW:
            move(
                s,
                app,
                S.PREPARING,
                actor="user",
                run_id=ctx.run_id,
                message="You chose not to submit. Nothing was sent.",
            )
    return {"result": {"status": "not_submitted"}}


async def _autopilot_gate(
    ctx: RunContext, has_declarations: bool, page_url: str
) -> tuple[bool, list[str]]:
    """May the user's standing policy approve this submission? Deterministic (domain/policy)."""
    from nexscout.application.autopilot import to_policy
    from nexscout.domain.policy import SubmitContext, may_auto_submit
    from nexscout.domain.site_policy import site_verdict
    from nexscout.infrastructure.fetch import SafeFetcher

    async with ctx.tenant() as s:
        app = await s.get(Application, _app_id(ctx))
        assert app is not None
        row = await s.scalar(select(AutopilotPolicy).where(AutopilotPolicy.case_id == app.case_id))
        if row is None:
            return False, ["No autopilot settings for this case."]
        day = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        submitted_today = int(
            await s.scalar(
                select(func.count()).where(
                    Application.owner_user_id == ctx.owner_user_id, Application.submitted_at >= day
                )
            )
            or 0
        )
        versions = list(
            await s.scalars(
                select(GeneratedDocumentVersion)
                .join(
                    GeneratedDocument,
                    (GeneratedDocument.id == GeneratedDocumentVersion.document_id)
                    & (GeneratedDocument.current_version == GeneratedDocumentVersion.number),
                )
                .where(GeneratedDocument.id.in_([uuid.UUID(x) for x in app.document_ids]))
            )
        )
        policy = to_policy(row)
    demo = fixture_origin(ctx.settings)
    url = page_url or ""
    robots = (
        True
        if demo and url.startswith(demo + "/")
        else await SafeFetcher(allow_private=False).robots_allows(url)
    )
    verdict = may_auto_submit(
        policy,
        SubmitContext(
            site=site_verdict(url, robots_allows=robots, demo_origin=demo),
            submitted_today=submitted_today,
            has_declarations=has_declarations,
            mock_documents=any(v.is_mock for v in versions),
            placeholders=any(v.placeholders for v in versions),
            unanswered=0,
        ),
    )
    return verdict.allowed, verdict.reasons


def _route_after_approve(state: State) -> str:
    return END if state.get("result") else "submit"


async def submit(state: State, runtime: Runtime[RunContext]) -> dict[str, Any]:
    ctx = runtime.context
    step = ctx.extras.get("current_step")
    async with ctx.tenant() as s:
        app = await s.get(Application, _app_id(ctx), with_for_update=True)
        assert app is not None
        if app.status == S.SUBMITTING:  # a previous attempt was interrupted mid-submit
            app.evidence = {"source": "none", "reason": "interrupted during submission"}
            move(
                s,
                app,
                S.SUBMISSION_UNCERTAIN,
                actor="agent",
                run_id=ctx.run_id,
                message="NexScout was interrupted while submitting. Check whether the "
                "application arrived, then confirm.",
            )
            return {"result": {"status": S.SUBMISSION_UNCERTAIN.value}}
        if app.status != S.AWAITING_REVIEW:
            return {"result": {"status": "skipped", "message": f"Application is {app.status}."}}
        move(s, app, S.APPROVED, actor="user", run_id=ctx.run_id, message="You approved.")
        move(s, app, S.SUBMITTING, actor="agent", run_id=ctx.run_id)
        snapshot = Inputs.of(app, await answers_for(s, app.owner_user_id, app.case_id))
        url = str(app.apply_url)
    digest = str(state["digest"])

    async def do_submit() -> dict[str, Any]:
        workdir = Path(tempfile.mkdtemp(prefix="nexscout-submit-"))
        try:
            who = await _applicant(ctx, snapshot, workdir)
            out = await submit_form(
                url, who, digest, _guard(ctx), headless=ctx.settings.browser_headless
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        key = ctx.store.put(ctx.owner_user_id, out.screenshot)[0] if out.screenshot else None
        return {
            "clicked": out.clicked,
            "confirmed": out.confirmed,
            "reference": out.reference,
            "excerpt": out.excerpt,
            "final_url": out.final_url,
            "error": out.error,
            "plan_changed": out.plan_changed,
            "screenshot_key": key,
        }

    try:
        out = await ctx.side_effect(
            tool="browser.submit_application",
            key=str(_app_id(ctx)),
            request={"url": url, "digest": digest},
            call=do_submit,
        )
    except UncertainOutcome:
        out = {"clicked": True, "confirmed": False, "error": "interrupted"}
    async with ctx.tenant() as s:
        app = await s.get(Application, _app_id(ctx), with_for_update=True)
        assert app is not None
        payload = {
            k: out.get(k) for k in ("final_url", "reference", "excerpt", "screenshot_key", "error")
        }
        if not out.get("clicked"):
            msg = out.get("error") or "Nothing was submitted."
            event(
                s,
                app,
                "submit_not_attempted",
                actor="agent",
                run_id=ctx.run_id,
                message=msg,
                payload=payload,
            )
            move(
                s,
                app,
                S.FAILED,
                actor="agent",
                run_id=ctx.run_id,
                message=f"Not submitted: {msg} Fill it in again to review the new form.",
            )
            status = S.FAILED
        elif out.get("confirmed"):
            app.submitted_at = datetime.now(UTC)
            app.evidence = {"source": "observed", **payload}
            event(
                s,
                app,
                "submitted",
                actor="agent",
                run_id=ctx.run_id,
                payload=payload,
                message="The site confirmed the application (reference "
                f"{out.get('reference') or 'not shown'}).",
            )
            move(s, app, S.SUBMITTED, actor="agent", run_id=ctx.run_id)
            status = S.SUBMITTED
        else:
            app.evidence = {"source": "none", **payload}
            event(
                s,
                app,
                "submission_uncertain",
                actor="agent",
                run_id=ctx.run_id,
                payload=payload,
                message="The form was sent, but the page didn't confirm it. Check your email "
                "or the site, then confirm here.",
            )
            move(s, app, S.SUBMISSION_UNCERTAIN, actor="agent", run_id=ctx.run_id)
            status = S.SUBMISSION_UNCERTAIN
    await ctx.note(step, f"Result: {status.value.replace('_', ' ')}.")
    return {"result": {"status": status.value, "reference": out.get("reference")}}


def build() -> StateGraph[State, RunContext, Any, Any]:
    g: StateGraph[State, RunContext, Any, Any] = StateGraph(State, context_schema=RunContext)
    for name, fn in (("fill", fill), ("approve", approve), ("submit", submit)):
        g.add_node(name, cast(Any, tracked(name, fn)))
    g.add_edge(START, "fill")
    g.add_conditional_edges("fill", _route_after_fill, {"approve": "approve", END: END})
    g.add_conditional_edges("approve", _route_after_approve, {"submit": "submit", END: END})
    g.add_edge("submit", END)
    return g


SPEC = register(
    WorkflowSpec(
        kind="browser_apply",
        title="Fill in and submit an application",
        description="Fills in an application form, waits for your approval, then submits once.",
        build=build,
        user_startable=False,
    )
)
