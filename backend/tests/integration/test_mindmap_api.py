import httpx
import pytest

from tests.fixtures.documents import ada_cv_text
from tests.helpers import create_case, facts, register, upload

pytestmark = pytest.mark.db


async def _accepted_profile(client: httpx.AsyncClient) -> str:
    await register(client)
    case_id = str((await create_case(client))["id"])
    await upload(client, case_id, ada_cv_text().encode(), "ada.md")
    rows = await facts(client, case_id)
    await client.post(
        f"/api/v1/cases/{case_id}/facts/review", json={"accept": [r["id"] for r in rows]}
    )
    return case_id


async def test_mindmap_contains_only_accepted_facts_with_evidence(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    case_id = str((await create_case(client))["id"])
    await upload(client, case_id, ada_cv_text().encode(), "ada.md")
    mm = (await client.get(f"/api/v1/cases/{case_id}/mindmap")).json()
    assert [n["kind"] for n in mm["nodes"]] == ["candidate"]  # nothing accepted yet

    rows = await facts(client, case_id)
    await client.post(
        f"/api/v1/cases/{case_id}/facts/review", json={"accept": [r["id"] for r in rows]}
    )
    mm = (await client.get(f"/api/v1/cases/{case_id}/mindmap")).json()
    fact_nodes = [n for n in mm["nodes"] if n["kind"] == "fact"]
    assert len(fact_nodes) == len(rows)
    assert all(n["evidence_count"] >= 1 and n["status"] == "extracted" for n in fact_nodes)
    derived = [e for e in mm["edges"] if e["derived"]]
    assert derived
    assert all(e["basis"] for e in derived)
    assert not [e for e in mm["edges"] if e["kind"] == "mentions_skill"]  # none in this CV

    job = (
        await client.post(
            f"/api/v1/cases/{case_id}/facts",
            json={
                "section": "employment",
                "data": {
                    "title": "Intern",
                    "organization": "Lab",
                    "description": "Trained PyTorch models",
                },
            },
        )
    ).json()
    mm = (await client.get(f"/api/v1/cases/{case_id}/mindmap")).json()
    pytorch = next(n for n in mm["nodes"] if n["label"] == "PyTorch")
    mention = next(e for e in mm["edges"] if e["kind"] == "mentions_skill")
    assert (mention["source"], mention["target"]) == (f"fact:{job['id']}", pytorch["key"])
    assert "appears in this entry" in mention["basis"]


async def test_overrides_survive_regeneration_and_reset(client: httpx.AsyncClient) -> None:
    case_id = await _accepted_profile(client)
    mm = (await client.get(f"/api/v1/cases/{case_id}/mindmap")).json()
    node = next(n for n in mm["nodes"] if n["kind"] == "fact")
    key = node["key"]
    put = await client.put(
        f"/api/v1/cases/{case_id}/mindmap/nodes/{key}",
        json={"x": 120.5, "y": -40, "hidden": False, "label": "My first job"},
    )
    assert put.status_code == 204

    # A profile change regenerates the map. The override is still applied.
    await client.post(
        f"/api/v1/cases/{case_id}/facts", json={"section": "skill", "data": {"name": "Rust"}}
    )
    mm = (await client.get(f"/api/v1/cases/{case_id}/mindmap")).json()
    again = next(n for n in mm["nodes"] if n["key"] == key)
    assert (again["x"], again["y"], again["label_override"]) == (120.5, -40, "My first job")

    # Deleting the underlying fact leaves the override orphaned (kept, reported).
    await client.delete(f"/api/v1/facts/{node['fact_id']}")
    mm = (await client.get(f"/api/v1/cases/{case_id}/mindmap")).json()
    assert mm["orphaned_overrides"] == [key]
    assert (await client.delete(f"/api/v1/cases/{case_id}/mindmap/overrides")).status_code == 204
    assert (await client.get(f"/api/v1/cases/{case_id}/mindmap")).json()["orphaned_overrides"] == []

    bad = await client.put(
        f"/api/v1/cases/{case_id}/mindmap/nodes/../../etc", json={"hidden": True}
    )
    assert bad.status_code in (404, 422)


async def test_snapshot_compare(client: httpx.AsyncClient) -> None:
    case_id = await _accepted_profile(client)
    await client.post(f"/api/v1/cases/{case_id}/snapshots", json={"reason": "v1"})
    skill = (await facts(client, case_id, section="skill"))[0]
    await client.patch(
        f"/api/v1/facts/{skill['id']}",
        json={"version": skill["version"], "data": {**skill["data"], "level": "expert"}},
    )
    await client.post(
        f"/api/v1/cases/{case_id}/facts", json={"section": "skill", "data": {"name": "Rust"}}
    )
    await client.post(f"/api/v1/cases/{case_id}/snapshots", json={"reason": "v2"})
    diff = (
        await client.get(
            f"/api/v1/cases/{case_id}/snapshots/compare", params={"from_number": 1, "to_number": 2}
        )
    ).json()
    assert [a["label"] for a in diff["added"]] == ["Rust"]
    assert diff["changed"][0]["fields"] == ["level"]
    assert diff["removed"] == []
    missing = await client.get(
        f"/api/v1/cases/{case_id}/snapshots/compare", params={"from_number": 1, "to_number": 9}
    )
    assert missing.status_code == 404
