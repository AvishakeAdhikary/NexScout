"""Jobs list + detail routes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from ...core.bundle import bundle_dir_for
from ...core.database import init_db
from ...core.pipeline_status import PER_JOB_STAGES, eligible_stage
from ...core.profile import Profile

router = APIRouter()

#: Columns needed to compute a row's eligible stage (the stage-lock).
_ELIGIBILITY_COLS = (
    "detail_scraped_at, (full_description IS NOT NULL) AS has_desc, "
    "COALESCE(tailor_attempts, 0) AS tailor_attempts, COALESCE(apply_attempts, 0) AS apply_attempts"
)

#: Friendly button label for each per-job stage action.
_STAGE_ACTION_LABEL = {
    "enrich": "Read details",
    "score": "Score now",
    "tailor": "Tailor résumé",
    "apply": "Queue to apply",
}


def _attach_eligibility(rows: list[dict[str, Any]], min_score: int) -> None:
    """Tag each row with the single stage it's eligible for (the stage-lock)."""
    for r in rows:
        probe = dict(r)
        probe["full_description"] = True if r.get("has_desc") else None
        r["eligible_stage"] = eligible_stage(probe, min_score=min_score)
        r["stage_action_label"] = _STAGE_ACTION_LABEL.get(r["eligible_stage"] or "", "")


def _build_jobs_query(
    *,
    min_score: int | None,
    site: str | None,
    status: str | None,
    sort: str,
    page: int,
    per_page: int,
) -> tuple[str, list[Any], str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if min_score is not None:
        clauses.append("fit_score >= ?")
        params.append(int(min_score))
    if site:
        clauses.append("site = ?")
        params.append(site)
    if status == "applied":
        clauses.append("apply_status = 'applied'")
    elif status == "failed":
        clauses.append("apply_status IN ('failed','captcha','login_issue','expired')")
    elif status == "pending":
        clauses.append("(apply_status IS NULL OR apply_status = 'failed')")
    elif status == "paused":
        clauses.append("apply_status = 'paused_for_question'")

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    order_col = "fit_score" if sort == "score" else "discovered_at"
    offset = max(0, (page - 1) * per_page)
    count_sql = f"SELECT COUNT(*) AS n FROM jobs {where}"
    list_sql = (
        f"SELECT rowid AS id, url, title, site, location, fit_score, "
        f"apply_status, tailored_resume_path, cover_letter_path, discovered_at, {_ELIGIBILITY_COLS} "
        f"FROM jobs {where} ORDER BY {order_col} DESC, url LIMIT {per_page} OFFSET {offset}"
    )
    return list_sql, params, count_sql, params


@router.get("/jobs", response_class=HTMLResponse)
async def list_jobs(
    request: Request,
    min_score: int | None = None,
    site: str | None = None,
    status: str | None = None,
    sort: str = "score",
    page: int = 1,
) -> HTMLResponse:
    per_page = 50
    list_sql, params, count_sql, count_params = _build_jobs_query(
        min_score=min_score, site=site, status=status, sort=sort, page=page, per_page=per_page
    )
    conn = init_db()
    rows = [dict(r) for r in conn.execute(list_sql, params).fetchall()]
    total = int(conn.execute(count_sql, count_params).fetchone()["n"])
    _attach_eligibility(rows, Profile.from_path().search.min_score)
    # Query string carrying the active filters (no `page`) so pagination links
    # preserve the current filter/sort selection.
    filt: dict[str, Any] = {}
    if min_score is not None:
        filt["min_score"] = min_score
    if site:
        filt["site"] = site
    if status:
        filt["status"] = status
    if sort:
        filt["sort"] = sort
    templates = request.app.state.templates
    context = {
        "rows": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "filter_qs": urlencode(filt),
        "filters": {"min_score": min_score, "site": site, "status": status, "sort": sort},
    }
    # htmx swaps the `#jobs-table` element — return just the partial.
    template_name = "_jobs_table.html" if request.headers.get("HX-Request") else "jobs.html"
    return templates.TemplateResponse(request, template_name, context)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: int) -> HTMLResponse:
    conn = init_db()
    row = conn.execute("SELECT rowid AS id, * FROM jobs WHERE rowid = ?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="job not found")
    job = dict(row)
    bundle = bundle_dir_for(int(job_id))
    transcript: list[dict[str, Any]] = []
    transcript_path = bundle / "transcript.jsonl"
    if transcript_path.exists():
        for raw in transcript_path.read_text(encoding="utf-8").splitlines():
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                transcript.append(json.loads(stripped))
            except json.JSONDecodeError:
                continue
    screenshots = sorted((bundle / "screenshots").glob("*.png")) if (bundle / "screenshots").exists() else []
    min_score = Profile.from_path().search.min_score
    job["eligible_stage"] = eligible_stage(job, min_score=min_score)
    job["stage_action_label"] = _STAGE_ACTION_LABEL.get(job["eligible_stage"] or "", "")
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "job_detail.html",
        {
            "job": job,
            "transcript": transcript,
            "screenshots": [s.name for s in screenshots],
            "has_resume_pdf": (bundle / "resume.pdf").exists(),
            "has_cover_pdf": (bundle / "cover_letter.pdf").exists(),
        },
    )


def _build_router(profile: Profile) -> Any:
    from ...llm.budget import BudgetLedger
    from ...llm.router import LLMRouter

    return LLMRouter(
        profile,
        budget=BudgetLedger(
            monthly_usd=profile.llm.budgets.monthly_usd,
            daily_calls=profile.llm.budgets.daily_calls,
        ),
    )


def _run_one_stage(profile: Profile, conn: Any, job: dict[str, Any], stage: str) -> None:
    """Run a single stage for exactly one job (targeted). ``apply`` only queues
    the job — the browser-heavy submit is left to the engine's apply stage."""
    url = job["url"]
    if stage == "score":
        from ...scoring.scorer import persist_score, score_job

        score, reasoning = score_job(_build_router(profile), profile, job)
        if score >= 1:  # don't clobber a good score with a failed (0) result
            persist_score(conn, url, score, reasoning)
    elif stage == "enrich":
        from ...enrichment import detail as _detail

        try:
            from ...browser.driver import UndetectedFactory

            factory = UndetectedFactory()
            result = _detail.enrich_row(row=job, factory=factory, router=_build_router(profile), headless=True)
        except Exception as e:  # surface any browser/extractor failure on the row
            _detail.persist_enrichment_error(conn, url, str(e)[:400])
            return
        if result is None:
            _detail.persist_enrichment_error(conn, url, "no_extractor_succeeded")
        else:
            _detail.persist_enrichment(conn, url, result)
    elif stage == "tailor":
        from datetime import UTC, datetime

        from ...core.bundle import write_bundle_file
        from ...scoring.tailor import tailor_resume

        result = tailor_resume(router=_build_router(profile), profile=profile, job=job, mode="normal")
        if result.status == "approved" and result.text:
            txt = write_bundle_file(int(job["id"]), "resume.txt", result.text)
            if result.data is not None:
                write_bundle_file(int(job["id"]), "resume.json", json.dumps(result.data, indent=2, ensure_ascii=False))
            conn.execute(
                "UPDATE jobs SET tailored_resume_path=?, tailored_at=?, "
                "tailor_attempts=COALESCE(tailor_attempts,0)+? WHERE url=?",
                (str(txt), datetime.now(UTC).isoformat(), result.attempts, url),
            )
        else:
            conn.execute(
                "UPDATE jobs SET tailor_attempts=COALESCE(tailor_attempts,0)+? WHERE url=?",
                (max(1, result.attempts), url),
            )
    elif stage == "apply":
        # Queue it: reset apply state so the engine's apply stage submits it on
        # the next pass (or when the user clicks "Run one full pass now").
        conn.execute("UPDATE jobs SET apply_status=NULL, apply_attempts=0, apply_error=NULL WHERE url=?", (url,))


def _job_row_response(request: Request, conn: Any, job_id: int, min_score: int) -> Any:
    """Re-fetch one job (with eligibility) and render the table-row partial."""
    r = conn.execute(
        "SELECT rowid AS id, url, title, site, location, fit_score, apply_status, "
        f"discovered_at, {_ELIGIBILITY_COLS} FROM jobs WHERE rowid = ?",
        (job_id,),
    ).fetchone()
    row = dict(r)
    _attach_eligibility([row], min_score)
    return request.app.state.templates.TemplateResponse(request, "_job_row.html", {"row": row})


@router.post("/jobs/{job_id}/stage/{stage}", response_class=HTMLResponse)
def run_job_stage(request: Request, job_id: int, stage: str) -> Any:
    """Run (or queue) one pipeline stage for a single job, honouring the stage-lock.

    Sync handler so FastAPI runs it in a worker thread — the LLM/browser calls
    block, and the per-thread autocommit SQLite connection makes this safe. The
    stage only runs if the job is genuinely eligible for it (so you can't, say,
    apply before scoring). HTMX gets the refreshed row; a form POST redirects.
    """
    if stage not in PER_JOB_STAGES:
        raise HTTPException(status_code=422, detail=f"unknown stage: {stage}")
    conn = init_db()
    r = conn.execute("SELECT rowid AS id, * FROM jobs WHERE rowid = ?", (job_id,)).fetchone()
    if r is None:
        raise HTTPException(status_code=404, detail="job not found")
    job = dict(r)
    profile = Profile.from_path()
    if eligible_stage(job, min_score=profile.search.min_score) == stage:
        _run_one_stage(profile, conn, job, stage)
    if request.headers.get("HX-Request"):
        return _job_row_response(request, conn, job_id, profile.search.min_score)
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@router.post("/jobs/{job_id}/score", response_class=HTMLResponse)
def score_job_now(request: Request, job_id: int) -> Any:
    """Back-compat alias for running the score stage on one job."""
    return run_job_stage(request, job_id, "score")


@router.post("/api/reapply")
async def reapply(request: Request) -> Any:
    """Reset a job so the next apply pass picks it up.

    Accepts both the form-style submission used by the "Re-apply" button
    on ``/jobs/{job_id}`` (redirects on success) AND a JSON body
    ``{"job_id": N}`` for tooling (returns ``{"status": "ok", ...}``).
    """
    content_type = (request.headers.get("content-type") or "").lower()
    job_id: int | None = None
    is_json = "application/json" in content_type

    if is_json:
        body = await request.json()
        if isinstance(body, dict) and "job_id" in body:
            try:
                job_id = int(body["job_id"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail="job_id must be an integer") from None
    else:
        form = await request.form()
        raw = form.get("job_id")
        if raw is not None:
            try:
                job_id = int(str(raw))
            except ValueError:
                raise HTTPException(status_code=422, detail="job_id must be an integer") from None

    if job_id is None:
        raise HTTPException(status_code=422, detail="job_id is required")

    conn = init_db()
    row = conn.execute("SELECT rowid AS id, url FROM jobs WHERE rowid=?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="job not found")
    conn.execute(
        "UPDATE jobs SET apply_status=NULL, apply_attempts=0, apply_error=NULL WHERE rowid=?",
        (job_id,),
    )

    if is_json:
        from fastapi.responses import JSONResponse as _JR

        return _JR({"status": "ok", "id": job_id, "url": row["url"]})
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@router.get("/bundles/{job_id}/{filename}")
async def bundle_file(job_id: int, filename: str) -> FileResponse:
    bundle = bundle_dir_for(job_id)
    safe = Path(filename).name
    target = bundle / safe
    if not target.exists():
        # Maybe inside the screenshots/ subdir.
        target = bundle / "screenshots" / safe
        if not target.exists():
            raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(str(target))


__all__ = ["router"]
