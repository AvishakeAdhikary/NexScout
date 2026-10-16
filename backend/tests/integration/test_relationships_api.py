import httpx
import pytest

from tests.helpers import create_case, register

pytestmark = pytest.mark.db


async def _case(client: httpx.AsyncClient) -> str:
    await register(client)
    return str((await create_case(client))["id"])


async def test_preferences_defaults_put_and_conflict(client: httpx.AsyncClient) -> None:
    case_id = await _case(client)
    url = f"/api/v1/cases/{case_id}/preferences"
    got = (await client.get(url)).json()
    assert got["version"] == 0
    assert got["data"]["experience_mode"] == "strict"
    assert got["data"]["sensitive"]["use_for_eligibility"] is False

    resp = await client.put(
        url,
        json={
            "version": 0,
            "data": {
                "countries": ["Germany", "Netherlands"],
                "remote": "hybrid",
                "experience_mode": "flexible",
                "salary_min": 60000,
                "salary_currency": "eur",
                "sensitive": {"work_authorization": ["Germany"]},
            },
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 1
    assert resp.json()["data"]["salary_currency"] == "EUR"

    stale = await client.put(url, json={"version": 0, "data": {}})
    assert stale.status_code == 409
    bad = await client.put(url, json={"version": 1, "data": {"salary_currency": "euros"}})
    assert bad.status_code == 422
    bad = await client.put(
        url, json={"version": 1, "data": {"min_years_experience": 5, "max_years_experience": 2}}
    )
    assert bad.status_code == 422
    bad = await client.put(url, json={"version": 1, "data": {"race": "x"}})
    assert bad.status_code == 422  # unknown attributes are never stored


async def test_social_profiles(client: httpx.AsyncClient) -> None:
    case_id = await _case(client)
    url = f"/api/v1/cases/{case_id}/social-profiles"
    resp = await client.post(url, json={"url": "github.com/ada-example"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["kind"] == "github"
    assert resp.json()["url"] == "https://github.com/ada-example"
    resp = await client.post(url, json={"url": "https://orcid.org/0000-0002-1825-0097"})
    assert resp.json()["kind"] == "orcid"
    dup = await client.post(url, json={"url": "https://github.com/ada-example"})
    assert dup.status_code == 409
    for bad in (
        "javascript:alert(1)",
        "ftp://example.com/x",
        "https://user:pw@example.com",
        "not a url",
    ):
        assert (await client.post(url, json={"url": bad})).status_code == 422, bad
    links = (await client.get(url)).json()
    assert len(links) == 2
    assert (await client.delete(f"/api/v1/social-profiles/{links[0]['id']}")).status_code == 204


async def test_affiliations_crud_and_validation(client: httpx.AsyncClient) -> None:
    case_id = await _case(client)
    url = f"/api/v1/cases/{case_id}/affiliations"
    resp = await client.post(
        url,
        json={
            "person_name": "Dr. Sam Example",
            "organization": "University of Sampleford",
            "relationship_type": "supervisor",
            "role": "MSc thesis supervisor",
            "start_date": "2019",
            "end_date": "2020",
            "status": "former",
        },
    )
    assert resp.status_code == 201, resp.text
    row = resp.json()
    assert row["may_use_for_referral"] is False  # never assumed
    assert row["may_use_in_applications"] is False

    upd = await client.patch(
        f"/api/v1/affiliations/{row['id']}",
        json={"version": row["version"], "may_use_for_referral": True},
    )
    assert upd.status_code == 200
    assert upd.json()["may_use_for_referral"] is True
    stale = await client.patch(
        f"/api/v1/affiliations/{row['id']}", json={"version": row["version"], "notes": "x"}
    )
    assert stale.status_code == 409

    for bad in (
        {"organization": "", "relationship_type": "alumnus"},
        {"organization": "X", "relationship_type": "best_friend"},
        {"organization": "X", "relationship_type": "alumnus", "start_date": "spring"},
    ):
        assert (await client.post(url, json=bad)).status_code == 422, bad
    assert (await client.delete(f"/api/v1/affiliations/{row['id']}")).status_code == 204
    assert (await client.get(url)).json() == []
