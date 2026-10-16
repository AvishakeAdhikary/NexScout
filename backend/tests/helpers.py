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


async def upload(
    client: httpx.AsyncClient,
    case_id: str,
    data: bytes,
    filename: str = "cv.md",
    purpose: str = "cv",
) -> httpx.Response:
    resp = await client.post(
        f"/api/v1/cases/{case_id}/documents",
        files={"file": (filename, data, "application/octet-stream")},
        data={"purpose": purpose},
    )
    if resp.status_code == 201:
        await drain()
    return resp


async def facts(client: httpx.AsyncClient, case_id: str, **params: str) -> list[dict[str, Any]]:
    resp = await client.get(f"/api/v1/cases/{case_id}/facts", params=params)
    assert resp.status_code == 200, resp.text
    body: list[dict[str, Any]] = resp.json()
    return body


# The in-process worker registered by integration/security conftest (None elsewhere).
CURRENT_WORKER: Any = None


async def drain() -> None:
    """Run background work to completion, as the real worker process would."""
    if CURRENT_WORKER is not None:
        await CURRENT_WORKER.run_until_idle()


async def run_result(client: httpx.AsyncClient, run_id: str) -> dict[str, Any]:
    detail = (await client.get(f"/api/v1/runs/{run_id}")).json()
    assert detail["run"]["status"] == "succeeded", detail["run"]
    result: dict[str, Any] = detail["run"]["result"]
    return result


async def uploaded(
    client: httpx.AsyncClient,
    case_id: str,
    data: bytes,
    filename: str = "cv.md",
    purpose: str = "cv",
) -> dict[str, Any]:
    """Upload, let the worker read it, and return the processed document + extraction result."""
    resp = await upload(client, case_id, data, filename, purpose)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    await drain()
    result = await run_result(client, body["run_id"])
    doc = (await client.get(f"/api/v1/documents/{body['document']['id']}")).json()
    return {"document": doc, "facts_created": result["facts_created"], "result": result}


async def sync(client: httpx.AsyncClient, case_id: str) -> dict[str, Any]:
    """Start a search, let the worker finish it, and return summaries keyed by source."""
    resp = await client.post(f"/api/v1/cases/{case_id}/opportunities/sync", json={})
    assert resp.status_code == 202, resp.text
    await drain()
    result = await run_result(client, resp.json()["run_id"])
    return {s["source_key"]: s for s in result["sources"]}
