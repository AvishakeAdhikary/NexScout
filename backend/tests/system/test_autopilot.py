"""M12: the human-in-the-loop autopilot, end to end against the demo site with a real browser.

- With consent to submit without asking: cycle → research → resume → the placeholder becomes a
  question → answered → files → fill → the form question becomes a question → answered (and
  reused) → submitted once under the policy, with the approval recorded as policy-decided.
- Without that consent: the same pipeline stops at an approval that the user decides.
- STOP turns everything off. Assisted mode: the person solves the CAPTCHA and submits; NexScout
  only records the confirmation.
"""

# ruff: noqa: F811  (pytest fixtures imported from test_browser_apply)
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.engine import Engine

from nexscout.infrastructure import browser as browser_infra
from nexscout.integrations import fixture_site
from tests.conftest import make_settings
from tests.helpers import create_case, register
from tests.system.test_browser_apply import _app, site_origin  # noqa: F401

pytestmark = pytest.mark.db


@pytest.fixture
async def app(clean_db: Engine, storage_dir: Path, site_origin: str) -> AsyncIterator[Any]:
    from nexscout.api.app import create_app

    application = create_app(
        make_settings(
            storage_dir=storage_dir, fixture_site_origin=site_origin, assisted_browser=True
        )
    )
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def worker(clean_db: Engine, storage_dir: Path, site_origin: str) -> AsyncIterator[Any]:
    from nexscout.agent_runtime.worker import Worker

    w = Worker(
        make_settings(
            storage_dir=storage_dir,
            fixture_site_origin=site_origin,
            assisted_browser=True,
            assist_timeout_s=30,
            assist_headless=True,
            autopilot_site_spacing_s=0,
        ),
        worker_id="test-worker-autopilot",
    )
    await w.open()
    yield w
    await w.close()


async def _case(client: httpx.AsyncClient) -> str:
    await register(client)
    case_id = str((await create_case(client, "Jobs"))["id"])
    await client.patch(f"/api/v1/cases/{case_id}", json={"version": 1, "career_path": "both"})
    await client.post(
        f"/api/v1/cases/{case_id}/facts", json={"section": "skill", "data": {"name": "Python"}}
    )
    return case_id


async def _policy(client: httpx.AsyncClient, case_id: str, **changes: Any) -> dict[str, Any]:
    current = (await client.get(f"/api/v1/cases/{case_id}/autopilot")).json()
    r = await client.put(
        f"/api/v1/cases/{case_id}/autopilot",
        json={"version": current["policy"]["version"], **changes},
    )
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


async def _items(client: httpx.AsyncClient, case_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = (await client.get(f"/api/v1/cases/{case_id}/autopilot")).json()[
        "items"
    ]
    return items


async def _settle(
    client: httpx.AsyncClient, worker: Any, case_id: str, stop: set[str], rounds: int = 25
) -> dict[str, Any]:
    """Let the reconciler and the worker run until the item reaches one of `stop`."""
    for _ in range(rounds):
        await worker.autopilot_once()
        await worker.run_until_idle(timeout_s=120)
        items = await _items(client, case_id)
        if items and items[0]["stage"] in stop:
            return items[0]
    raise AssertionError(f"autopilot item did not reach {stop}: {await _items(client, case_id)}")


async def _questions(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    notes = (await client.get("/api/v1/notifications")).json()["items"]
    return [n for n in notes if n["kind"] == "question"]


async def _answer_all(client: httpx.AsyncClient, answers: dict[str, str]) -> list[str]:
    asked = []
    for q in await _questions(client):
        text = next((a for k, a in answers.items() if k in q["title"]), None)
        assert text, f"unexpected question: {q['title']}"
        r = await client.post(f"/api/v1/notifications/{q['id']}/answer", json={"answer": text})
        assert r.status_code == 204, r.text
        asked.append(q["title"])
    return asked


ANSWERS = {
    "contact details": "ada@example.com · +44 20 7946 0000 · London",
    "Why are you interested": "I enjoy building ML platforms.",
}


async def test_autopilot_submits_within_consented_policy_and_asks_instead_of_guessing(
    client: httpx.AsyncClient, worker: Any
) -> None:
    fixture_site.SUBMISSIONS.clear()
    case_id = await _case(client)

    # Consent is checked word for word; it can't be switched on by a bare flag.
    current = (await client.get(f"/api/v1/cases/{case_id}/autopilot")).json()
    assert current["policy"]["enabled"] is False
    bad = await client.put(
        f"/api/v1/cases/{case_id}/autopilot",
        json={"version": current["policy"]["version"], "auto_submit": True, "consent": "yes"},
    )
    assert bad.status_code == 422
    await _policy(
        client,
        case_id,
        enabled=True,
        min_fit=0,
        max_new_per_run=1,
        kinds=["job"],
        doc_types=["resume"],
        steps={"submit": True},
        auto_submit=True,
        consent=current["auto_submit_consent"],
        declarations=True,
        declarations_consent=current["declarations_consent"],
    )
    r = await client.post(f"/api/v1/cases/{case_id}/autopilot/run")
    assert r.status_code == 202, r.text
    await worker.run_until_idle(timeout_s=120)
    cycle = (await client.get(f"/api/v1/runs/{r.json()['run_id']}")).json()["run"]
    assert cycle["status"] == "succeeded", cycle
    assert cycle["result"]["picked"] == 1
    assert all(c["reasons"] for c in cycle["result"]["considered"])

    # 1) The assembled resume has a placeholder: NexScout asks instead of inventing it.
    item = await _settle(client, worker, case_id, {"needs_input"})
    assert "contact details" in item["reason"]
    assert any("contact details" in t for t in await _answer_all(client, ANSWERS))
    assert fixture_site.SUBMISSIONS == []

    # 2) Answer used → files → the form asks a question NexScout has no answer for → asked.
    item = await _settle(client, worker, case_id, {"needs_user_action"})
    assert "Why are you interested" in item["reason"]
    assert fixture_site.SUBMISSIONS == []
    await _answer_all(client, ANSWERS)

    # 3) Answered → filled → submitted under the consented policy, exactly once.
    item = await _settle(client, worker, case_id, {"submitted"})
    assert len(fixture_site.SUBMISSIONS) == 1
    sub = fixture_site.SUBMISSIONS[0]
    assert sub["motivation"] == "I enjoy building ML platforms."
    assert sub["declaration"] is True
    assert sub["files"]["cv"]["is_pdf"] is True
    app_view = await _app(client, item["application_id"])
    assert app_view["status"] == "submitted"
    assert app_view["evidence"]["source"] == "observed"
    approvals = (await client.get(f"/api/v1/cases/{case_id}/approvals?status=")).json()
    submit = next(a for a in approvals if a["action_kind"] == "submit_application")
    assert submit["status"] == "approved"
    assert submit["decision_note"] == "Approved by your autopilot settings."
    notes = (await client.get("/api/v1/notifications")).json()["items"]
    assert any(n["kind"] == "submitted" for n in notes)

    # 4) Answers are the user's own, stored once per question, and reused next time.
    bank = (await client.get(f"/api/v1/cases/{case_id}/answers")).json()
    assert {a["answer"] for a in bank} == set(ANSWERS.values())
    again = await client.post(f"/api/v1/cases/{case_id}/autopilot/run")
    await worker.run_until_idle(timeout_s=120)
    result = (await client.get(f"/api/v1/runs/{again.json()['run_id']}")).json()["run"]["result"]
    done = next(c for c in result["considered"] if c["opportunity_id"] == item["opportunity_id"])
    assert done["taken"] is False
    assert done["reasons"][0] == "Already being worked on or applied to."
    assert len(await _items(client, case_id)) == 1 + result["picked"]


async def test_without_consent_it_asks_for_approval_then_stop_turns_it_off(
    client: httpx.AsyncClient, worker: Any
) -> None:
    fixture_site.SUBMISSIONS.clear()
    case_id = await _case(client)
    for question, answer in (
        ("Why are you interested in this role?", ANSWERS["Why are you interested"]),
    ):
        r = await client.post(
            f"/api/v1/cases/{case_id}/answers", json={"question": question, "answer": answer}
        )
        assert r.status_code == 201, r.text
    await _policy(
        client,
        case_id,
        enabled=True,
        min_fit=0,
        max_new_per_run=1,
        kinds=["job"],
        doc_types=["resume"],
        steps={"submit": True},
    )
    await client.post(f"/api/v1/cases/{case_id}/autopilot/run")
    await worker.run_until_idle(timeout_s=120)
    await _settle(client, worker, case_id, {"needs_input"})
    await _answer_all(client, ANSWERS)
    # The saved motivation answer is reused: no question this time, straight to approval.
    item = await _settle(client, worker, case_id, {"waiting_approval"})
    assert not any("Why are you interested" in q["title"] for q in await _questions(client))
    approvals = (await client.get(f"/api/v1/cases/{case_id}/approvals")).json()
    assert approvals[0]["action_kind"] == "submit_application"
    assert "You haven't allowed submitting without asking." in approvals[0]["summary"]
    assert fixture_site.SUBMISSIONS == []
    notes = (await client.get("/api/v1/notifications")).json()["items"]
    assert any(n["kind"] == "approval" and n["link"].startswith("/approve/") for n in notes)

    await client.post(f"/api/v1/approvals/{approvals[0]['id']}/decision", json={"approve": True})
    item = await _settle(client, worker, case_id, {"submitted"})
    assert len(fixture_site.SUBMISSIONS) == 1

    stop = await client.post("/api/v1/autopilot/stop")
    assert stop.status_code == 200
    view = (await client.get(f"/api/v1/cases/{case_id}/autopilot")).json()
    assert view["policy"]["enabled"] is False
    assert view["policy"]["stopped_reason"] == "Stop pressed in NexScout"
    assert (await client.post(f"/api/v1/cases/{case_id}/autopilot/run")).status_code == 422
    assert item["stage"] == "submitted"


async def test_assisted_mode_person_solves_captcha_and_submits(
    client: httpx.AsyncClient, worker: Any, site_origin: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.system.test_browser_apply import _application, _browser, _setup

    fixture_site.SUBMISSIONS.clear()
    case_id, opps, resume = await _setup(client, worker)
    a = await _application(
        client,
        case_id,
        opps["a-3001"],
        resume,
        apply_url=f"{site_origin}/fixture-site/apply/captcha-7",
    )
    await client.patch(
        f"/api/v1/applications/{a['id']}",
        json={"version": a["version"], "answers": {"Why are you interested in this role?": "X"}},
    )
    d = await _browser(client, worker, a["id"])
    assert d["run"]["result"]["blocker"] == "captcha"  # NexScout stops at the challenge
    notes = (await client.get("/api/v1/notifications")).json()["items"]
    assert any("CAPTCHA" in n["title"] for n in notes)

    seen: list[str] = []

    def person(page: Any, phase: str) -> None:  # what the human does in the window
        seen.append(phase)
        if phase == "blocked":
            page.click("#verify")
        elif phase == "filled":
            page.check("#declaration")
            page.click("button[type=submit]")

    monkeypatch.setattr(browser_infra, "ASSIST_HUMAN", person)
    r = await client.post(f"/api/v1/applications/{a['id']}/assist")
    assert r.status_code == 202, r.text
    await worker.run_until_idle(timeout_s=120)
    run = (await client.get(f"/api/v1/runs/{r.json()['run_id']}")).json()["run"]
    assert run["result"]["status"] == "submitted", (run, seen)
    assert seen == ["blocked", "filled"]
    view = await _app(client, a["id"])
    assert view["status"] == "submitted"
    assert view["evidence"]["assisted"] is True
    assert view["evidence"]["reference"] == fixture_site.SUBMISSIONS[0]["reference"]
    assert len(fixture_site.SUBMISSIONS) == 1
