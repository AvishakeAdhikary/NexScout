"""JSON variants of the HTML routes + Prometheus metrics."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse

from ...core.database import get_stats, init_db

router = APIRouter(prefix="/api")


@router.get("/stats")
async def api_stats() -> JSONResponse:
    return JSONResponse(get_stats(init_db()))


@router.get("/jobs")
async def api_jobs(min_score: int = 0, limit: int = 50) -> JSONResponse:
    conn = init_db()
    rows = conn.execute(
        "SELECT rowid AS id, url, title, site, fit_score, apply_status "
        "FROM jobs WHERE fit_score >= ? ORDER BY fit_score DESC LIMIT ?",
        (min_score, limit),
    ).fetchall()
    return JSONResponse([dict(r) for r in rows])


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
