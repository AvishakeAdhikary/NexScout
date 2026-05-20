"""Pending-questions list + answer endpoint."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ...core.database import init_db
from ...openclaw.memory import append_learned_answer

router = APIRouter()


@router.get("/questions", response_class=HTMLResponse)
async def list_questions(request: Request) -> HTMLResponse:
    conn = init_db()
    rows = conn.execute(
        "SELECT id, job_url, question, asked_at, channel, answered_at, answer "
        "FROM pending_questions ORDER BY id DESC"
    ).fetchall()
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "questions.html", {"rows": [dict(r) for r in rows]})


@router.post("/api/answer")
async def answer(
    request: Request,
    question_id: int = Form(...),
    reply: str = Form(...),
) -> RedirectResponse:
    conn = init_db()
    row = conn.execute(
        "SELECT id, job_url, question FROM pending_questions WHERE id = ?", (question_id,)
    ).fetchone()
    if row is None:
        return RedirectResponse(url="/questions", status_code=303)

    now = datetime.now(UTC).isoformat()
    conn.execute(
        "UPDATE pending_questions SET answer=?, answered_at=? WHERE id=?",
        (reply, now, question_id),
    )
    if row["job_url"]:
        conn.execute(
            "UPDATE jobs SET apply_status=NULL WHERE url=? AND apply_status='paused_for_question'",
            (row["job_url"],),
        )

    # Persist to OpenClaw memory.
    append_learned_answer(row["question"], reply, ts=now)
    _ = request  # mark used
    _ = Path  # imported for type-hint clarity; not used directly here
    return RedirectResponse(url="/questions", status_code=303)


__all__ = ["router"]
