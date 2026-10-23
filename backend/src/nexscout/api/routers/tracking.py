"""Notifications, reminders, dashboard, diagnostics, and the case assistant."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, Response, status
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.api.deps import CurrentActor, DbSession, SettingsDep
from nexscout.api.schemas import ApiModel
from nexscout.application import assistant
from nexscout.application import dashboard as dash
from nexscout.application import notifications as notes
from nexscout.application.actor import Actor
from nexscout.domain.errors import NotFound
from nexscout.infrastructure.db.models import ChatConversation, ChatMessage, Reminder

router = APIRouter(tags=["tracking"])


class NotificationOut(ApiModel):
    id: uuid.UUID
    case_id: uuid.UUID | None
    kind: str
    title: str
    body: str | None
    link: str | None
    read: bool
    created_at: datetime


class NotificationsOut(ApiModel):
    unread: int
    items: list[NotificationOut]


class ReminderIn(ApiModel):
    title: str = Field(min_length=1, max_length=300)
    due_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    application_id: uuid.UUID | None = None


class ReminderDoneIn(ApiModel):
    done: bool


class ReminderOut(ApiModel):
    id: uuid.UUID
    case_id: uuid.UUID
    application_id: uuid.UUID | None
    kind: str
    title: str
    due_on: str
    done: bool
    created_at: datetime


class ChatIn(ApiModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: uuid.UUID | None = None


class ChatMessageOut(ApiModel):
    id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    role: str
    content: str
    intent: str | None
    actions: list[dict[str, Any]]
    created_at: datetime


def _reminder(r: Reminder) -> ReminderOut:
    return ReminderOut(
        id=r.id,
        case_id=r.case_id,
        application_id=r.application_id,
        kind=r.kind,
        title=r.title,
        due_on=r.due_on,
        done=r.done_at is not None,
        created_at=r.created_at,
    )


def _chat(m: ChatMessage) -> ChatMessageOut:
    return ChatMessageOut(
        id=m.id,
        conversation_id=m.conversation_id,
        role=m.role,
        content=m.content,
        intent=m.intent,
        actions=list(m.actions or []),
        created_at=m.created_at,
    )


@router.get("/notifications", response_model=NotificationsOut)
async def list_notifications(
    actor: CurrentActor,
    db: DbSession,
    before: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> NotificationsOut:
    rows, unread = await notes.list_notifications(db, actor, limit=limit, before=before)
    return NotificationsOut(
        unread=unread, items=[NotificationOut(**notes.notification_dict(n)) for n in rows]
    )


@router.post("/notifications/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def read_all(actor: CurrentActor, db: DbSession) -> Response:
    await notes.mark_read(db, actor, None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class ClearIn(ApiModel):
    read_only: bool = True


class ClearedOut(ApiModel):
    cleared: int


@router.post("/notifications/clear", response_model=ClearedOut)
async def clear_notifications(body: ClearIn, actor: CurrentActor, db: DbSession) -> ClearedOut:
    return ClearedOut(cleared=await notes.clear_notifications(db, actor, read_only=body.read_only))


@router.delete("/notifications/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    notification_id: uuid.UUID, actor: CurrentActor, db: DbSession
) -> Response:
    await notes.delete_notification(db, actor, notification_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/notifications/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def read_one(notification_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> Response:
    await notes.mark_read(db, actor, notification_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/cases/{case_id}/reminders", response_model=list[ReminderOut])
async def list_reminders(
    case_id: uuid.UUID, actor: CurrentActor, db: DbSession, include_done: bool = False
) -> list[ReminderOut]:
    return [
        _reminder(r)
        for r in await notes.list_reminders(db, actor, case_id, include_done=include_done)
    ]


@router.post(
    "/cases/{case_id}/reminders", response_model=ReminderOut, status_code=status.HTTP_201_CREATED
)
async def create_reminder(
    case_id: uuid.UUID, body: ReminderIn, actor: CurrentActor, db: DbSession
) -> ReminderOut:
    r = await notes.create_reminder(
        db, actor, case_id, title=body.title, due_on=body.due_on, application_id=body.application_id
    )
    return _reminder(r)


@router.patch("/reminders/{reminder_id}", response_model=ReminderOut)
async def update_reminder(
    reminder_id: uuid.UUID, body: ReminderDoneIn, actor: CurrentActor, db: DbSession
) -> ReminderOut:
    return _reminder(await notes.set_reminder_done(db, actor, reminder_id, body.done))


@router.delete("/reminders/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reminder(reminder_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> Response:
    await notes.delete_reminder(db, actor, reminder_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/cases/{case_id}/dashboard")
async def dashboard(case_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> dict[str, Any]:
    return await dash.case_dashboard(db, actor, case_id)


@router.get("/diagnostics")
async def diagnostics(actor: CurrentActor, db: DbSession) -> dict[str, Any]:
    return await dash.diagnostics(db, actor)


class ConversationOut(ApiModel):
    id: uuid.UUID
    case_id: uuid.UUID
    consented: bool
    created_at: datetime


class AiChatIn(ApiModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: uuid.UUID
    provider_id: uuid.UUID | None = None


class AiChatOut(ApiModel):
    message: ChatMessageOut
    run_id: uuid.UUID


def _conversation(c: ChatConversation) -> ConversationOut:
    return ConversationOut(
        id=c.id, case_id=c.case_id, consented=c.consented_at is not None, created_at=c.created_at
    )


@router.get("/cases/{case_id}/chat/conversation", response_model=ConversationOut)
async def current_conversation(
    case_id: uuid.UUID, actor: CurrentActor, db: DbSession
) -> ConversationOut:
    """The case's newest conversation (started on first use)."""
    return _conversation(await assistant.current_conversation(db, actor, case_id))


@router.post(
    "/cases/{case_id}/chat/conversations",
    response_model=ConversationOut,
    status_code=status.HTTP_201_CREATED,
)
async def new_conversation(
    case_id: uuid.UUID, actor: CurrentActor, db: DbSession
) -> ConversationOut:
    """Start over. An online AI model asks for consent again in the new conversation."""
    return _conversation(await assistant.new_conversation(db, actor, case_id))


@router.delete("/chat/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_conversation(
    conversation_id: uuid.UUID, actor: CurrentActor, db: DbSession
) -> Response:
    await assistant.clear_conversation(db, actor, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/cases/{case_id}/chat/ai", response_model=AiChatOut, status_code=202)
async def chat_ai(
    case_id: uuid.UUID, body: AiChatIn, actor: CurrentActor, db: DbSession
) -> AiChatOut:
    """Ask the AI assistant. The reply is written in the background; follow the run."""
    msg, run = await assistant.start_ai_turn(
        db,
        actor,
        case_id,
        conversation_id=body.conversation_id,
        message=body.message,
        provider_id=body.provider_id,
    )
    return AiChatOut(message=_chat(msg), run_id=run.id)


async def _conversation_id(
    db: AsyncSession, actor: Actor, case_id: uuid.UUID, conversation_id: uuid.UUID | None
) -> uuid.UUID:
    if conversation_id is None:
        return (await assistant.current_conversation(db, actor, case_id)).id
    conv = await assistant.get_conversation(db, actor, conversation_id)
    if conv.case_id != case_id:
        raise NotFound("Conversation not found.")
    return conv.id


@router.get("/cases/{case_id}/chat", response_model=list[ChatMessageOut])
async def chat_history(
    case_id: uuid.UUID,
    actor: CurrentActor,
    db: DbSession,
    conversation_id: uuid.UUID | None = None,
) -> list[ChatMessageOut]:
    """A conversation's messages (the current conversation unless one is named)."""
    conv = await _conversation_id(db, actor, case_id, conversation_id)
    return [_chat(m) for m in await assistant.conversation_messages(db, actor, conv)]


@router.post("/cases/{case_id}/chat", response_model=list[ChatMessageOut])
async def chat(
    case_id: uuid.UUID, body: ChatIn, actor: CurrentActor, db: DbSession, settings: SettingsDep
) -> list[ChatMessageOut]:
    """The assistant without AI (rule-based, answered right away)."""
    conv = await _conversation_id(db, actor, case_id, body.conversation_id)
    replies = await dash.chat(db, settings, actor, case_id, body.message, conversation_id=conv)
    return [_chat(m) for m in replies]
