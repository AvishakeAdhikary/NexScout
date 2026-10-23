"""Reminders and in-app notifications, plus the worker's periodic maintenance sweep.

Notifications stay inside NexScout: nothing is emailed or pushed elsewhere (sending messages is
a consequential action and no outbound channel is configured).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.application.actor import Actor
from nexscout.application.cases import get_case
from nexscout.domain.errors import NotFound, ValidationFailed
from nexscout.domain.timezones import local_today
from nexscout.infrastructure.db.models import (
    Application,
    ApprovalRequest,
    Notification,
    Reminder,
    User,
)

# Applications in these states don't need deadline reminders.
DONE_STATES = frozenset(
    {
        "submitted",
        "tracking",
        "completed",
        "cancelled",
        "rejected",
        "withdrawn",
        "submission_uncertain",
    }
)
REMIND_DAYS_BEFORE = (7, 1)
NEEDS_YOU = {
    "needs_user_action": "needs you",
    "submission_uncertain": "may not have been submitted",
}


def _today(now: datetime) -> date:
    return now.astimezone(UTC).date()


async def _notify(
    s: AsyncSession,
    *,
    owner: uuid.UUID,
    case_id: uuid.UUID | None,
    kind: str,
    title: str,
    body: str | None,
    link: str | None,
    key: str,
    data: dict[str, Any] | None = None,
) -> bool:
    """Create a notification once per dedupe key and, in the same transaction, queue it for
    the user's paired channels (transactional outbox)."""
    from nexscout.application.channels import enqueue_deliveries

    res = await s.execute(
        insert(Notification)
        .values(
            id=uuid.uuid4(),
            owner_user_id=owner,
            case_id=case_id,
            kind=kind,
            title=title[:300],
            body=(body or "")[:1000] or None,
            link=link,
            data=data or {},
            dedupe_key=key,
        )
        .on_conflict_do_nothing(constraint="uq_notifications_dedupe")
        .returning(Notification.id)
    )
    nid = res.scalar()
    if nid is None:
        return False
    await enqueue_deliveries(s, owner=owner, notification_id=nid, kind=kind)
    return True


notify = _notify  # public name for other use cases (agents, autopilot)


async def run_maintenance(s: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    """Idempotent sweep across users (worker system role). Safe to run concurrently."""
    now = now or datetime.now(UTC)
    # Dates are the user's own calendar days: "today" differs by up to a day across zones.
    zones = dict((await s.execute(select(User.id, User.timezone))).all())
    created_reminders = notified = 0

    # 1) Deadline reminders for open applications.
    apps = await s.execute(
        select(
            Application.id,
            Application.owner_user_id,
            Application.case_id,
            Application.title,
            Application.deadline,
            Application.status,
        ).where(Application.deadline.is_not(None), Application.status.not_in(DONE_STATES))
    )
    for app_id, owner, case_id, title, deadline, _ in apps.all():
        try:
            due = date.fromisoformat(str(deadline))
        except ValueError:
            continue
        today = local_today(now, zones.get(owner))
        for days in REMIND_DAYS_BEFORE:
            on = due - timedelta(days=days)
            if on < today - timedelta(days=1) or due < today:
                continue
            res = await s.execute(
                insert(Reminder)
                .values(
                    id=uuid.uuid4(),
                    owner_user_id=owner,
                    case_id=case_id,
                    application_id=app_id,
                    kind="deadline",
                    title=f"{title}: deadline in {days} day{'s' if days > 1 else ''}",
                    due_on=on.isoformat(),
                    dedupe_key=f"deadline:{app_id}:{due}:{days}",
                )
                .on_conflict_do_nothing(constraint="uq_reminders_dedupe")
                .returning(Reminder.id)
            )
            created_reminders += int(res.scalar() is not None)

    # 2) Due reminders become notifications (once). No zone is more than a day ahead of UTC.
    latest = (_today(now) + timedelta(days=1)).isoformat()
    due_rows = (
        await s.scalars(
            select(Reminder)
            .where(
                Reminder.due_on <= latest,
                Reminder.done_at.is_(None),
                Reminder.notified_at.is_(None),
            )
            .with_for_update(skip_locked=True)
        )
    ).all()
    for r in due_rows:
        if r.due_on > local_today(now, zones.get(r.owner_user_id)).isoformat():
            continue
        link = (
            f"/cases/{r.case_id}/applications/{r.application_id}"
            if r.application_id
            else f"/cases/{r.case_id}"
        )
        notified += await _notify(
            s,
            owner=r.owner_user_id,
            case_id=r.case_id,
            kind="reminder",
            title=r.title,
            body=f"Due {r.due_on}.",
            link=link,
            key=f"reminder:{r.id}",
        )
        r.notified_at = now

    # 3) Things waiting for the user: approvals and blocked/uncertain applications.
    approvals = await s.execute(
        select(
            ApprovalRequest.id,
            ApprovalRequest.owner_user_id,
            ApprovalRequest.case_id,
            ApprovalRequest.title,
        ).where(ApprovalRequest.status == "pending")
    )
    for ap_id, owner, case_id, title in approvals.all():
        notified += await _notify(
            s,
            owner=owner,
            case_id=case_id,
            kind="approval",
            title=f"Approval needed: {title}",
            body=None,
            link=f"/approve/{ap_id}",
            key=f"approval:{ap_id}",
            data={"approval_id": str(ap_id)},
        )
    blocked = await s.execute(
        select(
            Application.id,
            Application.owner_user_id,
            Application.case_id,
            Application.title,
            Application.status,
            Application.version,
        ).where(Application.status.in_(list(NEEDS_YOU)))
    )
    for app_id, owner, case_id, title, status, version in blocked.all():
        notified += await _notify(
            s,
            owner=owner,
            case_id=case_id,
            kind="application",
            title=f"{title} {NEEDS_YOU[status]}",
            body=None,
            link=f"/cases/{case_id}/applications/{app_id}",
            key=f"application:{app_id}:{status}:{version}",
        )
    purged = await enforce_retention(s, now)
    return {"reminders_created": created_reminders, "notifications_created": notified, **purged}


# Retention defaults (docs/OPERATIONS.md). Deleting old operational data limits what a breach
# could expose; it never touches the user's profile, documents or applications.
RETENTION_DAYS = {
    "workflow_events": 90,
    "notifications_read": 90,
    "login_attempts": 30,
    "sessions_after_expiry": 30,
    "audit_events": 365,
}


async def enforce_retention(s: AsyncSession, now: datetime) -> dict[str, int]:
    from sqlalchemy import delete

    from nexscout.infrastructure.db.models import (
        AuditEvent,
        AuthSession,
        LoginAttempt,
        WorkflowEvent,
    )

    def before(days: int) -> datetime:
        return now - timedelta(days=days)

    out: dict[str, int] = {}
    for key, stmt in (
        (
            "purged_workflow_events",
            delete(WorkflowEvent).where(
                WorkflowEvent.created_at < before(RETENTION_DAYS["workflow_events"])
            ),
        ),
        (
            "purged_notifications",
            delete(Notification).where(
                Notification.read_at.is_not(None),
                Notification.read_at < before(RETENTION_DAYS["notifications_read"]),
            ),
        ),
        (
            "purged_login_attempts",
            delete(LoginAttempt).where(
                LoginAttempt.created_at < before(RETENTION_DAYS["login_attempts"])
            ),
        ),
        (
            "purged_sessions",
            delete(AuthSession).where(
                AuthSession.expires_at < before(RETENTION_DAYS["sessions_after_expiry"])
            ),
        ),
        (
            "purged_audit_events",
            delete(AuditEvent).where(
                AuditEvent.created_at < before(RETENTION_DAYS["audit_events"])
            ),
        ),
    ):
        res = await s.execute(stmt)
        out[key] = int(res.rowcount or 0)  # type: ignore[attr-defined]
    return out


# --- User-facing use cases (app role, RLS) --------------------------------------------------


async def list_notifications(
    s: AsyncSession, actor: Actor, *, limit: int = 50, before: datetime | None = None
) -> tuple[list[Notification], int]:
    """Newest first; `before` pages back in time. The unread count covers everything."""
    stmt = select(Notification).where(Notification.owner_user_id == actor.user_id)
    if before is not None:
        stmt = stmt.where(Notification.created_at < before)
    rows = list(
        await s.scalars(
            stmt.order_by(Notification.created_at.desc()).limit(max(1, min(limit, 200)))
        )
    )
    unread = await s.scalar(
        select(func.count()).where(
            Notification.owner_user_id == actor.user_id, Notification.read_at.is_(None)
        )
    )
    return rows, int(unread or 0)


async def mark_read(s: AsyncSession, actor: Actor, notification_id: uuid.UUID | None) -> None:
    stmt = update(Notification).where(
        Notification.owner_user_id == actor.user_id, Notification.read_at.is_(None)
    )
    if notification_id is not None:
        exists = await s.scalar(
            select(Notification.id).where(
                Notification.id == notification_id, Notification.owner_user_id == actor.user_id
            )
        )
        if exists is None:
            raise NotFound("Notification not found.")
        stmt = stmt.where(Notification.id == notification_id)
    await s.execute(stmt.values(read_at=datetime.now(UTC)))


async def delete_notification(s: AsyncSession, actor: Actor, notification_id: uuid.UUID) -> None:
    """Remove one notification (and its delivery records). A chat reply to it is no longer
    recognised; anything it pointed at (an approval, a question) is still in the app."""
    result = await s.execute(
        delete(Notification)
        .where(Notification.id == notification_id, Notification.owner_user_id == actor.user_id)
        .returning(Notification.id)
    )
    if result.scalar_one_or_none() is None:
        raise NotFound("Notification not found.")


async def clear_notifications(s: AsyncSession, actor: Actor, *, read_only: bool) -> int:
    """Clear the read notifications, or all of them."""
    stmt = delete(Notification).where(Notification.owner_user_id == actor.user_id)
    if read_only:
        stmt = stmt.where(Notification.read_at.is_not(None))
    return len((await s.execute(stmt.returning(Notification.id))).all())


async def list_reminders(
    s: AsyncSession, actor: Actor, case_id: uuid.UUID, *, include_done: bool = False
) -> list[Reminder]:
    await get_case(s, actor, case_id)
    stmt = select(Reminder).where(
        Reminder.owner_user_id == actor.user_id, Reminder.case_id == case_id
    )
    if not include_done:
        stmt = stmt.where(Reminder.done_at.is_(None))
    return list(await s.scalars(stmt.order_by(Reminder.due_on)))


async def create_reminder(
    s: AsyncSession,
    actor: Actor,
    case_id: uuid.UUID,
    *,
    title: str,
    due_on: str,
    application_id: uuid.UUID | None,
) -> Reminder:
    await get_case(s, actor, case_id)
    try:
        date.fromisoformat(due_on)
    except ValueError as exc:
        raise ValidationFailed("Use a date like 2026-12-01.") from exc
    if application_id is not None:
        owned = await s.scalar(
            select(Application.id).where(
                Application.id == application_id,
                Application.owner_user_id == actor.user_id,
                Application.case_id == case_id,
            )
        )
        if owned is None:
            raise NotFound("Application not found.")
    r = Reminder(
        owner_user_id=actor.user_id,
        case_id=case_id,
        application_id=application_id,
        kind="custom",
        title=title.strip()[:300],
        due_on=due_on,
    )
    s.add(r)
    await s.flush()
    return r


async def _reminder(s: AsyncSession, actor: Actor, reminder_id: uuid.UUID) -> Reminder:
    r = await s.scalar(
        select(Reminder).where(Reminder.id == reminder_id, Reminder.owner_user_id == actor.user_id)
    )
    if r is None:
        raise NotFound("Reminder not found.")
    return r


async def set_reminder_done(
    s: AsyncSession, actor: Actor, reminder_id: uuid.UUID, done: bool
) -> Reminder:
    r = await _reminder(s, actor, reminder_id)
    r.done_at = datetime.now(UTC) if done else None
    await s.flush()
    return r


async def delete_reminder(s: AsyncSession, actor: Actor, reminder_id: uuid.UUID) -> None:
    await s.delete(await _reminder(s, actor, reminder_id))


def notification_dict(n: Notification) -> dict[str, Any]:
    return {
        "id": n.id,
        "kind": n.kind,
        "title": n.title,
        "body": n.body,
        "link": n.link,
        "read": n.read_at is not None,
        "created_at": n.created_at,
        "case_id": n.case_id,
    }
