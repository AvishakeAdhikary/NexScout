"""M8: reminders and notifications sweep, dashboard, bulk status, export, chat, diagnostics."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.helpers import create_case, register

pytestmark = pytest.mark.db


async def _case_with_apps(
    client: httpx.AsyncClient, worker: Any
) -> tuple[str, list[dict[str, Any]]]:
    await register(client)
    case_id = str((await create_case(client, "Tracking"))["id"])
    await client.patch(f"/api/v1/cases/{case_id}", json={"version": 1, "career_path": "both"})
    await client.post(f"/api/v1/cases/{case_id}/opportunities/sync", json={})
    await worker.run_until_idle()
    opps = (await client.get(f"/api/v1/cases/{case_id}/opportunities?academic=false")).json()
    opps += list((await client.get(f"/api/v1/cases/{case_id}/opportunities?academic=true")).json())
    apps = []
    for o in opps[:3]:
        r = await client.post(
            f"/api/v1/cases/{case_id}/applications",
            json={"opportunity_id": o["id"], "document_ids": []},
        )
        assert r.status_code == 201, r.text
        apps.append(r.json())
    return case_id, apps


async def test_deadline_reminders_and_notifications_are_idempotent(
    client: httpx.AsyncClient, worker: Any, clean_db: Engine
) -> None:
    case_id, apps = await _case_with_apps(client, worker)
    today = datetime.now(UTC).date()
    deadline = (today + timedelta(days=7)).isoformat()
    a = apps[0]
    r = await client.patch(
        f"/api/v1/applications/{a['id']}", json={"version": a["version"], "deadline": deadline}
    )
    assert r.status_code == 200, r.text
    with clean_db.begin() as conn:  # another one needs the user
        conn.execute(
            text("UPDATE applications SET status = 'needs_user_action' WHERE id = :id"),
            {"id": apps[1]["id"]},
        )

    first = await worker.maintenance_once()
    second = await worker.maintenance_once()
    assert first["reminders_created"] >= 2  # 7 days and 1 day before
    assert second == {"reminders_created": 0, "notifications_created": 0}

    reminders = (await client.get(f"/api/v1/cases/{case_id}/reminders")).json()
    due = sorted(x["due_on"] for x in reminders if x["application_id"] == a["id"])
    assert due == [today.isoformat(), (today + timedelta(days=6)).isoformat()]
    notes = (await client.get("/api/v1/notifications")).json()
    kinds = sorted(n["kind"] for n in notes["items"])
    assert kinds == ["application", "reminder"]  # the 1-day reminder isn't due yet
    assert notes["unread"] == 2
    assert all(n["link"].startswith(f"/cases/{case_id}/applications/") for n in notes["items"])

    one = notes["items"][0]["id"]
    assert (await client.post(f"/api/v1/notifications/{one}/read")).status_code == 204
    assert (await client.get("/api/v1/notifications")).json()["unread"] == 1
    await client.post("/api/v1/notifications/read-all")
    assert (await client.get("/api/v1/notifications")).json()["unread"] == 0

    custom = await client.post(
        f"/api/v1/cases/{case_id}/reminders",
        json={"title": "Email Dr. Sample", "due_on": today.isoformat()},
    )
    assert custom.status_code == 201
    done = await client.patch(f"/api/v1/reminders/{custom.json()['id']}", json={"done": True})
    assert done.json()["done"] is True


async def test_dashboard_bulk_and_export(client: httpx.AsyncClient, worker: Any) -> None:
    case_id, apps = await _case_with_apps(client, worker)
    run = await client.post(
        f"/api/v1/cases/{case_id}/runs",
        json={"kind": "system_check", "params": {"require_approval": True}},
    )
    assert run.status_code == 201
    await worker.run_until_idle()

    d = (await client.get(f"/api/v1/cases/{case_id}/dashboard")).json()
    assert d["applications_total"] == 3
    assert d["applications_by_status"] == {"preparing": 3}
    assert any(i["kind"] == "approval" for i in d["needs_you"])
    assert d["recent_runs"][0]["status"] == "waiting_approval"
    assert d["opportunities"]["matches"] >= 3

    ids = [a["id"] for a in apps[:2]]
    res = (
        await client.post(
            f"/api/v1/cases/{case_id}/applications/bulk-status",
            json={"ids": ids, "status": "withdrawn"},
        )
    ).json()
    assert [r["ok"] for r in res] == [False, False]  # preparing → withdrawn isn't allowed
    res = (
        await client.post(
            f"/api/v1/cases/{case_id}/applications/bulk-status",
            json={"ids": ids, "status": "cancelled"},
        )
    ).json()
    assert [r["ok"] for r in res] == [True, True]
    left = (await client.get(f"/api/v1/cases/{case_id}/applications?status=preparing")).json()
    assert [a["id"] for a in left] == [apps[2]["id"]]
    found = (
        await client.get(
            f"/api/v1/cases/{case_id}/applications", params={"q": apps[2]["organization"][:4]}
        )
    ).json()
    assert apps[2]["id"] in [a["id"] for a in found]

    csv = await client.get(f"/api/v1/cases/{case_id}/applications/export.csv")
    assert csv.status_code == 200
    assert csv.headers["content-type"].startswith("text/csv")
    body = csv.content.decode("utf-8-sig").splitlines()
    assert body[0].startswith("title,organization,status")
    assert len(body) == 4


async def test_assistant_routes_to_use_cases_and_never_submits(
    client: httpx.AsyncClient, worker: Any
) -> None:
    case_id, apps = await _case_with_apps(client, worker)

    async def say(message: str) -> dict[str, Any]:
        r = await client.post(f"/api/v1/cases/{case_id}/chat", json={"message": message})
        assert r.status_code == 200, r.text
        user, bot = r.json()
        assert user["role"] == "user"
        assert bot["role"] == "assistant"
        return dict(bot)

    bot = await say("Submit my application now")
    assert bot["intent"] == "submit"
    assert "never submit" in bot["content"]

    bot = await say(f"What is the status of my application to {apps[0]['organization']}?")
    assert bot["intent"] == "status"
    assert "preparing" in bot["content"]
    assert bot["actions"][0]["href"].endswith(apps[0]["id"])

    runs_before = len((await client.get(f"/api/v1/cases/{case_id}/runs")).json())
    bot = await say("find jobs for me")
    assert bot["intent"] == "find_jobs"
    assert len((await client.get(f"/api/v1/cases/{case_id}/runs")).json()) == runs_before + 1

    bot = await say("Create my academic CV")
    assert "no AI" in bot["content"]
    await worker.run_until_idle()
    docs = (await client.get(f"/api/v1/cases/{case_id}/generated-documents")).json()
    assert [d["doc_type"] for d in docs] == ["academic_cv"]

    bot = await say("What needs me?")
    assert "document(s) with placeholders" in bot["content"]
    bot = await say("tell me a joke")
    assert bot["intent"] == "unknown"
    assert "Here's what I can do" in bot["content"]

    history = (await client.get(f"/api/v1/cases/{case_id}/chat")).json()
    assert len(history) == 12
    assert history[0]["content"] == "Submit my application now"


async def test_diagnostics_show_only_safe_facts(client: httpx.AsyncClient, worker: Any) -> None:
    await register(client)
    d = (await client.get("/api/v1/diagnostics")).json()
    assert d["workers_alive"] >= 1  # the test worker heartbeats on open
    assert "hostname" not in str(d)
    assert d["my_tasks"] == {"queued": 0, "running": 0}
    assert d["database"].startswith("PostgreSQL")
