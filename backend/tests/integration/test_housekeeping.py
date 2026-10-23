"""M20: clearing notifications and finished Agent Activity."""

from typing import Any

import httpx
import pytest

from tests.helpers import create_case, register

pytestmark = pytest.mark.db


async def _notifications(client: httpx.AsyncClient, worker: Any, case_id: str, n: int) -> None:
    for i in range(n):
        await client.post(
            f"/api/v1/cases/{case_id}/reminders",
            json={"title": f"Reminder {i}", "due_on": "2026-01-01"},
        )
    await worker.maintenance_once()  # due reminders become notifications


async def test_notifications_can_be_deleted_cleared_and_paged(
    client: httpx.AsyncClient, worker: Any
) -> None:
    await register(client)
    case_id = str((await create_case(client))["id"])
    await _notifications(client, worker, case_id, 4)
    listed = (await client.get("/api/v1/notifications")).json()
    assert len(listed["items"]) == 4
    assert listed["unread"] == 4

    # Paging back in time: two, then the rest.
    first = (await client.get("/api/v1/notifications", params={"limit": 2})).json()["items"]
    rest = (
        await client.get(
            "/api/v1/notifications", params={"limit": 2, "before": first[-1]["created_at"]}
        )
    ).json()["items"]
    assert len(first) == 2
    assert {n["id"] for n in first}.isdisjoint({n["id"] for n in rest})

    one = listed["items"][0]["id"]
    assert (await client.delete(f"/api/v1/notifications/{one}")).status_code == 204
    assert (await client.delete(f"/api/v1/notifications/{one}")).status_code == 404

    # "Clear read" keeps unread ones; "Clear all" removes everything.
    await client.post(f"/api/v1/notifications/{listed['items'][1]['id']}/read")
    out = (await client.post("/api/v1/notifications/clear", json={"read_only": True})).json()
    assert out == {"cleared": 1}
    assert len((await client.get("/api/v1/notifications")).json()["items"]) == 2
    out = (await client.post("/api/v1/notifications/clear", json={"read_only": False})).json()
    assert out == {"cleared": 2}
    assert (await client.get("/api/v1/notifications")).json() == {"unread": 0, "items": []}


async def test_finished_activity_is_cleared_but_kept(
    client: httpx.AsyncClient, worker: Any
) -> None:
    await register(client)
    case_id = str((await create_case(client))["id"])
    done = (
        await client.post(f"/api/v1/cases/{case_id}/runs", json={"kind": "system_check"})
    ).json()
    await worker.run_until_idle()
    waiting = (
        await client.post(f"/api/v1/cases/{case_id}/runs", json={"kind": "system_check"})
    ).json()  # still pending: not run by the worker yet

    # A run that isn't finished can't be cleared.
    refused = await client.post(f"/api/v1/runs/{waiting['id']}/hide")
    assert refused.status_code == 422
    out = (await client.post(f"/api/v1/cases/{case_id}/runs/clear-finished")).json()
    assert out == {"hidden": 1}
    listed = [r["id"] for r in (await client.get(f"/api/v1/cases/{case_id}/runs")).json()]
    assert listed == [waiting["id"]]
    # Its record is still there (usage, links from documents).
    assert (await client.get(f"/api/v1/runs/{done['id']}")).status_code == 200
