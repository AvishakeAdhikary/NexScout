"""M16: AI providers are edited in place; the stored key never follows a changed destination."""

from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.helpers import register

pytestmark = pytest.mark.db

KEY = "sk-test-abcdef123456"  # a fake key for tests
REMOTE = {
    "name": "Remote model",
    "kind": "openai_compatible",
    "model": "wrong-model",
    "base_url": "https://api.example.com/v1",
    "api_key": KEY,
}


async def _create(client: httpx.AsyncClient) -> dict[str, Any]:
    r = await client.post("/api/v1/providers", json=REMOTE)
    assert r.status_code == 201, r.text
    return dict(r.json())


async def test_edit_keeps_key_and_resets_verification(
    client: httpx.AsyncClient, clean_db: Engine
) -> None:
    await register(client)
    p = await _create(client)
    with clean_db.begin() as conn:  # pretend it was checked before
        conn.execute(
            text("UPDATE provider_configs SET last_verified_at = now() WHERE id = :id"),
            {"id": p["id"]},
        )
    r = await client.patch(
        f"/api/v1/providers/{p['id']}",
        json={"version": p["version"], "model": "meta/llama-3.3-70b-instruct", "name": "NIM"},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["name"], out["model"], out["version"]) == (
        "NIM",
        "meta/llama-3.3-70b-instruct",
        p["version"] + 1,
    )
    assert out["has_api_key"] is True
    assert out["api_key_hint"] == p["api_key_hint"]  # the key was kept
    assert out["last_verified_at"] is None  # a different model needs a fresh check
    assert KEY not in r.text

    # A stale version is refused.
    stale = await client.patch(
        f"/api/v1/providers/{p['id']}", json={"version": p["version"], "name": "Old"}
    )
    assert stale.status_code == 409

    # Sending nothing new changes nothing (no version bump, no audit entry).
    same = await client.patch(
        f"/api/v1/providers/{p['id']}", json={"version": out["version"], "name": "NIM"}
    )
    assert same.json()["version"] == out["version"]
    with clean_db.connect() as conn:
        audits = conn.execute(
            text("SELECT meta FROM audit_events WHERE action = 'provider.updated'")
        ).all()
    assert [a.meta for a in audits] == [{"fields": ["model", "name"]}]  # names, never values


async def test_key_never_follows_a_new_destination(
    client: httpx.AsyncClient, clean_db: Engine
) -> None:
    await register(client)
    p = await _create(client)
    moved = await client.patch(
        f"/api/v1/providers/{p['id']}",
        json={"version": p["version"], "base_url": "https://evil.example.net/v1"},
    )
    assert moved.status_code == 422
    assert "Enter the API key again" in moved.json()["detail"]

    # With the key entered again the move is allowed, and the old secret is deleted.
    r = await client.patch(
        f"/api/v1/providers/{p['id']}",
        json={
            "version": p["version"],
            "base_url": "https://integrate.api.example.org/v1/",
            "api_key": "nv-test-new-key-9876",
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["base_url"].startswith("https://integrate.api.example.org")
    assert out["api_key_hint"] == "…9876"
    with clean_db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM secrets")).scalar() == 1

    # Remove the key; moving is then fine without one.
    cleared = await client.patch(
        f"/api/v1/providers/{p['id']}", json={"version": out["version"], "clear_api_key": True}
    )
    assert cleared.json()["has_api_key"] is False
    with clean_db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM secrets")).scalar() == 0
    both = await client.patch(
        f"/api/v1/providers/{p['id']}",
        json={"version": cleared.json()["version"], "api_key": "x" * 20, "clear_api_key": True},
    )
    assert both.status_code == 422


async def test_edit_validation_and_default(client: httpx.AsyncClient) -> None:
    await register(client)
    p = await _create(client)
    mock = (
        await client.post(
            "/api/v1/providers",
            json={"name": "Mock", "kind": "mock", "model": "nexscout-mock-1", "is_default": True},
        )
    ).json()
    bad = await client.patch(
        f"/api/v1/providers/{p['id']}",
        json={
            "version": p["version"],
            "base_url": "http://169.254.169.254/v1",
            "api_key": "sk-test-zzzzzzzz",
        },
    )
    assert bad.status_code == 422  # cloud metadata address refused
    nulls = await client.patch(
        f"/api/v1/providers/{p['id']}", json={"version": p["version"], "name": None}
    )
    assert nulls.status_code == 200  # null on a required field means "unchanged"
    assert nulls.json()["name"] == "Remote model"
    r = await client.patch(
        f"/api/v1/providers/{p['id']}", json={"version": p["version"], "is_default": True}
    )
    assert r.json()["is_default"] is True
    listed = {x["id"]: x for x in (await client.get("/api/v1/providers")).json()}
    assert listed[mock["id"]]["is_default"] is False  # only one default
