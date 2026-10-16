"""Liveness and readiness probes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from nexscout.api.schemas import HealthOut, ReadyOut
from nexscout.infrastructure.db.migrations import expected_head

router = APIRouter(tags=["health"])
READY_TIMEOUT_S = 3.0


async def _current_revision(request: Request) -> str | None:
    async with request.app.state.sessionmaker() as session:
        revision: str | None = await session.scalar(text("SELECT version_num FROM alembic_version"))
    return revision


@router.get("/healthz", response_model=HealthOut)
async def healthz() -> HealthOut:
    return HealthOut(status="ok")


@router.get("/readyz", response_model=ReadyOut)
async def readyz(request: Request) -> JSONResponse:
    db_state, mig_state = "ok", "ok"
    try:
        current = await asyncio.wait_for(_current_revision(request), timeout=READY_TIMEOUT_S)
        head = expected_head()
        if current != head:
            mig_state = f"behind (db={current}, code={head})"
    except Exception:  # noqa: BLE001 - readiness reports, never raises (incl. timeout)
        db_state, mig_state = "unreachable", "unknown"
    ok = db_state == "ok" and mig_state == "ok"
    body = ReadyOut(status="ok" if ok else "degraded", database=db_state, migrations=mig_state)
    return JSONResponse(status_code=200 if ok else 503, content=body.model_dump())
