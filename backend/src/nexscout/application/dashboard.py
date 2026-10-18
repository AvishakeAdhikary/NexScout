"""Case dashboard, user diagnostics, and the case assistant (chat)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.application import generated_documents as gen
from nexscout.application.actor import Actor
from nexscout.application.applications import list_applications
from nexscout.application.cases import get_case
from nexscout.application.notifications import DONE_STATES, list_reminders
from nexscout.application.opportunities import start_sync
from nexscout.application.profile import profile_gaps
from nexscout.config import Settings
from nexscout.domain.chat import CAPABILITIES, classify
from nexscout.domain.errors import DomainError
from nexscout.domain.timezones import local_today
from nexscout.infrastructure.db.models import (
    ApprovalRequest,
    ChatMessage,
    GeneratedDocument,
    GeneratedDocumentVersion,
    OpportunityMatch,
    ProfileFact,
    ProviderConfig,
    Task,
    User,
    WorkerHeartbeat,
    WorkflowRun,
)

UPCOMING_DAYS = 30


async def needs_you(s: AsyncSession, actor: Actor, case_id: uuid.UUID) -> list[dict[str, str]]:
    base = f"/cases/{case_id}"
    items: list[dict[str, str]] = []
    for title in await s.scalars(
        select(ApprovalRequest.title).where(
            ApprovalRequest.owner_user_id == actor.user_id,
            ApprovalRequest.case_id == case_id,
            ApprovalRequest.status == "pending",
        )
    ):
        items.append(
            {"kind": "approval", "title": f"Approve or reject: {title}", "href": f"{base}/activity"}
        )
    for a in await list_applications(
        s, actor, case_id, status="needs_user_action,submission_uncertain"
    ):
        what = "needs you" if a.status == "needs_user_action" else "may not have been submitted"
        items.append(
            {
                "kind": "application",
                "title": f"{a.title} {what}",
                "href": f"{base}/applications/{a.id}",
            }
        )
    pending = await s.scalar(
        select(func.count()).where(
            ProfileFact.owner_user_id == actor.user_id,
            ProfileFact.case_id == case_id,
            ProfileFact.review_state == "pending",
        )
    )
    if pending:
        items.append(
            {
                "kind": "review",
                "title": f"{pending} profile entries to review",
                "href": f"{base}/profile#review",
            }
        )
    unfinished = await s.scalar(
        select(func.count())
        .select_from(GeneratedDocument)
        .join(
            GeneratedDocumentVersion,
            (GeneratedDocumentVersion.document_id == GeneratedDocument.id)
            & (GeneratedDocumentVersion.number == GeneratedDocument.current_version),
        )
        .where(
            GeneratedDocument.owner_user_id == actor.user_id,
            GeneratedDocument.case_id == case_id,
            func.jsonb_array_length(GeneratedDocumentVersion.placeholders) > 0,
        )
    )
    if unfinished:
        items.append(
            {
                "kind": "document",
                "title": f"{unfinished} document(s) with placeholders",
                "href": f"{base}/documents",
            }
        )
    return items


async def user_today(s: AsyncSession, actor: Actor, now: datetime | None = None) -> date:
    """Today on the user's own calendar."""
    tz = await s.scalar(select(User.timezone).where(User.id == actor.user_id))
    return local_today(now or datetime.now(UTC), tz)


async def upcoming(
    s: AsyncSession, actor: Actor, case_id: uuid.UUID, today: date
) -> list[dict[str, Any]]:
    horizon = (today + timedelta(days=UPCOMING_DAYS)).isoformat()
    out: list[dict[str, Any]] = []
    for a in await list_applications(s, actor, case_id, sort="deadline"):
        if (
            a.deadline
            and a.status not in DONE_STATES
            and today.isoformat() <= a.deadline <= horizon
        ):
            out.append(
                {
                    "kind": "deadline",
                    "date": a.deadline,
                    "title": a.title,
                    "href": f"/cases/{case_id}/applications/{a.id}",
                }
            )
    for r in await list_reminders(s, actor, case_id):
        if r.due_on <= horizon and r.kind != "deadline":
            out.append(
                {
                    "kind": "reminder",
                    "date": r.due_on,
                    "title": r.title,
                    "href": f"/cases/{case_id}/applications/{r.application_id}"
                    if r.application_id
                    else f"/cases/{case_id}",
                }
            )
    return sorted(out, key=lambda x: x["date"])


async def case_dashboard(
    s: AsyncSession, actor: Actor, case_id: uuid.UUID, now: datetime | None = None
) -> dict[str, Any]:
    await get_case(s, actor, case_id)
    today = await user_today(s, actor, now)
    apps = await list_applications(s, actor, case_id)
    by_status: dict[str, int] = {}
    for a in apps:
        by_status[a.status] = by_status.get(a.status, 0) + 1
    facts = dict(
        (
            await s.execute(
                select(ProfileFact.review_state, func.count())
                .where(ProfileFact.owner_user_id == actor.user_id, ProfileFact.case_id == case_id)
                .group_by(ProfileFact.review_state)
            )
        ).all()
    )
    matches = dict(
        (
            await s.execute(
                select(OpportunityMatch.status, func.count())
                .where(
                    OpportunityMatch.owner_user_id == actor.user_id,
                    OpportunityMatch.case_id == case_id,
                )
                .group_by(OpportunityMatch.status)
            )
        ).all()
    )
    runs = list(
        await s.scalars(
            select(WorkflowRun)
            .where(WorkflowRun.owner_user_id == actor.user_id, WorkflowRun.case_id == case_id)
            .order_by(WorkflowRun.created_at.desc())
            .limit(5)
        )
    )
    return {
        "applications_by_status": by_status,
        "applications_total": len(apps),
        "needs_you": await needs_you(s, actor, case_id),
        "upcoming": await upcoming(s, actor, case_id, today),
        "recent_runs": [
            {
                "id": str(r.id),
                "title": r.title,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r in runs
        ],
        "profile": {
            "accepted": int(facts.get("accepted", 0)),
            "pending": int(facts.get("pending", 0)),
            "gaps": len(await profile_gaps(s, actor, case_id)),
        },
        "opportunities": {
            "matches": sum(int(v) for k, v in matches.items() if k != "dismissed"),
            "shortlisted": int(matches.get("shortlisted", 0)),
        },
    }


async def diagnostics(s: AsyncSession, actor: Actor) -> dict[str, Any]:
    """What a user may know about the system serving them (no hostnames, no other users)."""
    now = datetime.now(UTC)
    beats = (
        await s.execute(
            select(WorkerHeartbeat.status, WorkerHeartbeat.in_flight, WorkerHeartbeat.last_seen_at)
        )
    ).all()
    alive = [
        b for b in beats if b.status == "running" and now - b.last_seen_at < timedelta(minutes=2)
    ]
    tasks = dict(
        (
            await s.execute(
                select(Task.status, func.count())
                .where(Task.owner_user_id == actor.user_id, Task.status.in_(["queued", "running"]))
                .group_by(Task.status)
            )
        ).all()
    )
    failed = list(
        await s.scalars(
            select(WorkflowRun)
            .where(
                WorkflowRun.owner_user_id == actor.user_id,
                WorkflowRun.status == "failed",
                WorkflowRun.created_at > now - timedelta(days=7),
            )
            .order_by(WorkflowRun.created_at.desc())
            .limit(10)
        )
    )
    providers = list(
        await s.scalars(select(ProviderConfig).where(ProviderConfig.owner_user_id == actor.user_id))
    )
    from nexscout import __version__

    head = (await s.execute(select(func.current_setting("server_version")))).scalar()
    return {
        "app_version": __version__,
        "database": f"PostgreSQL {head}",
        "workers_alive": len(alive),
        "worker_last_seen": max((b.last_seen_at for b in beats), default=None),
        "worker_busy": sum(b.in_flight for b in alive),
        "my_tasks": {
            "queued": int(tasks.get("queued", 0)),
            "running": int(tasks.get("running", 0)),
        },
        "recent_failures": [
            {
                "id": str(r.id),
                "title": r.title,
                "error": r.error,
                "case_id": str(r.case_id),
                "created_at": r.created_at.isoformat(),
            }
            for r in failed
        ],
        "providers": [
            {
                "name": p.name,
                "kind": p.kind,
                "last_check": p.last_verification.get("ok") if p.last_verification else None,
                "checked_at": p.last_verified_at.isoformat() if p.last_verified_at else None,
            }
            for p in providers
        ],
    }


# --- Assistant --------------------------------------------------------------------------------


async def chat_history(s: AsyncSession, actor: Actor, case_id: uuid.UUID) -> list[ChatMessage]:
    await get_case(s, actor, case_id)
    rows = await s.scalars(
        select(ChatMessage)
        .where(ChatMessage.owner_user_id == actor.user_id, ChatMessage.case_id == case_id)
        .order_by(ChatMessage.seq.desc())
        .limit(100)
    )
    return list(reversed(list(rows)))


async def chat(
    s: AsyncSession, settings: Settings, actor: Actor, case_id: uuid.UUID, message: str
) -> list[ChatMessage]:
    await get_case(s, actor, case_id)
    text = message.strip()[:2000]
    intent = classify(text)
    base = f"/cases/{case_id}"
    actions: list[dict[str, str]] = []
    try:
        reply = await _answer(s, settings, actor, case_id, intent.name, intent.args, base, actions)
    except DomainError as exc:  # same validation as the screens
        reply = f"I couldn't do that: {exc}"
    user = ChatMessage(
        owner_user_id=actor.user_id,
        case_id=case_id,
        role="user",
        content=text,
        intent=intent.name,
        actions=[],
    )
    bot = ChatMessage(
        owner_user_id=actor.user_id,
        case_id=case_id,
        role="assistant",
        content=reply,
        intent=intent.name,
        actions=actions,
    )
    s.add(user)
    await s.flush()
    s.add(bot)
    await s.flush()
    return [user, bot]


async def _answer(
    s: AsyncSession,
    settings: Settings,
    actor: Actor,
    case_id: uuid.UUID,
    name: str,
    args: dict[str, str],
    base: str,
    actions: list[dict[str, str]],
) -> str:
    if name == "submit":
        actions.append({"label": "Open applications", "href": f"{base}/applications"})
        return (
            "I never submit or send anything from chat. Open the application, check what "
            "NexScout filled in, and approve the submission there."
        )
    if name == "needs_you":
        items = await needs_you(s, actor, case_id)
        actions.extend({"label": i["title"], "href": i["href"]} for i in items[:8])
        return (
            "Nothing needs you right now."
            if not items
            else f"{len(items)} thing(s) need you:\n" + "\n".join(f"- {i['title']}" for i in items)
        )
    if name == "deadlines":
        items = await upcoming(s, actor, case_id, await user_today(s, actor))
        actions.extend(
            {"label": f"{i['date']}: {i['title']}", "href": i["href"]} for i in items[:8]
        )
        return (
            "No deadlines in the next 30 days."
            if not items
            else "Coming up:\n" + "\n".join(f"- {i['date']}: {i['title']}" for i in items)
        )
    if name == "status":
        q = args.get("q", "")
        apps = await list_applications(s, actor, case_id, q=q or None)
        if not apps:
            actions.append({"label": "All applications", "href": f"{base}/applications"})
            return (
                f"I didn't find an application matching “{q}”."
                if q
                else "You have no applications yet."
            )
        actions.extend({"label": a.title, "href": f"{base}/applications/{a.id}"} for a in apps[:8])
        return "\n".join(
            f"- {a.title} ({a.organization}): {a.status.replace('_', ' ')}" for a in apps[:8]
        )
    if name in ("find_phd", "find_jobs"):
        run = await start_sync(s, actor, case_id, source_keys=None)
        page = "phd" if name == "find_phd" else "jobs"
        actions.append({"label": "See results", "href": f"{base}/{page}"})
        actions.append({"label": "Watch progress", "href": f"{base}/activity"})
        return (
            f"Searching your enabled sources now (run {str(run.id)[:8]}). Results appear on "
            f"the {'PhD' if page == 'phd' else 'Jobs'} page with explained fit estimates."
        )
    if name in ("draft_resume", "draft_academic_cv"):
        doc_type = "resume" if name == "draft_resume" else "academic_cv"
        await gen.start_draft(s, actor, case_id, doc_type=doc_type, opportunity_id=None)
        actions.append({"label": "Documents", "href": f"{base}/documents"})
        label = "resume" if doc_type == "resume" else "academic CV"
        return (
            f"Assembling your {label} from your confirmed entries (no AI). It will appear "
            "under Documents → Application materials for you to review."
        )
    if name == "review_profile":
        actions.append({"label": "Review entries", "href": f"{base}/profile#review"})
        return "Your entries waiting for review are on My Profile."
    actions.append({"label": "Dashboard", "href": base})
    intro = "Hi! " if name == "help" else "I can't help with that yet. "
    return intro + "Here's what I can do:\n" + "\n".join(f"- {c}" for c in CAPABILITIES)
