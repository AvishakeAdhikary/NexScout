"""Autopilot (M12, ADR-0014): standing approvals for one case, run on a schedule, with a person
in the loop for everything NexScout can't decide from what it already knows.

- The **policy** says what may happen unattended (discover, research, documents, fill, submit)
  and within which limits. Submitting without asking needs explicit, recorded consent.
- A **cycle** (`autopilot_cycle` workflow) discovers positions and shortlists them with the
  deterministic rules in domain/policy.py; each shortlisted position becomes an **item**.
- The **reconciler** (worker maintenance tick, level-triggered) moves every item one stage at a
  time by calling the same use cases as the screens: research → documents → application → fill
  → submit (or ask for approval). It never guesses: document placeholders and unanswered form
  questions become questions on the user's channels, answers go to the case answer bank and
  are reused; CAPTCHAs and sign-ins are handed to the user.
- **Stop** (UI button, or "STOP" from a paired chat) turns every policy off and cancels the
  autopilot's running work.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexscout.application import runs
from nexscout.application.actor import Actor
from nexscout.application.answers import answers_for
from nexscout.application.applications import (
    create_application,
    fixture_origin,
    start_browser,
)
from nexscout.application.audit import record_audit
from nexscout.application.cases import get_case
from nexscout.application.generated_documents import save_edit, start_draft, start_render
from nexscout.application.notifications import notify
from nexscout.application.research import start_research
from nexscout.config import Settings
from nexscout.domain.drafting import PLACEHOLDER
from nexscout.domain.errors import DomainError, ValidationFailed
from nexscout.domain.forms import normalize_question
from nexscout.domain.geo import normalize_list
from nexscout.domain.opportunities import ACADEMIC_KINDS
from nexscout.domain.policy import (
    AUTO_SUBMIT_CONSENT,
    DECLARATIONS_CONSENT,
    DEFAULT_DOC_TYPES,
    DEFAULT_STEPS,
    STEPS,
    Policy,
)
from nexscout.domain.site_policy import host_of, site_verdict
from nexscout.domain.state_machines import RunStatus
from nexscout.infrastructure.db.engine import bind_tenant
from nexscout.infrastructure.db.models import (
    Application,
    AutopilotItem,
    AutopilotPolicy,
    GeneratedDocument,
    GeneratedDocumentVersion,
    Opportunity,
    WorkflowRun,
)

log = structlog.get_logger()

ACTIVE_STAGES = (
    "queued",
    "researching",
    "drafting",
    "rendering",
    "needs_input",
    "applying",
    "waiting_approval",
    "needs_user_action",
)
TERMINAL_RUN = frozenset(
    {RunStatus.SUCCEEDED.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value}
)
ALLOWED_DOC_TYPES = ("resume", "cover_letter", "academic_cv", "sop", "research_proposal")
MAX_FILL_ATTEMPTS = 3


# --- policy ----------------------------------------------------------------------------------


def to_policy(row: AutopilotPolicy) -> Policy:
    return Policy(
        enabled=row.enabled,
        steps={**DEFAULT_STEPS, **(row.steps or {})},
        min_fit=row.min_fit,
        max_new_per_run=row.max_new_per_run,
        daily_submit_cap=row.daily_submit_cap,
        per_org_cap=row.per_org_cap,
        countries=tuple(row.countries or ()),
        countries_exclude=tuple(row.countries_exclude or ()),
        kinds=tuple(row.kinds or ()),
        exclude_orgs=tuple(row.exclude_orgs or ()),
        auto_submit=row.auto_submit,
        declarations=row.declarations,
        consented=row.consented_at is not None,
    )


def _default(actor: Actor, case_id: uuid.UUID) -> AutopilotPolicy:
    return AutopilotPolicy(
        owner_user_id=actor.user_id,
        case_id=case_id,
        enabled=False,
        interval_hours=24,
        steps=dict(DEFAULT_STEPS),
        min_fit=60,
        max_new_per_run=3,
        daily_submit_cap=3,
        per_org_cap=1,
        countries=[],
        countries_exclude=[],
        kinds=[],
        exclude_orgs=[],
        doc_types=[],
        auto_submit=False,
        declarations=False,
        version=0,
    )


async def get_policy(s: AsyncSession, actor: Actor, case_id: uuid.UUID) -> AutopilotPolicy:
    """The case's policy, or an unsaved default (off) when there is none yet."""
    await get_case(s, actor, case_id)
    row = await s.scalar(
        select(AutopilotPolicy).where(
            AutopilotPolicy.case_id == case_id, AutopilotPolicy.owner_user_id == actor.user_id
        )
    )
    return row or _default(actor, case_id)


def _strings(value: Any, *, limit: int, length: int, what: str) -> list[str]:
    items = [str(v).strip() for v in (value or []) if str(v).strip()]
    if len(items) > limit or any(len(v) > length for v in items):
        raise ValidationFailed(f"Too many or too long {what}.")
    return list(dict.fromkeys(items))


async def save_policy(
    s: AsyncSession,
    actor: Actor,
    case_id: uuid.UUID,
    *,
    version: int,
    changes: dict[str, Any],
) -> AutopilotPolicy:
    await get_case(s, actor, case_id)
    row = await s.scalar(
        select(AutopilotPolicy)
        .where(AutopilotPolicy.case_id == case_id, AutopilotPolicy.owner_user_id == actor.user_id)
        .with_for_update()
    )
    if row is None:
        if version != 0:
            raise ValidationFailed("These settings changed. Reload and try again.")
        row = _default(actor, case_id)
        row.version = 1
        s.add(row)
    elif row.version != version:
        raise ValidationFailed("These settings changed. Reload and try again.")
    else:
        row.version += 1
    now = datetime.now(UTC)
    if "steps" in changes and changes["steps"] is not None:
        steps = {k: bool(v) for k, v in dict(changes["steps"]).items()}
        if set(steps) - set(STEPS):
            raise ValidationFailed("Unknown autopilot step.")
        row.steps = {**DEFAULT_STEPS, **steps}
    for key, lo, hi in (
        ("interval_hours", 1, 168),
        ("min_fit", 0, 100),
        ("max_new_per_run", 0, 20),
        ("daily_submit_cap", 0, 20),
        ("per_org_cap", 1, 10),
    ):
        if changes.get(key) is not None:
            value = int(changes[key])
            if not lo <= value <= hi:
                raise ValidationFailed(f"{key.replace('_', ' ')} must be between {lo} and {hi}.")
            setattr(row, key, value)
    for field_name in ("countries", "countries_exclude"):
        if changes.get(field_name) is not None:
            codes, unknown = normalize_list(
                _strings(changes[field_name], limit=60, length=60, what="countries")
            )
            if unknown:
                raise ValidationFailed(f"Unknown countries: {', '.join(unknown)}.")
            setattr(row, field_name, codes)
    if changes.get("kinds") is not None:
        kinds = _strings(changes["kinds"], limit=2, length=10, what="kinds")
        if set(kinds) - {"job", "academic"}:
            raise ValidationFailed("Kinds are job and academic.")
        row.kinds = kinds
    if changes.get("exclude_orgs") is not None:
        row.exclude_orgs = _strings(
            changes["exclude_orgs"], limit=50, length=200, what="organizations"
        )
    if changes.get("doc_types") is not None:
        types = _strings(changes["doc_types"], limit=5, length=30, what="document types")
        if set(types) - set(ALLOWED_DOC_TYPES):
            raise ValidationFailed("Unknown document type for autopilot.")
        row.doc_types = types
    if changes.get("auto_submit") is not None:
        if changes["auto_submit"]:
            if changes.get("consent") != AUTO_SUBMIT_CONSENT:
                raise ValidationFailed("To submit without asking, agree to the statement shown.")
            row.auto_submit, row.consent_text, row.consented_at = True, AUTO_SUBMIT_CONSENT, now
        else:
            row.auto_submit, row.declarations, row.consented_at = False, False, None
    if changes.get("declarations") is not None:
        if changes["declarations"]:
            if not row.auto_submit:
                raise ValidationFailed("Allow submitting without asking first.")
            if changes.get("declarations_consent") != DECLARATIONS_CONSENT:
                raise ValidationFailed(
                    "To tick declarations for you, agree to the statement shown."
                )
            row.declarations = True
            row.consent_text = (
                f"{row.consent_text or AUTO_SUBMIT_CONSENT}\n\n{DECLARATIONS_CONSENT}"
            )
        else:
            row.declarations = False
    if changes.get("enabled") is not None:
        was = row.enabled
        row.enabled = bool(changes["enabled"])
        if row.enabled and not was:
            row.next_run_at, row.stopped_reason = now, None
    await s.flush()
    record_audit(
        s,
        "autopilot.policy_saved",
        actor_user_id=actor.user_id,
        target_type="case",
        target_id=case_id,
        meta={
            "enabled": row.enabled,
            "auto_submit": row.auto_submit,
            "declarations": row.declarations,
            "fields": sorted(k for k, v in changes.items() if v is not None),
        },
    )
    await s.refresh(row)
    return row


async def stop_all(s: AsyncSession, actor: Actor, *, reason: str) -> dict[str, int]:
    """The kill switch: every policy off, the autopilot's running work cancelled."""
    policies = list(
        await s.scalars(
            select(AutopilotPolicy)
            .where(AutopilotPolicy.owner_user_id == actor.user_id)
            .with_for_update()
        )
    )
    for p in policies:
        p.enabled, p.stopped_reason, p.version = False, reason[:300], p.version + 1
    cancelled = 0
    items = list(
        await s.scalars(
            select(AutopilotItem)
            .where(
                AutopilotItem.owner_user_id == actor.user_id,
                AutopilotItem.stage.in_(ACTIVE_STAGES),
            )
            .with_for_update()
        )
    )
    run_ids = [uuid.UUID(r) for i in items for r in i.child_run_ids]
    cycle_runs = list(
        await s.scalars(
            select(WorkflowRun.id).where(
                WorkflowRun.owner_user_id == actor.user_id,
                WorkflowRun.kind == "autopilot_cycle",
                WorkflowRun.status.not_in(list(TERMINAL_RUN)),
            )
        )
    )
    for run_id in [*run_ids, *cycle_runs]:
        run = await s.get(WorkflowRun, run_id)
        if run is None or run.status in TERMINAL_RUN:
            continue
        try:
            await runs.control(s, actor, run_id, "cancel")
            cancelled += 1
        except DomainError:
            pass
    for i in items:
        i.stage, i.reason = "stopped", f"Stopped: {reason}"[:1000]
    record_audit(
        s,
        "autopilot.stopped",
        actor_user_id=actor.user_id,
        meta={"reason": reason[:300], "policies": len(policies), "cancelled": cancelled},
    )
    return {"policies": len(policies), "items": len(items), "runs_cancelled": cancelled}


async def run_now(s: AsyncSession, actor: Actor, case_id: uuid.UUID) -> WorkflowRun:
    policy = await get_policy(s, actor, case_id)
    if not policy.enabled:
        raise ValidationFailed("Turn autopilot on first.")
    return await _start_cycle(s, actor, policy, datetime.now(UTC))


async def _start_cycle(
    s: AsyncSession, actor: Actor, policy: AutopilotPolicy, now: datetime
) -> WorkflowRun:
    busy = await s.scalar(
        select(WorkflowRun).where(
            WorkflowRun.case_id == policy.case_id,
            WorkflowRun.kind == "autopilot_cycle",
            WorkflowRun.status.not_in(list(TERMINAL_RUN)),
        )
    )
    if busy is not None:
        return busy
    run = await runs.start_run(
        s,
        actor,
        policy.case_id,
        kind="autopilot_cycle",
        params={"policy_id": str(policy.id)},
        internal=True,
    )
    policy.last_run_at, policy.last_run_id = now, run.id
    policy.next_run_at = now + timedelta(hours=policy.interval_hours)
    return run


async def list_items(s: AsyncSession, actor: Actor, case_id: uuid.UUID) -> list[AutopilotItem]:
    await get_case(s, actor, case_id)
    return list(
        await s.scalars(
            select(AutopilotItem)
            .where(AutopilotItem.case_id == case_id, AutopilotItem.owner_user_id == actor.user_id)
            .order_by(AutopilotItem.created_at.desc())
            .limit(200)
        )
    )


# --- shortlist (called by the autopilot_cycle workflow) --------------------------------------


@dataclass
class Considered:
    opportunity_id: str
    title: str
    organization: str
    fit: int
    taken: bool
    reasons: list[str]


async def shortlist_case(
    s: AsyncSession, actor: Actor, case_id: uuid.UUID, today: date | None = None
) -> list[Considered]:
    from nexscout.application.opportunities import list_opportunities
    from nexscout.domain.policy import Candidate, shortlist

    today = today or datetime.now(UTC).date()
    row = await get_policy(s, actor, case_id)
    policy = to_policy(row)
    tracked = set(
        await s.scalars(
            select(AutopilotItem.opportunity_id).where(AutopilotItem.case_id == case_id)
        )
    ) | set(
        await s.scalars(select(Application.opportunity_id).where(Application.case_id == case_id))
    )
    org_counts: dict[str, int] = {}
    for (org,) in (
        await s.execute(select(Application.organization).where(Application.case_id == case_id))
    ).all():
        key = " ".join(org.lower().split())
        org_counts[key] = org_counts.get(key, 0) + 1
    candidates = []
    for v in await list_opportunities(s, actor, case_id):
        opp, match = v.opportunity, v.match
        closes = opp.data.get("closes_at")
        try:
            deadline = date.fromisoformat(str(closes)[:10]) if closes else None
        except ValueError:
            deadline = None
        candidates.append(
            Candidate(
                opportunity_id=str(opp.id),
                title=opp.title,
                organization=opp.organization_name,
                kind="academic" if opp.kind in {k.value for k in ACADEMIC_KINDS} else "job",
                fit=int(match.score),
                eligible=bool(match.eligible),
                open=opp.status == "open" and match.status not in ("dismissed", "hidden"),
                country=(opp.data.get("country_codes") or [None])[0]
                or opp.data.get("location_country"),
                countries=tuple(opp.data.get("country_codes") or ()),
                remote_scope=opp.data.get("remote_scope"),
                deadline=deadline,
                already_tracked=opp.id in tracked,
            )
        )
    out: list[Considered] = []
    for c, verdict in shortlist(policy, candidates, today=today, org_counts=org_counts):
        out.append(
            Considered(
                c.opportunity_id, c.title, c.organization, c.fit, verdict.allowed, verdict.reasons
            )
        )
        if verdict.allowed:
            s.add(
                AutopilotItem(
                    owner_user_id=actor.user_id,
                    case_id=case_id,
                    opportunity_id=uuid.UUID(c.opportunity_id),
                    stage="queued",
                    reason="; ".join(verdict.reasons)[:1000],
                    fit=c.fit,
                    title=c.title[:300],
                    organization=c.organization[:300],
                )
            )
    await s.flush()
    return out


# --- reconciler (worker) ---------------------------------------------------------------------


@dataclass
class Tick:
    started_cycles: int = 0
    advanced: int = 0


async def tick(
    system: async_sessionmaker[AsyncSession],
    app: async_sessionmaker[AsyncSession],
    settings: Settings,
    now: datetime | None = None,
) -> Tick:
    """One maintenance pass: start due cycles, then advance every active item."""
    now = now or datetime.now(UTC)
    out = Tick()
    async with system() as s:
        due = (
            await s.execute(
                select(AutopilotPolicy.owner_user_id, AutopilotPolicy.id).where(
                    AutopilotPolicy.enabled.is_(True), AutopilotPolicy.next_run_at <= now
                )
            )
        ).all()
        owners = set(
            await s.scalars(
                select(AutopilotItem.owner_user_id)
                .where(AutopilotItem.stage.in_(ACTIVE_STAGES))
                .distinct()
            )
        )
    for owner, policy_id in due:
        async with app() as s, s.begin():
            await bind_tenant(s, owner)
            policy = await s.get(AutopilotPolicy, policy_id, with_for_update=True)
            if policy is None or not policy.enabled or (policy.next_run_at or now) > now:
                continue
            try:
                await _start_cycle(s, _actor(owner), policy, now)
                out.started_cycles += 1
            except DomainError as exc:
                policy.next_run_at = now + timedelta(hours=1)
                log.warning("autopilot_cycle_not_started", error=str(exc)[:200])
    for owner in owners:
        try:
            out.advanced += await _advance_owner(app, settings, owner, now)
        except Exception:
            log.exception("autopilot_reconcile_failed")
    return out


def _actor(owner: uuid.UUID) -> Actor:
    return Actor(user_id=owner, session_id=uuid.uuid4(), request_id="autopilot")


async def _advance_owner(
    app: async_sessionmaker[AsyncSession], settings: Settings, owner: uuid.UUID, now: datetime
) -> int:
    async with app() as s:
        await bind_tenant(s, owner)
        ids = list(
            await s.scalars(
                select(AutopilotItem.id).where(
                    AutopilotItem.owner_user_id == owner, AutopilotItem.stage.in_(ACTIVE_STAGES)
                )
            )
        )
    moved = 0
    for item_id in ids:
        async with app() as s, s.begin():
            await bind_tenant(s, owner)
            item = await s.scalar(
                select(AutopilotItem)
                .where(AutopilotItem.id == item_id)
                .with_for_update(skip_locked=True)
            )
            if item is None or item.stage not in ACTIVE_STAGES:
                continue
            policy_row = await s.scalar(
                select(AutopilotPolicy).where(AutopilotPolicy.case_id == item.case_id)
            )
            if policy_row is None or not policy_row.enabled:
                continue
            before = (item.stage, item.reason)
            try:
                await _advance(s, settings, _actor(owner), item, policy_row, now)
            except DomainError as exc:
                item.stage, item.reason = "failed", f"{exc}"[:1000]
                await _tell(s, item, "Autopilot stopped on a position", str(exc))
            if (item.stage, item.reason) != before:
                moved += 1
    return moved


async def _children(s: AsyncSession, item: AutopilotItem) -> list[WorkflowRun]:
    ids = [uuid.UUID(r) for r in item.child_run_ids]
    if not ids:
        return []
    return list(await s.scalars(select(WorkflowRun).where(WorkflowRun.id.in_(ids))))


async def _tell(
    s: AsyncSession,
    item: AutopilotItem,
    title: str,
    body: str,
    *,
    kind: str = "autopilot",
    key: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    await notify(
        s,
        owner=item.owner_user_id,
        case_id=item.case_id,
        kind=kind,
        title=f"{title}: {item.title} ({item.organization})"[:300],
        body=body[:1000],
        link=f"/cases/{item.case_id}/autopilot",
        key=key or f"autopilot:{item.id}:{item.stage}:{title}"[:200],
        data={"autopilot_item_id": str(item.id), **(data or {})},
    )


async def _advance(
    s: AsyncSession,
    settings: Settings,
    actor: Actor,
    item: AutopilotItem,
    row: AutopilotPolicy,
    now: datetime,
) -> None:
    policy = to_policy(row)
    children = await _children(s, item)
    if any(r.status == RunStatus.WAITING_APPROVAL.value for r in children):
        item.stage, item.reason = "waiting_approval", "Waiting for your approval (sent to you)."
        return
    if any(r.status not in TERMINAL_RUN for r in children):
        return  # still working
    stage = item.stage
    if stage == "queued":
        if policy.step("research"):
            run = await start_research(s, actor, item.case_id, item.opportunity_id)
            item.child_run_ids, item.stage = [str(run.id)], "researching"
            item.reason = "Reading the posting and its linked pages."
            return
        stage = "researching"
    if stage == "researching":
        if not policy.step("documents"):
            item.stage, item.reason, item.child_run_ids = (
                "needs_input",
                "Prepare documents for this position yourself (drafting is off).",
                [],
            )
            return
        started = []
        for doc_type in await _doc_types(s, row, item):
            if await _document(s, item, doc_type) is not None:
                continue
            run = await start_draft(
                s, actor, item.case_id, doc_type=doc_type, opportunity_id=item.opportunity_id
            )
            started.append(str(run.id))
        item.child_run_ids, item.stage = started, "drafting"
        item.reason = "Writing your documents from your confirmed profile."
        return
    if stage in ("drafting", "rendering", "needs_input"):
        failed = [r for r in children if r.status == RunStatus.FAILED.value]
        if failed and stage == "drafting":
            raise ValidationFailed(f"A document couldn't be written: {failed[0].error or 'error'}")
        await _documents_ready(s, settings, actor, item, row, policy)
        return
    if stage in ("applying", "waiting_approval", "needs_user_action"):
        await _after_fill(s, settings, actor, item, policy, now)


async def _doc_types(s: AsyncSession, row: AutopilotPolicy, item: AutopilotItem) -> list[str]:
    if row.doc_types:
        return list(row.doc_types)
    kind = await s.scalar(select(Opportunity.kind).where(Opportunity.id == item.opportunity_id))
    academic = kind in {k.value for k in ACADEMIC_KINDS}
    return list(DEFAULT_DOC_TYPES["academic" if academic else "job"])


async def _document(
    s: AsyncSession, item: AutopilotItem, doc_type: str
) -> tuple[GeneratedDocument, GeneratedDocumentVersion] | None:
    row = (
        await s.execute(
            select(GeneratedDocument, GeneratedDocumentVersion)
            .join(
                GeneratedDocumentVersion,
                (GeneratedDocumentVersion.document_id == GeneratedDocument.id)
                & (GeneratedDocumentVersion.number == GeneratedDocument.current_version),
            )
            .where(
                GeneratedDocument.case_id == item.case_id,
                GeneratedDocument.opportunity_id == item.opportunity_id,
                GeneratedDocument.doc_type == doc_type,
            )
            .order_by(GeneratedDocument.created_at.desc())
            .limit(1)
        )
    ).first()
    return (row[0], row[1]) if row else None


async def _documents_ready(
    s: AsyncSession,
    settings: Settings,
    actor: Actor,
    item: AutopilotItem,
    row: AutopilotPolicy,
    policy: Policy,
) -> None:
    """Fill placeholders from the answer bank (or ask), render, check, then apply."""
    bank = await answers_for(s, item.owner_user_id, item.case_id)
    waiting: list[str] = []
    renders: list[str] = []
    doc_ids: list[str] = []
    for doc_type in await _doc_types(s, row, item):
        found = await _document(s, item, doc_type)
        if found is None:
            waiting.append(f"No {doc_type.replace('_', ' ')} yet.")
            continue
        doc, version = found
        doc_ids.append(str(doc.id))
        if version.placeholders:
            markdown, missing = version.markdown, []
            for p in version.placeholders:
                answer = bank.get(normalize_question(p))
                if answer:
                    markdown = re.sub(
                        r"\[\[PLACEHOLDER:\s*" + re.escape(p) + r"\s*\]\]", answer, markdown
                    )
                else:
                    missing.append(p)
            if not missing and not PLACEHOLDER.search(markdown):
                await save_edit(
                    s, actor, doc.id, markdown=markdown, base_version=doc.current_version
                )
                await s.refresh(doc)
                run = await start_render(s, actor, doc.id, doc.current_version)
                renders.append(str(run.id))
                continue
            for p in missing:
                await _tell(
                    s,
                    item,
                    f"NexScout needs: {p}"[:200],
                    f"Your {doc_type.replace('_', ' ')} needs: {p}. Reply with the exact text "
                    "to use. It's saved and reused; nothing is guessed.",
                    kind="question",
                    key=f"placeholder:{item.case_id}:{normalize_question(p)}"[:200],
                    data={"case_id": str(item.case_id), "question": p, "placeholder": True},
                )
            waiting.append(f"{doc.title} needs: {'; '.join(missing)}.")
            continue
        if not (version.artifacts or {}).get("pdf"):
            run = await start_render(s, actor, doc.id, version.number)
            renders.append(str(run.id))
            continue
        compliance = (version.artifacts or {}).get("compliance") or {}
        if compliance.get("status") == "blocking":
            failed = [
                c["rule"]
                for c in compliance.get("checks", [])
                if not c["ok"] and c["severity"] == "blocking"
            ]
            waiting.append(f"{doc.title} doesn't meet the posting: {'; '.join(failed)}.")
    if renders:
        item.child_run_ids, item.stage = renders, "rendering"
        item.reason = "Creating the PDF and Word files."
        return
    if waiting:
        item.stage, item.reason = "needs_input", " ".join(waiting)[:1000]
        return
    item.document_ids = doc_ids
    await _apply(s, settings, actor, item, policy)


async def _apply(
    s: AsyncSession, settings: Settings, actor: Actor, item: AutopilotItem, policy: Policy
) -> None:
    if item.application_id is None:
        existing = await s.scalar(
            select(Application).where(
                Application.case_id == item.case_id,
                Application.opportunity_id == item.opportunity_id,
            )
        )
        app = existing or await create_application(
            s,
            settings,
            actor,
            item.case_id,
            opportunity_id=item.opportunity_id,
            document_ids=[uuid.UUID(d) for d in item.document_ids],
        )
        item.application_id = app.id
    app_row = await s.get(Application, item.application_id)
    assert app_row is not None
    if not app_row.apply_url:
        item.stage = "manual"
        item.reason = "Documents are ready. This posting has no online form: apply as it says."
        await _tell(s, item, "Ready for you to send", item.reason)
        return
    verdict = site_verdict(
        app_row.apply_url, robots_allows=True, demo_origin=fixture_origin(settings)
    )
    if verdict.mode == "manual":
        item.stage, item.reason = "manual", verdict.reason
        await _tell(
            s,
            item,
            "Apply on the site yourself",
            f"{verdict.reason} Your documents are ready in NexScout.",
        )
        return
    if not policy.step("fill"):
        item.stage = "manual"
        item.reason = "Documents are ready. Filling in forms is off in your autopilot settings."
        await _tell(s, item, "Ready for you to apply", item.reason)
        return
    if await _site_busy(
        s, item.owner_user_id, app_row.apply_url, settings.autopilot_site_spacing_s
    ):
        item.reason = "Waiting a few minutes before opening this site again."
        return
    run = await start_browser(s, actor, app_row.id, autopilot=True)
    item.child_run_ids, item.stage, item.attempts = [str(run.id)], "applying", item.attempts + 1
    item.reason = "Filling in the application form."


async def _site_busy(s: AsyncSession, owner: uuid.UUID, url: str, spacing_s: float) -> bool:
    """Per-site pacing: at most one autopilot browser session per site every few minutes."""
    if spacing_s <= 0:
        return False
    since = datetime.now(UTC) - timedelta(seconds=spacing_s)
    rows = (
        await s.execute(
            select(Application.apply_url)
            .join(
                WorkflowRun,
                WorkflowRun.params["application_id"].astext == func.cast(Application.id, _text()),
            )
            .where(
                WorkflowRun.owner_user_id == owner,
                WorkflowRun.kind == "browser_apply",
                WorkflowRun.created_at > since,
                WorkflowRun.params["autopilot"].astext == "true",
            )
        )
    ).all()
    host = host_of(url)
    return any(host_of(u or "") == host for (u,) in rows)


def _text() -> Any:
    from sqlalchemy import Text

    return Text()


async def _after_fill(
    s: AsyncSession,
    settings: Settings,
    actor: Actor,
    item: AutopilotItem,
    policy: Policy,
    now: datetime,
) -> None:
    app = await s.get(Application, item.application_id) if item.application_id else None
    if app is None:
        raise ValidationFailed("The application was deleted.")
    status = app.status
    if status in ("submitted", "tracking", "completed"):
        item.stage = "submitted"
        item.reason = f"Submitted ({(app.evidence or {}).get('source', 'unknown')} evidence)."
        await _tell(s, item, "Application submitted", item.reason, kind="submitted")
        return
    if status in ("awaiting_review", "approved"):
        item.stage, item.reason = "waiting_approval", "Waiting for your approval (sent to you)."
        return
    if status == "preparing":
        item.stage, item.reason = "skipped", "You chose not to submit. Nothing was sent."
        return
    if status == "submission_uncertain":
        item.stage = "needs_user_action"
        item.reason = "The site didn't confirm the submission. Check, then confirm in NexScout."
        return
    if status == "needs_user_action":
        missing = _missing_questions(app)
        if missing:
            bank = await answers_for(s, item.owner_user_id, item.case_id)
            known = {**bank, **(app.answers or {})}
            if all(normalize_question(q) in known for q in missing):
                if item.attempts >= MAX_FILL_ATTEMPTS:
                    raise ValidationFailed("The form still isn't complete after 3 tries.")
                await _apply(s, settings, actor, item, policy)
                return
        item.stage = "needs_user_action"
        item.reason = (app.blocker or "The application needs you.")[:1000]
        return
    if status == "failed":
        if item.attempts < 2:
            await _apply(s, settings, actor, item, policy)
            return
        raise ValidationFailed(app.blocker or "Filling in the form failed twice.")
    item.reason = f"Application is {status.replace('_', ' ')}."


def _missing_questions(app: Application) -> list[str]:
    """The questions the last fill couldn't answer (from the blocker text's event payload)."""
    text = app.blocker or ""
    marker = "The form asks for things NexScout has no answer for: "
    if not text.startswith(marker):
        return []
    body = text[len(marker) :].removesuffix(". Add your answers, then try again.")
    return [q.strip() for q in body.split(";") if q.strip()]


async def digest(
    app: async_sessionmaker[AsyncSession],
    system: async_sessionmaker[AsyncSession],
    now: datetime | None = None,
) -> int:
    """Once a day per user with autopilot on: what happened and what waits for them."""
    now = now or datetime.now(UTC)
    async with system() as s:
        owners = set(
            await s.scalars(
                select(AutopilotPolicy.owner_user_id).where(AutopilotPolicy.enabled.is_(True))
            )
        )
    sent = 0
    for owner in owners:
        async with app() as s, s.begin():
            await bind_tenant(s, owner)
            counts = dict(
                (
                    await s.execute(
                        select(AutopilotItem.stage, func.count())
                        .where(AutopilotItem.owner_user_id == owner)
                        .group_by(AutopilotItem.stage)
                    )
                ).all()
            )
            if not counts:
                continue
            waiting = sum(
                counts.get(k, 0)
                for k in ("needs_input", "waiting_approval", "needs_user_action", "manual")
            )
            body = (
                f"Submitted: {counts.get('submitted', 0)} · Waiting for you: {waiting} · "
                f"In progress: {sum(counts.get(k, 0) for k in ACTIVE_STAGES) - waiting}"
            )
            sent += await notify(
                s,
                owner=owner,
                case_id=None,
                kind="digest",
                title="Your NexScout autopilot today",
                body=body,
                link="/cases",
                key=f"digest:{owner}:{now.date().isoformat()}",
            )
    return sent
