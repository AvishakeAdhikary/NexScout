"""Opportunity sources, sync, explained matches, and duplicate reports."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from nexscout.api.deps import CurrentActor, DbSession
from nexscout.api.schemas import (
    CountryGroupOut,
    CountryOut,
    DedupReportIn,
    FactorOut,
    GeoOut,
    ManualSourceOut,
    MatchGapOut,
    MatchStatusIn,
    OpportunityOut,
    OpportunitySourceOut,
    RescoreOut,
    RunStartedOut,
    SourceAddIn,
    SourceAddOut,
    SourceBulkIn,
    SourceConfigIn,
    SourceImportIn,
    SourceImportOut,
    SourceOut,
    SourceTestOut,
    SyncIn,
)
from nexscout.application import opportunities as opps
from nexscout.application import sources
from nexscout.integrations.sources.registry import adapters

router = APIRouter(tags=["opportunities"])


def _source_out(view: opps.SourceView) -> SourceOut:
    cap = view.adapter.capabilities
    info, cfg = view.info, view.config
    return SourceOut(
        origin=info.origin if info else "demo",
        provider=info.provider if info else "",
        category=info.category if info else "",
        url=info.url if info else "",
        countries=list(info.countries) if info else [],
        last_status=cfg.last_status if cfg else None,
        last_error=cfg.last_error if cfg else None,
        last_count=cfg.last_count if cfg else None,
        last_fetched_at=cfg.last_fetched_at if cfg else None,
        key=view.adapter.key,
        name=view.adapter.name,
        kinds=sorted(k.value for k in cap.kinds),
        enabled=view.enabled,
        settings=view.settings,
        is_demo_data=cap.is_demo_data,
        auth=cap.auth,
        rate_limit=cap.rate_limit,
        terms=cap.terms,
        incremental=cap.incremental,
        pagination=cap.pagination,
        limitations=list(cap.limitations),
    )


def _opp_out(view: opps.OpportunityView) -> OpportunityOut:
    registry = adapters()
    demo = bool(view.sources) and all(
        (a := registry.get(s.source_key)) is not None and a.capabilities.is_demo_data
        for s in view.sources
    )
    m, o = view.match, view.opportunity
    return OpportunityOut(
        id=o.id,
        kind=o.kind,
        title=o.title,
        organization_name=o.organization_name,
        status=o.status,
        data=o.data,
        is_demo_data=demo,
        first_seen_at=o.first_seen_at,
        last_seen_at=o.last_seen_at,
        sources=[OpportunitySourceOut.model_validate(s) for s in view.sources],
        score=m.score,
        eligible=m.eligible,
        mode=m.mode,
        factors=[FactorOut(**f) for f in m.factors],
        gaps=[MatchGapOut(**g) for g in m.gaps],
        match_status=m.status,
        match_version=m.version,
        matched_at=m.computed_at,
    )


@router.get("/sources", response_model=list[SourceOut])
async def list_sources(actor: CurrentActor, db: DbSession) -> list[SourceOut]:
    return [_source_out(v) for v in await opps.list_sources(db, actor)]


@router.put("/sources/{source_key}", response_model=SourceOut)
async def configure_source(
    source_key: str, body: SourceConfigIn, actor: CurrentActor, db: DbSession
) -> SourceOut:
    view = await opps.configure_source(
        db, actor, source_key, enabled=body.enabled, settings=body.settings
    )
    return _source_out(view)


@router.post("/sources/bulk", response_model=dict[str, int])
async def bulk_enable(body: SourceBulkIn, actor: CurrentActor, db: DbSession) -> dict[str, int]:
    """Turn many sources on or off at once (e.g. every Finnish source)."""
    return {"changed": await sources.set_enabled(db, actor, body.keys, body.enabled)}


@router.post("/sources", response_model=SourceAddOut, status_code=status.HTTP_201_CREATED)
async def add_source(body: SourceAddIn, actor: CurrentActor, db: DbSession) -> SourceAddOut:
    """Add a source by address: a company's careers board, a job board, a feed, or a vacancies
    page with JobPosting data. NexScout checks it can read it before saving."""
    r = await sources.add_custom(
        db, actor, url=body.url, name=body.name, kinds=body.kinds, countries=body.countries
    )
    return SourceAddOut(
        key=r.key,
        provider=r.provider,
        name=r.name,
        postings=r.postings,
        already_in_catalog=r.already_in_catalog,
    )


@router.post("/sources/import", response_model=SourceImportOut)
async def import_sources(
    body: SourceImportIn, actor: CurrentActor, db: DbSession
) -> SourceImportOut:
    """Import a career-ops portals.yml."""
    r = await sources.import_portals(db, actor, body.content)
    return SourceImportOut(
        enabled_catalog=r.enabled_catalog, added=r.added, unsupported=r.unsupported
    )


@router.get("/sources/manual", response_model=list[ManualSourceOut])
async def manual_sources(actor: CurrentActor) -> list[ManualSourceOut]:
    """Boards NexScout doesn't automate, and why (search those yourself)."""
    return [ManualSourceOut(**m) for m in sources.manual_only()]


@router.post("/sources/{source_key}/test", response_model=SourceTestOut)
async def test_source(source_key: str, actor: CurrentActor, db: DbSession) -> SourceTestOut:
    return SourceTestOut(**await sources.test_source(db, actor, source_key))


@router.delete("/sources/{source_key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_key: str, actor: CurrentActor, db: DbSession) -> Response:
    await sources.delete_custom(db, actor, source_key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/geo", response_model=GeoOut)
async def geo_data() -> GeoOut:
    """Every country (ISO 3166-1) and the groups people pick from (EU, Nordics, …)."""
    from nexscout.domain.geo import countries, groups

    return GeoOut(
        countries=[
            CountryOut(code=c.code, name=c.name, continent=c.continent)
            for c in sorted(countries().values(), key=lambda c: c.name)
        ],
        groups=[CountryGroupOut(key=k, name=v[0], codes=list(v[1])) for k, v in groups().items()],
    )


@router.post(
    "/cases/{case_id}/opportunities/sync",
    response_model=RunStartedOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def sync(
    case_id: uuid.UUID, body: SyncIn, actor: CurrentActor, db: DbSession
) -> RunStartedOut:
    """Start a background search. Follow the run for progress and the per-source summary."""
    run = await opps.start_sync(db, actor, case_id, source_keys=body.sources)
    return RunStartedOut(run_id=run.id)


@router.post("/cases/{case_id}/opportunities/rescore", response_model=RescoreOut)
async def rescore(case_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> RescoreOut:
    return RescoreOut(rescored=await opps.rescore_case(db, actor, case_id))


@router.get("/cases/{case_id}/opportunities", response_model=list[OpportunityOut])
async def list_opportunities(
    case_id: uuid.UUID,
    actor: CurrentActor,
    db: DbSession,
    academic: bool | None = None,
    match_status: str | None = None,
) -> list[OpportunityOut]:
    views = await opps.list_opportunities(
        db, actor, case_id, academic=academic, status=match_status
    )
    return [_opp_out(v) for v in views]


@router.get("/cases/{case_id}/opportunities/{opportunity_id}", response_model=OpportunityOut)
async def get_opportunity(
    case_id: uuid.UUID, opportunity_id: uuid.UUID, actor: CurrentActor, db: DbSession
) -> OpportunityOut:
    return _opp_out(await opps.get_opportunity(db, actor, case_id, opportunity_id))


@router.patch("/cases/{case_id}/opportunities/{opportunity_id}", response_model=OpportunityOut)
async def set_status(
    case_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    body: MatchStatusIn,
    actor: CurrentActor,
    db: DbSession,
) -> OpportunityOut:
    view = await opps.set_match_status(
        db, actor, case_id, opportunity_id, status=body.status, expected_version=body.version
    )
    return _opp_out(view)


@router.post(
    "/cases/{case_id}/opportunities/{opportunity_id}/reports", status_code=status.HTTP_201_CREATED
)
async def report(
    case_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    body: DedupReportIn,
    actor: CurrentActor,
    db: DbSession,
) -> dict[str, str]:
    rep = await opps.report_dedup(
        db,
        actor,
        case_id,
        opportunity_id,
        kind=body.kind,
        other_opportunity_id=body.other_opportunity_id,
        note=body.note,
    )
    return {"id": str(rep.id), "status": "received"}
