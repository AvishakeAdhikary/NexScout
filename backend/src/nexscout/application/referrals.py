"""Referral suggestions for one opportunity (R-JOB-5)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.application.actor import Actor
from nexscout.application.opportunities import get_opportunity
from nexscout.domain.referrals import ReferralSuggestion, suggest_referrals
from nexscout.infrastructure.db.models import Affiliation


async def referrals_for(
    session: AsyncSession, actor: Actor, case_id: uuid.UUID, opportunity_id: uuid.UUID
) -> tuple[list[ReferralSuggestion], int]:
    view = await get_opportunity(session, actor, case_id, opportunity_id)
    rows = await session.scalars(
        select(Affiliation).where(
            Affiliation.owner_user_id == actor.user_id, Affiliation.case_id == case_id
        )
    )
    affiliations = [
        {
            "id": a.id,
            "person_name": a.person_name,
            "organization": a.organization,
            "relationship_type": a.relationship_type,
            "role": a.role,
            "status": a.status,
            "may_use_for_referral": a.may_use_for_referral,
        }
        for a in rows
    ]
    return suggest_referrals(view.opportunity.organization_name, affiliations)
