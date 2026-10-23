"""The AI assistant's tool executor and conversations (ADR-0020).

Each allowed tool (`domain/assistant_tools.TOOLS`) runs the same use case a screen uses, as the
user, and returns plain data for the model plus links for the user. Results are what the user
could already see; nothing here submits, sends, approves, pays or deletes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.application import dashboard
from nexscout.application import generated_documents as gen
from nexscout.application import notifications as notes
from nexscout.application import opportunities as opps
from nexscout.application.actor import Actor
from nexscout.application.applications import list_applications
from nexscout.application.audit import record_audit
from nexscout.application.cases import get_case
from nexscout.application.profile import profile_gaps
from nexscout.application.research import start_research
from nexscout.application.runs import start_run
from nexscout.domain.assistant_tools import ToolCall
from nexscout.domain.errors import NotFound, ValidationFailed
from nexscout.infrastructure.db.models import ChatConversation, ChatMessage, WorkflowRun

MAX_RESULT_ITEMS = 10


@dataclass
class ToolOutcome:
    data: dict[str, Any]  # for the model (as untrusted data)
    actions: list[dict[str, str]] = field(default_factory=list)  # links for the user


def _opp_brief(v: opps.OpportunityView) -> dict[str, Any]:
    d = v.opportunity.data
    return {
        "id": str(v.opportunity.id),
        "title": v.opportunity.title,
        "organization": v.opportunity.organization_name,
        "kind": v.opportunity.kind,
        "location": ", ".join(
            str(x) for x in (d.get("location_city"), d.get("location_country")) if x
        ),
        "deadline": d.get("closes_at"),
        "fit_estimate": v.match.score,
        "fits_requirements": v.match.eligible,
        "gaps": [g.get("message") for g in v.match.gaps][:5],
    }


async def run_tool(
    s: AsyncSession, actor: Actor, case_id: uuid.UUID, call: ToolCall
) -> ToolOutcome:
    """Run one allowed tool. Domain errors surface to the caller (told to the model)."""
    base = f"/cases/{case_id}"
    a = call.args
    if call.name == "needs_you":
        items = await dashboard.needs_you(s, actor, case_id)
        return ToolOutcome(
            {"items": [i["title"] for i in items[:MAX_RESULT_ITEMS]], "total": len(items)},
            [{"label": i["title"], "href": i["href"]} for i in items[:5]],
        )
    if call.name == "upcoming_deadlines":
        items = await dashboard.upcoming(s, actor, case_id, await dashboard.user_today(s, actor))
        return ToolOutcome(
            {"items": [{"date": i["date"], "title": i["title"]} for i in items[:MAX_RESULT_ITEMS]]},
            [{"label": f"{i['date']}: {i['title']}", "href": i["href"]} for i in items[:5]],
        )
    if call.name == "find_applications":
        apps = await list_applications(s, actor, case_id, q=a.get("q") or None)
        return ToolOutcome(
            {
                "applications": [
                    {
                        "title": x.title,
                        "organization": x.organization,
                        "status": x.status,
                        "deadline": x.deadline,
                    }
                    for x in apps[:MAX_RESULT_ITEMS]
                ],
                "total": len(apps),
            },
            [{"label": x.title, "href": f"{base}/applications/{x.id}"} for x in apps[:5]],
        )
    if call.name == "top_matches":
        page = await opps.page_opportunities(
            s,
            actor,
            case_id,
            academic=bool(a["academic"]),
            view="matches",
            q=a.get("q"),
            limit=int(a["limit"]),
        )
        section = "phd" if a["academic"] else "jobs"
        return ToolOutcome(
            {"matches": [_opp_brief(v) for v in page.items], "counts": page.counts},
            [
                {"label": v.opportunity.title, "href": f"{base}/{section}/{v.opportunity.id}"}
                for v in page.items[:5]
            ],
        )
    if call.name == "opportunity_details":
        v = await opps.get_opportunity(s, actor, case_id, uuid.UUID(a["opportunity_id"]))
        d = v.opportunity.data
        brief = _opp_brief(v)
        brief["requirements"] = d.get("requirements")
        brief["description_start"] = str(d.get("description") or "")[:1500]
        brief["fit_reasons"] = [f.get("explanation") for f in v.match.factors][:8]
        section = "jobs" if v.opportunity.kind == "job" else "phd"
        return ToolOutcome(
            brief, [{"label": v.opportunity.title, "href": f"{base}/{section}/{v.opportunity.id}"}]
        )
    if call.name == "profile_gaps":
        gaps = await profile_gaps(s, actor, case_id)
        return ToolOutcome(
            {"gaps": [g.message for g in gaps[:MAX_RESULT_ITEMS]]},
            [{"label": "My Profile", "href": f"{base}/profile"}],
        )
    if call.name == "start_search":
        run = await opps.start_sync(s, actor, case_id, source_keys=None)
        return ToolOutcome(
            {"started": True, "run_id": str(run.id)},
            [{"label": "Watch the search", "href": f"{base}/activity"}],
        )
    if call.name == "start_research":
        run = await start_research(s, actor, case_id, uuid.UUID(a["opportunity_id"]))
        return ToolOutcome(
            {"started": True, "run_id": str(run.id)},
            [{"label": "Research progress", "href": f"{base}/activity"}],
        )
    if call.name == "start_draft":
        opp = uuid.UUID(a["opportunity_id"]) if a.get("opportunity_id") else None
        run = await gen.start_draft(s, actor, case_id, doc_type=a["doc_type"], opportunity_id=opp)
        return ToolOutcome(
            {"started": True, "run_id": str(run.id), "note": "The user reviews it before use."},
            [{"label": "Documents", "href": f"{base}/documents"}],
        )
    if call.name == "add_reminder":
        rem = await notes.create_reminder(
            s, actor, case_id, title=a["title"], due_on=a["due_on"], application_id=None
        )
        return ToolOutcome({"added": True, "reminder_id": str(rem.id), "due_on": a["due_on"]})
    raise NotFound("Unknown tool.")  # parse_call only lets TOOLS through


# --------------------------------------------------------------------------- conversations
async def new_conversation(s: AsyncSession, actor: Actor, case_id: uuid.UUID) -> ChatConversation:
    await get_case(s, actor, case_id)
    conv = ChatConversation(owner_user_id=actor.user_id, case_id=case_id)
    s.add(conv)
    await s.flush()
    return conv


async def current_conversation(
    s: AsyncSession, actor: Actor, case_id: uuid.UUID
) -> ChatConversation:
    """The newest conversation of the case (started on first use)."""
    await get_case(s, actor, case_id)
    conv = await s.scalar(
        select(ChatConversation)
        .where(ChatConversation.owner_user_id == actor.user_id, ChatConversation.case_id == case_id)
        .order_by(ChatConversation.created_at.desc())
        .limit(1)
    )
    return conv or await new_conversation(s, actor, case_id)


async def get_conversation(
    s: AsyncSession, actor: Actor, conversation_id: uuid.UUID
) -> ChatConversation:
    conv = await s.get(ChatConversation, conversation_id)
    if conv is None or conv.owner_user_id != actor.user_id:
        raise NotFound("Conversation not found.")
    return conv


async def conversation_messages(
    s: AsyncSession, actor: Actor, conversation_id: uuid.UUID
) -> list[ChatMessage]:
    conv = await get_conversation(s, actor, conversation_id)
    rows = await s.scalars(
        select(ChatMessage)
        .where(ChatMessage.owner_user_id == actor.user_id, ChatMessage.conversation_id == conv.id)
        .order_by(ChatMessage.seq.desc())
        .limit(200)
    )
    return list(reversed(list(rows)))


async def clear_conversation(s: AsyncSession, actor: Actor, conversation_id: uuid.UUID) -> None:
    """Delete a conversation and its messages. Consent ends with it."""
    conv = await get_conversation(s, actor, conversation_id)
    await s.delete(conv)
    record_audit(
        s,
        "assistant.conversation_deleted",
        actor_user_id=actor.user_id,
        target_type="chat_conversation",
        target_id=conversation_id,
    )


async def record_consent(s: AsyncSession, owner: uuid.UUID, conversation_id: uuid.UUID) -> None:
    await s.execute(
        update(ChatConversation)
        .where(ChatConversation.id == conversation_id, ChatConversation.owner_user_id == owner)
        .values(consented_at=datetime.now(UTC))
    )


async def start_ai_turn(
    s: AsyncSession,
    actor: Actor,
    case_id: uuid.UUID,
    *,
    conversation_id: uuid.UUID,
    message: str,
    provider_id: uuid.UUID | None,
) -> tuple[ChatMessage, WorkflowRun]:
    """Save the user's message and start the AI reply in the background (`assistant_turn`)."""
    conv = await get_conversation(s, actor, conversation_id)
    if conv.case_id != case_id:
        raise NotFound("Conversation not found.")
    text = message.strip()[:2000]
    if not text:
        raise ValidationFailed("Write a message first.")
    msg = ChatMessage(
        owner_user_id=actor.user_id,
        case_id=case_id,
        conversation_id=conv.id,
        role="user",
        content=text,
        intent="ai",
        actions=[],
    )
    s.add(msg)
    await s.flush()
    run = await start_run(
        s,
        actor,
        case_id,
        kind="assistant_turn",
        params={
            "conversation_id": str(conv.id),
            "message_id": str(msg.id),
            **({"provider_id": str(provider_id)} if provider_id else {}),
        },
        internal=True,
    )
    return msg, run
