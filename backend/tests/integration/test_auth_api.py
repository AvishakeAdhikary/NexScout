import httpx
import pytest

from tests.helpers import DEFAULT_PASSWORD, register

pytestmark = pytest.mark.db


async def test_register_sets_httponly_session_and_returns_csrf(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "Ada@Example.com", "password": DEFAULT_PASSWORD, "display_name": "Ada"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["user"]["email"] == "ada@example.com"  # normalized
    assert body["csrf_token"]
    set_cookie = "; ".join(resp.headers.get_list("set-cookie")).lower()
    assert "nexscout_session=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "password" not in resp.text.lower() or "password_hash" not in resp.text


async def test_me_requires_session(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")


async def test_login_logout_cycle(client: httpx.AsyncClient) -> None:
    await register(client)
    assert (await client.get("/api/v1/auth/me")).status_code == 200

    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 204
    client.cookies.clear()
    assert (await client.get("/api/v1/auth/me")).status_code == 401

    resp = await client.post(
        "/api/v1/auth/login", json={"email": "ada@example.com", "password": DEFAULT_PASSWORD}
    )
    assert resp.status_code == 200
    assert (await client.get("/api/v1/auth/me")).json()["display_name"] == "Ada Example"


async def test_revoked_session_token_is_rejected(client: httpx.AsyncClient) -> None:
    await register(client)
    token = client.cookies.get("nexscout_session")
    await client.post("/api/v1/auth/logout")
    client.cookies.set("nexscout_session", token or "")
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_wrong_password_and_unknown_user_look_identical(client: httpx.AsyncClient) -> None:
    await register(client)
    client.cookies.clear()
    a = await client.post(
        "/api/v1/auth/login", json={"email": "ada@example.com", "password": "wrong password!!"}
    )
    b = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong password!!"}
    )
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"]


async def test_login_rate_limited_after_repeated_failures(client: httpx.AsyncClient) -> None:
    statuses = []
    for _ in range(12):
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "victim@example.com", "password": "nope nope nope"},
        )
        statuses.append(r.status_code)
    assert statuses[:10] == [401] * 10
    assert statuses[-1] == 429


async def test_mutation_without_csrf_is_forbidden(client: httpx.AsyncClient) -> None:
    await register(client)
    del client.headers["X-CSRF-Token"]
    resp = await client.post("/api/v1/cases", json={"name": "No CSRF"})
    assert resp.status_code == 403
    client.headers["X-CSRF-Token"] = "forged-token-value"
    resp = await client.post("/api/v1/cases", json={"name": "Forged CSRF"})
    assert resp.status_code == 403


async def test_duplicate_registration_conflicts(client: httpx.AsyncClient) -> None:
    await register(client)
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "ada@example.com", "password": DEFAULT_PASSWORD, "display_name": "Ada 2"},
    )
    assert resp.status_code == 409


async def test_weak_password_rejected(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "bob@example.com", "password": "short", "display_name": "Bob"},
    )
    assert resp.status_code == 422
