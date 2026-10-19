"""M15: real-source plumbing end to end (providers faked at the provider boundary).

Catalog sources stay off until turned on; a sync reads them in parallel, keeps only postings in
the case's countries and keywords, records each source's health, and one failing source never
stops the others. Custom sources and career-ops imports are owned by the user.
"""

from typing import Any

import httpx
import pytest

from nexscout.application import sources as sources_app
from nexscout.integrations.sources import providers as prov
from nexscout.integrations.sources.core import Entry, Http, Job, SourceError
from tests.helpers import create_case, register, sync

pytestmark = pytest.mark.db


class FakeBoard:
    id, label, category = "fakeboard", "Fake board", "board"
    terms = "Test double."

    def detect(self, url: str) -> dict[str, Any] | None:
        return {"slug": url.rsplit("/", 1)[-1]} if "fake.example" in url else None

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        if entry.config.get("slug") == "broken":
            raise SourceError("The source answered with HTTP 503.")
        return [
            Job(
                title="Computer Vision Engineer",
                url="https://fake.example/j/1",
                company="Nordic AI Oy",
                location="Espoo, Finland",
                description="We offer visa sponsorship. English is our working language.",
            ),
            Job(
                title="Machine Learning Engineer",
                url="https://fake.example/j/2",
                company="Bangalore AI",
                location="Bengaluru, India",
            ),
            Job(
                title="Senior Java Developer",
                url="https://fake.example/j/3",
                company="Nordic AI Oy",
                location="Helsinki, Finland",
            ),
            Job(
                title="ML Engineer (Remote EU)",
                url="https://fake.example/j/4",
                company="Remote Co",
                location="Remote - EU",
            ),
        ]


@pytest.fixture
def fake_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    board = FakeBoard()
    monkeypatch.setitem(prov.PROVIDERS, "fakeboard", board)
    monkeypatch.setitem(sources_app.PROVIDERS, "fakeboard", board)
    entries = {
        "fakeboard:good": Entry(
            key="fakeboard:good",
            provider="fakeboard",
            name="Good board",
            config={"slug": "good"},
            countries=["FI"],
            category="board",
        ),
        "greenhouse:anthropic": Entry(
            key="greenhouse:anthropic",
            provider="greenhouse",
            name="Anthropic",
            url="https://job-boards.greenhouse.io/anthropic",
            config={"slug": "anthropic"},
        ),
        "fakeboard:broken": Entry(
            key="fakeboard:broken",
            provider="fakeboard",
            name="Broken board",
            config={"slug": "broken"},
            category="board",
        ),
    }
    monkeypatch.setattr(sources_app, "catalog_entries", lambda: entries)


async def _case(client: httpx.AsyncClient) -> str:
    await register(client)
    case_id = str((await create_case(client, "Europe AI"))["id"])
    await client.patch(f"/api/v1/cases/{case_id}", json={"version": 1, "career_path": "employment"})
    prefs = (await client.get(f"/api/v1/cases/{case_id}/preferences")).json()
    r = await client.put(
        f"/api/v1/cases/{case_id}/preferences",
        json={
            "version": prefs["version"],
            "data": {
                **prefs["data"],
                "countries": ["Europe"],
                "countries_exclude": ["IN"],
                "search_keywords": ["machine learning", "computer vision", "ml"],
                "exclude_keywords": ["java"],
                "needs_visa_sponsorship": True,
            },
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["countries"] == ["EUROPE"]  # names become codes/groups
    return case_id


async def test_catalog_sources_filters_health_and_isolation(
    client: httpx.AsyncClient, fake_catalog: None
) -> None:
    case_id = await _case(client)
    listed = {s["key"]: s for s in (await client.get("/api/v1/sources")).json()}
    assert listed["fakeboard:good"]["enabled"] is False  # off until the user turns it on
    r = await client.post(
        "/api/v1/sources/bulk",
        json={"keys": ["fakeboard:good", "fakeboard:broken"], "enabled": True},
    )
    assert r.json() == {"changed": 2}
    # Turn the demo sources off so only the real ones run.
    demo = [k for k, s in listed.items() if s["is_demo_data"]]
    await client.post("/api/v1/sources/bulk", json={"keys": demo, "enabled": False})

    result = await sync(client, case_id)
    good, broken = result["fakeboard:good"], result["fakeboard:broken"]
    assert broken["skipped_reason"] == "The source answered with HTTP 503."
    # Kept: CV engineer in Finland and the remote-EU ML role. Dropped: India (excluded),
    # Java (excluded word).
    assert (good["fetched"], good["filtered"]) == (2, 2)
    opps = (await client.get(f"/api/v1/cases/{case_id}/opportunities")).json()
    titles = {o["title"] for o in opps}
    assert titles == {"Computer Vision Engineer", "ML Engineer (Remote EU)"}
    cv = next(o for o in opps if o["title"] == "Computer Vision Engineer")
    assert cv["data"]["country_codes"] == ["FI"]
    assert cv["data"]["sponsorship"] == "yes"
    assert cv["eligible"] is True
    health = {s["key"]: s for s in (await client.get("/api/v1/sources")).json()}
    assert health["fakeboard:good"]["last_status"] == "ok"
    assert health["fakeboard:good"]["last_count"] == 4
    assert health["fakeboard:broken"]["last_status"] == "error"
    assert "503" in health["fakeboard:broken"]["last_error"]


async def test_add_by_url_import_and_test(
    client: httpx.AsyncClient, other_client: httpx.AsyncClient, fake_catalog: None
) -> None:
    await register(client)
    added = await client.post(
        "/api/v1/sources", json={"url": "https://fake.example/acme", "name": "Acme"}
    )
    assert added.status_code == 201, added.text
    body = added.json()
    assert (body["provider"], body["postings"]) == ("fakeboard", 4)
    tested = await client.post(f"/api/v1/sources/{body['key']}/test")
    assert tested.json()["ok"] is True
    assert tested.json()["postings"] == 4
    nope = await client.post("/api/v1/sources", json={"url": "http://127.0.0.1/x"})
    assert nope.status_code == 422  # private addresses are refused

    portals = """
tracked_companies:
  - name: Anthropic
    careers_url: https://job-boards.greenhouse.io/anthropic
  - name: Some Co
    careers_url: https://jobs.lever.co/someco
  - name: Branded
    careers_url: https://www.example.com/careers
    scan_method: websearch
  - name: Off
    careers_url: https://jobs.lever.co/off
    enabled: false
"""
    rep = (await client.post("/api/v1/sources/import", json={"content": portals})).json()
    assert rep["enabled_catalog"] == ["Anthropic"]  # in the catalog: turned on, not duplicated
    assert rep["added"] == ["Some Co"]
    assert [u["name"] for u in rep["unsupported"]] == ["Branded"]
    keys = {s["key"]: s for s in (await client.get("/api/v1/sources")).json()}
    assert keys["custom:lever:someco"]["enabled"] is True
    assert keys["custom:lever:someco"]["origin"] == "custom"

    # Another user sees none of it and can't touch it.
    await register(other_client, email="eve@example.com", name="Eve")
    theirs = {s["key"] for s in (await other_client.get("/api/v1/sources")).json()}
    assert "custom:lever:someco" not in theirs
    assert (await other_client.delete("/api/v1/sources/custom:lever:someco")).status_code == 404
    assert (await client.delete("/api/v1/sources/custom:lever:someco")).status_code == 204


async def test_manual_only_sites_are_never_fetched_and_import_is_capped(
    client: httpx.AsyncClient, fake_catalog: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    await register(client)

    async def no_network(*_: Any, **__: Any) -> Any:
        raise AssertionError("a manual-only site must not be fetched")

    monkeypatch.setattr(sources_app, "probe", no_network)
    refused = await client.post("/api/v1/sources", json={"url": "https://duunitori.fi/tyopaikat"})
    assert refused.status_code == 422
    assert "Duunitori" in refused.json()["detail"]
    assert "automated" in refused.json()["detail"]

    monkeypatch.setattr(sources_app, "MAX_CUSTOM", 1)
    portals = """
tracked_companies:
  - name: Linked
    careers_url: https://www.linkedin.com/company/acme/jobs
  - name: First
    careers_url: https://jobs.lever.co/first
  - name: Second
    careers_url: https://jobs.lever.co/second
"""
    rep = (await client.post("/api/v1/sources/import", json={"content": portals})).json()
    assert rep["added"] == ["First"]
    reasons = {u["name"]: u["reason"] for u in rep["unsupported"]}
    assert "LinkedIn" in reasons["Linked"]
    assert "up to 1 sources" in reasons["Second"]
    # Importing the same file again uses no extra room.
    again = (await client.post("/api/v1/sources/import", json={"content": portals})).json()
    assert again["added"] == ["First"]
