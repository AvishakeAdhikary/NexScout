"""M6: job research, permission-gated referral suggestions, resume, cover letter, referral."""

from typing import Any

import httpx
import pytest

from tests.helpers import create_case, register

pytestmark = pytest.mark.db


async def _job_case(client: httpx.AsyncClient, worker: Any) -> tuple[str, str]:
    await register(client)
    case_id = str((await create_case(client, "Job search"))["id"])
    await client.patch(f"/api/v1/cases/{case_id}", json={"version": 1, "career_path": "employment"})
    for section, data in (
        ("employment", {"title": "ML Engineer", "organization": "Examplecorp", "start": "2021"}),
        ("education", {"institution": "University of Sampleford", "degree": "BSc"}),
        ("project", {"name": "Feature store"}),
        ("skill", {"name": "Python"}),
    ):
        r = await client.post(
            f"/api/v1/cases/{case_id}/facts", json={"section": section, "data": data}
        )
        assert r.status_code == 201, r.text
    r = await client.post(f"/api/v1/cases/{case_id}/opportunities/sync", json={})
    assert r.status_code == 202
    await worker.run_until_idle()
    opps = (await client.get(f"/api/v1/cases/{case_id}/opportunities?academic=false")).json()
    acme = next(
        o for o in opps if any(s["source_url"].endswith("/jobs/a-1001") for s in o["sources"])
    )
    return case_id, str(acme["id"])


async def _relationship(client: httpx.AsyncClient, case_id: str, **body: Any) -> str:
    r = await client.post(f"/api/v1/cases/{case_id}/affiliations", json=body)
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def _draft(
    client: httpx.AsyncClient, worker: Any, case_id: str, **body: Any
) -> dict[str, Any]:
    r = await client.post(f"/api/v1/cases/{case_id}/generated-documents", json=body)
    assert r.status_code == 202, r.text
    await worker.run_until_idle()
    d = (await client.get(f"/api/v1/runs/{r.json()['run_id']}")).json()
    assert d["run"]["status"] == "succeeded", d["run"]
    doc: dict[str, Any] = (
        await client.get(f"/api/v1/generated-documents/{d['run']['result']['document_id']}")
    ).json()
    return doc


async def test_job_research_reads_demo_pages(client: httpx.AsyncClient, worker: Any) -> None:
    case_id, opp_id = await _job_case(client, worker)
    r = await client.post(f"/api/v1/cases/{case_id}/opportunities/{opp_id}/research")
    assert r.status_code == 202
    await worker.run_until_idle()
    research = (await client.get(f"/api/v1/cases/{case_id}/opportunities/{opp_id}/research")).json()
    kinds = {(f["kind"], f["field"]) for f in research["findings"]}
    assert ("deadline", "application") in kinds
    assert ("document_required", "statement") in kinds  # the cover letter
    assert any("70,000" in f["summary"] for f in research["findings"] if f["kind"] == "funding")


async def test_referrals_only_from_permitted_people_at_the_employer(
    client: httpx.AsyncClient, worker: Any
) -> None:
    case_id, opp_id = await _job_case(client, worker)
    sam = await _relationship(
        client,
        case_id,
        person_name="Sam Example",
        organization="ACME",
        relationship_type="current_employee",
        may_use_for_referral=True,
    )
    lee = await _relationship(
        client,
        case_id,
        person_name="Lee Hidden",
        organization="Acme GmbH",
        relationship_type="colleague",
        may_use_for_referral=False,
    )
    await _relationship(
        client,
        case_id,
        person_name="Pat Elsewhere",
        organization="Initech",
        relationship_type="mentor",
        may_use_for_referral=True,
    )
    await _relationship(  # the candidate's own link can't refer anyone
        client,
        case_id,
        organization="Acme",
        relationship_type="former_employee",
        may_use_for_referral=True,
    )
    refs = (await client.get(f"/api/v1/cases/{case_id}/opportunities/{opp_id}/referrals")).json()
    assert [s["person_name"] for s in refs["suggestions"]] == ["Sam Example"]
    assert "allowed" in refs["suggestions"][0]["reason"]
    assert refs["not_permitted"] == 1
    assert "Lee Hidden" not in str(refs)

    denied = await client.post(
        f"/api/v1/cases/{case_id}/generated-documents",
        json={"doc_type": "referral_request", "opportunity_id": opp_id, "affiliation_id": lee},
    )
    assert denied.status_code == 403
    missing = await client.post(
        f"/api/v1/cases/{case_id}/generated-documents",
        json={"doc_type": "referral_request", "opportunity_id": opp_id},
    )
    assert missing.status_code == 422

    doc = await _draft(
        client,
        worker,
        case_id,
        doc_type="referral_request",
        opportunity_id=opp_id,
        affiliation_id=sam,
    )
    md = doc["current"]["markdown"]
    assert md.startswith("Subject: ")
    assert "Hi Sam Example," in md
    assert "Lee Hidden" not in md
    assert doc["current"]["report"]["contact"]["value"]["person_name"] == "Sam Example"


async def test_cover_letter_mentions_only_relationships_allowed_in_applications(
    client: httpx.AsyncClient, worker: Any
) -> None:
    case_id, opp_id = await _job_case(client, worker)
    await _relationship(
        client,
        case_id,
        person_name="Sam Example",
        organization="ACME",
        relationship_type="current_employee",
        may_use_for_referral=True,
    )
    doc = await _draft(client, worker, case_id, doc_type="cover_letter", opportunity_id=opp_id)
    md = doc["current"]["markdown"]
    assert "Dear hiring team," in md
    assert "I worked as ML Engineer at Examplecorp." in md
    assert "Connection:" not in md  # not allowed in applications

    await _relationship(
        client,
        case_id,
        organization="Acme GmbH",
        relationship_type="former_employee",
        may_use_in_applications=True,
    )
    doc = await _draft(client, worker, case_id, doc_type="cover_letter", opportunity_id=opp_id)
    assert "Connection: You: former employee at Acme GmbH." in doc["current"]["markdown"]
    assert doc["current"]["is_mock"] is True


async def test_resume_is_assembled_for_jobs(client: httpx.AsyncClient, worker: Any) -> None:
    case_id, _ = await _job_case(client, worker)
    doc = await _draft(client, worker, case_id, doc_type="resume")
    cur = doc["current"]
    assert cur["origin"] == "assembled"
    assert cur["model"] is None
    md = cur["markdown"]
    assert md.index("## Experience") < md.index("## Projects") < md.index("## Skills")
    assert md.index("## Skills") < md.index("## Education")
    assert doc["doc_label"] == "Resume"
    assert cur["files"]["docx"]["checks"]["ok"]
