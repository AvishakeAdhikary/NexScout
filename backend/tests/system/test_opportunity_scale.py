"""M20 performance: a case with 5,000 opportunities (descriptions of 4 KB each).

The board's page requests stay small and fast however long the list is. The old whole-list
route is measured next to them for the record. Numbers are printed (`-s`); the assertions are
generous bounds, since timings depend on the machine.
"""

import time
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.helpers import create_case, register

pytestmark = pytest.mark.db
N = 5000


async def _timed(client: httpx.AsyncClient, url: str, **params: str) -> tuple[Any, float, int]:
    t0 = time.perf_counter()
    r = await client.get(url, params=params)
    elapsed = time.perf_counter() - t0
    assert r.status_code == 200, r.text
    return r.json(), elapsed, len(r.content)


async def test_pages_stay_small_and_fast_with_5000_opportunities(
    client: httpx.AsyncClient, clean_db: Engine
) -> None:
    await register(client)
    me = (await client.get("/api/v1/auth/me")).json()
    case_id = str((await create_case(client, "Big search"))["id"])
    with clean_db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organizations (id, name, normalized_key, aliases)"
                " SELECT gen_random_uuid(), 'Scale Org ' || g, 'scale org ' || g, '[]'"
                " FROM generate_series(0, 399) g"
            )
        )
        conn.execute(
            text(
                "INSERT INTO opportunities (id, kind, organization_id, organization_name, title,"
                " normalized_title, data, status, first_seen_at, last_seen_at)"
                " SELECT gen_random_uuid(), 'job', org.id, org.name,"
                " 'Role ' || lpad(g::text, 5, '0'), 'role ' || g,"
                " jsonb_build_object('description', repeat('x', 4000), 'location_country', 'DE'),"
                " 'open', now(), now() FROM generate_series(1, :n) g"
                " JOIN organizations org ON org.normalized_key = 'scale org ' || (g % 400)"
            ),
            {"n": N},
        )
        conn.execute(
            text(
                "INSERT INTO opportunity_matches (id, owner_user_id, case_id, opportunity_id,"
                " score, eligible, mode, factors, gaps, status, first_seen_at, computed_at,"
                " version)"
                " SELECT gen_random_uuid(), :owner, :case, o.id, abs(hashtext(o.title)) % 100,"
                " abs(hashtext(o.title)) % 5 <> 0, 'strict', '[]', '[]', 'new', now(), now(), 1"
                " FROM opportunities o WHERE o.title LIKE 'Role %'"
            ),
            {"owner": me["id"], "case": case_id},
        )

    base = f"/api/v1/cases/{case_id}/opportunities"
    whole, whole_s, whole_bytes = await _timed(client, base, academic="false")
    assert len(whole) == N
    first, first_s, first_bytes = await _timed(client, f"{base}/page", academic="false")
    assert sum(first["counts"].values()) == N
    assert len(first["items"]) == 50
    # Twenty pages further on costs the same as the first (keyset, not offset).
    cursor = first["next_cursor"]
    deep_s = 0.0
    for _ in range(20):
        page, deep_s, _ = await _timed(client, f"{base}/page", academic="false", cursor=cursor)
        cursor = page["next_cursor"]
    found, search_s, _ = await _timed(client, f"{base}/page", academic="false", q="Role 00420")
    assert sum(found["counts"].values()) == 1  # in whichever list its fit put it

    print(
        f"\n5,000 opportunities: whole list {whole_s:.2f} s / {whole_bytes / 1e6:.1f} MB;"
        f" first page {first_s * 1000:.0f} ms / {first_bytes / 1e3:.0f} KB;"
        f" page 21 {deep_s * 1000:.0f} ms; search {search_s * 1000:.0f} ms"
    )
    assert first_bytes < 150_000  # descriptions stay out of list pages
    assert whole_bytes > 20 * first_bytes
    assert first_s < 2.0
    assert deep_s < 2.0
    assert search_s < 2.0
