"""Concurrency/load: many users at once through the real API and worker.

Correctness under concurrency is asserted (no cross-tenant leakage, no duplicate catalog
entries, every run finishes). Throughput and memory are measured and printed, not asserted
tightly: they depend on the machine. Size with NEXSCOUT_LOAD_USERS (default 12).
"""

import asyncio
import json
import os
import time
from typing import Any

import httpx
import psutil
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.fixtures.documents import ada_cv_text

pytestmark = pytest.mark.db
USERS = int(os.environ.get("NEXSCOUT_LOAD_USERS", "12"))


async def test_many_users_concurrently(app: Any, worker: Any, clean_db: Engine) -> None:
    proc = psutil.Process()
    rss_before = proc.memory_info().rss

    async def one(i: int) -> dict[str, Any]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as c:
            t0 = time.perf_counter()
            r = await c.post(
                "/api/v1/auth/register",
                json={
                    "email": f"load{i}@example.com",
                    "password": "correct horse battery staple",
                    "display_name": f"Load {i}",
                },
            )
            assert r.status_code == 201, r.text
            c.headers["X-CSRF-Token"] = c.cookies.get("nexscout_csrf") or ""
            case = (await c.post("/api/v1/cases", json={"name": f"Case {i}"})).json()
            await c.patch(f"/api/v1/cases/{case['id']}", json={"version": 1, "career_path": "both"})
            up = await c.post(
                f"/api/v1/cases/{case['id']}/documents",
                files={"file": (f"cv{i}.md", ada_cv_text().encode(), "text/markdown")},
                data={"purpose": "cv"},
            )
            assert up.status_code == 201, up.text
            sync = await c.post(f"/api/v1/cases/{case['id']}/opportunities/sync", json={})
            draft = await c.post(
                f"/api/v1/cases/{case['id']}/generated-documents", json={"doc_type": "academic_cv"}
            )
            assert sync.status_code == draft.status_code == 202
            return {
                "client": c.cookies,
                "case": case["id"],
                "api_s": time.perf_counter() - t0,
                "runs": [up.json()["run_id"], sync.json()["run_id"], draft.json()["run_id"]],
            }

    t0 = time.perf_counter()
    users = await asyncio.gather(*(one(i) for i in range(USERS)))
    api_s = time.perf_counter() - t0
    t1 = time.perf_counter()
    await worker.run_until_idle(timeout_s=600)
    worker_s = time.perf_counter() - t1

    with clean_db.connect() as conn:
        statuses = dict(
            conn.execute(text("SELECT status, count(*) FROM workflow_runs GROUP BY status")).all()
        )
        dupes = conn.execute(
            text(
                "SELECT count(*) FROM (SELECT canonical_url FROM opportunities "
                "WHERE canonical_url IS NOT NULL GROUP BY canonical_url HAVING count(*) > 1) d"
            )
        ).scalar()
        per_case = conn.execute(
            text("SELECT count(DISTINCT case_id) FROM generated_documents")
        ).scalar()
        leaked = conn.execute(
            text(
                "SELECT count(*) FROM generated_documents g "
                "JOIN candidate_cases c ON c.id = g.case_id "
                "WHERE c.owner_user_id <> g.owner_user_id"
            )
        ).scalar()
    assert statuses == {"succeeded": USERS * 3}, statuses
    assert dupes == 0
    assert per_case == USERS
    assert leaked == 0

    # Each user sees exactly their own case through the API (cookie jars are separate).
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies=users[0]["client"],
    ) as c:
        mine = (await c.get("/api/v1/cases")).json()
        assert [x["id"] for x in mine] == [users[0]["case"]]

    rss_after = proc.memory_info().rss
    report = {
        "users": USERS,
        "runs": USERS * 3,
        "api_phase_s": round(api_s, 2),
        "worker_phase_s": round(worker_s, 2),
        "runs_per_s": round(USERS * 3 / worker_s, 2),
        "slowest_user_api_s": round(max(u["api_s"] for u in users), 2),
        "rss_mb_before": round(rss_before / 2**20, 1),
        "rss_mb_after": round(rss_after / 2**20, 1),
    }
    print("\nLOAD " + json.dumps(report))
