"""M20: opportunity lists come in pages (keyset), per view, with counts and search."""

from typing import Any

import httpx
import pytest

from tests.helpers import create_case, register, sync

pytestmark = pytest.mark.db


async def _case_with_jobs(client: httpx.AsyncClient) -> str:
    await register(client)
    case_id = str((await create_case(client, "Jobs"))["id"])
    await client.patch(f"/api/v1/cases/{case_id}", json={"version": 1, "career_path": "both"})
    await sync(client, case_id)
    return case_id


async def _walk(client: httpx.AsyncClient, case_id: str, **params: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor = None
    for _ in range(50):
        query = {
            "academic": "false",
            "limit": "2",
            **params,
            **({"cursor": cursor} if cursor else {}),
        }
        r = await client.get(f"/api/v1/cases/{case_id}/opportunities/page", params=query)
        assert r.status_code == 200, r.text
        page = r.json()
        assert len(page["items"]) <= 2
        items += page["items"]
        cursor = page["next_cursor"]
        if cursor is None:
            return items
    raise AssertionError("paging never ended")


async def test_pages_list_every_opportunity_once_in_board_order(
    client: httpx.AsyncClient,
) -> None:
    case_id = await _case_with_jobs(client)
    everything = (
        await client.get(f"/api/v1/cases/{case_id}/opportunities", params={"academic": "false"})
    ).json()
    first = (
        await client.get(
            f"/api/v1/cases/{case_id}/opportunities/page", params={"academic": "false"}
        )
    ).json()
    expected = {
        "matches": [o for o in everything if o["eligible"] and o["match_status"] != "dismissed"],
        "not_fit": [
            o for o in everything if not o["eligible"] and o["match_status"] != "dismissed"
        ],
        "dismissed": [o for o in everything if o["match_status"] == "dismissed"],
    }
    assert first["counts"] == {k: len(v) for k, v in expected.items()}
    # The longest list (an empty profile makes most jobs "not a fit" in strict mode).
    view = max(first["counts"], key=lambda k: first["counts"][k])
    assert first["counts"][view] >= 3  # enough to need several pages of 2

    walked = await _walk(client, case_id, view=view)
    ids = [o["id"] for o in walked]
    assert len(ids) == len(set(ids))  # nothing twice
    assert set(ids) == {o["id"] for o in expected[view]}  # nothing missed
    keys = [(-o["score"], o["title"]) for o in walked]
    assert keys == sorted(keys)  # best fit first, then by title
    # Lists leave the (long) description out; the opportunity itself has it.
    assert all("description" not in o["data"] for o in walked)
    with_text = next(o for o in walked if o["has_description"])
    full = (await client.get(f"/api/v1/cases/{case_id}/opportunities/{with_text['id']}")).json()
    assert full["data"]["description"]

    # Dismissing moves an opportunity to the other list, and the counts follow.
    gone = walked[0]
    await client.patch(
        f"/api/v1/cases/{case_id}/opportunities/{gone['id']}",
        json={"status": "dismissed", "version": gone["match_version"]},
    )
    dismissed = await _walk(client, case_id, view="dismissed")
    assert [o["id"] for o in dismissed] == [gone["id"]]
    after = (await client.get(f"/api/v1/cases/{case_id}/opportunities/page")).json()
    assert after["counts"]["dismissed"] == 1


async def test_search_and_bad_input(client: httpx.AsyncClient) -> None:
    case_id = await _case_with_jobs(client)
    url = f"/api/v1/cases/{case_id}/opportunities/page"
    found = (await client.get(url, params={"academic": "false", "q": "ENGINEER"})).json()
    assert found["items"]
    assert all(
        "engineer" in f"{o['title']} {o['organization_name']}".lower() for o in found["items"]
    )
    # % and _ are literal characters, not wildcards.
    literal = (await client.get(url, params={"academic": "false", "q": "%"})).json()
    assert literal["counts"] == {"matches": 0, "not_fit": 0, "dismissed": 0}
    assert (await client.get(url, params={"cursor": "not-a-cursor"})).status_code == 422
    assert (await client.get(url, params={"view": "everything"})).status_code == 422
    assert (await client.get(url, params={"limit": "1000"})).status_code == 422
