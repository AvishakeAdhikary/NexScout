import asyncio
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.helpers import create_case, register, sync

pytestmark = pytest.mark.db


async def _case(
    client: httpx.AsyncClient, path: str = "employment", email: str = "ada@example.com"
) -> str:
    await register(client, email)
    case = await create_case(client)
    await client.patch(f"/api/v1/cases/{case['id']}", json={"version": 1, "career_path": path})
    await client.post(
        f"/api/v1/cases/{case['id']}/facts", json={"section": "skill", "data": {"name": "Python"}}
    )
    await client.post(
        f"/api/v1/cases/{case['id']}/facts", json={"section": "skill", "data": {"name": "SQL"}}
    )
    await client.post(
        f"/api/v1/cases/{case['id']}/facts",
        json={
            "section": "employment",
            "data": {
                "title": "ML Engineer",
                "organization": "X",
                "start": "2021-01",
                "end": "present",
            },
        },
    )
    await client.post(
        f"/api/v1/cases/{case['id']}/facts",
        json={"section": "education", "data": {"institution": "Uni", "degree": "MSc"}},
    )
    return str(case["id"])


async def _sync(client: httpx.AsyncClient, case_id: str) -> dict[str, Any]:
    return await sync(client, case_id)


async def _opps(client: httpx.AsyncClient, case_id: str, **params: Any) -> list[dict[str, Any]]:
    resp = await client.get(f"/api/v1/cases/{case_id}/opportunities", params=params)
    assert resp.status_code == 200, resp.text
    body: list[dict[str, Any]] = resp.json()
    return body


async def test_sources_are_declared_with_honest_capabilities(client: httpx.AsyncClient) -> None:
    await register(client)
    sources = (await client.get("/api/v1/sources")).json()
    demo = [s for s in sources if s["origin"] == "demo"]
    assert {s["key"] for s in demo} == {
        "demo_jobs_board_a",
        "demo_jobs_board_b",
        "demo_academic_portal",
    }
    assert all(s["is_demo_data"] and "not real" in s["terms"] for s in demo)
    # The real catalog is listed with its terms, and stays off until the user turns it on.
    real = [s for s in sources if s["origin"] == "catalog"]
    assert len(real) >= 150
    assert not any(s["enabled"] or s["is_demo_data"] for s in real)
    assert all(s["terms"] and s["provider"] for s in real)
    keys = {s["key"] for s in real}
    assert {"greenhouse:anthropic", "workinfinland:work-in-finland-business-finland"} <= keys


async def test_sync_dedups_across_sources_and_keeps_distinct_requisitions(
    client: httpx.AsyncClient,
) -> None:
    case_id = await _case(client)
    result = await _sync(client, case_id)
    a, b = result["demo_jobs_board_a"], result["demo_jobs_board_b"]
    assert result["demo_academic_portal"]["skipped_reason"]  # employment path: not applicable
    assert (a["fetched"], a["new_opportunities"], a["merged_duplicates"]) == (7, 7, 0)
    # B1 merges into A1 (canonical URL), B2 into A4 (similar text); B3 is new.
    assert (b["fetched"], b["new_opportunities"], b["merged_duplicates"]) == (3, 1, 2)
    assert all(m["reasons"] for m in b["merges"])

    opps = await _opps(client, case_id, academic="false")
    assert len(opps) == 8
    acme_ml = [
        o
        for o in opps
        if o["organization_name"] == "Acme GmbH" and o["title"] == "Machine Learning Engineer"
    ]
    assert len(acme_ml) == 3  # REQ-100 (2 sources), REQ-101 Munich, REQ-102 Berlin: never merged
    req100 = next(o for o in acme_ml if o["data"]["requisition_id"] == "REQ-100")
    assert sorted(s["source_key"] for s in req100["sources"]) == [
        "demo_jobs_board_a",
        "demo_jobs_board_b",
    ]
    assert all(o["is_demo_data"] for o in opps)


async def test_repeated_sync_creates_no_duplicates_and_detects_changes(
    client: httpx.AsyncClient, clean_db: Engine
) -> None:
    case_id = await _case(client)
    await _sync(client, case_id)
    again = await _sync(client, case_id)
    for key in ("demo_jobs_board_a", "demo_jobs_board_b"):
        s = again[key]
        assert (s["new_opportunities"], s["merged_duplicates"], s["new_for_case"]) == (0, 0, 0)
        assert s["unchanged"] == s["fetched"]
    with clean_db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM opportunities")).scalar() == 8

    # Newer postings appear on board B: one changed listing, one new listing.
    await client.put(
        "/api/v1/sources/demo_jobs_board_b",
        json={"enabled": True, "settings": {"include_later_postings": True}},
    )
    later = (await _sync(client, case_id))["demo_jobs_board_b"]
    assert (later["new_opportunities"], later["updated"], later["new_for_case"]) == (1, 1, 1)
    backend = next(o for o in await _opps(client, case_id) if o["title"] == "Backend Engineer")
    assert backend["data"]["closes_at"] == "2027-01-15"


async def test_strict_vs_flexible_and_explanations(client: httpx.AsyncClient) -> None:
    case_id = await _case(client)
    await client.put(
        f"/api/v1/cases/{case_id}/preferences",
        json={"version": 0, "data": {"countries": ["Germany"]}},
    )
    await _sync(client, case_id)
    senior = next(o for o in await _opps(client, case_id) if o["title"] == "Senior Data Scientist")
    assert senior["eligible"] is False
    assert any(
        g["code"] == "experience_below_minimum" and g["severity"] == "blocker"
        for g in senior["gaps"]
    )
    closed = next(o for o in await _opps(client, case_id) if o["organization_name"] == "Contoso AG")
    assert closed["eligible"] is False
    assert closed["status"] == "closed"

    await client.put(
        f"/api/v1/cases/{case_id}/preferences",
        json={"version": 1, "data": {"countries": ["Germany"], "experience_mode": "flexible"}},
    )
    assert (await client.post(f"/api/v1/cases/{case_id}/opportunities/rescore")).json() == {
        "rescored": 8
    }
    senior = next(o for o in await _opps(client, case_id) if o["title"] == "Senior Data Scientist")
    assert senior["eligible"] is True
    gap = next(g for g in senior["gaps"] if g["code"] == "experience_below_minimum")
    assert gap["severity"] == "gap"

    top = (await _opps(client, case_id))[0]
    assert sum(f["weight"] for f in top["factors"]) == 100
    skills = next(f for f in top["factors"] if f["name"] == "Skills")
    assert skills["fact_ids"]  # every point is backed by profile entries


async def test_status_changes_and_reports(client: httpx.AsyncClient) -> None:
    case_id = await _case(client)
    await _sync(client, case_id)
    opp = (await _opps(client, case_id))[0]
    url = f"/api/v1/cases/{case_id}/opportunities/{opp['id']}"
    resp = await client.patch(url, json={"status": "shortlisted", "version": opp["match_version"]})
    assert resp.status_code == 200
    assert resp.json()["match_status"] == "shortlisted"
    stale = await client.patch(url, json={"status": "dismissed", "version": opp["match_version"]})
    assert stale.status_code == 409
    assert len(await _opps(client, case_id, match_status="shortlisted")) == 1
    rep = await client.post(f"{url}/reports", json={"kind": "wrong_merge", "note": "two roles"})
    assert rep.status_code == 201


async def test_phd_path_uses_academic_sources(client: httpx.AsyncClient) -> None:
    case_id = await _case(client, path="phd")
    result = await _sync(client, case_id)
    acad = result["demo_academic_portal"]
    assert (acad["fetched"], acad["new_opportunities"], acad["merged_duplicates"]) == (4, 3, 1)
    assert result["demo_jobs_board_a"]["skipped_reason"]
    opps = await _opps(client, case_id, academic="true")
    assert {o["kind"] for o in opps} == {"phd", "postdoc"}
    postdoc = next(o for o in opps if o["kind"] == "postdoc")
    assert any(g["code"] == "education_below_requirement" for g in postdoc["gaps"])


async def test_concurrent_syncs_by_two_users_do_not_duplicate_catalog(
    client: httpx.AsyncClient, other_client: httpx.AsyncClient, clean_db: Engine
) -> None:
    case_a = await _case(client, email="a@example.com")
    case_b = await _case(other_client, email="b@example.com")
    await asyncio.gather(_sync(client, case_a), _sync(other_client, case_b))
    with clean_db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM opportunities")).scalar() == 8
        assert conn.execute(text("SELECT count(*) FROM opportunity_matches")).scalar() == 16
    # Each user sees only their own matches.
    assert len(await _opps(client, case_a)) == 8
    assert len(await _opps(other_client, case_b)) == 8
