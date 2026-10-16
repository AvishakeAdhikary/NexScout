"""`phd_research`: read an opportunity's sources and record requirements with provenance.

1. `read_sources`: the listing itself, then each page it links to. Demo addresses (reserved
   `.example` hosts) come from bundled demo pages; real addresses go through the SSRF-safe
   fetcher (robots.txt respected) when web research is enabled. One commit per source, so the
   step can resume after a crash without fetching everything again.
2. `extract`: rule-based findings (`rules_v1`), each with a verbatim quote from its source;
   disagreements between sources (e.g. two different deadlines) are marked as conflicts.
Fetched pages are untrusted data: they are stored and quoted, never followed as instructions.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from nexscout.agent_runtime.context import RunContext
from nexscout.agent_runtime.registry import WorkflowSpec, register, tracked
from nexscout.domain.research import METHOD, conflicts, extract_findings
from nexscout.infrastructure.db.models import (
    Opportunity,
    OpportunityMatch,
    OpportunitySource,
    ResearchFinding,
    ResearchSource,
)
from nexscout.infrastructure.fetch import FetchBlocked, FetchFailed, SafeFetcher, html_to_text
from nexscout.integrations.research.demo_pages import demo_page, is_reserved_demo_host

MAX_PAGES = 6


class State(TypedDict, total=False):
    result: dict[str, Any]


def _opportunity_id(ctx: RunContext) -> uuid.UUID:
    return uuid.UUID(str(ctx.params["opportunity_id"]))


def listing_text(opp: Opportunity) -> str:
    """The listing as readable lines (what the source adapter gave us)."""
    d = opp.data
    lines = [f"{opp.title}", f"{opp.organization_name}"]
    if d.get("description"):
        lines.append(str(d["description"]))
    if d.get("funding"):
        lines.append(str(d["funding"]))
    if d.get("education_level"):
        lines.append(f"Expected education level: {d['education_level']}.")
    if d.get("required_skills"):
        lines.append(f"Required skills: {', '.join(map(str, d['required_skills']))}.")
    if d.get("research_areas"):
        lines.append(f"Research areas: {', '.join(map(str, d['research_areas']))}.")
    if d.get("closes_at"):
        lines.append(f"Closing date: {d['closes_at']}.")
    return "\n".join(lines)


async def _upsert_source(ctx: RunContext, values: dict[str, Any]) -> None:
    async with ctx.tenant() as s:
        stmt = insert(ResearchSource).values(
            id=uuid.uuid4(), owner_user_id=ctx.owner_user_id, case_id=ctx.case_id, **values
        )
        update = {k: stmt.excluded[k] for k in values if k not in ("url", "opportunity_id")}
        await s.execute(
            stmt.on_conflict_do_update(constraint="uq_research_sources_case_url", set_=update)
        )


async def read_sources(state: State, runtime: Runtime[RunContext]) -> dict[str, Any]:
    ctx = runtime.context
    step = ctx.extras.get("current_step")
    opp_id = _opportunity_id(ctx)
    async with ctx.tenant() as s:
        match = await s.scalar(
            select(OpportunityMatch.id).where(
                OpportunityMatch.case_id == ctx.case_id, OpportunityMatch.opportunity_id == opp_id
            )
        )
        if match is None:
            raise LookupError("This position is no longer in your list.")
        opp = await s.get(Opportunity, opp_id)
        if opp is None:
            raise LookupError("This position no longer exists.")
        links = list(
            await s.scalars(
                select(OpportunitySource.source_url).where(
                    OpportunitySource.opportunity_id == opp_id
                )
            )
        )
        title, text = opp.title, listing_text(opp)
        canonical = opp.canonical_url
    now = datetime.now(UTC)
    listing_url = links[0] if links else f"urn:nexscout:opportunity:{opp_id}"
    await _upsert_source(
        ctx,
        {
            "opportunity_id": opp_id,
            "url": f"{listing_url}#listing",
            "final_url": listing_url,
            "title": f"Listing: {title}",
            "origin": "listing",
            "status": "ok",
            "http_status": None,
            "content_type": "text/plain",
            "content_hash": hashlib.sha256(text.encode()).hexdigest(),
            "text": text,
            "links": [],
            "error": None,
            "retrieved_at": now,
        },
    )
    urls = list(dict.fromkeys([u for u in [canonical, *links] if u]))[:MAX_PAGES]
    fetcher = SafeFetcher(allow_private=False)
    read = 0
    for url in urls:
        values: dict[str, Any] = {
            "opportunity_id": opp_id,
            "url": url,
            "final_url": None,
            "title": None,
            "http_status": None,
            "content_type": None,
            "content_hash": None,
            "text": "",
            "links": [],
            "error": None,
            "retrieved_at": datetime.now(UTC),
        }
        if is_reserved_demo_host(url):
            page = demo_page(url)
            if page is None:
                values.update(
                    origin="demo", status="skipped", error="No demo page for this address."
                )
            else:
                page_title, html = page
                _, page_text, page_links = html_to_text(html, url)
                values.update(
                    origin="demo",
                    status="ok",
                    final_url=url,
                    title=page_title,
                    content_type="text/html",
                    content_hash=hashlib.sha256(html.encode()).hexdigest(),
                    text=page_text,
                    links=[list(x) for x in page_links],
                )
                read += 1
        elif not ctx.settings.research_fetch_enabled:
            values.update(origin="web", status="skipped", error="Reading web pages is turned off.")
        else:
            await ctx.note(step, f"Reading {url}")
            try:
                res = await fetcher.fetch(url)
                values.update(
                    origin="web",
                    status="ok",
                    final_url=res.final_url,
                    title=res.title,
                    http_status=res.status,
                    content_type=res.content_type,
                    content_hash=res.sha256,
                    text=res.text,
                    links=[list(x) for x in res.links[:500]],
                    retrieved_at=res.fetched_at,
                )
                read += 1
            except FetchBlocked as exc:
                values.update(origin="web", status="blocked", error=str(exc)[:500])
            except FetchFailed as exc:
                values.update(origin="web", status="failed", error=str(exc)[:500])
        await _upsert_source(ctx, values)
    await ctx.note(step, f"Read the listing and {read} of {len(urls)} linked page(s).")
    return {}


async def extract(state: State, runtime: Runtime[RunContext]) -> dict[str, Any]:
    ctx = runtime.context
    opp_id = _opportunity_id(ctx)
    async with ctx.tenant() as s:
        sources = list(
            await s.scalars(
                select(ResearchSource).where(
                    ResearchSource.case_id == ctx.case_id,
                    ResearchSource.opportunity_id == opp_id,
                    ResearchSource.status == "ok",
                )
            )
        )
        pairs: list[tuple[str, uuid.UUID, Any]] = []
        for src in sources:
            links = [(str(x[0]), str(x[1])) for x in src.links or [] if len(x) == 2]
            for f in extract_findings(src.text, links):
                pairs.append((src.url, src.id, f))
        notes = conflicts([(url, f) for url, _, f in pairs])
        # Replace this method's previous findings in one transaction (safe to re-run).
        await s.execute(
            delete(ResearchFinding).where(
                ResearchFinding.case_id == ctx.case_id,
                ResearchFinding.opportunity_id == opp_id,
                ResearchFinding.method == METHOD,
            )
        )
        for i, (_, source_id, f) in enumerate(pairs):
            s.add(
                ResearchFinding(
                    owner_user_id=ctx.owner_user_id,
                    case_id=ctx.case_id,
                    opportunity_id=opp_id,
                    source_id=source_id,
                    kind=f.kind.value,
                    field=f.field,
                    summary=f.summary[:500],
                    quote=f.quote,
                    value=f.value,
                    confidence=f.confidence,
                    method=METHOD,
                    status="conflict" if i in notes else "current",
                    note=notes.get(i),
                )
            )
        demo = any(src.origin in ("demo",) for src in sources)
    kinds: dict[str, int] = {}
    for _, _, f in pairs:
        kinds[f.kind.value] = kinds.get(f.kind.value, 0) + 1
    await ctx.note(
        ctx.extras.get("current_step"),
        f"Found {len(pairs)} item(s); {len(notes)} disagree between sources.",
    )
    return {
        "result": {
            "opportunity_id": str(opp_id),
            "sources": len(sources),
            "findings": len(pairs),
            "by_kind": kinds,
            "conflicts": len(notes),
            "demo_data": demo,
        }
    }


def build() -> StateGraph[State, RunContext, Any, Any]:
    g: StateGraph[State, RunContext, Any, Any] = StateGraph(State, context_schema=RunContext)
    g.add_node("read_sources", cast(Any, tracked("read_sources", read_sources)))
    g.add_node("extract", cast(Any, tracked("extract", extract)))
    g.add_edge(START, "read_sources")
    g.add_edge("read_sources", "extract")
    g.add_edge("extract", END)
    return g


SPEC = register(
    WorkflowSpec(
        kind="phd_research",
        title="Research a position",
        description="Reads the listing and its linked pages and records requirements, deadlines "
        "and supervisors, each with a quote from its source.",
        build=build,
        user_startable=False,
    )
)
