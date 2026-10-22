"""M18: reading a CV and a letter well, linking entries, bulk actions, snapshots, auto-arrange,
and moving a whole profile to a new case with export/import (nothing existing is changed)."""

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.helpers import create_case, facts, register, uploaded

pytestmark = pytest.mark.db
PERSONAS = Path(__file__).parent.parent / "fixtures" / "personas"


async def _profile(client: httpx.AsyncClient) -> tuple[str, list[dict[str, Any]]]:
    await register(client)
    case_id = str((await create_case(client, "Rohan's search"))["id"])
    await uploaded(client, case_id, (PERSONAS / "rohan_cv.md").read_bytes(), "cv.md")
    await uploaded(
        client,
        case_id,
        (PERSONAS / "letter_formal.txt").read_bytes(),
        "letter.txt",
        purpose="recommendation_letter",
    )
    return case_id, await facts(client, case_id)


def _by_label(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {f["label"]: f for f in rows}


async def test_reading_links_letters_and_reread(client: httpx.AsyncClient) -> None:
    case_id, rows = await _profile(client)
    assert all("**" not in json.dumps(f["data"]) for f in rows)
    by = _by_label(rows)
    job = by["Machine Learning Engineer at Lumen Robotics"]
    assert by["VisionDesk"]["data"]["related_fact_ids"] == [job["id"]]
    ref = next(f for f in rows if f["section"] == "reference")
    assert ref["data"]["name"] == "Dr. Vikram Sample"
    assert ref["is_private"] is True  # references are private by default
    assert ref["review_state"] == "pending"

    # The mind map shows the link once the entries are confirmed.
    ids = [f["id"] for f in rows]
    r = await client.post(
        f"/api/v1/cases/{case_id}/facts/bulk", json={"action": "accept", "ids": ids}
    )
    assert r.json()["changed"] == len(ids)
    mm = (await client.get(f"/api/v1/cases/{case_id}/mindmap")).json()
    assert {"source": f"fact:{by['VisionDesk']['id']}", "target": f"fact:{job['id']}"} in [
        {"source": e["source"], "target": e["target"]}
        for e in mm["edges"]
        if e["kind"] == "part_of"
    ]

    # A link must point at a role or place in the same case.
    skill = next(f for f in rows if f["section"] == "skill")
    bad = await client.patch(
        f"/api/v1/facts/{by['VisionDesk']['id']}",
        json={
            "version": by["VisionDesk"]["version"] + 1,
            "data": {**by["VisionDesk"]["data"], "related_fact_ids": [skill["id"]]},
        },
    )
    assert bad.status_code == 422

    # Re-reading replaces only pending, unedited entries; confirmed ones stay.
    docs = (await client.get(f"/api/v1/cases/{case_id}/documents")).json()
    cv = next(d for d in docs if d["filename"] == "cv.md")
    again = (await client.post(f"/api/v1/documents/{cv['id']}/reread")).json()
    assert again == {"removed": 0, "created": 0}  # everything was confirmed, nothing duplicated
    assert len(await facts(client, case_id)) == len(rows)


async def test_reread_never_brings_back_what_was_rejected(client: httpx.AsyncClient) -> None:
    case_id, rows = await _profile(client)
    skills = [f for f in rows if f["section"] == "skill"]
    reject = skills[0]
    await client.post(
        f"/api/v1/cases/{case_id}/facts/bulk", json={"action": "reject", "ids": [reject["id"]]}
    )
    docs = (await client.get(f"/api/v1/cases/{case_id}/documents")).json()
    cv = next(d for d in docs if d["filename"] == "cv.md")
    pending_before = [f for f in await facts(client, case_id) if f["review_state"] == "pending"]
    out = (await client.post(f"/api/v1/documents/{cv['id']}/reread")).json()
    assert out["removed"] == len([f for f in pending_before if f["section"] != "reference"])
    after = await facts(client, case_id)
    assert [f["label"] for f in after].count(reject["label"]) == 1  # not re-added
    assert next(f for f in after if f["id"] == reject["id"])["review_state"] == "rejected"


async def test_reread_doesnt_suggest_what_you_edited_again(client: httpx.AsyncClient) -> None:
    """A job the user retitled (same employer give or take "Pvt. Ltd.", same start) isn't
    offered again as new, and a project re-read from the CV links to the user's version."""
    case_id, rows = await _profile(client)
    job = _by_label(rows)["Machine Learning Engineer at Lumen Robotics"]
    edited = {
        **job["data"],
        "title": "Senior ML Engineer",
        "organization": "Lumen Robotics Pvt. Ltd.",
    }
    r = await client.patch(
        f"/api/v1/facts/{job['id']}",
        json={"version": job["version"], "review_state": "accepted", "data": edited},
    )
    assert r.status_code == 200, r.text
    docs = (await client.get(f"/api/v1/cases/{case_id}/documents")).json()
    cv = next(d for d in docs if d["filename"] == "cv.md")
    await client.post(f"/api/v1/documents/{cv['id']}/reread")
    after = await facts(client, case_id)
    jobs = [f["label"] for f in after if f["section"] == "employment"]
    assert sorted(jobs) == [
        "Senior ML Engineer at Lumen Robotics Pvt. Ltd.",
        "Teaching Assistant at Example Institute of Technology",
    ]
    desk = _by_label(after)["VisionDesk"]
    assert desk["review_state"] == "pending"
    assert desk["data"]["related_fact_ids"] == [job["id"]]


async def test_bulk_actions_snapshots_and_auto_arrange(client: httpx.AsyncClient) -> None:
    case_id, rows = await _profile(client)
    ids = [f["id"] for f in rows]
    base = f"/api/v1/cases/{case_id}"
    await client.post(f"{base}/facts/bulk", json={"action": "accept", "ids": ids})
    priv = await client.post(f"{base}/facts/bulk", json={"action": "private", "ids": ids[:3]})
    assert priv.json()["changed"] >= 2
    skills = [f["id"] for f in rows if f["section"] == "skill"][:2]
    gone = await client.post(f"{base}/facts/bulk", json={"action": "delete", "ids": skills})
    assert gone.json()["changed"] == 2
    assert len(await facts(client, case_id)) == len(rows) - 2
    assert (
        await client.post(f"{base}/facts/bulk", json={"action": "nope", "ids": ids})
    ).status_code == 422

    for _ in range(3):
        assert (await client.post(f"{base}/snapshots", json={})).status_code == 201
    assert (await client.delete(f"{base}/snapshots/2")).status_code == 204
    assert [s["number"] for s in (await client.get(f"{base}/snapshots")).json()] == [3, 1]
    assert (await client.delete(f"{base}/snapshots/2")).status_code == 404

    node = f"fact:{ids[0]}"
    await client.put(
        f"{base}/mindmap/nodes/{node}", json={"x": 10, "y": 20, "hidden": False, "label": "Renamed"}
    )
    await client.put(f"{base}/mindmap/nodes/fact:{ids[1]}", json={"x": 5, "y": 5, "hidden": False})
    assert (await client.post(f"{base}/mindmap/layout/reset")).status_code == 204
    nodes = {n["key"]: n for n in (await client.get(f"{base}/mindmap")).json()["nodes"]}
    assert (nodes[node]["x"], nodes[node]["y"], nodes[node]["label_override"]) == (
        None,
        None,
        "Renamed",
    )
    assert nodes[f"fact:{ids[1]}"]["x"] is None  # position forgotten, nothing else to keep


async def test_export_then_import_is_a_faithful_new_case(client: httpx.AsyncClient) -> None:
    case_id, rows = await _profile(client)
    base = f"/api/v1/cases/{case_id}"
    by = _by_label(rows)
    await client.post(
        f"{base}/facts/bulk", json={"action": "accept", "ids": [f["id"] for f in rows[:20]]}
    )
    await client.post(f"{base}/snapshots", json={"reason": "before"})
    job = by["Machine Learning Engineer at Lumen Robotics"]
    await client.put(
        f"{base}/mindmap/nodes/fact:{job['id']}",
        json={"x": 1, "y": 2, "hidden": False, "label": "Lumen"},
    )
    await client.post(
        f"{base}/affiliations",
        json={"organization": "Lumen Robotics", "relationship_type": "current_employee"},
    )
    await client.post(f"{base}/social-profiles", json={"url": "https://github.com/rohan-example"})
    await client.post(f"{base}/answers", json={"question": "Notice period?", "answer": "One month"})

    exported = await client.get(f"{base}/export")
    assert exported.status_code == 200
    assert exported.headers["content-disposition"].endswith('.nexscout"')
    zf = zipfile.ZipFile(io.BytesIO(exported.content))
    payload = json.loads(zf.read("profile.json"))
    assert payload["format"] == "nexscout-profile/1"
    assert len([n for n in zf.namelist() if n.startswith("documents/")]) == 2
    assert "secret" not in json.dumps(payload).lower()

    r = await client.post(
        "/api/v1/cases/import", files={"file": ("p.nexscout", exported.content, "application/zip")}
    )
    assert r.status_code == 201, r.text
    report = r.json()
    assert report["case_name"] == "Rohan's search (imported)"
    assert report["counts"]["facts"] == len(rows)
    assert report["counts"]["documents"] == 2
    new = report["case_id"]

    copied = await facts(client, new)
    assert sorted((f["label"], f["review_state"], f["is_private"]) for f in copied) == sorted(
        (f["label"], f["review_state"], f["is_private"]) for f in await facts(client, case_id)
    )
    cby = _by_label(copied)
    new_job = cby["Machine Learning Engineer at Lumen Robotics"]
    assert cby["VisionDesk"]["data"]["related_fact_ids"] == [new_job["id"]]  # remapped
    assert new_job["id"] != job["id"]
    mm = (await client.get(f"/api/v1/cases/{new}/mindmap")).json()
    node = next(n for n in mm["nodes"] if n["key"] == f"fact:{new_job['id']}")
    assert (node["x"], node["y"], node["label_override"]) == (1, 2, "Lumen")
    snaps = (await client.get(f"/api/v1/cases/{new}/snapshots")).json()
    assert [s["reason"] for s in snaps] == ["before"]
    ev = (await client.get(f"/api/v1/facts/{new_job['id']}/evidence")).json()
    assert ev
    assert ev[0]["excerpt"].startswith("### Machine Learning Engineer")
    docs = (await client.get(f"/api/v1/cases/{new}/documents")).json()
    assert {d["filename"] for d in docs} == {"cv.md", "letter.txt"}
    assert (await client.get(f"/api/v1/cases/{new}/affiliations")).json()[0][
        "organization"
    ] == "Lumen Robotics"
    answers = (await client.get(f"/api/v1/cases/{new}/answers")).json()
    assert answers[0]["answer"] == "One month"
    # The original is untouched.
    assert len(await facts(client, case_id)) == len(rows)


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


async def test_import_refuses_unsafe_or_foreign_files(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await register(client)

    async def post(data: bytes) -> httpx.Response:
        return await client.post(
            "/api/v1/cases/import", files={"file": ("x.nexscout", data, "application/zip")}
        )

    good = json.dumps({"format": "nexscout-profile/1", "case": {"name": "X"}, "facts": []}).encode()
    assert (await post(b"not a zip")).status_code == 422
    assert (await post(_zip({"other.json": b"{}"}))).status_code == 422
    assert (await post(_zip({"profile.json": good, "../evil.txt": b"x"}))).status_code == 422
    newer = json.dumps({"format": "nexscout-profile/9", "case": {"name": "X"}}).encode()
    r = await post(_zip({"profile.json": newer}))
    assert r.status_code == 422
    assert "newer NexScout" in r.json()["detail"]
    from nexscout.application import profile_bundle

    monkeypatch.setattr(profile_bundle, "MAX_UNCOMPRESSED", 1000)
    assert (await post(_zip({"profile.json": good, "big.bin": b"0" * 5000}))).status_code == 422
    monkeypatch.undo()

    odd = json.dumps(
        {
            "format": "nexscout-profile/1",
            "case": {"name": "Odd"},
            "facts": [
                {
                    "id": "a",
                    "section": "skill",
                    "data": {"name": "Python"},
                    "review_state": "accepted",
                },
                {"id": "b", "section": "spaceship", "data": {"name": "X"}},
                {"id": "c", "section": "skill", "data": {"name": ""}},
            ],
            "future_part": {"x": 1},
        }
    ).encode()
    r = await post(_zip({"profile.json": odd}))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["counts"]["facts"] == 1
    assert len(body["warnings"]) == 3  # two bad entries and the unknown part, all reported
