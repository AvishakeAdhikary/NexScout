"""M9: read-only MCP server, scoped to one user by a personal access token."""

import json
from typing import Any

import httpx
import pytest
from mcp.client.client import Client

from nexscout.application.tokens import authenticate_token
from nexscout.domain.errors import AuthenticationFailed
from nexscout.mcp_server import build_server
from tests.helpers import create_case, register

pytestmark = pytest.mark.db


def _data(result: Any) -> Any:
    assert not result.is_error, result
    if result.structured_content is not None:
        sc = result.structured_content
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    return json.loads(result.content[0].text)


async def _token(client: httpx.AsyncClient, **body: Any) -> dict[str, Any]:
    r = await client.post("/api/v1/me/tokens", json={"name": "Claude Desktop", **body})
    assert r.status_code == 201, r.text
    return dict(r.json())


async def _user_id(app: Any, token: str) -> Any:
    async with app.state.sessionmaker() as s, s.begin():
        return await authenticate_token(s, token)


async def test_tools_are_read_only_and_scoped(
    app: Any, client: httpx.AsyncClient, other_client: httpx.AsyncClient
) -> None:
    await register(client)
    case_id = str((await create_case(client, "PhD"))["id"])
    for section, data in (("skill", {"name": "Python"}), ("reference", {"name": "Dr. Private"})):
        await client.post(f"/api/v1/cases/{case_id}/facts", json={"section": section, "data": data})
    created = await _token(client)
    assert created["token"].startswith("nxs_")
    listed = (await client.get("/api/v1/me/tokens")).json()
    assert "token" not in listed[0]  # never shown again
    assert listed[0]["prefix"] == created["token"][:10]

    await register(other_client, "other@example.com", "Other")
    other_case = str((await create_case(other_client, "Theirs"))["id"])

    server = build_server(app.state.sessionmaker, await _user_id(app, created["token"]))
    async with Client(server) as mcp:
        tools = {t.name: t for t in (await mcp.list_tools()).tools}
        assert set(tools) == {
            "list_my_cases",
            "get_confirmed_profile",
            "list_matches",
            "list_applications",
            "get_application_timeline",
            "list_documents",
            "get_document",
        }
        assert all(t.annotations and t.annotations.read_only_hint for t in tools.values())

        cases = _data(await mcp.call_tool("list_my_cases", {}))
        assert [c["case_id"] for c in cases] == [case_id]
        profile = _data(await mcp.call_tool("get_confirmed_profile", {"case_id": case_id}))
        labels = [e["label"] for e in profile["entries"]]
        assert labels == ["Python"]  # private reference never shared
        assert _data(await mcp.call_tool("list_applications", {"case_id": case_id})) == []

        theirs = await mcp.call_tool("get_confirmed_profile", {"case_id": other_case})
        assert theirs.is_error  # another user's case is invisible
        bad = await mcp.call_tool("list_matches", {"case_id": "not-a-uuid"})
        assert bad.is_error


async def test_revoked_and_expired_tokens_fail(app: Any, client: httpx.AsyncClient) -> None:
    await register(client)
    t = await _token(client)
    assert await _user_id(app, t["token"])
    assert (await client.delete(f"/api/v1/me/tokens/{t['id']}")).status_code == 204
    with pytest.raises(AuthenticationFailed):
        await _user_id(app, t["token"])
    with pytest.raises(AuthenticationFailed):
        await _user_id(app, "nxs_" + "x" * 43)
    with pytest.raises(AuthenticationFailed):
        await _user_id(app, "not-a-token")
    async with app.state.sessionmaker() as s, s.begin():
        from sqlalchemy import text

        await s.execute(
            text("UPDATE personal_access_tokens SET expires_at = now(), revoked_at = NULL")
        )
    with pytest.raises(AuthenticationFailed):
        await _user_id(app, t["token"])
