"""Jobs list + detail routes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from ...core.bundle import bundle_dir_for
from ...core.database import init_db

router = APIRouter()


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
        f"apply_status, tailored_resume_path, cover_letter_path, discovered_at "
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
    templates = request.app.state.templates
    context = {
        "rows": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
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
