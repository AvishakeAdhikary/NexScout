"""JSON variants of the HTML routes + Prometheus metrics."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from ...core.database import get_stats, init_db
from ...openclaw.memory import append_learned_answer

router = APIRouter(prefix="/api")


@router.get("/stats")
async def api_stats() -> JSONResponse:
    """JSON mirror of the dashboard counters."""
    return JSONResponse(get_stats(init_db()))


@router.get("/jobs")
async def api_jobs(min_score: int = 0, limit: int = 50, site: str | None = None) -> JSONResponse:
    """JSON mirror of ``/jobs`` with score + site filters."""
    conn = init_db()
    clauses = ["fit_score >= ?"]
    params: list[Any] = [min_score]
    if site:
        clauses.append("site = ?")
        params.append(site)
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"SELECT rowid AS id, url, title, site, location, fit_score, apply_status, "
        f"tailored_resume_path, cover_letter_path, discovered_at, applied_at "
        f"FROM jobs WHERE {where} ORDER BY fit_score DESC, url LIMIT ?",
        (*params, limit),
    ).fetchall()
    return JSONResponse([dict(r) for r in rows])


@router.get("/applications")
async def api_applications(limit: int = 100) -> JSONResponse:
    """JSON mirror of ``/applications`` (jobs with ``apply_status='applied'``)."""
    conn = init_db()
    rows = conn.execute(
        "SELECT rowid AS id, url, title, site, location, fit_score, applied_at, "
        "cost_usd, tailored_resume_path, cover_letter_path "
        "FROM jobs WHERE apply_status='applied' ORDER BY applied_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return JSONResponse([dict(r) for r in rows])


@router.get("/questions")
async def api_questions() -> JSONResponse:
    """JSON mirror of ``/questions`` (unanswered pending_questions rows)."""
    conn = init_db()
    rows = conn.execute(
        "SELECT id, job_url, question, asked_at, channel, channel_delivered_at "
        "FROM pending_questions WHERE answered_at IS NULL ORDER BY id"
    ).fetchall()
    return JSONResponse([dict(r) for r in rows])


class AnswerPayload(BaseModel):
    """JSON body for ``POST /api/answer/json`` (tooling form-free variant)."""

    question_id: int
    reply: str


@router.post("/answer/json")
async def api_answer_json(payload: AnswerPayload) -> JSONResponse:
    """JSON variant of ``POST /api/answer`` (the form-based version stays for the web UI).

    Returns ``{"status": "ok", "id": ...}`` on success or 404 when the
    referenced question doesn't exist.
    """
    conn = init_db()
    row = conn.execute(
        "SELECT id, job_url, question FROM pending_questions WHERE id = ?",
        (payload.question_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="question not found")
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "UPDATE pending_questions SET answer=?, answered_at=? WHERE id=?",
        (payload.reply, now, payload.question_id),
    )
    if row["job_url"]:
        conn.execute(
            "UPDATE jobs SET apply_status=NULL WHERE url=? AND apply_status='paused_for_question'",
            (row["job_url"],),
        )
    append_learned_answer(row["question"], payload.reply, ts=now)
    return JSONResponse({"status": "ok", "id": payload.question_id})


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> PlainTextResponse:
    """Prometheus exposition format."""
    stats = get_stats(init_db())
    lines = [
        "# HELP nexscout_jobs_total Total jobs known to NexScout.",
        "# TYPE nexscout_jobs_total gauge",
        f"nexscout_jobs_total {stats['total']}",
        "# TYPE nexscout_jobs_applied gauge",
        f"nexscout_jobs_applied {stats['applied']}",
        "# TYPE nexscout_jobs_scored gauge",
        f"nexscout_jobs_scored {stats['scored']}",
        "# TYPE nexscout_jobs_ready_to_apply gauge",
        f"nexscout_jobs_ready_to_apply {stats['ready_to_apply']}",
        "# TYPE nexscout_jobs_apply_errors gauge",
        f"nexscout_jobs_apply_errors {stats['apply_errors']}",
    ]
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


# Top-level /metrics alias (Prometheus conventions).
top_router = APIRouter()


@top_router.get("/metrics", response_class=PlainTextResponse)
async def top_metrics() -> PlainTextResponse:
    return await metrics()


__all__ = ["router", "top_router"]
