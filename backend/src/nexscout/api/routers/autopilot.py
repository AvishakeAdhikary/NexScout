"""Autopilot (M12): settings with explicit consent, its work list, the kill switch, and the
case answer bank (the user's own answers, reused instead of guessed)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Response, status
from pydantic import Field
from sqlalchemy import select

from nexscout.api.deps import CurrentActor, DbSession
from nexscout.api.schemas import ApiModel
from nexscout.application import answers, autopilot
from nexscout.domain.errors import NotFound
from nexscout.domain.policy import AUTO_SUBMIT_CONSENT, DECLARATIONS_CONSENT, DEFAULT_STEPS
from nexscout.domain.site_policy import MANUAL_ONLY
from nexscout.infrastructure.db.models import AutopilotItem, AutopilotPolicy, Notification

router = APIRouter(tags=["autopilot"])


class PolicyOut(ApiModel):
    enabled: bool
    interval_hours: int
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_run_id: uuid.UUID | None
    steps: dict[str, bool]
    min_fit: int
    max_new_per_run: int
    daily_submit_cap: int
    per_org_cap: int
    countries: list[str]
    kinds: list[str]
    exclude_orgs: list[str]
    doc_types: list[str]
    auto_submit: bool
    declarations: bool
    consented_at: datetime | None
    stopped_reason: str | None
    version: int


class ItemOut(ApiModel):
    id: uuid.UUID
    opportunity_id: uuid.UUID
    title: str
    organization: str
    fit: int
    stage: str
    reason: str | None
    application_id: uuid.UUID | None
    attempts: int
    updated_at: datetime


class AutopilotOut(ApiModel):
    policy: PolicyOut
    items: list[ItemOut]
    auto_submit_consent: str
    declarations_consent: str
    manual_only_sites: list[str]


class PolicyIn(ApiModel):
    version: int
    enabled: bool | None = None
    interval_hours: int | None = None
    steps: dict[str, bool] | None = None
    min_fit: int | None = None
    max_new_per_run: int | None = None
    daily_submit_cap: int | None = None
    per_org_cap: int | None = None
    countries: list[str] | None = Field(default=None, max_length=40)
    kinds: list[str] | None = Field(default=None, max_length=2)
    exclude_orgs: list[str] | None = Field(default=None, max_length=50)
    doc_types: list[str] | None = Field(default=None, max_length=5)
    auto_submit: bool | None = None
    consent: str | None = Field(default=None, max_length=2000)
    declarations: bool | None = None
    declarations_consent: str | None = Field(default=None, max_length=2000)


class StopOut(ApiModel):
    policies: int
    items: int
    runs_cancelled: int


class AnswerIn(ApiModel):
    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(min_length=1, max_length=5000)


class AnswerOut(ApiModel):
    id: uuid.UUID
    question: str
    answer: str
    source: str
    updated_at: datetime


class ReplyIn(ApiModel):
    answer: str = Field(min_length=1, max_length=5000)


def _policy(row: AutopilotPolicy) -> PolicyOut:
    return PolicyOut(
        enabled=row.enabled,
        interval_hours=row.interval_hours,
        next_run_at=row.next_run_at,
        last_run_at=row.last_run_at,
        last_run_id=row.last_run_id,
        steps={**DEFAULT_STEPS, **(row.steps or {})},
        min_fit=row.min_fit,
        max_new_per_run=row.max_new_per_run,
        daily_submit_cap=row.daily_submit_cap,
        per_org_cap=row.per_org_cap,
        countries=list(row.countries or []),
        kinds=list(row.kinds or []),
        exclude_orgs=list(row.exclude_orgs or []),
        doc_types=list(row.doc_types or []),
        auto_submit=row.auto_submit,
        declarations=row.declarations,
        consented_at=row.consented_at,
        stopped_reason=row.stopped_reason,
        version=row.version,
    )


def _item(i: AutopilotItem) -> ItemOut:
    return ItemOut.model_validate(i)


async def _view(db: Any, actor: Any, case_id: uuid.UUID) -> AutopilotOut:
    row = await autopilot.get_policy(db, actor, case_id)
    items = await autopilot.list_items(db, actor, case_id)
    return AutopilotOut(
        policy=_policy(row),
        items=[_item(i) for i in items],
        auto_submit_consent=AUTO_SUBMIT_CONSENT,
        declarations_consent=DECLARATIONS_CONSENT,
        manual_only_sites=sorted(MANUAL_ONLY),
    )


@router.get("/cases/{case_id}/autopilot", response_model=AutopilotOut)
async def get_autopilot(case_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> AutopilotOut:
    return await _view(db, actor, case_id)


@router.put("/cases/{case_id}/autopilot", response_model=AutopilotOut)
async def save_autopilot(
    case_id: uuid.UUID, body: PolicyIn, actor: CurrentActor, db: DbSession
) -> AutopilotOut:
    await autopilot.save_policy(
        db, actor, case_id, version=body.version, changes=body.model_dump(exclude={"version"})
    )
    return await _view(db, actor, case_id)


@router.post("/cases/{case_id}/autopilot/run", status_code=status.HTTP_202_ACCEPTED)
async def run_autopilot(case_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> dict[str, str]:
    run = await autopilot.run_now(db, actor, case_id)
    return {"run_id": str(run.id)}


@router.post("/autopilot/stop", response_model=StopOut)
async def stop_autopilot(actor: CurrentActor, db: DbSession) -> StopOut:
    """The kill switch: every autopilot off, its running work cancelled."""
    return StopOut(**await autopilot.stop_all(db, actor, reason="Stop pressed in NexScout"))


@router.get("/cases/{case_id}/answers", response_model=list[AnswerOut])
async def list_answers(case_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> list[AnswerOut]:
    return [AnswerOut.model_validate(a) for a in await answers.list_answers(db, actor, case_id)]


@router.post(
    "/cases/{case_id}/answers", response_model=AnswerOut, status_code=status.HTTP_201_CREATED
)
async def save_answer(
    case_id: uuid.UUID, body: AnswerIn, actor: CurrentActor, db: DbSession
) -> AnswerOut:
    row = await answers.save_answer(db, actor, case_id, body.question, body.answer)
    return AnswerOut.model_validate(row)


@router.delete("/answers/{answer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_answer(answer_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> Response:
    await answers.delete_answer(db, actor, answer_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/notifications/{notification_id}/answer", status_code=status.HTTP_204_NO_CONTENT)
async def answer_question(
    notification_id: uuid.UUID, body: ReplyIn, actor: CurrentActor, db: DbSession
) -> Response:
    """Answer a question NexScout asked, from the app (the same as replying in a chat)."""
    n = await db.scalar(
        select(Notification).where(
            Notification.id == notification_id, Notification.owner_user_id == actor.user_id
        )
    )
    if n is None or n.kind != "question":
        raise NotFound("Question not found.")
    await answers.record_answer(db, actor, n.data or {}, body.answer, source="app")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
