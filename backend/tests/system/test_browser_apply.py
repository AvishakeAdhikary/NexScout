"""M7: fill → approve → submit once against a real HTTP demo site with a real headless browser.

Covers: missing answers stop the run, nothing is submitted before approval, declarations are
ticked only after approval, exactly-once submission, observed vs uncertain outcomes, CAPTCHA
hand-over, rejection, a crash mid-submit never resubmits, and SSRF-safe application URLs.
"""

import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.engine import Engine

from nexscout.integrations import fixture_site
from tests.conftest import make_settings
from tests.helpers import create_case, register

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def site_origin() -> Iterator[str]:
    """The demo application site on a real port, as an external site would be."""
    wrapper = FastAPI()
    wrapper.mount("/fixture-site", fixture_site.create_fixture_site())
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(wrapper, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
async def app(clean_db: Engine, storage_dir: Path, site_origin: str) -> AsyncIterator[Any]:
    from nexscout.api.app import create_app

    application = create_app(
        make_settings(storage_dir=storage_dir, fixture_site_origin=site_origin)
    )
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def worker(clean_db: Engine, storage_dir: Path, site_origin: str) -> AsyncIterator[Any]:
    from nexscout.agent_runtime.worker import Worker

    w = Worker(
        make_settings(storage_dir=storage_dir, fixture_site_origin=site_origin),
        worker_id="test-worker-browser",
    )
    await w.open()
    yield w
    await w.close()


def _submissions(job: str) -> list[dict[str, Any]]:
    return [s for s in fixture_site.SUBMISSIONS if s["job"] == job]


async def _setup(client: httpx.AsyncClient, worker: Any) -> tuple[str, dict[str, str], str]:
    """Case with a profile, demo jobs, and a rendered resume. Returns (case, opps, resume)."""
    await register(client)
    case_id = str((await create_case(client, "Jobs"))["id"])
    await client.patch(f"/api/v1/cases/{case_id}", json={"version": 1, "career_path": "both"})
    await client.post(
        f"/api/v1/cases/{case_id}/facts", json={"section": "skill", "data": {"name": "Python"}}
    )
    await client.post(f"/api/v1/cases/{case_id}/opportunities/sync", json={})
    r = await client.post(
        f"/api/v1/cases/{case_id}/generated-documents", json={"doc_type": "resume"}
    )
    await worker.run_until_idle()
    resume = (await client.get(f"/api/v1/runs/{r.json()['run_id']}")).json()["run"]["result"][
        "document_id"
    ]
    # Like a real user: fill in the contact placeholder, then create the files for version 2.
    doc = (await client.get(f"/api/v1/generated-documents/{resume}")).json()
    md = doc["current"]["markdown"].replace(
        "[[PLACEHOLDER: contact details (email, phone, city)]]", "test@example.com"
    )
    await client.post(
        f"/api/v1/generated-documents/{resume}/versions", json={"markdown": md, "base_version": 1}
    )
    await client.post(f"/api/v1/generated-documents/{resume}/render", json={})
    await worker.run_until_idle()
    opps = (await client.get(f"/api/v1/cases/{case_id}/opportunities?academic=false")).json()
    by_source = {}
    for o in opps:
        for s in o["sources"]:
            by_source[s["source_url"].rsplit("/", 1)[1]] = o["id"]
    return case_id, by_source, resume


async def _application(
    client: httpx.AsyncClient, case_id: str, opp: str, resume: str, **extra: Any
) -> dict[str, Any]:
    r = await client.post(
        f"/api/v1/cases/{case_id}/applications",
        json={"opportunity_id": opp, "document_ids": [resume], **extra},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _browser(client: httpx.AsyncClient, worker: Any, app_id: str) -> dict[str, Any]:
    r = await client.post(f"/api/v1/applications/{app_id}/browser")
    assert r.status_code == 202, r.text
    await worker.run_until_idle()
    d: dict[str, Any] = (await client.get(f"/api/v1/runs/{r.json()['run_id']}")).json()
    return d


async def _app(client: httpx.AsyncClient, app_id: str) -> dict[str, Any]:
    d: dict[str, Any] = (await client.get(f"/api/v1/applications/{app_id}")).json()
    return d


async def test_fill_approve_submit_exactly_once(
    client: httpx.AsyncClient, worker: Any, site_origin: str
) -> None:
    case_id, opps, resume = await _setup(client, worker)
    a = await _application(client, case_id, opps["a-1001"], resume)
    assert a["apply_url"] == f"{site_origin}/fixture-site/apply/REQ-100"
    assert a["status"] == "preparing"

    # 1) The form asks a question the user hasn't answered: stop, don't guess.
    d = await _browser(client, worker, a["id"])
    assert d["run"]["status"] == "succeeded"
    assert d["run"]["result"]["status"] == "needs_user_action"
    app = await _app(client, a["id"])
    assert app["status"] == "needs_user_action"
    assert "Why are you interested in this role?" in app["blocker"]
    assert _submissions("REQ-100") == []

    # 2) The user answers; NexScout fills in and waits for approval. Nothing is sent yet.
    r = await client.patch(
        f"/api/v1/applications/{a['id']}",
        json={
            "version": app["version"],
            "answers": {"Why are you interested in this role? *": "I enjoy building ML platforms."},
        },
    )
    assert r.status_code == 200, r.text
    d = await _browser(client, worker, a["id"])
    assert d["run"]["status"] == "waiting_approval"
    approval = d["approvals"][0]
    assert approval["action_kind"] == "submit_application"
    fields = "\n".join(approval["details"]["fields"])
    assert "Full name *: " in fields
    assert "Email address *: " in fields
    assert "CV / résumé (PDF) *: Resume" in fields
    assert "Send me job alerts" not in fields
    assert approval["details"]["declarations"] == [
        "I confirm that the information in this application is accurate and complete."
    ]
    app = await _app(client, a["id"])
    assert app["status"] == "awaiting_review"
    shot_event = next(e for e in app["events"] if e["type"] == "form_filled")
    assert shot_event["has_screenshot"]
    png = await client.get(f"/api/v1/applications/{a['id']}/events/{shot_event['id']}/screenshot")
    assert png.status_code == 200
    assert png.content.startswith(b"\x89PNG")
    assert _submissions("REQ-100") == []  # filled, not submitted

    # 3) Approve: submitted once, confirmation observed.
    await client.post(f"/api/v1/approvals/{approval['id']}/decision", json={"approve": True})
    await worker.run_until_idle()
    d = (await client.get(f"/api/v1/runs/{d['run']['id']}")).json()
    assert d["run"]["status"] == "succeeded", d["run"]
    app = await _app(client, a["id"])
    assert app["status"] == "submitted"
    assert app["evidence"]["source"] == "observed"
    subs = _submissions("REQ-100")
    assert len(subs) == 1
    assert app["evidence"]["reference"] == subs[0]["reference"]
    assert subs[0]["declaration"] is True
    assert subs[0]["newsletter"] is False
    assert subs[0]["motivation"] == "I enjoy building ML platforms."
    assert subs[0]["files"]["cv"]["is_pdf"] is True
    assert subs[0]["phone"] is None
    statuses = [e["to_status"] for e in app["events"] if e["type"] == "status_changed"]
    assert statuses[-3:] == ["approved", "submitting", "submitted"]

    # 4) It can't be submitted again.
    again = await client.post(f"/api/v1/applications/{a['id']}/browser")
    assert again.status_code == 422
    assert len(_submissions("REQ-100")) == 1


async def test_reject_sends_nothing(client: httpx.AsyncClient, worker: Any) -> None:
    case_id, opps, resume = await _setup(client, worker)
    a = await _application(client, case_id, opps["a-2001"], resume)
    await client.patch(
        f"/api/v1/applications/{a['id']}",
        json={
            "version": a["version"],
            "answers": {"Why are you interested in this role?": "Data."},
        },
    )
    d = await _browser(client, worker, a["id"])
    await client.post(
        f"/api/v1/approvals/{d['approvals'][0]['id']}/decision", json={"approve": False}
    )
    await worker.run_until_idle()
    app = await _app(client, a["id"])
    assert app["status"] == "preparing"
    assert _submissions(app["apply_url"].rsplit("/", 1)[1]) == []


async def test_captcha_hands_over_and_user_confirms_manually(
    client: httpx.AsyncClient, worker: Any, site_origin: str
) -> None:
    case_id, opps, resume = await _setup(client, worker)
    a = await _application(
        client,
        case_id,
        opps["a-3001"],
        resume,
        apply_url=f"{site_origin}/fixture-site/apply/captcha-1",
    )
    d = await _browser(client, worker, a["id"])
    assert d["run"]["result"]["blocker"] == "captcha"
    app = await _app(client, a["id"])
    assert app["status"] == "needs_user_action"
    assert "doesn't solve CAPTCHAs" in app["blocker"]
    assert "submitted" in app["allowed_statuses"]
    r = await client.post(
        f"/api/v1/applications/{a['id']}/status",
        json={
            "version": app["version"],
            "status": "submitted",
            "reference": "MY-42",
            "note": "Applied myself.",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["evidence"] == {
        "source": "user",
        "reference": "MY-42",
        "note": "Applied myself.",
    }


async def test_unconfirmed_submission_is_uncertain_until_the_user_decides(
    client: httpx.AsyncClient, worker: Any, site_origin: str
) -> None:
    case_id, opps, resume = await _setup(client, worker)
    a = await _application(
        client,
        case_id,
        opps["a-4001"],
        resume,
        apply_url=f"{site_origin}/fixture-site/apply/uncertain-1",
    )
    await client.patch(
        f"/api/v1/applications/{a['id']}",
        json={
            "version": a["version"],
            "answers": {"Why are you interested in this role?": "Data."},
        },
    )
    d = await _browser(client, worker, a["id"])
    await client.post(
        f"/api/v1/approvals/{d['approvals'][0]['id']}/decision", json={"approve": True}
    )
    await worker.run_until_idle()
    app = await _app(client, a["id"])
    assert app["status"] == "submission_uncertain"
    assert app["evidence"]["source"] == "none"
    assert len(_submissions("uncertain-1")) == 1
    bad = await client.post(f"/api/v1/applications/{a['id']}/browser")
    assert bad.status_code == 422  # never retried automatically
    r = await client.post(
        f"/api/v1/applications/{a['id']}/resolve", json={"submitted": True, "reference": "EMAIL-7"}
    )
    assert r.json()["status"] == "submitted"
    assert r.json()["evidence"]["source"] == "user"


async def test_crash_during_submit_never_resubmits(
    client: httpx.AsyncClient, worker: Any, clean_db: Engine
) -> None:
    case_id, opps, resume = await _setup(client, worker)
    a = await _application(client, case_id, opps["b-79"], resume)
    await client.patch(
        f"/api/v1/applications/{a['id']}",
        json={
            "version": a["version"],
            "answers": {"Why are you interested in this role?": "APIs."},
        },
    )
    d = await _browser(client, worker, a["id"])
    # Simulate a worker that crashed after committing SUBMITTING but before recording a result.
    with clean_db.begin() as conn:
        conn.execute(
            text("UPDATE applications SET status = 'submitting' WHERE id = :id"), {"id": a["id"]}
        )
    job = (await _app(client, a["id"]))["apply_url"].rsplit("/", 1)[1]
    before = len(_submissions(job))
    await client.post(
        f"/api/v1/approvals/{d['approvals'][0]['id']}/decision", json={"approve": True}
    )
    await worker.run_until_idle()
    app = await _app(client, a["id"])
    assert app["status"] == "submission_uncertain"
    assert len(_submissions(job)) == before  # nothing was sent again


async def test_application_urls_are_ssrf_checked(client: httpx.AsyncClient, worker: Any) -> None:
    case_id, opps, resume = await _setup(client, worker)
    for url in ("http://169.254.169.254/latest", "http://10.0.0.7/apply", "file:///etc/passwd"):
        r = await client.post(
            f"/api/v1/cases/{case_id}/applications",
            json={"opportunity_id": opps["a-1002"], "document_ids": [resume], "apply_url": url},
        )
        assert r.status_code == 422, (url, r.text)
    dup = await _application(client, case_id, opps["a-1002"], resume)
    again = await client.post(
        f"/api/v1/cases/{case_id}/applications",
        json={"opportunity_id": opps["a-1002"], "document_ids": []},
    )
    assert again.status_code == 409
    assert dup["status"] == "preparing"
