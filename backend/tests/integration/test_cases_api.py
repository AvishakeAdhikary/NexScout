import httpx
import pytest

from tests.helpers import create_case, register

pytestmark = pytest.mark.db


async def test_case_crud(client: httpx.AsyncClient) -> None:
    await register(client)
    case = await create_case(client, "My PhD search")
    assert case["career_path"] == "undecided"
    assert case["status"] == "active"
    assert case["version"] == 1

    listed = (await client.get("/api/v1/cases")).json()
    assert [c["id"] for c in listed] == [case["id"]]

    resp = await client.patch(
        f"/api/v1/cases/{case['id']}",
        json={"version": 1, "career_path": "both", "description": "Undecided between PhD and jobs"},
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["career_path"] == "both"
    assert updated["version"] == 2
    assert updated["description"] == "Undecided between PhD and jobs"

    assert (await client.delete(f"/api/v1/cases/{case['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/cases/{case['id']}")).status_code == 404


async def test_stale_version_conflicts(client: httpx.AsyncClient) -> None:
    await register(client)
    case = await create_case(client)
    ok = await client.patch(f"/api/v1/cases/{case['id']}", json={"version": 1, "name": "A"})
    assert ok.status_code == 200
    stale = await client.patch(f"/api/v1/cases/{case['id']}", json={"version": 1, "name": "B"})
    assert stale.status_code == 409
    assert stale.json()["code"] == "concurrency_conflict"


async def test_duplicate_case_name_conflicts(client: httpx.AsyncClient) -> None:
    await register(client)
    await create_case(client, "Jobs")
    resp = await client.post("/api/v1/cases", json={"name": "Jobs"})
    assert resp.status_code == 409


async def test_archived_cases_hidden_by_default(client: httpx.AsyncClient) -> None:
    await register(client)
    case = await create_case(client)
    await client.patch(f"/api/v1/cases/{case['id']}", json={"version": 1, "status": "archived"})
    assert (await client.get("/api/v1/cases")).json() == []
    assert len((await client.get("/api/v1/cases?include_archived=true")).json()) == 1


async def test_invalid_payload_is_problem_json(client: httpx.AsyncClient) -> None:
    await register(client)
    resp = await client.post("/api/v1/cases", json={"name": "x", "career_path": "astronaut"})
    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_failed"
    resp = await client.post("/api/v1/cases", json={"name": "x", "owner_user_id": "spoof"})
    assert resp.status_code == 422  # extra fields forbidden: owner cannot be client-supplied
