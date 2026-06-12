"""Applications list + bulk-download ZIP."""

from __future__ import annotations

import io
import zipfile
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from ...core.bundle import bundle_dir_for
from ...core.database import init_db

router = APIRouter()


@router.get("/applications", response_class=HTMLResponse)
async def list_applications(request: Request, page: int = 1) -> HTMLResponse:
    per_page = 25
    conn = init_db()
    total = int(conn.execute("SELECT COUNT(*) AS n FROM jobs WHERE apply_status='applied'").fetchone()["n"])
    offset = max(0, (page - 1) * per_page)
    rows: list[dict[str, Any]] = [
        dict(r)
        for r in conn.execute(
            "SELECT rowid AS id, url, title, site, location, fit_score, applied_at, "
            "cost_usd, tailored_resume_path, cover_letter_path "
            "FROM jobs WHERE apply_status='applied' ORDER BY applied_at DESC LIMIT ? OFFSET ?",
            (per_page, offset),
        ).fetchall()
    ]
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request, "applications.html", {"rows": rows, "total": total, "page": page, "per_page": per_page}
    )


@router.get("/applications/download.zip")
async def download_all_zip() -> StreamingResponse:
    conn = init_db()
    rows = conn.execute("SELECT rowid AS id FROM jobs WHERE apply_status='applied'").fetchall()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for row in rows:
            jid = int(row["id"])
            bundle = bundle_dir_for(jid)
            for path in bundle.rglob("*"):
                if path.is_file():
                    arcname = f"{jid:06d}/{path.relative_to(bundle)}"
                    zf.write(path, arcname)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=nexscout-bundles.zip"},
    )


__all__ = ["router"]
