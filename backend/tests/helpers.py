"""Test helpers (synthetic personas only)."""

from __future__ import annotations

from typing import Any

import httpx

DEFAULT_PASSWORD = "correct horse battery staple"


async def register(
    client: httpx.AsyncClient,
    email: str = "ada@example.com",
    name: str = "Ada Example",
    password: str = DEFAULT_PASSWORD,
) -> dict[str, Any]:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": name},
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    # Mirror the browser: echo the CSRF token on subsequent mutating requests.
    client.headers["X-CSRF-Token"] = body["csrf_token"]
    return body


async def create_case(client: httpx.AsyncClient, name: str = "My PhD search") -> dict[str, Any]:
    resp = await client.post("/api/v1/cases", json={"name": name})
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body
