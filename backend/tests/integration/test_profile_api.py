import httpx
import pytest

from tests.fixtures.documents import ada_cv_text
from tests.helpers import create_case, facts, register, upload

pytestmark = pytest.mark.db


async def _case(client: httpx.AsyncClient) -> str:
    await register(client)
    return str((await create_case(client))["id"])


async def test_manual_fact_is_accepted_user_entered(client: httpx.AsyncClient) -> None:
    case_id = await _case(client)
    resp = await client.post(
        f"/api/v1/cases/{case_id}/facts",
        json={
            "section": "employment",
            "data": {
                "organization": "Acme",
                "title": "Engineer",
                "start": "2020",
                "end": "present",
            },
        },
    )
    assert resp.status_code == 201, resp.text
    fact = resp.json()
    assert fact["status"] == "user_entered"
    assert fact["review_state"] == "accepted"
    assert fact["label"] == "Engineer at Acme"
    ev = (await client.get(f"/api/v1/facts/{fact['id']}/evidence")).json()
    assert ev[0]["kind"] == "user_entry"


async def test_references_private_by_default(client: httpx.AsyncClient) -> None:
    case_id = await _case(client)
    resp = await client.post(
        f"/api/v1/cases/{case_id}/facts",
        json={"section": "reference", "data": {"name": "Dr. Example", "contact": "x@example.com"}},
    )
    assert resp.json()["is_private"] is True


async def test_invalid_fact_data_rejected(client: httpx.AsyncClient) -> None:
    case_id = await _case(client)
    resp = await client.post(
        f"/api/v1/cases/{case_id}/facts",
        json={"section": "education", "data": {"institution": "Uni", "start": "last spring"}},
    )
    assert resp.status_code == 422
    resp = await client.post(
        f"/api/v1/cases/{case_id}/facts",
        json={"section": "skill", "data": {"name": "Python", "secret_score": 10}},
    )
    assert resp.status_code == 422


async def test_edit_records_original_and_bumps_version(client: httpx.AsyncClient) -> None:
    case_id = await _case(client)
    await upload(client, case_id, ada_cv_text().encode(), "ada.md")
    job = (await facts(client, case_id, section="employment"))[0]
    new = {**job["data"], "title": "Senior Machine Learning Engineer"}
    resp = await client.patch(
        f"/api/v1/facts/{job['id']}",
        json={"version": job["version"], "data": new, "review_state": "accepted"},
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["data"]["title"] == "Senior Machine Learning Engineer"
    assert updated["meta"]["edited_by_user"] is True
    assert updated["meta"]["original_data"]["title"] == "Machine Learning Engineer"
    assert updated["status"] == "extracted"  # provenance is kept
    assert updated["review_state"] == "accepted"
    stale = await client.patch(
        f"/api/v1/facts/{job['id']}", json={"version": job["version"], "is_private": True}
    )
    assert stale.status_code == 409


async def test_bulk_review_and_filters(client: httpx.AsyncClient) -> None:
    case_id = await _case(client)
    await upload(client, case_id, ada_cv_text().encode(), "ada.md")
    skills = await facts(client, case_id, section="skill")
    accept = [s["id"] for s in skills[:3]]
    reject = [skills[3]["id"]]
    resp = await client.post(
        f"/api/v1/cases/{case_id}/facts/review", json={"accept": accept, "reject": reject}
    )
    assert resp.json() == {"changed": 4}
    accepted = await facts(client, case_id, review_state="accepted")
    assert sorted(a["id"] for a in accepted) == sorted(accept)
    both = await client.post(
        f"/api/v1/cases/{case_id}/facts/review", json={"accept": accept[:1], "reject": accept[:1]}
    )
    assert both.status_code == 422


async def test_merge_moves_evidence(client: httpx.AsyncClient) -> None:
    case_id = await _case(client)
    a = (
        await client.post(
            f"/api/v1/cases/{case_id}/facts", json={"section": "skill", "data": {"name": "Python"}}
        )
    ).json()
    b = (
        await client.post(
            f"/api/v1/cases/{case_id}/facts", json={"section": "skill", "data": {"name": "python3"}}
        )
    ).json()
    c = (
        await client.post(
            f"/api/v1/cases/{case_id}/facts",
            json={"section": "education", "data": {"institution": "Uni"}},
        )
    ).json()

    bad = await client.post(
        f"/api/v1/cases/{case_id}/facts/merge", json={"keep_id": a["id"], "merge_ids": [c["id"]]}
    )
    assert bad.status_code == 422  # different sections

    resp = await client.post(
        f"/api/v1/cases/{case_id}/facts/merge", json={"keep_id": a["id"], "merge_ids": [b["id"]]}
    )
    assert resp.status_code == 200, resp.text
    merged = resp.json()
    assert merged["evidence_count"] == 3  # a's entry + b's entry + merge note
    assert (await client.get(f"/api/v1/facts/{b['id']}")).status_code == 404


async def test_gaps_reflect_accepted_facts_only(client: httpx.AsyncClient) -> None:
    case_id = await _case(client)
    codes = {g["code"] for g in (await client.get(f"/api/v1/cases/{case_id}/profile/gaps")).json()}
    assert "missing_education" in codes
    await upload(client, case_id, ada_cv_text().encode(), "ada.md")  # pending only
    codes = {g["code"] for g in (await client.get(f"/api/v1/cases/{case_id}/profile/gaps")).json()}
    assert "missing_education" in codes  # pending facts don't count until accepted
    edu = await facts(client, case_id, section="education")
    await client.post(
        f"/api/v1/cases/{case_id}/facts/review", json={"accept": [e["id"] for e in edu]}
    )
    codes = {g["code"] for g in (await client.get(f"/api/v1/cases/{case_id}/profile/gaps")).json()}
    assert "missing_education" not in codes


async def test_snapshots_freeze_accepted_profile(client: httpx.AsyncClient) -> None:
    case_id = await _case(client)
    await client.post(
        f"/api/v1/cases/{case_id}/facts", json={"section": "skill", "data": {"name": "SQL"}}
    )
    s1 = (
        await client.post(
            f"/api/v1/cases/{case_id}/snapshots", json={"reason": "before PhD applications"}
        )
    ).json()
    await client.post(
        f"/api/v1/cases/{case_id}/facts", json={"section": "skill", "data": {"name": "Rust"}}
    )
    s2 = (await client.post(f"/api/v1/cases/{case_id}/snapshots", json={})).json()
    assert (s1["number"], s1["fact_count"]) == (1, 1)
    assert (s2["number"], s2["fact_count"]) == (2, 2)
    listed = (await client.get(f"/api/v1/cases/{case_id}/snapshots")).json()
    assert [s["number"] for s in listed] == [2, 1]


async def test_deleting_case_removes_profile(client: httpx.AsyncClient) -> None:
    case_id = await _case(client)
    await upload(client, case_id, ada_cv_text().encode(), "ada.md")
    rows = await facts(client, case_id)
    assert (await client.delete(f"/api/v1/cases/{case_id}")).status_code == 204
    assert (await client.get(f"/api/v1/facts/{rows[0]['id']}")).status_code == 404
