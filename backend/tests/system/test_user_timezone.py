"""Date-only reminders fall due on the user's own calendar day, not the server's (UTC) day."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from nexscout.application.notifications import run_maintenance
from nexscout.domain.timezones import local_today, valid_timezone
from tests.helpers import DEFAULT_PASSWORD, create_case

pytestmark = pytest.mark.db


async def _register(client: httpx.AsyncClient, email: str, tz: str | None) -> dict[str, Any]:
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": DEFAULT_PASSWORD, "display_name": "Ada", "timezone": tz},
    )
    assert r.status_code == 201, r.text
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return dict(r.json()["user"])


def test_zone_validation() -> None:
    assert valid_timezone("Europe/Helsinki") == "Europe/Helsinki"
    for bad in (None, "", "Mars/Olympus", "../etc/passwd", "/UTC", "x" * 65):
        assert valid_timezone(bad) is None
    noon = datetime(2030, 1, 1, 12, tzinfo=UTC)
    assert local_today(noon, "Pacific/Kiritimati").isoformat() == "2030-01-02"  # UTC+14
    assert local_today(noon, "Nope/Nope").isoformat() == "2030-01-01"


async def test_reminders_follow_each_users_day(
    client: httpx.AsyncClient, other_client: httpx.AsyncClient, worker: Any
) -> None:
    # Noon UTC on the next day: already the day after at UTC+14, still that day at UTC-11.
    # (Close to the real clock, so the sweep's retention purge leaves the sessions alone.)
    noon = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    day1, day2 = noon + timedelta(days=1), noon + timedelta(days=2)
    due = day2.date().isoformat()
    ahead = await _register(client, "ahead@example.com", "Pacific/Kiritimati")  # UTC+14
    behind = await _register(other_client, "behind@example.com", "Pacific/Pago_Pago")  # UTC-11
    assert (ahead["timezone"], behind["timezone"]) == ("Pacific/Kiritimati", "Pacific/Pago_Pago")
    for c in (client, other_client):
        case_id = (await create_case(c, "Zones"))["id"]
        r = await c.post(
            f"/api/v1/cases/{case_id}/reminders", json={"title": "Call", "due_on": due}
        )
        assert r.status_code == 201, r.text

    async def sweep(now: datetime) -> None:
        async with worker.system_sessions() as s, s.begin():
            await run_maintenance(s, now=now)

    async def reminded(c: httpx.AsyncClient) -> bool:
        r = await c.get("/api/v1/notifications")
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        return any(n["kind"] == "reminder" for n in items)

    await sweep(day1)
    assert await reminded(client)
    assert not await reminded(other_client)
    await sweep(day2)  # 01:00 on the due day at UTC-11: due there too
    assert await reminded(other_client)


async def test_login_follows_the_users_zone(client: httpx.AsyncClient) -> None:
    await _register(client, "trav@example.com", None)
    me = (await client.get("/api/v1/auth/me")).json()
    assert me["timezone"] == "UTC"  # nothing reported: UTC

    async def login(tz: str) -> str:
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "trav@example.com", "password": DEFAULT_PASSWORD, "timezone": tz},
        )
        assert r.status_code == 200, r.text
        return str(r.json()["user"]["timezone"])

    assert await login("Asia/Kolkata") == "Asia/Kolkata"
    assert await login("Not/AZone") == "Asia/Kolkata"  # unknown names are ignored
