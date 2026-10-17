"""The case answer bank (M12): the user's own answers, reused instead of guessed.

Questions come from application forms ("Why are you interested in this role?") and from document
placeholders ("contact details (email, phone, city)"). Answers are stored per case under the
normalized question, so the same question is never asked twice. Nothing here is generated.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.application.actor import Actor
from nexscout.application.audit import record_audit
from nexscout.application.cases import get_case
from nexscout.domain.errors import NotFound, ValidationFailed
from nexscout.domain.forms import normalize_question
from nexscout.infrastructure.db.models import CaseAnswer

MAX_ANSWERS = 300


async def answers_for(s: AsyncSession, owner: uuid.UUID, case_id: uuid.UUID) -> dict[str, str]:
    rows = await s.execute(
        select(CaseAnswer.question_key, CaseAnswer.answer).where(
            CaseAnswer.owner_user_id == owner, CaseAnswer.case_id == case_id
        )
    )
    return dict(rows.all())


async def list_answers(s: AsyncSession, actor: Actor, case_id: uuid.UUID) -> list[CaseAnswer]:
    await get_case(s, actor, case_id)
    return list(
        await s.scalars(
            select(CaseAnswer)
            .where(CaseAnswer.owner_user_id == actor.user_id, CaseAnswer.case_id == case_id)
            .order_by(CaseAnswer.question)
        )
    )


async def save_answer(
    s: AsyncSession,
    actor: Actor,
    case_id: uuid.UUID,
    question: str,
    answer: str,
    *,
    source: str = "user",
) -> CaseAnswer:
    await get_case(s, actor, case_id)
    question, answer = question.strip(), answer.strip()
    if not question or not answer:
        raise ValidationFailed("Both the question and your answer are needed.")
    if len(question) > 1000 or len(answer) > 5000:
        raise ValidationFailed("That question or answer is too long.")
    key = normalize_question(question)[:500]
    existing = await s.scalar(
        select(CaseAnswer).where(CaseAnswer.case_id == case_id, CaseAnswer.question_key == key)
    )
    if existing is None:
        count = len(await answers_for(s, actor.user_id, case_id))
        if count >= MAX_ANSWERS:
            raise ValidationFailed("You have too many saved answers in this case.")
    await s.execute(
        insert(CaseAnswer)
        .values(
            id=uuid.uuid4(),
            owner_user_id=actor.user_id,
            case_id=case_id,
            question_key=key,
            question=question,
            answer=answer,
            source=source[:100],
        )
        .on_conflict_do_update(
            constraint="uq_case_answers_key",
            set_={"answer": answer, "question": question, "source": source[:100]},
        )
    )
    record_audit(
        s,
        "answer.saved",
        actor_user_id=actor.user_id,
        target_type="case",
        target_id=case_id,
        meta={"source": source[:100]},
    )
    row = await s.scalar(
        select(CaseAnswer).where(CaseAnswer.case_id == case_id, CaseAnswer.question_key == key)
    )
    assert row is not None
    await s.refresh(row)
    return row


async def delete_answer(s: AsyncSession, actor: Actor, answer_id: uuid.UUID) -> None:
    row = await s.scalar(
        select(CaseAnswer).where(
            CaseAnswer.id == answer_id, CaseAnswer.owner_user_id == actor.user_id
        )
    )
    if row is None:
        raise NotFound("Answer not found.")
    await s.delete(row)


async def record_answer(
    s: AsyncSession, actor: Actor, data: dict[str, Any], answer: str, *, source: str
) -> None:
    """An answer to a question NexScout asked (in the app or by replying on a paired chat).
    Saved to the case's answer bank and, for a form question, to that application too."""
    from nexscout.application.applications import record_answer as record_on_application

    question = str(data.get("question") or "").strip()
    if not question or not answer.strip():
        raise ValidationFailed("Nothing to answer.")
    case_id = data.get("case_id")
    if data.get("application_id"):
        app = await record_on_application(s, actor, data, answer, source=source)
        case_id = app.case_id
    if not case_id:
        raise ValidationFailed("This question isn't linked to a case.")
    await save_answer(s, actor, uuid.UUID(str(case_id)), question, answer, source=source)
