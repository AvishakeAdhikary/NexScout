from pathlib import Path

import httpx
import pytest

from tests.fixtures.documents import ada_cv_text, make_docx, make_pdf
from tests.helpers import create_case, facts, register, upload

pytestmark = pytest.mark.db


async def _setup(client: httpx.AsyncClient) -> str:
    await register(client)
    return str((await create_case(client))["id"])


async def test_markdown_cv_upload_creates_pending_facts_with_evidence(
    client: httpx.AsyncClient, storage_dir: Path
) -> None:
    case_id = await _setup(client)
    resp = await upload(client, case_id, ada_cv_text().encode(), "ada.md")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    doc = body["document"]
    assert doc["parse_status"] == "parsed"
    assert doc["file_kind"] == "markdown"
    assert doc["extraction_method"] == "heuristic_v1"
    assert body["facts_created"] == doc["facts_extracted"] > 10

    rows = await facts(client, case_id)
    assert len(rows) == body["facts_created"]
    assert {r["review_state"] for r in rows} == {"pending"}
    assert {r["status"] for r in rows} == {"extracted"}
    assert all(r["evidence_count"] == 1 for r in rows)

    job = next(r for r in rows if r["section"] == "employment")
    ev = (await client.get(f"/api/v1/facts/{job['id']}/evidence")).json()
    assert ev[0]["document_id"] == doc["id"]
    assert ev[0]["kind"] == "document"
    text = (await client.get(f"/api/v1/documents/{doc['id']}/text")).json()["text"]
    assert text[ev[0]["char_start"] : ev[0]["char_end"]].startswith(ev[0]["excerpt"][:20])

    # Original bytes are stored and downloadable, always as an attachment.
    dl = await client.get(f"/api/v1/documents/{doc['id']}/content")
    assert dl.status_code == 200
    assert dl.content == ada_cv_text().encode()
    assert dl.headers["content-disposition"].startswith("attachment;")
    assert "sandbox" in dl.headers["content-security-policy"]
    assert len(list(storage_dir.rglob("*"))) >= 1


async def test_pdf_and_docx_uploads_parse(client: httpx.AsyncClient) -> None:
    case_id = await _setup(client)
    pdf = make_pdf(
        [["Skills", "Python, SQL"], ["Education", "BSc in Physics, University of Sampleford"]]
    )
    resp = await upload(client, case_id, pdf, "cv.pdf")
    assert resp.status_code == 201, resp.text
    assert resp.json()["document"]["page_count"] == 2
    edu = await facts(client, case_id, section="education")
    ev = (await client.get(f"/api/v1/facts/{edu[0]['id']}/evidence")).json()
    assert ev[0]["page"] == 2

    resp = await upload(client, case_id, make_docx(ada_cv_text().splitlines()), "cv.docx")
    assert resp.status_code == 201, resp.text
    assert resp.json()["document"]["file_kind"] == "docx"
    assert resp.json()["facts_created"] > 5


async def test_unsupported_file_rejected_and_not_stored(
    client: httpx.AsyncClient, storage_dir: Path
) -> None:
    case_id = await _setup(client)
    resp = await upload(client, case_id, b"MZ\x90\x00\x03\x00\x00\x00binary", "cv.pdf")
    assert resp.status_code == 422
    assert "Unsupported file type" in resp.json()["detail"]
    assert not any(p.is_file() for p in storage_dir.rglob("*"))
    assert (await client.get(f"/api/v1/cases/{case_id}/documents")).json() == []


async def test_unreadable_pdf_is_kept_with_failed_status(client: httpx.AsyncClient) -> None:
    case_id = await _setup(client)
    resp = await upload(client, case_id, b"%PDF-1.4\n not really a pdf", "scan.pdf")
    assert resp.status_code == 201
    doc = resp.json()["document"]
    assert doc["parse_status"] == "failed"
    assert doc["parse_error"]
    assert resp.json()["facts_created"] == 0


async def test_non_cv_documents_are_not_mined_for_facts(client: httpx.AsyncClient) -> None:
    case_id = await _setup(client)
    resp = await upload(
        client, case_id, ada_cv_text().encode(), "letter.md", purpose="recommendation_letter"
    )
    assert resp.status_code == 201
    assert resp.json()["facts_created"] == 0
    assert await facts(client, case_id) == []


async def test_delete_document_keeps_accepted_facts_and_excerpts(
    client: httpx.AsyncClient, storage_dir: Path
) -> None:
    case_id = await _setup(client)
    doc = (await upload(client, case_id, ada_cv_text().encode(), "ada.md")).json()["document"]
    rows = await facts(client, case_id)
    keep = rows[0]["id"]
    await client.post(f"/api/v1/cases/{case_id}/facts/review", json={"accept": [keep]})

    resp = await client.delete(
        f"/api/v1/documents/{doc['id']}", params={"delete_pending_facts": "true"}
    )
    assert resp.status_code == 204
    remaining = await facts(client, case_id)
    assert [r["id"] for r in remaining] == [keep]
    ev = (await client.get(f"/api/v1/facts/{keep}/evidence")).json()
    assert ev[0]["document_id"] is None  # unlinked from the deleted file
    assert ev[0]["excerpt"]  # but the quoted source text remains
    assert not any(p.is_file() for p in storage_dir.rglob("*"))
    assert (await client.get(f"/api/v1/documents/{doc['id']}")).status_code == 404


async def test_upload_to_missing_case_is_404(client: httpx.AsyncClient) -> None:
    await register(client)
    resp = await upload(client, "00000000-0000-0000-0000-000000000000", b"hello")
    assert resp.status_code == 404
