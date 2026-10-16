"""Cross-tenant sweep: user B must get 404 on every route that names one of user A's resources.

When a route with a path parameter is added, it must be covered here.
`test_every_id_route_is_covered` fails if a new route isn't.
"""

from typing import Any

import httpx
import pytest
from fastapi.routing import APIRoute
from sqlalchemy import text
from sqlalchemy.engine import Engine

from nexscout.infrastructure.db.models import OWNED_TABLES
from tests.fixtures.documents import ada_cv_text
from tests.helpers import create_case, facts, register, upload

pytestmark = pytest.mark.db


async def _seed_owner(client: httpx.AsyncClient) -> dict[str, str]:
    await register(client, "owner@example.com", "Owner")
    case_id = str((await create_case(client, "Owner case"))["id"])
    doc = (await upload(client, case_id, ada_cv_text().encode(), "ada.md")).json()["document"]
    fact = (await facts(client, case_id))[0]
    link = (
        await client.post(
            f"/api/v1/cases/{case_id}/social-profiles", json={"url": "https://github.com/owner"}
        )
    ).json()
    aff = (
        await client.post(
            f"/api/v1/cases/{case_id}/affiliations",
            json={"organization": "Org", "relationship_type": "alumnus"},
        )
    ).json()
    return {
        "case_id": case_id,
        "document_id": doc["id"],
        "fact_id": fact["id"],
        "link_id": link["id"],
        "affiliation_id": aff["id"],
        "fact_version": str(fact["version"]),
        "aff_version": str(aff["version"]),
    }


def _requests(ids: dict[str, str]) -> list[tuple[str, str, dict[str, Any] | None]]:
    c, d, f, link, a = (
        ids["case_id"],
        ids["document_id"],
        ids["fact_id"],
        ids["link_id"],
        ids["affiliation_id"],
    )
    return [
        ("GET", f"/api/v1/cases/{c}", None),
        ("PATCH", f"/api/v1/cases/{c}", {"version": 1, "name": "pwned"}),
        ("DELETE", f"/api/v1/cases/{c}", None),
        ("GET", f"/api/v1/cases/{c}/facts", None),
        ("POST", f"/api/v1/cases/{c}/facts", {"section": "skill", "data": {"name": "x"}}),
        ("POST", f"/api/v1/cases/{c}/facts/review", {"accept": [f]}),
        ("POST", f"/api/v1/cases/{c}/facts/merge", {"keep_id": f, "merge_ids": [f]}),
        ("GET", f"/api/v1/cases/{c}/profile/gaps", None),
        ("POST", f"/api/v1/cases/{c}/snapshots", {}),
        ("GET", f"/api/v1/cases/{c}/snapshots", None),
        ("GET", f"/api/v1/facts/{f}", None),
        ("PATCH", f"/api/v1/facts/{f}", {"version": int(ids["fact_version"]), "is_private": True}),
        ("DELETE", f"/api/v1/facts/{f}", None),
        ("GET", f"/api/v1/facts/{f}/evidence", None),
        ("GET", f"/api/v1/cases/{c}/documents", None),
        ("GET", f"/api/v1/documents/{d}", None),
        ("GET", f"/api/v1/documents/{d}/text", None),
        ("GET", f"/api/v1/documents/{d}/content", None),
        ("DELETE", f"/api/v1/documents/{d}", None),
        ("GET", f"/api/v1/cases/{c}/preferences", None),
        ("PUT", f"/api/v1/cases/{c}/preferences", {"version": 0, "data": {}}),
        ("GET", f"/api/v1/cases/{c}/social-profiles", None),
        ("POST", f"/api/v1/cases/{c}/social-profiles", {"url": "https://example.com"}),
        ("DELETE", f"/api/v1/social-profiles/{link}", None),
        ("GET", f"/api/v1/cases/{c}/affiliations", None),
        (
            "POST",
            f"/api/v1/cases/{c}/affiliations",
            {"organization": "X", "relationship_type": "alumnus"},
        ),
        (
            "PATCH",
            f"/api/v1/affiliations/{a}",
            {"version": int(ids["aff_version"]), "notes": "pwned"},
        ),
        ("DELETE", f"/api/v1/affiliations/{a}", None),
    ]


async def test_other_user_gets_404_everywhere(
    client: httpx.AsyncClient, other_client: httpx.AsyncClient
) -> None:
    ids = await _seed_owner(client)
    await register(other_client, "intruder@example.com", "Intruder")
    for method, url, body in _requests(ids):
        resp = await other_client.request(method, url, json=body)
        assert resp.status_code == 404, f"{method} {url} -> {resp.status_code}: {resp.text}"
    # Owner's data is intact afterwards.
    assert (await client.get(f"/api/v1/cases/{ids['case_id']}")).json()["name"] == "Owner case"
    assert (await client.get(f"/api/v1/documents/{ids['document_id']}/content")).status_code == 200
    assert (await client.get(f"/api/v1/facts/{ids['fact_id']}")).json()["is_private"] is False


async def test_upload_into_other_users_case_is_404(
    client: httpx.AsyncClient, other_client: httpx.AsyncClient
) -> None:
    ids = await _seed_owner(client)
    await register(other_client, "intruder@example.com", "Intruder")
    resp = await upload(other_client, ids["case_id"], b"hello")
    assert resp.status_code == 404


def test_every_id_route_is_covered(app: Any) -> None:
    """Guard: a new route with an ID path parameter must be added to the sweep above."""
    covered = {
        (
            m,
            u.replace("{case_id}", "C")
            .replace("{fact_id}", "F")
            .replace("{document_id}", "D")
            .replace("{link_id}", "L")
            .replace("{affiliation_id}", "A"),
        )
        for m, u, _ in _requests(
            {
                "case_id": "C",
                "document_id": "D",
                "fact_id": "F",
                "link_id": "L",
                "affiliation_id": "A",
                "fact_version": "1",
                "aff_version": "1",
            }
        )
    }
    missing = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or "{" not in route.path:
            continue
        path = (
            route.path.replace("{case_id}", "C")
            .replace("{fact_id}", "F")
            .replace("{document_id}", "D")
            .replace("{link_id}", "L")
            .replace("{affiliation_id}", "A")
        )
        missing += [f"{m} {route.path}" for m in route.methods if (m, path) not in covered]
    assert missing == [], f"Add these routes to the IDOR sweep: {missing}"


def test_all_owned_tables_have_forced_rls(migrated_db: Engine) -> None:
    with migrated_db.connect() as conn:
        for table in OWNED_TABLES:
            row = conn.execute(
                text(
                    "SELECT c.relrowsecurity, c.relforcerowsecurity, "
                    "(SELECT count(*) FROM pg_policies p WHERE p.tablename = c.relname) "
                    "FROM pg_class c WHERE c.relname = :t"
                ),
                {"t": table},
            ).one()
            assert tuple(row) == (True, True, 1), f"{table}: {tuple(row)}"
