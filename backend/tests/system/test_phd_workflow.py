"""M5: research a position with provenance, draft truthful documents, edit, render, download."""

import io
import zipfile
from typing import Any

import httpx
import pytest
from pypdf import PdfReader
from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.helpers import create_case, register

pytestmark = pytest.mark.db

NLP_TITLE = "Doctoral Researcher in Trustworthy Natural Language Processing"


async def _phd_case(client: httpx.AsyncClient, worker: Any) -> tuple[str, str]:
    await register(client)
    case_id = str((await create_case(client))["id"])
    await client.patch(f"/api/v1/cases/{case_id}", json={"version": 1, "career_path": "phd"})
    for section, data in (
        (
            "education",
            {
                "institution": "University of Sampleford",
                "degree": "MSc",
                "field_of_study": "Computer Science",
                "start": "2021",
                "end": "2023",
            },
        ),
        ("employment", {"title": "ML Engineer", "organization": "Examplecorp", "start": "2023"}),
        ("research", {"title": "Calibration of text classifiers", "organization": "Sampleford"}),
        ("skill", {"name": "Python"}),
        ("skill", {"name": "PyTorch"}),
        ("reference", {"name": "Dr. Private Person"}),  # private by default: never used
    ):
        r = await client.post(
            f"/api/v1/cases/{case_id}/facts", json={"section": section, "data": data}
        )
        assert r.status_code == 201, r.text
    synced = await client.post(f"/api/v1/cases/{case_id}/opportunities/sync", json={})
    assert synced.status_code == 202, synced.text
    await worker.run_until_idle()
    opps = (await client.get(f"/api/v1/cases/{case_id}/opportunities")).json()
    opp = next(o for o in opps if o["title"] == NLP_TITLE)
    return case_id, str(opp["id"])


async def _run(client: httpx.AsyncClient, worker: Any, resp: httpx.Response) -> dict[str, Any]:
    assert resp.status_code == 202, resp.text
    await worker.run_until_idle()
    d: dict[str, Any] = (await client.get(f"/api/v1/runs/{resp.json()['run_id']}")).json()
    return d


async def _research(
    client: httpx.AsyncClient, worker: Any, case_id: str, opp_id: str
) -> dict[str, Any]:
    d = await _run(
        client,
        worker,
        await client.post(f"/api/v1/cases/{case_id}/opportunities/{opp_id}/research"),
    )
    assert d["run"]["status"] == "succeeded", d["run"]
    r: dict[str, Any] = (
        await client.get(f"/api/v1/cases/{case_id}/opportunities/{opp_id}/research")
    ).json()
    return r


async def test_research_records_requirements_with_quotes_and_conflicts(
    client: httpx.AsyncClient, worker: Any, clean_db: Engine
) -> None:
    case_id, opp_id = await _phd_case(client, worker)
    research = await _research(client, worker, case_id, opp_id)
    origins = sorted(s["origin"] for s in research["sources"])
    assert origins == ["demo", "demo", "demo", "listing"]  # nothing went to the network
    assert all(s["status"] == "ok" and not s["is_stale"] for s in research["sources"])
    f = research["findings"]
    deadlines = [x for x in f if x["kind"] == "deadline"]
    # The university page and listing say 1 December; a mirror says 15 November: flagged.
    assert {x["value"]["date"] for x in deadlines} == {"2026-12-01", "2026-11-15"}
    assert all(x["status"] == "conflict" and "disagree" in x["note"] for x in deadlines)
    sup = next(x for x in f if x["kind"] == "supervisor" and "Beispiel" in x["summary"])
    assert sup["value"]["research_interests"][0] == "model calibration"
    assert sup["value"]["profile_url"] == "https://tu-exampleton.example/people/beispiel"
    docs = {x["field"] for x in f if x["kind"] == "document_required"}
    assert {"cv", "transcript", "statement", "reference_letter"} <= docs
    assert {x["field"] for x in f if x["kind"] == "language_test"} == {"ielts", "toefl"}
    with clean_db.connect() as conn:  # every quote is verbatim from its stored source text
        rows = conn.execute(
            text(
                "SELECT f.quote, s.text FROM research_findings f "
                "JOIN research_sources s ON s.id = f.source_id"
            )
        ).all()
    assert rows
    assert all(q in t for q, t in rows)

    again = await _research(client, worker, case_id, opp_id)  # re-running replaces, no duplicates
    assert len(again["findings"]) == len(f)
    assert len(again["sources"]) == len(research["sources"])


async def test_sop_is_grounded_with_placeholders_and_removed_claims(
    client: httpx.AsyncClient, worker: Any
) -> None:
    case_id, opp_id = await _phd_case(client, worker)
    await _research(client, worker, case_id, opp_id)
    d = await _run(
        client,
        worker,
        await client.post(
            f"/api/v1/cases/{case_id}/generated-documents",
            json={"doc_type": "sop", "opportunity_id": opp_id},
        ),
    )
    assert d["run"]["status"] == "succeeded", d["run"]
    result = d["run"]["result"]
    assert result["status"] == "drafted"
    assert result["files_ok"] is True
    assert result["model"]["is_mock"] is True
    doc = (await client.get(f"/api/v1/generated-documents/{result['document_id']}")).json()
    cur = doc["current"]
    assert doc["doc_type"] == "sop"
    assert doc["opportunity_id"] == opp_id
    assert cur["is_mock"] is True
    assert cur["origin"] == "generated"
    md = cur["markdown"]
    assert md.startswith("# ")
    assert "## Motivation" in md
    assert "## Goals" in md
    assert "I studied MSc, Computer Science at University of Sampleford." in md
    assert "[[PLACEHOLDER:" in md
    assert len(cur["placeholders"]) >= 2
    # The mock's deliberately unsupported claim was removed and reported, not published.
    assert "12 peer-reviewed papers" not in md
    removed = cur["report"]["removed"]
    assert any("12 peer-reviewed" in r["text"] and "numbers" in r["reason"] for r in removed)
    assert all(c["fact_ids"] for c in cur["report"]["claims"])
    assert cur["report"]["to_check"]  # intent sentences flagged for the user
    assert "Private Person" not in md
    assert cur["files"]["pdf"]["checks"]["ok"]
    assert cur["files"]["docx"]["checks"]["ok"]

    pdf = await client.get(f"/api/v1/generated-documents/{doc['id']}/versions/1/files/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert "attachment" in pdf.headers["content-disposition"]
    text_ = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "Motivation" in text_
    assert "PLACEHOLDER" in text_
    docx = await client.get(f"/api/v1/generated-documents/{doc['id']}/versions/1/files/docx")
    assert docx.status_code == 200
    assert zipfile.is_zipfile(io.BytesIO(docx.content))


async def test_edit_creates_version_and_render_on_demand(
    client: httpx.AsyncClient, worker: Any
) -> None:
    case_id, opp_id = await _phd_case(client, worker)
    d = await _run(
        client,
        worker,
        await client.post(
            f"/api/v1/cases/{case_id}/generated-documents",
            json={"doc_type": "research_proposal", "opportunity_id": opp_id},
        ),
    )
    doc_id = d["run"]["result"]["document_id"]
    doc = (await client.get(f"/api/v1/generated-documents/{doc_id}")).json()
    edited = doc["current"]["markdown"].replace(
        "[[PLACEHOLDER: a rough plan for each year]]", "Year 1: literature review."
    )
    r = await client.post(
        f"/api/v1/generated-documents/{doc_id}/versions",
        json={"markdown": edited, "base_version": 1},
    )
    assert r.status_code == 201, r.text
    v2 = r.json()
    assert v2["current_version"] == 2
    assert v2["current"]["origin"] == "user_edit"
    assert len(v2["current"]["placeholders"]) == len(doc["current"]["placeholders"]) - 1
    assert v2["current"]["has_files"] is False  # needs rendering again
    stale = await client.post(
        f"/api/v1/generated-documents/{doc_id}/versions",
        json={"markdown": "late edit", "base_version": 1},
    )
    assert stale.status_code == 409  # optimistic concurrency: no silent overwrite
    missing = await client.get(f"/api/v1/generated-documents/{doc_id}/versions/2/files/pdf")
    assert missing.status_code == 404
    d = await _run(
        client,
        worker,
        await client.post(f"/api/v1/generated-documents/{doc_id}/render", json={"version": 2}),
    )
    assert d["run"]["status"] == "succeeded"
    assert d["run"]["result"]["pdf"]["ok"]
    pdf = await client.get(f"/api/v1/generated-documents/{doc_id}/versions/2/files/pdf")
    text_ = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "Year 1: literature review." in text_
    v1 = (await client.get(f"/api/v1/generated-documents/{doc_id}/versions/1")).json()
    assert "a rough plan for each year" in v1["markdown"]  # versions are immutable


async def test_academic_cv_is_assembled_without_ai(
    client: httpx.AsyncClient, worker: Any, clean_db: Engine
) -> None:
    case_id, _ = await _phd_case(client, worker)
    d = await _run(
        client,
        worker,
        await client.post(
            f"/api/v1/cases/{case_id}/generated-documents", json={"doc_type": "academic_cv"}
        ),
    )
    assert d["run"]["status"] == "succeeded", d["run"]
    doc = (
        await client.get(f"/api/v1/generated-documents/{d['run']['result']['document_id']}")
    ).json()
    cur = doc["current"]
    assert cur["origin"] == "assembled"
    assert cur["model"] is None
    assert cur["is_mock"] is False
    md = cur["markdown"]
    for heading in (
        "## Education",
        "## Research experience",
        "## Professional experience",
        "## Skills",
    ):
        assert heading in md
    assert "Python, PyTorch" in md
    assert "Private Person" not in md
    # No position, so the international format (and its contact hint) is used.
    assert cur["placeholders"] == ["contact details (city and country, phone, email)"]
    assert cur["report"]["format"]["key"] == "international"
    with clean_db.connect() as conn:  # no model call
        assert conn.execute(text("SELECT count(*) FROM usage_records")).scalar() == 0


async def test_inquiry_email_addresses_the_researched_supervisor(
    client: httpx.AsyncClient, worker: Any
) -> None:
    case_id, opp_id = await _phd_case(client, worker)
    research = await _research(client, worker, case_id, opp_id)
    sup = next(x for x in research["findings"] if "Beispiel" in x["summary"])
    d = await _run(
        client,
        worker,
        await client.post(
            f"/api/v1/cases/{case_id}/generated-documents",
            json={
                "doc_type": "inquiry_email",
                "opportunity_id": opp_id,
                "supervisor_finding_id": sup["id"],
            },
        ),
    )
    doc = (
        await client.get(f"/api/v1/generated-documents/{d['run']['result']['document_id']}")
    ).json()
    md = doc["current"]["markdown"]
    assert md.startswith("Subject: ")
    assert "## " not in md
    assert "Dear Prof. Dr. Jana Beispiel," in md
    assert "model calibration" in md


async def test_external_model_needs_consent_and_rejection_creates_nothing(
    client: httpx.AsyncClient, worker: Any
) -> None:
    case_id, opp_id = await _phd_case(client, worker)
    provider = (
        await client.post(
            "/api/v1/providers",
            json={
                "name": "Remote",
                "kind": "openai_compatible",
                "model": "x",
                "base_url": "https://api.example.com/v1",
                "api_key": "sk-test-1234567890",
                "is_default": True,
            },
        )
    ).json()
    resp = await client.post(
        f"/api/v1/cases/{case_id}/generated-documents",
        json={"doc_type": "sop", "opportunity_id": opp_id},
    )
    d = await _run(client, worker, resp)
    assert d["run"]["status"] == "waiting_approval"
    approval = d["approvals"][0]
    assert "Remote" in approval["title"]
    assert "Private Person" not in str(approval["details"])
    await client.post(f"/api/v1/approvals/{approval['id']}/decision", json={"approve": False})
    await worker.run_until_idle()
    d = (await client.get(f"/api/v1/runs/{resp.json()['run_id']}")).json()
    assert d["run"]["result"]["status"] == "not_sent"
    assert (await client.get(f"/api/v1/cases/{case_id}/generated-documents")).json() == []
    assert provider["data_leaves_device"] is True


async def test_draft_validation(client: httpx.AsyncClient) -> None:
    await register(client)
    case_id = str((await create_case(client))["id"])
    bad = await client.post(
        f"/api/v1/cases/{case_id}/generated-documents", json={"doc_type": "ransom_note"}
    )
    assert bad.status_code == 422
    needs_opp = await client.post(
        f"/api/v1/cases/{case_id}/generated-documents", json={"doc_type": "sop"}
    )
    assert needs_opp.status_code == 422
    later = await client.post(
        f"/api/v1/cases/{case_id}/generated-documents", json={"doc_type": "cover_letter"}
    )
    assert later.status_code == 422  # job documents arrive in M6
