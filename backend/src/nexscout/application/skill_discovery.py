"""Adding the skills the user chose from an AI suggestion run (ADR-0020).

The choices are names; everything else (the quote, the source) comes from the run's own
verified result, never from the request. Each added skill is confirmed (the user chose it in
the dialog) and keeps the quote as its evidence.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.application.actor import Actor
from nexscout.application.audit import record_audit
from nexscout.application.cases import get_case
from nexscout.application.profile import new_fact
from nexscout.domain.errors import NotFound, ValidationFailed
from nexscout.domain.profile import FactStatus, ReviewState, Section, identity_keys
from nexscout.infrastructure.db.models import Document, FactEvidence, ProfileFact, WorkflowRun

METHOD = "ai_v1"
MAX_CHOSEN = 500


async def add_discovered_skills(
    s: AsyncSession, actor: Actor, case_id: uuid.UUID, *, run_id: uuid.UUID, names: list[str]
) -> list[ProfileFact]:
    await get_case(s, actor, case_id)
    if len(names) > MAX_CHOSEN:
        raise ValidationFailed("Too many skills at once.")
    run = await s.get(WorkflowRun, run_id)
    if run is None or run.owner_user_id != actor.user_id or run.case_id != case_id:
        raise NotFound("Suggestion run not found.")
    if run.kind != "skill_discovery" or run.status != "succeeded":
        raise ValidationFailed("These suggestions aren't ready.")
    result: dict[str, Any] = run.result or {}
    chosen = set(names)
    proposals = [p for p in result.get("skills", []) if p.get("name") in chosen]

    have: set[tuple[str, ...]] = set()
    for data in await s.scalars(
        select(ProfileFact.data).where(
            ProfileFact.owner_user_id == actor.user_id,
            ProfileFact.case_id == case_id,
            ProfileFact.section == Section.SKILL.value,
        )
    ):
        have |= identity_keys(Section.SKILL, data)
    model = (result.get("model") or {}).get("name")
    created: list[ProfileFact] = []
    for p in proposals:
        data = {"name": p["name"], "category": p.get("category")}
        keys = identity_keys(Section.SKILL, data)
        if keys & have:  # already there (or chosen twice): adding again would duplicate
            continue
        have |= keys
        fact = new_fact(
            actor.user_id,
            case_id,
            Section.SKILL,
            data,
            status=FactStatus.EXTRACTED,
            review_state=ReviewState.ACCEPTED,  # the user chose it
            meta={
                "method": METHOD,
                "run_id": str(run.id),
                "model": model,
                "source_id": p.get("source_id"),
                "quote": p.get("quote"),
            },
        )
        s.add(fact)
        await s.flush()
        source = str(p.get("source_id") or "")
        quote = str(p.get("quote") or "")
        document_id: uuid.UUID | None = None
        start: int | None = None
        if source.startswith("document:"):
            doc = await s.get(Document, uuid.UUID(source.split(":", 1)[1]))
            if doc is not None and doc.owner_user_id == actor.user_id:
                document_id = doc.id
                found = (doc.text_content or "").lower().find(quote.lower())
                start = found if found >= 0 else None
        s.add(
            FactEvidence(
                owner_user_id=actor.user_id,
                fact_id=fact.id,
                document_id=document_id,
                kind="document" if document_id else "user_entry",
                method=METHOD,
                char_start=start,
                char_end=start + len(quote) if start is not None else None,
                excerpt=quote[:1000],
            )
        )
        created.append(fact)
    record_audit(
        s,
        "facts.ai_skills_added",
        actor_user_id=actor.user_id,
        target_type="case",
        target_id=case_id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={"run_id": str(run.id), "added": len(created), "chosen": len(names)},
    )
    await s.flush()
    return created
