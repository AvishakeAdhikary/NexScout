"""Contact details per case: saved by the user, suggested from the CV, filled into documents,
carried by Export/Import. Deleting a generated document takes it off applications."""

import io
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.helpers import create_case, drain, register, sync, uploaded

pytestmark = pytest.mark.db
PERSONAS = Path(__file__).parent.parent / "fixtures" / "personas"
DETAILS = {
    "full_name": "Rohan Example",
    "email": "rohan.example@example.com",
    "phone": "+91 00000 00000",
    "city": "Pune",
    "country": "India",
}


async def _case(client: httpx.AsyncClient) -> str:
    await register(client)
    return str((await create_case(client, "Rohan's search"))["id"])


async def test_contact_details_are_suggested_from_the_cv_and_saved_only_when_asked(
    client: httpx.AsyncClient,
) -> None:
    case_id = await _case(client)
    empty = (await client.get(f"/api/v1/cases/{case_id}/contact")).json()
    assert empty == {
        "data": dict.fromkeys(empty["data"]),
        "version": 0,
        "suggested": {},
        "suggested_from": None,
    }

    await uploaded(client, case_id, (PERSONAS / "rohan_cv.md").read_bytes(), "cv.md")
    got = (await client.get(f"/api/v1/cases/{case_id}/contact")).json()
    assert got["version"] == 0  # nothing saved by itself
    assert got["suggested"] == DETAILS
    assert got["suggested_from"] == "cv.md"

    r = await client.put(
        f"/api/v1/cases/{case_id}/contact",
        json={"version": 0, "data": {**got["suggested"], "city": "Mumbai"}},
    )
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["version"] == 1
    assert saved["data"]["city"] == "Mumbai"
    assert saved["suggested"] == {"city": "Pune"}  # only what differs is still suggested

    stale = await client.put(
        f"/api/v1/cases/{case_id}/contact", json={"version": 0, "data": DETAILS}
    )
    assert stale.status_code == 409
    bad = await client.put(
        f"/api/v1/cases/{case_id}/contact", json={"version": 1, "data": {"email": "nope"}}
    )
    assert bad.status_code == 422


async def _resume(client: httpx.AsyncClient, case_id: str) -> dict[str, Any]:
    await client.post(
        f"/api/v1/cases/{case_id}/facts", json={"section": "skill", "data": {"name": "Python"}}
    )
    r = await client.post(
        f"/api/v1/cases/{case_id}/generated-documents", json={"doc_type": "resume"}
    )
    assert r.status_code == 202, r.text
    await drain()
    doc_id = (await client.get(f"/api/v1/runs/{r.json()['run_id']}")).json()["run"]["result"][
        "document_id"
    ]
    doc: dict[str, Any] = (await client.get(f"/api/v1/generated-documents/{doc_id}")).json()
    return doc


async def test_fill_in_my_details_turns_placeholders_into_a_new_version(
    client: httpx.AsyncClient,
) -> None:
    case_id = await _case(client)
    doc = await _resume(client, case_id)  # drafted before any contact details were saved
    assert any(p.startswith("contact details") for p in doc["current"]["placeholders"])

    await client.put(f"/api/v1/cases/{case_id}/contact", json={"version": 0, "data": DETAILS})
    out = (await client.post(f"/api/v1/generated-documents/{doc['id']}/fill")).json()
    assert out == {"filled": 1, "placeholders_left": 0, "current_version": 2}
    after = (await client.get(f"/api/v1/generated-documents/{doc['id']}")).json()
    assert "Pune, India" in after["current"]["markdown"]
    assert after["current"]["origin"] == "user_edit"
    # Nothing left to fill: no new version.
    again = (await client.post(f"/api/v1/generated-documents/{doc['id']}/fill")).json()
    assert again == {"filled": 0, "placeholders_left": 0, "current_version": 2}


async def test_deleting_a_document_takes_it_off_applications(client: httpx.AsyncClient) -> None:
    case_id = await _case(client)
    doc = await _resume(client, case_id)
    await sync(client, case_id)
    opps = (await client.get(f"/api/v1/cases/{case_id}/opportunities?academic=false")).json()
    r = await client.post(
        f"/api/v1/cases/{case_id}/applications",
        json={"opportunity_id": opps[0]["id"], "document_ids": [doc["id"]]},
    )
    assert r.status_code == 201, r.text
    app = r.json()
    assert (await client.delete(f"/api/v1/generated-documents/{doc['id']}")).status_code == 204
    after = (await client.get(f"/api/v1/applications/{app['id']}")).json()
    assert after["document_ids"] == []
    assert after["version"] == app["version"] + 1


async def test_contact_details_travel_with_an_exported_profile(client: httpx.AsyncClient) -> None:
    case_id = await _case(client)
    await client.put(f"/api/v1/cases/{case_id}/contact", json={"version": 0, "data": DETAILS})
    bundle = (await client.get(f"/api/v1/cases/{case_id}/export?documents=false")).content
    r = await client.post(
        "/api/v1/cases/import", files={"file": ("p.nexscout", bundle, "application/zip")}
    )
    assert r.status_code == 201, r.text
    new_case = r.json()["case_id"]
    got = (await client.get(f"/api/v1/cases/{new_case}/contact")).json()
    assert {k: v for k, v in got["data"].items() if v} == DETAILS

    # A bundle from before contact details existed still imports (same format number).
    with zipfile.ZipFile(io.BytesIO(bundle)) as zin:
        import json

        payload = json.loads(zin.read("profile.json"))
        payload.pop("contact")
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as zout:
            for item in zin.infolist():
                data = json.dumps(payload) if item.filename == "profile.json" else zin.read(item)
                zout.writestr(item.filename, data)
    r = await client.post(
        "/api/v1/cases/import", files={"file": ("old.nexscout", out.getvalue(), "application/zip")}
    )
    assert r.status_code == 201, r.text
