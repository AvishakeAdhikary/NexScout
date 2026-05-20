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
async def list_applications(request: Request) -> HTMLResponse:
    conn = init_db()
    rows: list[dict[str, Any]] = [
        dict(r)
        for r in conn.execute(
            "SELECT rowid AS id, url, title, site, location, fit_score, applied_at, "
            "cost_usd, tailored_resume_path, cover_letter_path "
            "FROM jobs WHERE apply_status='applied' ORDER BY applied_at DESC"
        ).fetchall()
    ]
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "applications.html", {"rows": rows})


@router.get("/applications/download.zip")
async def download_all_zip() -> StreamingResponse:
    conn = init_db()
    rows = conn.execute(
        "SELECT rowid AS id FROM jobs WHERE apply_status='applied'"
    ).fetchall()

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
