"""Opportunity discovery: source configuration, incremental sync with dedup, explained matches.

Interim (until the M4 worker): sync runs in the request. Fixture sources are small and local.
Live sources will run as durable worker tasks.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import and_, func, literal_column, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.application.actor import Actor
from nexscout.application.audit import record_audit
from nexscout.application.cases import get_case
from nexscout.application.profile import list_facts
from nexscout.application.relationships import get_preferences
from nexscout.domain.cases import CareerPath
from nexscout.domain.errors import ConcurrencyConflict, NotFound, ValidationFailed
from nexscout.domain.matching import CandidateSummary, MatchResult, match, summarize
from nexscout.domain.mindmap import normalize_org
from nexscout.domain.opportunities import (
    ACADEMIC_KINDS,
    DedupDecision,
    NormalizedOpportunity,
    OpportunityKind,
    candidate_from,
    decide,
    normalize_title,
)
from nexscout.domain.profile import ReviewState, Section
from nexscout.infrastructure.db.engine import bind_tenant
from nexscout.infrastructure.db.models import (
    DedupReport,
    Opportunity,
    OpportunityMatch,
    OpportunitySource,
    Organization,
    SourceConfig,
    SyncCheckpoint,
)
from nexscout.integrations.sources.base import (
    SourceAdapter,
    SourceQuery,
    SourceSettings,
    content_hash,
    query_hash,
)
from nexscout.integrations.sources.registry import adapters, get_adapter

MAX_PAGES = 50
MAX_DEDUP_CANDIDATES = 200
MATCH_STATUSES = frozenset({"new", "seen", "shortlisted", "dismissed"})


def kinds_for(path: CareerPath) -> frozenset[OpportunityKind]:
    if path is CareerPath.PHD:
        return frozenset(ACADEMIC_KINDS)
    if path is CareerPath.EMPLOYMENT:
        return frozenset({OpportunityKind.JOB})
    return frozenset(OpportunityKind)


# ------------------------------------------------------------------------------- sources
@dataclass
class SourceView:
    adapter: SourceAdapter
    enabled: bool
    settings: dict[str, Any]


async def list_sources(session: AsyncSession, actor: Actor) -> list[SourceView]:
    configs = {
        c.adapter_key: c
        for c in await session.scalars(
            select(SourceConfig).where(SourceConfig.owner_user_id == actor.user_id)
        )
    }
    out = []
    for key, adapter in adapters().items():
        cfg = configs.get(key)
        out.append(SourceView(adapter, cfg.enabled if cfg else True, cfg.settings if cfg else {}))
    return out


_ALLOWED_SETTINGS = {"include_later_postings": bool, "keywords": list}


async def configure_source(
    session: AsyncSession,
    actor: Actor,
    key: str,
    *,
    enabled: bool,
    settings: dict[str, Any],
) -> SourceView:
    adapter = get_adapter(key)
    if adapter is None:
        raise NotFound("Source not found.")
    for name, value in settings.items():
        expected = _ALLOWED_SETTINGS.get(name)
        if expected is None or not isinstance(value, expected):
            raise ValidationFailed(f"Unsupported setting: {name}")
    if "keywords" in settings:
        kws = settings["keywords"]
        if len(kws) > 20 or not all(isinstance(k, str) and 0 < len(k) <= 80 for k in kws):
            raise ValidationFailed("Up to 20 keywords of at most 80 characters.")
    stmt = (
        insert(SourceConfig)
        .values(
            id=uuid.uuid4(),
            owner_user_id=actor.user_id,
            adapter_key=key,
            enabled=enabled,
            settings=settings,
        )
        .on_conflict_do_update(
            constraint="uq_source_configs_owner_key",
            set_={"enabled": enabled, "settings": settings},
        )
    )
    await session.execute(stmt)
    record_audit(
        session,
        "source.configured",
        actor_user_id=actor.user_id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={"source": key, "enabled": enabled},
    )
    return SourceView(adapter, enabled, settings)


# --------------------------------------------------------------------------------- sync
@dataclass
class SyncSummary:
    source_key: str
    fetched: int = 0
    new_opportunities: int = 0
    merged_duplicates: int = 0
    updated: int = 0
    unchanged: int = 0
    invalid: int = 0
    new_for_case: int = 0
    skipped_reason: str | None = None
    merges: list[dict[str, Any]] = field(default_factory=list)


async def _candidate(session: AsyncSession, actor: Actor, case_id: uuid.UUID) -> CandidateSummary:
    prefs, _ = await get_preferences(session, actor, case_id)
    facts = await list_facts(session, actor, case_id, review_state=ReviewState.ACCEPTED)
    return summarize([(str(f.id), Section(f.section), f.data) for f in facts], prefs)


async def _organization(session: AsyncSession, name: str) -> Organization:
    key = normalize_org(name) or name.strip().lower()
    await session.execute(
        insert(Organization)
        .values(
            id=uuid.uuid4(),
            name=name.strip(),
            normalized_key=key,
            aliases=[],
        )
        .on_conflict_do_nothing(index_elements=["normalized_key"])
    )
    org = await session.scalar(select(Organization).where(Organization.normalized_key == key))
    assert org is not None
    return org


def _status(opp: NormalizedOpportunity, today: date) -> str:
    if opp.closes_at is None:
        return "unknown"
    return "closed" if opp.closes_at < today else "open"


async def _upsert_listing(
    session: AsyncSession,
    adapter: SourceAdapter,
    record: dict[str, Any],
    today: date,
    summary: SyncSummary,
) -> Opportunity | None:
    try:
        norm = adapter.normalize(record)
    except ValidationError:
        summary.invalid += 1
        return None
    summary.fetched += 1
    digest = content_hash(norm)
    now = datetime.now(UTC)
    new_cand = candidate_from(norm)
    # Serialize per employer and per canonical URL so concurrent syncs can't create duplicates.
    # Locks are taken in a global (sorted) order and held only for this listing's short
    # transaction (the caller commits per listing), so syncs can't deadlock each other.
    lock_keys = sorted(
        {new_cand.employer_key or norm.organization_name.lower(), new_cand.canonical_url or ""}
        - {""}
    )
    for key in lock_keys:
        await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(key))))
    # Look up again under the lock: another sync may have just committed this listing.
    src = await session.scalar(
        select(OpportunitySource).where(
            OpportunitySource.source_key == adapter.key,
            OpportunitySource.external_id == norm.external_id,
        )
    )
    if src is not None:
        opp = await session.get(Opportunity, src.opportunity_id)
        assert opp is not None
        if src.content_hash != digest:
            src.content_hash, src.raw, src.retrieved_at = digest, record, now
            src.source_url = norm.source_url
            # A posting merged from several sources keeps the data of the source that first
            # listed it; a later source's edit must not flip its title or details.
            primary = await session.scalar(
                select(OpportunitySource.id)
                .where(OpportunitySource.opportunity_id == opp.id)
                .order_by(OpportunitySource.id)  # UUIDv7: creation order
                .limit(1)
            )
            if primary is None or primary == src.id:
                opp.data = norm.model_dump(mode="json")
                opp.title, opp.normalized_title = norm.title, normalize_title(norm.title)
            summary.updated += 1
        else:
            summary.unchanged += 1
        opp.last_seen_at, opp.status = now, _status(norm, today)
        return opp

    org = await _organization(session, norm.organization_name)
    conds = [and_(Opportunity.organization_id == org.id, Opportunity.kind == norm.kind.value)]
    if new_cand.canonical_url:
        conds.append(Opportunity.canonical_url == new_cand.canonical_url)
    existing = list(
        await session.scalars(select(Opportunity).where(or_(*conds)).limit(MAX_DEDUP_CANDIDATES))
    )
    best: tuple[Opportunity, DedupDecision] | None = None
    for ex in existing:
        trial = decide(new_cand, candidate_from(NormalizedOpportunity.model_validate(ex.data)))
        if trial.duplicate and (best is None or trial.score > best[1].score):
            best = (ex, trial)
    decision: DedupDecision | None = None
    if best is not None:
        opp, decision = best
        summary.merged_duplicates += 1
        summary.merges.append(
            {"external_id": norm.external_id, "into": str(opp.id), "reasons": decision.reasons}
        )
    else:
        opp = Opportunity(
            kind=norm.kind.value,
            organization_id=org.id,
            organization_name=norm.organization_name,
            title=norm.title,
            normalized_title=normalize_title(norm.title),
            canonical_url=new_cand.canonical_url,
            requisition_id=norm.requisition_id,
            data=norm.model_dump(mode="json"),
            status=_status(norm, today),
        )
        session.add(opp)
        await session.flush()
        summary.new_opportunities += 1
    session.add(
        OpportunitySource(
            opportunity_id=opp.id,
            source_key=adapter.key,
            external_id=norm.external_id,
            source_url=norm.source_url,
            content_hash=digest,
            raw=record,
            dedup_score=decision.score if decision else None,
            dedup_reasons=decision.reasons if decision else [],
        )
    )
    opp.last_seen_at = now
    return opp


def _match_values(result: MatchResult) -> dict[str, Any]:
    return {
        "score": result.score,
        "eligible": result.eligible,
        "mode": result.mode,
        "factors": [asdict(f) for f in result.factors],
        "gaps": [asdict(g) for g in result.gaps],
    }


async def _upsert_match(
    session: AsyncSession,
    actor: Actor,
    case_id: uuid.UUID,
    opp: Opportunity,
    cand: CandidateSummary,
    today: date,
) -> bool:
    """Returns True if this opportunity is new for this case."""
    result = match(NormalizedOpportunity.model_validate(opp.data), cand, today)
    values = _match_values(result)
    # In Postgres, xmax = 0 on the returned row means this statement inserted it (vs. updated).
    inserted: Result[Any] = await session.execute(
        insert(OpportunityMatch)
        .values(
            id=uuid.uuid4(),
            owner_user_id=actor.user_id,
            case_id=case_id,
            opportunity_id=opp.id,
            status="new",
            **values,
        )
        .on_conflict_do_update(
            constraint="uq_opportunity_matches_case_opp",
            set_={**values, "computed_at": func.now()},
        )
        .returning(literal_column("(xmax = 0)").label("inserted"))
    )
    return bool(inserted.scalar_one())


async def _commit(session: AsyncSession, actor: Actor) -> None:
    """Commit and re-bind the tenant (app.user_id is transaction-local)."""
    await session.commit()
    await bind_tenant(session, actor.user_id)


async def sync_case(
    session: AsyncSession,
    actor: Actor,
    case_id: uuid.UUID,
    *,
    source_keys: list[str] | None = None,
    today: date | None = None,
) -> list[SyncSummary]:
    case = await get_case(session, actor, case_id)
    today = today or date.today()
    wanted_kinds = kinds_for(CareerPath(case.career_path))
    views = {v.adapter.key: v for v in await list_sources(session, actor)}
    keys = source_keys or [k for k, v in views.items() if v.enabled]
    cand = await _candidate(session, actor, case_id)
    summaries: list[SyncSummary] = []
    for key in keys:
        view = views.get(key)
        if view is None:
            raise NotFound(f"Source not found: {key}")
        summary = SyncSummary(source_key=key)
        summaries.append(summary)
        if not view.enabled:
            summary.skipped_reason = "This source is turned off."
            continue
        kinds = view.adapter.capabilities.kinds & wanted_kinds
        if not kinds:
            summary.skipped_reason = "This source has no opportunities for this case's path."
            continue
        query = SourceQuery(
            kinds=frozenset(kinds), keywords=tuple(view.settings.get("keywords", []))
        )
        qhash = query_hash(query)
        checkpoint = await session.scalar(
            select(SyncCheckpoint).where(
                SyncCheckpoint.case_id == case_id,
                SyncCheckpoint.adapter_key == key,
                SyncCheckpoint.query_hash == qhash,
            )
        )
        if checkpoint is None:
            checkpoint = SyncCheckpoint(
                owner_user_id=actor.user_id, case_id=case_id, adapter_key=key, query_hash=qhash
            )
            session.add(checkpoint)
        cursor = checkpoint.cursor  # resume an interrupted sync
        settings = SourceSettings(dict(view.settings))
        for _ in range(MAX_PAGES):
            page = await view.adapter.fetch(query, cursor, settings)
            for record in page.records:
                opp = await _upsert_listing(session, view.adapter, record, today, summary)
                if opp is not None and await _upsert_match(
                    session, actor, case_id, opp, cand, today
                ):
                    summary.new_for_case += 1
                await _commit(session, actor)  # one short transaction per listing
            cursor = page.next_cursor
            checkpoint.cursor = cursor  # resumable: progress survives an interruption
            await _commit(session, actor)
            if cursor is None:
                break
        checkpoint.last_run_at = datetime.now(UTC)
        checkpoint.last_result = {k: v for k, v in asdict(summary).items() if k != "merges"}
    record_audit(
        session,
        "opportunities.synced",
        actor_user_id=actor.user_id,
        target_type="case",
        target_id=case_id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={"sources": keys, "new": sum(s.new_for_case for s in summaries)},
    )
    return summaries


async def start_sync(
    session: AsyncSession, actor: Actor, case_id: uuid.UUID, *, source_keys: list[str] | None
) -> Any:
    """Validate the request now; the search itself runs on the durable worker."""
    from nexscout.application.runs import start_run

    await get_case(session, actor, case_id)
    known = adapters()
    for key in source_keys or []:
        if key not in known:
            raise NotFound(f"Source not found: {key}")
    params: dict[str, Any] = {"sources": source_keys} if source_keys else {}
    return await start_run(session, actor, case_id, kind="opportunity_discovery", params=params)


async def rescore_case(
    session: AsyncSession, actor: Actor, case_id: uuid.UUID, today: date | None = None
) -> int:
    """Recompute every match for this case (after profile or preference changes)."""
    await get_case(session, actor, case_id)
    cand = await _candidate(session, actor, case_id)
    today = today or date.today()
    rows = (
        await session.execute(
            select(OpportunityMatch, Opportunity)
            .join(Opportunity, Opportunity.id == OpportunityMatch.opportunity_id)
            .where(
                OpportunityMatch.case_id == case_id, OpportunityMatch.owner_user_id == actor.user_id
            )
        )
    ).all()
    for m, opp in rows:
        values = _match_values(match(NormalizedOpportunity.model_validate(opp.data), cand, today))
        for k, v in values.items():
            setattr(m, k, v)
        m.computed_at = datetime.now(UTC)
    return len(rows)


# ------------------------------------------------------------------------------- queries
@dataclass
class OpportunityView:
    match: OpportunityMatch
    opportunity: Opportunity
    sources: list[OpportunitySource]


async def list_opportunities(
    session: AsyncSession,
    actor: Actor,
    case_id: uuid.UUID,
    *,
    academic: bool | None = None,
    status: str | None = None,
    include_ineligible: bool = True,
) -> list[OpportunityView]:
    await get_case(session, actor, case_id)
    stmt = (
        select(OpportunityMatch, Opportunity)
        .join(Opportunity, Opportunity.id == OpportunityMatch.opportunity_id)
        .where(OpportunityMatch.case_id == case_id, OpportunityMatch.owner_user_id == actor.user_id)
    )
    if academic is True:
        stmt = stmt.where(Opportunity.kind.in_([k.value for k in ACADEMIC_KINDS]))
    elif academic is False:
        stmt = stmt.where(Opportunity.kind == OpportunityKind.JOB.value)
    if status is not None:
        stmt = stmt.where(OpportunityMatch.status == status)
    if not include_ineligible:
        stmt = stmt.where(OpportunityMatch.eligible.is_(True))
    stmt = stmt.order_by(
        OpportunityMatch.eligible.desc(), OpportunityMatch.score.desc(), Opportunity.title
    )
    rows = (await session.execute(stmt)).all()
    ids = [opp.id for _, opp in rows]
    sources: dict[uuid.UUID, list[OpportunitySource]] = {}
    if ids:
        for src in await session.scalars(
            select(OpportunitySource)
            .where(OpportunitySource.opportunity_id.in_(ids))
            .order_by(OpportunitySource.retrieved_at)
        ):
            sources.setdefault(src.opportunity_id, []).append(src)
    return [OpportunityView(m, opp, sources.get(opp.id, [])) for m, opp in rows]


async def get_opportunity(
    session: AsyncSession, actor: Actor, case_id: uuid.UUID, opportunity_id: uuid.UUID
) -> OpportunityView:
    await get_case(session, actor, case_id)
    row = (
        await session.execute(
            select(OpportunityMatch, Opportunity)
            .join(Opportunity, Opportunity.id == OpportunityMatch.opportunity_id)
            .where(
                OpportunityMatch.case_id == case_id,
                OpportunityMatch.owner_user_id == actor.user_id,
                OpportunityMatch.opportunity_id == opportunity_id,
            )
        )
    ).first()
    if row is None:
        raise NotFound("Opportunity not found.")
    m, opp = row
    sources = list(
        await session.scalars(
            select(OpportunitySource)
            .where(OpportunitySource.opportunity_id == opp.id)
            .order_by(OpportunitySource.retrieved_at)
        )
    )
    return OpportunityView(m, opp, sources)


async def set_match_status(
    session: AsyncSession,
    actor: Actor,
    case_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    *,
    status: str,
    expected_version: int,
) -> OpportunityView:
    if status not in MATCH_STATUSES:
        raise ValidationFailed("Unknown status.")
    view = await get_opportunity(session, actor, case_id, opportunity_id)
    result = await session.execute(
        update(OpportunityMatch)
        .where(
            OpportunityMatch.id == view.match.id,
            OpportunityMatch.owner_user_id == actor.user_id,
            OpportunityMatch.version == expected_version,
        )
        .values(status=status, version=OpportunityMatch.version + 1)
        .returning(OpportunityMatch.id)
    )
    if result.scalar_one_or_none() is None:
        raise ConcurrencyConflict("This item was changed elsewhere. Reload and try again.")
    await session.refresh(view.match)
    return view


async def report_dedup(
    session: AsyncSession,
    actor: Actor,
    case_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    *,
    kind: str,
    other_opportunity_id: uuid.UUID | None,
    note: str | None,
) -> DedupReport:
    await get_opportunity(session, actor, case_id, opportunity_id)
    if other_opportunity_id is not None:
        await get_opportunity(session, actor, case_id, other_opportunity_id)
    if kind not in {"wrong_merge", "missed_duplicate"}:
        raise ValidationFailed("Unknown report type.")
    report = DedupReport(
        owner_user_id=actor.user_id,
        case_id=case_id,
        opportunity_id=opportunity_id,
        other_opportunity_id=other_opportunity_id,
        kind=kind,
        note=(note or "").strip()[:2000] or None,
    )
    session.add(report)
    await session.flush()
    record_audit(
        session,
        "opportunity.dedup_reported",
        actor_user_id=actor.user_id,
        target_type="opportunity",
        target_id=opportunity_id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={"kind": kind},
    )
    return report
