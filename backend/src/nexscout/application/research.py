"""Opportunity research for a case: start it, and read what was found (with provenance)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.application.actor import Actor
from nexscout.application.opportunities import get_opportunity
from nexscout.application.runs import start_run
from nexscout.infrastructure.db.models import ResearchFinding, ResearchSource, WorkflowRun


@dataclass
class ResearchView:
    sources: list[ResearchSource]
    findings: list[ResearchFinding]


async def start_research(
    session: AsyncSession, actor: Actor, case_id: uuid.UUID, opportunity_id: uuid.UUID
) -> WorkflowRun:
    await get_opportunity(session, actor, case_id, opportunity_id)  # 404 unless it's this case's
    return await start_run(
        session,
        actor,
        case_id,
        kind="phd_research",
        params={"opportunity_id": str(opportunity_id)},
        internal=True,
    )


async def get_research(
    session: AsyncSession, actor: Actor, case_id: uuid.UUID, opportunity_id: uuid.UUID
) -> ResearchView:
    await get_opportunity(session, actor, case_id, opportunity_id)
    sources = list(
        await session.scalars(
            select(ResearchSource)
            .where(
                ResearchSource.owner_user_id == actor.user_id,
                ResearchSource.case_id == case_id,
                ResearchSource.opportunity_id == opportunity_id,
            )
            .order_by(ResearchSource.retrieved_at)
        )
    )
    findings = list(
        await session.scalars(
            select(ResearchFinding)
            .where(
                ResearchFinding.owner_user_id == actor.user_id,
                ResearchFinding.case_id == case_id,
                ResearchFinding.opportunity_id == opportunity_id,
            )
            .order_by(ResearchFinding.kind, ResearchFinding.created_at)
        )
    )
    return ResearchView(sources, findings)
