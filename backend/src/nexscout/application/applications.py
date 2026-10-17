"""Applications: create from an opportunity, track status (state machine), and hand off to the
browser workflow. Every status change is validated and written to the event timeline."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.application.actor import Actor
from nexscout.application.audit import record_audit
from nexscout.application.cases import get_case
from nexscout.application.opportunities import get_opportunity
from nexscout.application.runs import start_run
from nexscout.config import Settings
from nexscout.domain.errors import (
    ConcurrencyConflict,
    Conflict,
    InvalidTransition,
    NotFound,
    ValidationFailed,
)
from nexscout.domain.forms import normalize_question
from nexscout.domain.state_machines import APPLICATION_MACHINE, ApplicationStatus
from nexscout.infrastructure.db.models import (
    Application,
    ApplicationEvent,
    GeneratedDocument,
    GeneratedDocumentVersion,
    OpportunitySource,
    WorkflowRun,
)
from nexscout.infrastructure.security.urls import check_outbound_url
from nexscout.infrastructure.storage import ObjectStore
from nexscout.integrations.sources.registry import adapters

S = ApplicationStatus
# Statuses from which the browser workflow may (re)start filling the form.
BROWSER_START = frozenset(
    {S.PREPARING, S.NEEDS_USER_ACTION, S.FAILED, S.AWAITING_REVIEW, S.APPROVED}
)
# Changes a user may make by hand (the browser workflow makes the others).
USER_TARGETS = frozenset(
    {
        S.PREPARING,
        S.SUBMITTED,
        S.TRACKING,
        S.COMPLETED,
        S.REJECTED,
        S.WITHDRAWN,
        S.CANCELLED,
        S.PAUSED,
    }
)
CV_TYPES = ("resume", "academic_cv")
LETTER_TYPES = ("cover_letter", "sop")


@dataclass
class ApplicationView:
    application: Application
    events: list[ApplicationEvent]


def move(
    session: AsyncSession,
    app: Application,
    target: ApplicationStatus,
    *,
    actor: str,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
    run_id: uuid.UUID | None = None,
) -> None:
    """Validated transition + timeline event (in the caller's transaction)."""
    current = ApplicationStatus(app.status)
    APPLICATION_MACHINE.transition(current, target)
    app.status = target.value
    app.version += 1
    session.add(
        ApplicationEvent(
            owner_user_id=app.owner_user_id,
            application_id=app.id,
            type="status_changed",
            from_status=current.value,
            to_status=target.value,
            actor=actor,
            message=message,
            payload=payload or {},
            run_id=run_id,
        )
    )


def event(
    session: AsyncSession,
    app: Application,
    type: str,
    *,
    actor: str,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
    run_id: uuid.UUID | None = None,
) -> ApplicationEvent:
    ev = ApplicationEvent(
        owner_user_id=app.owner_user_id,
        application_id=app.id,
        type=type,
        actor=actor,
        message=message,
        payload=payload or {},
        run_id=run_id,
    )
    session.add(ev)
    return ev


def fixture_origin(settings: Settings) -> str | None:
    return settings.fixture_site_origin.rstrip("/") if settings.fixture_site_on else None


def check_apply_url(settings: Settings, url: str) -> str:
    origin = fixture_origin(settings)
    if origin and url.startswith(origin + "/"):
        return url
    return check_outbound_url(url, allow_private=False, resolve=False)


async def _default_apply_url(
    session: AsyncSession, settings: Settings, opportunity: Any
) -> str | None:
    sources = list(
        await session.scalars(
            select(OpportunitySource).where(OpportunitySource.opportunity_id == opportunity.id)
        )
    )
    registry = adapters()
    demo = bool(sources) and all(
        (a := registry.get(s.source_key)) is not None and a.capabilities.is_demo_data
        for s in sources
    )
    origin = fixture_origin(settings)
    if demo and origin:
        slug = opportunity.requisition_id or sources[0].external_id
        slug = re.sub(r"[^A-Za-z0-9_-]+", "-", str(slug)).strip("-") or "demo"
        return f"{origin}/fixture-site/apply/{slug}"
    if demo:
        return None  # demo listings have no real application page
    url = opportunity.data.get("application_url") or opportunity.canonical_url
    return str(url) if url else None


async def _check_documents(
    session: AsyncSession, actor: Actor, case_id: uuid.UUID, ids: list[uuid.UUID]
) -> list[str]:
    out: list[str] = []
    for doc_id in ids:
        doc = await session.scalar(
            select(GeneratedDocument.id).where(
                GeneratedDocument.id == doc_id,
                GeneratedDocument.owner_user_id == actor.user_id,
                GeneratedDocument.case_id == case_id,
            )
        )
        if doc is None:
            raise NotFound("Document not found.")
        out.append(str(doc_id))
    return list(dict.fromkeys(out))


async def create_application(
    session: AsyncSession,
    settings: Settings,
    actor: Actor,
    case_id: uuid.UUID,
    *,
    opportunity_id: uuid.UUID,
    document_ids: list[uuid.UUID],
    apply_url: str | None = None,
) -> Application:
    view = await get_opportunity(session, actor, case_id, opportunity_id)
    exists = await session.scalar(
        select(Application.id).where(
            Application.case_id == case_id, Application.opportunity_id == opportunity_id
        )
    )
    if exists is not None:
        raise Conflict("You already have an application for this position.")
    opp = view.opportunity
    url = (
        check_apply_url(settings, apply_url)
        if apply_url
        else await _default_apply_url(session, settings, opp)
    )
    closes = opp.data.get("closes_at")
    app = Application(
        owner_user_id=actor.user_id,
        case_id=case_id,
        opportunity_id=opp.id,
        title=opp.title,
        organization=opp.organization_name,
        status=S.PREPARING.value,
        apply_url=url,
        method="browser" if url else "manual",
        document_ids=await _check_documents(session, actor, case_id, document_ids),
        answers={},
        deadline=str(closes)[:10] if closes else None,
        evidence={},
    )
    session.add(app)
    await session.flush()
    event(session, app, "created", actor="user", message="Application started.")
    record_audit(
        session,
        "application.created",
        actor_user_id=actor.user_id,
        target_type="application",
        target_id=app.id,
    )
    await session.flush()
    return app


async def _get(
    session: AsyncSession, actor: Actor, app_id: uuid.UUID, *, lock: bool = False
) -> Application:
    stmt = select(Application).where(
        Application.id == app_id, Application.owner_user_id == actor.user_id
    )
    if lock:
        stmt = stmt.with_for_update()
    app = await session.scalar(stmt)
    if app is None:
        raise NotFound("Application not found.")
    return app


async def get_application(
    session: AsyncSession, actor: Actor, app_id: uuid.UUID
) -> ApplicationView:
    app = await _get(session, actor, app_id)
    events = list(
        await session.scalars(
            select(ApplicationEvent)
            .where(
                ApplicationEvent.application_id == app.id,
                ApplicationEvent.owner_user_id == actor.user_id,
            )
            .order_by(ApplicationEvent.seq)
        )
    )
    return ApplicationView(app, events)


async def list_applications(
    session: AsyncSession,
    actor: Actor,
    case_id: uuid.UUID,
    *,
    status: str | None = None,
    q: str | None = None,
    sort: str = "updated",
) -> list[Application]:
    await get_case(session, actor, case_id)
    stmt = select(Application).where(
        Application.owner_user_id == actor.user_id, Application.case_id == case_id
    )
    if status:
        stmt = stmt.where(Application.status.in_(status.split(",")))
    if q:
        like = f"%{q.strip().lower()}%"
        title, org = func.lower(Application.title), func.lower(Application.organization)
        stmt = stmt.where(title.like(like) | org.like(like))
    if sort == "deadline":
        stmt = stmt.order_by(Application.deadline.asc().nulls_last(), Application.title)
    else:
        stmt = stmt.order_by(Application.updated_at.desc())
    return list(await session.scalars(stmt))


async def bulk_status(
    session: AsyncSession, actor: Actor, case_id: uuid.UUID, ids: list[uuid.UUID], target: str
) -> list[dict[str, Any]]:
    """Apply one manual status change to many applications; each is validated on its own."""
    await get_case(session, actor, case_id)
    results: list[dict[str, Any]] = []
    for app_id in ids[:200]:
        app = await session.scalar(
            select(Application).where(
                Application.id == app_id,
                Application.owner_user_id == actor.user_id,
                Application.case_id == case_id,
            )
        )
        if app is None:
            results.append({"id": str(app_id), "ok": False, "error": "Not found."})
            continue
        try:
            async with session.begin_nested():
                await change_status(session, actor, app.id, version=app.version, target=target)
            results.append({"id": str(app_id), "ok": True, "error": None})
        except (ValidationFailed, InvalidTransition) as exc:
            results.append({"id": str(app_id), "ok": False, "error": str(exc).split(": ", 1)[-1]})
    return results


def _csv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    # Spreadsheet formula injection: neutralize cells that a spreadsheet would evaluate.
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


async def export_csv(session: AsyncSession, actor: Actor, case_id: uuid.UUID) -> str:
    import csv
    import io

    rows = await list_applications(session, actor, case_id, sort="deadline")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "title",
            "organization",
            "status",
            "deadline",
            "submitted_at",
            "evidence",
            "reference",
            "apply_url",
            "updated_at",
        ]
    )
    for a in rows:
        ev = a.evidence or {}
        w.writerow(
            [
                _csv_cell(v)
                for v in (
                    a.title,
                    a.organization,
                    a.status,
                    a.deadline,
                    a.submitted_at.isoformat() if a.submitted_at else "",
                    ev.get("source", ""),
                    ev.get("reference", ""),
                    a.apply_url,
                    a.updated_at.isoformat(),
                )
            ]
        )
    return buf.getvalue()


def _expect(app: Application, version: int) -> None:
    if app.version != version:
        raise ConcurrencyConflict("This application changed. Reload to see the latest version.")


async def update_application(
    session: AsyncSession,
    settings: Settings,
    actor: Actor,
    app_id: uuid.UUID,
    *,
    version: int,
    changes: dict[str, Any],
) -> ApplicationView:
    app = await _get(session, actor, app_id, lock=True)
    _expect(app, version)
    if "answers" in changes and changes["answers"] is not None:
        answers = {
            normalize_question(str(k)): str(v).strip()
            for k, v in dict(changes["answers"]).items()
            if str(v).strip()
        }
        if any(len(v) > 5000 for v in answers.values()) or len(answers) > 50:
            raise ValidationFailed("Answers are too long.")
        app.answers = answers
    if "phone" in changes:
        app.phone = (changes["phone"] or None) and str(changes["phone"]).strip()[:40]
    if changes.get("document_ids") is not None:
        app.document_ids = await _check_documents(
            session, actor, app.case_id, [uuid.UUID(str(d)) for d in changes["document_ids"]]
        )
    if "apply_url" in changes:
        url = changes["apply_url"]
        app.apply_url = check_apply_url(settings, url) if url else None
        app.method = "browser" if app.apply_url else "manual"
    if "notes" in changes:
        app.notes = changes["notes"]
    if "deadline" in changes:
        app.deadline = changes["deadline"]
    app.version += 1
    event(
        session,
        app,
        "updated",
        actor="user",
        message="Details updated.",
        payload={"fields": sorted(k for k in changes if changes[k] is not None)},
    )
    await session.flush()
    return await get_application(session, actor, app_id)


async def change_status(
    session: AsyncSession,
    actor: Actor,
    app_id: uuid.UUID,
    *,
    version: int,
    target: str,
    note: str | None = None,
    reference: str | None = None,
) -> ApplicationView:
    try:
        wanted = ApplicationStatus(target)
    except ValueError as exc:
        raise ValidationFailed("Unknown status.") from exc
    if wanted not in USER_TARGETS:
        raise ValidationFailed("That status is set by NexScout, not by hand.")
    app = await _get(session, actor, app_id, lock=True)
    _expect(app, version)
    if wanted is S.SUBMITTED:
        # The user tells us they submitted (e.g. manually after a CAPTCHA): their word is the
        # evidence, recorded as such.
        app.submitted_at = datetime.now(UTC)
        app.evidence = {"source": "user", "reference": reference, "note": note}
    move(session, app, wanted, actor="user", message=note)
    app.blocker = None if wanted is not S.PAUSED else app.blocker
    await session.flush()
    return await get_application(session, actor, app_id)


async def resolve_uncertain(
    session: AsyncSession,
    actor: Actor,
    app_id: uuid.UUID,
    *,
    submitted: bool,
    reference: str | None,
) -> ApplicationView:
    app = await _get(session, actor, app_id, lock=True)
    if app.status != S.SUBMISSION_UNCERTAIN.value:
        raise ValidationFailed("Only uncertain submissions need to be resolved.")
    if submitted:
        app.submitted_at = datetime.now(UTC)
        app.evidence = {**(app.evidence or {}), "source": "user", "reference": reference}
        move(
            session,
            app,
            S.SUBMITTED,
            actor="user",
            message="You confirmed the application was submitted.",
        )
    else:
        move(
            session,
            app,
            S.APPROVED,
            actor="user",
            message="You confirmed it was not submitted. You can try again.",
        )
    await session.flush()
    return await get_application(session, actor, app_id)


async def start_browser(session: AsyncSession, actor: Actor, app_id: uuid.UUID) -> WorkflowRun:
    app = await _get(session, actor, app_id)
    if ApplicationStatus(app.status) not in BROWSER_START:
        raise ValidationFailed(
            f"An application that is {app.status.replace('_', ' ')} can't be filled in again."
        )
    if not app.apply_url:
        raise ValidationFailed("Add the address of the application page first.")
    kinds = dict(
        (
            await session.execute(
                select(GeneratedDocument.id, GeneratedDocument.doc_type).where(
                    GeneratedDocument.id.in_([uuid.UUID(x) for x in app.document_ids])
                )
            )
        ).all()
    )
    if not any(k in CV_TYPES for k in kinds.values()):
        raise ValidationFailed("Choose a resume or academic CV to upload.")
    for doc_id in kinds:
        version = await session.scalar(
            select(GeneratedDocumentVersion)
            .join(GeneratedDocument, GeneratedDocument.id == GeneratedDocumentVersion.document_id)
            .where(
                GeneratedDocument.id == doc_id,
                GeneratedDocumentVersion.number == GeneratedDocument.current_version,
            )
        )
        if version is None or not (version.artifacts or {}).get("pdf"):
            raise ValidationFailed("Create the PDF files for the chosen documents first.")
        if version.placeholders:
            raise ValidationFailed(
                "A chosen document still has placeholders. Fill them in before applying."
            )
    return await start_run(
        session,
        actor,
        app.case_id,
        kind="browser_apply",
        params={"application_id": str(app.id)},
        internal=True,
    )


async def screenshot(
    session: AsyncSession,
    actor: Actor,
    store: ObjectStore,
    app_id: uuid.UUID,
    event_id: uuid.UUID,
) -> bytes:
    view = await get_application(session, actor, app_id)
    ev = next((e for e in view.events if e.id == event_id), None)
    key = (ev.payload or {}).get("screenshot_key") if ev else None
    if not key:
        raise NotFound("Screenshot not found.")
    return store.get(str(key))
