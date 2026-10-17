"""Location-aware documents: the format follows the position's country (or the user's
override), files use the right paper, and posting limits block uploads that would be rejected."""

import io
from typing import Any

import httpx
import pytest
from pypdf import PdfReader

from tests.helpers import create_case, register

pytestmark = pytest.mark.db


async def _case(client: httpx.AsyncClient, worker: Any) -> tuple[str, dict[str, str]]:
    await register(client)
    case_id = str((await create_case(client, "Formats"))["id"])
    await client.patch(f"/api/v1/cases/{case_id}", json={"version": 1, "career_path": "both"})
    for section, data in (
        ("employment", {"title": "ML Engineer", "organization": "Examplecorp", "start": "2021-03"}),
        ("education", {"institution": "University of Sampleford", "degree": "MSc", "end": "2020"}),
        ("skill", {"name": "Python"}),
    ):
        await client.post(f"/api/v1/cases/{case_id}/facts", json={"section": section, "data": data})
    await client.post(f"/api/v1/cases/{case_id}/opportunities/sync", json={})
    await worker.run_until_idle()
    by_source: dict[str, str] = {}
    for academic in ("true", "false"):
        for o in (
            await client.get(f"/api/v1/cases/{case_id}/opportunities?academic={academic}")
        ).json():
            for src in o["sources"]:
                by_source[src["source_url"].rsplit("/", 1)[1]] = o["id"]
    return case_id, by_source


async def _draft(
    client: httpx.AsyncClient, worker: Any, case_id: str, **body: Any
) -> dict[str, Any]:
    r = await client.post(f"/api/v1/cases/{case_id}/generated-documents", json=body)
    assert r.status_code == 202, r.text
    await worker.run_until_idle()
    run = (await client.get(f"/api/v1/runs/{r.json()['run_id']}")).json()
    assert run["run"]["status"] == "succeeded", (
        run["run"]["error"],
        [s["error"] for s in run["steps"]],
    )
    doc: dict[str, Any] = (
        await client.get(f"/api/v1/generated-documents/{run['run']['result']['document_id']}")
    ).json()
    return doc


async def _pdf_size(client: httpx.AsyncClient, doc: dict[str, Any], n: int = 1) -> tuple[int, int]:
    pdf = await client.get(f"/api/v1/generated-documents/{doc['id']}/versions/{n}/files/pdf")
    box = PdfReader(io.BytesIO(pdf.content)).pages[0].mediabox
    return round(float(box.width)), round(float(box.height))


async def test_format_follows_the_position_location(client: httpx.AsyncClient, worker: Any) -> None:
    case_id, opps = await _case(client, worker)
    german = opps["a-1001"]  # Acme GmbH, Berlin
    fmt = (
        await client.get(f"/api/v1/cases/{case_id}/opportunities/{german}/document-format")
    ).json()
    assert fmt["key"] == "dach"
    assert "Germany" in fmt["reason"]

    doc = await _draft(client, worker, case_id, doc_type="resume", opportunity_id=german)
    cur = doc["current"]
    assert cur["report"]["format"]["key"] == "dach"
    md = cur["markdown"]
    assert "- 03/2021 \u00b7 **ML Engineer at Examplecorp**" in md  # no end date invented
    assert "[[PLACEHOLDER: place]], [[PLACEHOLDER: date]]" in md
    assert await _pdf_size(client, doc) == (595, 842)  # A4 in points
    comp = cur["files"]["compliance"]
    assert comp["status"] == "blocking"  # placeholders still to fill
    assert cur["files"]["format"]["paper"] == "A4"

    dutch = await _draft(client, worker, case_id, doc_type="resume", opportunity_id=opps["a-4001"])
    assert dutch["current"]["report"]["format"]["key"] == "europass"
    assert "## Work experience" in dutch["current"]["markdown"]

    nowhere = await _draft(client, worker, case_id, doc_type="academic_cv")
    assert nowhere["current"]["report"]["format"]["key"] == "international"
    assert "isn't known" in nowhere["current"]["report"]["format"]["reason"]

    us = await _draft(
        client, worker, case_id, doc_type="resume", opportunity_id=german, format="north_america"
    )
    assert us["current"]["report"]["format"]["key"] == "north_america"
    assert await _pdf_size(client, us) == (612, 792)  # US Letter in points
    bad = await client.post(
        f"/api/v1/cases/{case_id}/generated-documents",
        json={"doc_type": "resume", "format": "klingon"},
    )
    assert bad.status_code == 422


async def test_posting_page_limit_blocks_an_overlong_statement(
    client: httpx.AsyncClient, worker: Any
) -> None:
    case_id, opps = await _case(client, worker)
    nlp = opps["acad-1"]  # its page asks for a research statement of max. 2 pages
    r = await client.post(f"/api/v1/cases/{case_id}/opportunities/{nlp}/research")
    assert r.status_code == 202
    await worker.run_until_idle()

    sop = await _draft(client, worker, case_id, doc_type="sop", opportunity_id=nlp)
    checks = sop["current"]["files"]["compliance"]["checks"]
    posting = [c for c in checks if c["source"].startswith("posting:")]
    assert posting
    assert posting[0]["rule"] == "At most 2 page(s), as the posting asks"
    assert posting[0]["ok"] is True  # the draft is short
    assert "max. 2 pages" in posting[0]["source"]

    # The user writes a 5-page statement with no placeholders left.
    long_text = "# Statement of purpose\n\n" + "\n\n".join(
        "I enjoy careful evaluation of language models and robust measurement. " * 12
        for _ in range(40)
    )
    edit = await client.post(
        f"/api/v1/generated-documents/{sop['id']}/versions",
        json={"markdown": long_text, "base_version": 1},
    )
    assert edit.status_code == 201
    assert edit.json()["current"]["report"]["format"]["key"] == "dach"  # format carried over
    await client.post(f"/api/v1/generated-documents/{sop['id']}/render", json={"version": 2})
    await worker.run_until_idle()
    v2 = (await client.get(f"/api/v1/generated-documents/{sop['id']}")).json()["current"]
    assert v2["files"]["compliance"]["status"] == "blocking"

    # A clean resume plus the over-long statement: NexScout refuses to upload.
    resume = await _draft(client, worker, case_id, doc_type="resume", opportunity_id=nlp)
    md = resume["current"]["markdown"]
    for ph in (
        "[[PLACEHOLDER: contact details (address, phone, email)]]",
        "[[PLACEHOLDER: place]]",
        "[[PLACEHOLDER: date]]",
    ):
        md = md.replace(ph, "Berlin")
    await client.post(
        f"/api/v1/generated-documents/{resume['id']}/versions",
        json={"markdown": md, "base_version": 1},
    )
    await client.post(f"/api/v1/generated-documents/{resume['id']}/render", json={"version": 2})
    await worker.run_until_idle()
    app = (
        await client.post(
            f"/api/v1/cases/{case_id}/applications",
            json={"opportunity_id": nlp, "document_ids": [resume["id"], sop["id"]]},
        )
    ).json()
    blocked = await client.post(f"/api/v1/applications/{app['id']}/browser")
    assert blocked.status_code == 422
    assert "doesn't meet the posting's requirements" in blocked.json()["detail"]
    assert "At most 2 page(s)" in blocked.json()["detail"]
