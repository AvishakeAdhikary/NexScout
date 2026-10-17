# ruff: noqa: F811  (pytest fixtures imported from test_browser_apply)
"""M11: notification channels over official provider APIs (mocked at the HTTP layer).

Every provider is faked with `httpx.MockTransport` (the real adapters build the real requests);
the Discord Gateway is a real WebSocket server speaking the Gateway protocol. Covers pairing,
the transactional outbox (retries, dead letter, circuit breaker, quiet hours), approvals and
answers from chat, identity binding, single-use buttons, idempotent inbound handling and
WhatsApp webhook signatures.
"""

import asyncio
import contextlib
import hashlib
import hmac
import json
import re
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from nexscout.infrastructure import channels as channel_infra
from nexscout.infrastructure.channels.simple import sign
from nexscout.integrations import fixture_site
from tests.helpers import create_case, register
from tests.system.test_browser_apply import (  # noqa: F401 - pytest fixtures
    _app,
    _application,
    _browser,
    _setup,
    app,
    site_origin,
    worker,
)

pytestmark = pytest.mark.db


class FakeProviders:
    """Answers like Telegram, Discord, WhatsApp Cloud API, Slack and a webhook receiver."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any], dict[str, str]]] = []
        self.tg_updates: list[dict[str, Any]] = []
        self.fail: dict[str, int] = {}  # host fragment -> status code to return
        self.gateway_url = ""
        self._id = 500

    def next_id(self) -> int:
        self._id += 1
        return self._id

    def sent(self, fragment: str) -> list[dict[str, Any]]:
        return [b for _, u, b, _ in self.calls if fragment in u]

    def handler(self, req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        try:
            body = json.loads(req.content) if req.content else {}
        except ValueError:
            body = {}
        self.calls.append((req.method, url, body, dict(req.headers)))
        for frag, code in self.fail.items():
            if frag in url:
                return httpx.Response(code, json={"description": "fake failure"})
        if "api.telegram.org" in url:
            method = url.rsplit("/", 1)[1]
            if method == "getMe":
                return httpx.Response(200, json={"ok": True, "result": {"username": "nex_bot"}})
            if method == "getUpdates":
                ups = [u for u in self.tg_updates if u["update_id"] >= body.get("offset", 0)]
                return httpx.Response(200, json={"ok": True, "result": ups})
            if method == "sendMessage":
                return httpx.Response(
                    200, json={"ok": True, "result": {"message_id": self.next_id()}}
                )
            return httpx.Response(200, json={"ok": True, "result": True})
        if "discord.com" in url:
            if url.endswith("/gateway/bot"):
                return httpx.Response(200, json={"url": self.gateway_url})
            if url.endswith("/users/@me/channels"):
                return httpx.Response(200, json={"id": "dm-1"})
            if "/messages" in url:
                return httpx.Response(200, json={"id": str(self.next_id())})
            if url.endswith("/callback"):
                return httpx.Response(204)
        if "graph.facebook.com" in url:
            return httpx.Response(200, json={"messages": [{"id": f"wamid.{self.next_id()}"}]})
        if "hooks.slack.com" in url or "127.0.0.1:8999" in url:
            return httpx.Response(200, text="ok")
        return httpx.Response(404)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeProviders]:
    f = FakeProviders()
    monkeypatch.setattr(
        channel_infra,
        "client_factory",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(f.handler)),
    )
    return f


def _loops(worker: Any) -> Any:
    return worker.channel_loops()


async def _telegram(
    client: httpx.AsyncClient, fake: FakeProviders, worker: Any, chat: int = 111
) -> dict[str, Any]:
    r = await client.post(
        "/api/v1/channels",
        json={"kind": "telegram", "name": "My Telegram", "secrets": {"bot_token": "123:ABC"}},
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["channel"]["status"] == "pending_pairing"
    assert "@nex_bot" in created["instructions"]
    assert "123:ABC" not in r.text  # the token is never returned
    code = created["pairing_code"]
    fake.tg_updates.append(
        {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "chat": {"id": chat, "type": "private"},
                "from": {"id": chat},
                "text": f"/start {code}",
            },
        }
    )
    await _loops(worker).telegram_poll_once(uuid_of(created), wait_s=0)
    ch = (await client.get("/api/v1/channels")).json()[0]
    assert ch["status"] == "active"
    assert ch["paired"] is True
    assert ch["config"]["chat_id"] == str(chat)
    assert any("Paired" in b.get("text", "") for b in fake.sent("sendMessage"))
    return ch


def uuid_of(created: dict[str, Any]) -> Any:
    import uuid

    return uuid.UUID(created["channel"]["id"])


def _tg_buttons(body: dict[str, Any]) -> dict[str, str]:
    rows = (body.get("reply_markup") or {}).get("inline_keyboard") or []
    return {b["text"]: b["callback_data"] for row in rows for b in row if "callback_data" in b}


async def test_telegram_question_answer_then_approve_submits_once(
    client: httpx.AsyncClient, worker: Any, fake: FakeProviders
) -> None:
    fixture_site.SUBMISSIONS.clear()  # module-level state shared with other tests
    case_id, opps, resume = await _setup(client, worker)
    ch = await _telegram(client, fake, worker)
    import uuid

    cid = uuid.UUID(ch["id"])
    loops = _loops(worker)
    a = await _application(client, case_id, opps["a-1001"], resume)

    # 1) Unknown question: NexScout asks on Telegram instead of guessing.
    d = await _browser(client, worker, a["id"])
    assert d["run"]["result"]["status"] == "needs_user_action"
    assert await loops.deliver_due() >= 1
    asked = [b for b in fake.sent("sendMessage") if "asks:" in b.get("text", "")]
    assert len(asked) == 1
    assert "Why are you interested in this role?" in asked[0]["text"]
    assert asked[0]["reply_markup"]["force_reply"] is True
    asked_id = fake._id  # the fake's message id for that message

    # 2) The user replies to that message; the answer is stored as theirs and reused.
    fake.tg_updates.append(
        {
            "update_id": 2,
            "message": {
                "message_id": 9,
                "chat": {"id": 111, "type": "private"},
                "from": {"id": 111},
                "text": "I enjoy building ML platforms.",
                "reply_to_message": {"message_id": asked_id},
            },
        }
    )
    await loops.telegram_poll_once(cid, wait_s=0)
    app_now = await _app(client, a["id"])
    assert app_now["answers"]["why are you interested in this role?"] == (
        "I enjoy building ML platforms."
    )
    assert any("Saved" in b.get("text", "") for b in fake.sent("sendMessage"))

    # 3) Fill again: approval request goes to Telegram with Approve / Reject buttons.
    d = await _browser(client, worker, a["id"])
    assert d["run"]["status"] == "waiting_approval"
    await loops.deliver_due()
    approval_msg = next(b for b in fake.sent("sendMessage") if _tg_buttons(b))
    buttons = _tg_buttons(approval_msg)
    assert set(buttons) == {"Approve", "Reject"}
    assert "Open in NexScout: http://localhost:3000/approve/" in approval_msg["text"]
    assert fixture_site.SUBMISSIONS == []  # asked and filled, nothing sent

    # 4) Someone else pressing the button does nothing.
    fake.tg_updates.append(
        {
            "update_id": 3,
            "callback_query": {
                "id": "cb-x",
                "from": {"id": 999},
                "data": buttons["Approve"],
                "message": {"message_id": 1, "chat": {"id": 999}},
            },
        }
    )
    await loops.telegram_poll_once(cid, wait_s=0)
    assert (await client.get(f"/api/v1/runs/{d['run']['id']}")).json()["run"]["status"] == (
        "waiting_approval"
    )

    # 5) The paired user approves from Telegram: submitted exactly once.
    fake.tg_updates.append(
        {
            "update_id": 4,
            "callback_query": {
                "id": "cb-1",
                "from": {"id": 111},
                "data": buttons["Approve"],
                "message": {"message_id": 1, "chat": {"id": 111}},
            },
        }
    )
    await loops.telegram_poll_once(cid, wait_s=0)
    await worker.run_until_idle()
    app_now = await _app(client, a["id"])
    assert app_now["status"] == "submitted"
    assert len([s for s in fixture_site.SUBMISSIONS if s["job"] == "REQ-100"]) == 1
    answered = list(fake.sent("answerCallbackQuery"))
    assert answered[-1]["text"].startswith("Approved")
    assert "isn't valid for you" in answered[0]["text"]

    # 6) Replays: the same update id is ignored; the used token can't act again.
    fake.tg_updates.append(
        {
            "update_id": 5,
            "callback_query": {
                "id": "cb-2",
                "from": {"id": 111},
                "data": buttons["Reject"],
                "message": {"message_id": 1, "chat": {"id": 111}},
            },
        }
    )
    await loops.telegram_poll_once(cid, wait_s=0)
    assert fake.sent("answerCallbackQuery")[-1]["text"].startswith("Already handled")
    n_before = len(fake.calls)
    await loops._telegram_update(None, "123:ABC", cid, _update(4))  # duplicate id 4
    assert len(fake.calls) == n_before
    assert len([s for s in fixture_site.SUBMISSIONS if s["job"] == "REQ-100"]) == 1


def _update(update_id: int) -> Any:
    from nexscout.infrastructure.channels.telegram import TelegramUpdate

    return TelegramUpdate(update_id, "callback", "111", "111", callback_id="x", data="nope")


async def _system_check_approval(client: httpx.AsyncClient, worker: Any) -> tuple[str, str]:
    case_id = str((await create_case(client))["id"])
    r = await client.post(
        f"/api/v1/cases/{case_id}/runs",
        json={"kind": "system_check", "params": {"require_approval": True}},
    )
    assert r.status_code == 201, r.text
    await worker.run_until_idle()
    ap = (await client.get(f"/api/v1/cases/{case_id}/approvals")).json()[0]
    detail = (await client.get(f"/api/v1/approvals/{ap['id']}")).json()
    assert detail["case_id"] == case_id
    return r.json()["id"], ap["id"]


async def _discord_gateway(
    events: list[dict[str, Any]],
    seen: list[dict[str, Any]],
) -> AsyncIterator[str]:
    """A tiny Gateway: HELLO, expects IDENTIFY, READY, then the given dispatches."""
    from websockets.asyncio.server import serve

    async def handler(ws: Any) -> None:
        await ws.send(json.dumps({"op": 10, "d": {"heartbeat_interval": 45000}}))
        seen.append(json.loads(await ws.recv()))
        await ws.send(
            json.dumps(
                {
                    "op": 0,
                    "s": 1,
                    "t": "READY",
                    "d": {"session_id": "s1", "resume_gateway_url": "ws://x"},
                }
            )
        )
        for i, e in enumerate(events, start=2):
            await ws.send(json.dumps({"op": 0, "s": i, **e}))
        with contextlib.suppress(Exception):
            async for raw in ws:
                seen.append(json.loads(raw))

    async with serve(handler, "127.0.0.1", 0) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        yield f"ws://127.0.0.1:{port}"


async def test_discord_pairing_and_gateway_button_approves(
    client: httpx.AsyncClient, worker: Any, fake: FakeProviders, clean_db: Engine
) -> None:
    await register(client)
    r = await client.post(
        "/api/v1/channels",
        json={
            "kind": "discord",
            "name": "Discord",
            "config": {"user_id": "123456789012345678"},
            "secrets": {"bot_token": "discord-token"},
        },
    )
    assert r.status_code == 201, r.text
    ch = r.json()["channel"]
    assert ch["status"] == "pending_pairing"
    dm = fake.sent("/channels/dm-1/messages")[0]["content"]
    code = re.search(r"code: ([0-9A-F]{8})", dm).group(1)  # type: ignore[union-attr]
    assert r.json()["pairing_code"] == code
    bad = await client.post(f"/api/v1/channels/{ch['id']}/pair", json={"code": "00000000"})
    assert bad.status_code == 422
    ok = await client.post(f"/api/v1/channels/{ch['id']}/pair", json={"code": code})
    assert ok.status_code == 200
    assert ok.json()["status"] == "active"

    run_id, approval_id = await _system_check_approval(client, worker)
    loops = _loops(worker)
    await loops.deliver_due()
    msg = fake.sent("/channels/dm-1/messages")[-1]
    comps = msg["components"][0]["components"]
    approve_token = next(c["custom_id"] for c in comps if c["label"] == "Approve")
    assert msg["allowed_mentions"] == {"parse": []}

    # Button pressed by another account, then by the paired user, through the Gateway.
    def interaction(i: str, user: str) -> dict[str, Any]:
        return {
            "t": "INTERACTION_CREATE",
            "d": {
                "id": i,
                "type": 3,
                "token": f"tok-{i}",
                "user": {"id": user},
                "data": {"custom_id": approve_token},
            },
        }

    seen: list[dict[str, Any]] = []
    gen = _discord_gateway(
        [interaction("901", "42"), interaction("902", "123456789012345678")], seen
    )
    fake.gateway_url = await gen.__anext__()
    with clean_db.begin() as conn:
        conn.execute(
            text(
                "UPDATE notification_channels SET config = config || "
                "jsonb_build_object('gateway_url', CAST(:u AS text))"
            ),
            {"u": fake.gateway_url},
        )
    stop = asyncio.Event()
    import uuid

    task = asyncio.create_task(loops._discord_session(uuid.UUID(ch["id"]), stop))
    for _ in range(100):
        if len(fake.sent("/callback")) >= 2:
            break
        await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, 10)
    with contextlib.suppress(StopAsyncIteration):
        await gen.__anext__()
    identify = seen[0]
    assert identify["op"] == 2
    assert identify["d"]["intents"] == 1 << 12
    callbacks = fake.sent("/callback")
    assert "isn't valid for you" in callbacks[0]["data"]["content"]
    assert callbacks[1]["data"]["content"].startswith("Approved")
    await worker.run_until_idle()
    run = (await client.get(f"/api/v1/runs/{run_id}")).json()["run"]
    assert run["status"] == "succeeded"
    ap = (await client.get(f"/api/v1/approvals/{approval_id}")).json()
    assert ap["status"] == "approved"
    assert "paired chat channel" in ap["decision_note"]


def _wa_body(from_id: str, msg: dict[str, Any]) -> bytes:
    return json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"value": {"messages": [{"from": from_id, **msg}]}}]}],
        }
    ).encode()


def _sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def test_whatsapp_webhook_verification_signatures_and_reject_button(
    client: httpx.AsyncClient, worker: Any, fake: FakeProviders
) -> None:
    await register(client)
    r = await client.post(
        "/api/v1/channels",
        json={
            "kind": "whatsapp",
            "name": "WhatsApp",
            "config": {"phone_number_id": "1234567890"},
            "secrets": {"access_token": "wa-token", "app_secret": "app-secret"},
        },
    )
    assert r.status_code == 201, r.text
    created = r.json()
    ch = created["channel"]
    hook = ch["webhook"]
    path = f"/api/v1/channels/{ch['id']}/whatsapp"
    assert hook["callback_url"].endswith(path)

    # Meta's verification handshake (no session; the derived token must match).
    v = await client.get(
        path, params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "c1"}
    )
    assert v.status_code == 403
    v = await client.get(
        path,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": hook["verify_token"],
            "hub.challenge": "c1",
        },
    )
    assert v.status_code == 200
    assert v.text == "c1"

    loops = _loops(worker)
    # A forged body (bad signature) is stored but rejected, so it can't pair the channel.
    forged = _wa_body(
        "15550001111",
        {"id": "wamid.f", "type": "text", "text": {"body": f"PAIR {created['pairing_code']}"}},
    )
    plain = httpx.AsyncClient(transport=client._transport, base_url="http://testserver")
    res = await plain.post(
        path,
        content=forged,
        headers={
            "x-hub-signature-256": _sig("not-the-secret", forged),
            "content-type": "application/json",
        },
    )
    assert res.status_code == 200
    await loops.whatsapp_inbox_once()
    assert (await client.get("/api/v1/channels")).json()[0]["status"] == "pending_pairing"

    # The real, signed message pairs the sender's number.
    good = _wa_body(
        "15550001111",
        {"id": "wamid.g", "type": "text", "text": {"body": f"PAIR {created['pairing_code']}"}},
    )
    await plain.post(
        path,
        content=good,
        headers={
            "x-hub-signature-256": _sig("app-secret", good),
            "content-type": "application/json",
        },
    )
    await loops.whatsapp_inbox_once()
    chan = (await client.get("/api/v1/channels")).json()[0]
    assert chan["status"] == "active"
    assert chan["config"]["wa_id"] == "15550001111"
    sent = fake.sent("graph.facebook.com")
    assert sent[-1]["to"] == "15550001111"
    assert "Paired" in sent[-1]["text"]["body"]

    # Approval goes out as interactive reply buttons; "Reject" from the paired number rejects.
    _run_id, approval_id = await _system_check_approval(client, worker)
    await loops.deliver_due()
    interactive = fake.sent("graph.facebook.com")[-1]
    assert interactive["type"] == "interactive"
    btns = {
        b["reply"]["title"]: b["reply"]["id"]
        for b in interactive["interactive"]["action"]["buttons"]
    }
    reject = _wa_body(
        "15550001111",
        {
            "id": "wamid.r",
            "type": "interactive",
            "interactive": {
                "type": "button_reply",
                "button_reply": {"id": btns["Reject"], "title": "Reject"},
            },
        },
    )
    for _ in range(2):  # Meta retries deliveries: the second copy changes nothing
        await plain.post(
            path,
            content=reject,
            headers={
                "x-hub-signature-256": _sig("app-secret", reject),
                "content-type": "application/json",
            },
        )
    await loops.whatsapp_inbox_once()
    await worker.run_until_idle()
    ap = (await client.get(f"/api/v1/approvals/{approval_id}")).json()
    assert ap["status"] == "rejected"
    texts = [b["text"]["body"] for b in fake.sent("graph.facebook.com") if b.get("type") == "text"]
    assert sum(t.startswith("Rejected") for t in texts) == 1
    await plain.aclose()


QUEUE_SQL = """
WITH n AS (
    INSERT INTO notifications (id, owner_user_id, kind, title, dedupe_key, data)
    SELECT gen_random_uuid(), owner_user_id, 'reminder', :title, :k, '{}'::jsonb
    FROM notification_channels WHERE name = 'n8n'
    RETURNING id, owner_user_id
)
INSERT INTO notification_deliveries
    (id, owner_user_id, notification_id, channel_id, status, attempts)
SELECT gen_random_uuid(), n.owner_user_id, n.id, c.id, 'pending', 0
FROM n, notification_channels c WHERE c.name = 'n8n'
"""


def _queue(conn: Any, title: str, key: str) -> None:
    """A notification queued for the 'n8n' webhook channel (bypassing the reminder sweep)."""
    conn.execute(text(QUEUE_SQL), {"title": title, "k": key})


async def test_outbox_retries_dead_letters_breaker_quiet_hours_and_isolation(
    client: httpx.AsyncClient,
    other_client: httpx.AsyncClient,
    worker: Any,
    fake: FakeProviders,
    clean_db: Engine,
) -> None:
    await register(client)
    hook = await client.post(
        "/api/v1/channels",
        json={"kind": "webhook", "name": "n8n", "secrets": {"url": "http://127.0.0.1:8999/hook"}},
    )
    assert hook.status_code == 201, hook.text
    assert "X-NexScout-Signature" in hook.json()["instructions"]
    slack = await client.post(
        "/api/v1/channels",
        json={
            "kind": "slack",
            "name": "Slack",
            "secrets": {"webhook_url": "https://hooks.slack.com/x"},
            "events": ["approval"],
        },
    )
    assert slack.status_code == 201
    bad = await client.post(
        "/api/v1/channels",
        json={"kind": "slack", "name": "S2", "secrets": {"webhook_url": "https://evil.example/x"}},
    )
    assert bad.status_code == 422

    # Another user can't see, test, pause or delete these channels.
    await register(other_client, email="eve@example.com", name="Eve")
    hid = hook.json()["channel"]["id"]
    assert (await other_client.get("/api/v1/channels")).json() == []
    assert (await other_client.post(f"/api/v1/channels/{hid}/test")).status_code == 404
    assert (await other_client.delete(f"/api/v1/channels/{hid}")).status_code == 404

    # Test message: signed webhook.
    t = await client.post(f"/api/v1/channels/{hid}/test")
    assert t.json() == {"ok": True, "error": None}
    _, _, body, headers = next(c for c in fake.calls if "8999" in c[1])
    raw = json.dumps(body, separators=(",", ":")).encode()
    signing = hook.json()["signing_secret"]
    assert signing
    assert headers["x-nexscout-signature"] == sign(signing, headers["x-nexscout-timestamp"], raw)
    assert (await client.get("/api/v1/channels")).text.count(signing) == 0  # shown once only
    assert headers["x-nexscout-signature"].startswith("sha256=")
    assert body["event"] == "test"

    # A reminder notification: only the webhook subscribes to reminders (Slack: approvals).
    case_id = str((await create_case(client))["id"])
    r = await client.post(
        f"/api/v1/cases/{case_id}/reminders",
        json={"title": "Email Prof. X", "due_on": "2020-01-01"},
    )
    assert r.status_code == 201, r.text
    await worker.maintenance_once()
    loops = _loops(worker)

    # Transient failure (503) → retried later with backoff; then success.
    fake.fail["8999"] = 503
    assert await loops.deliver_due() == 1
    with clean_db.begin() as conn:
        row = conn.execute(
            text("SELECT status, attempts, next_attempt_at > now() FROM notification_deliveries")
        ).one()
    assert row == ("pending", 1, True)
    assert len(fake.sent("hooks.slack.com")) == 0
    del fake.fail["8999"]
    with clean_db.begin() as conn:
        conn.execute(text("UPDATE notification_deliveries SET next_attempt_at = now()"))
    assert await loops.deliver_due() == 1
    with clean_db.begin() as conn:
        assert conn.execute(text("SELECT status FROM notification_deliveries")).scalar() == "sent"

    # Permanent failures dead-letter at once; five in a row open the circuit (status error).
    fake.fail["8999"] = 401
    with clean_db.begin() as conn:
        for i in range(5):
            _queue(conn, "t", f"k{i}")
    await loops.deliver_due()
    chans = {c["name"]: c for c in (await client.get("/api/v1/channels")).json()}
    assert chans["n8n"]["status"] == "error"
    assert "HTTP 401" in chans["n8n"]["last_error"]
    log = (await client.get(f"/api/v1/channels/{hid}/deliveries")).json()
    assert sum(d["status"] == "dead" for d in log) == 5
    resumed = await client.patch(
        f"/api/v1/channels/{hid}", json={"version": chans["n8n"]["version"], "paused": False}
    )
    assert resumed.json()["status"] == "active"

    # Quiet hours: deliveries wait until the quiet period ends.
    now = datetime.now(UTC)
    start, end = (
        (now - timedelta(hours=1)).strftime("%H:%M"),
        (now + timedelta(hours=1)).strftime("%H:%M"),
    )
    q = await client.patch(
        f"/api/v1/channels/{hid}",
        json={"version": resumed.json()["version"], "quiet_start": start, "quiet_end": end},
    )
    assert q.status_code == 200, q.text
    del fake.fail["8999"]
    with clean_db.begin() as conn:
        _queue(conn, "quiet", "quiet")
    before = len(fake.sent("8999"))
    await loops.deliver_due()
    assert len(fake.sent("8999")) == before
    with clean_db.begin() as conn:
        st = conn.execute(
            text(
                "SELECT d.status, d.next_attempt_at > now() + interval '30 minutes' FROM "
                "notification_deliveries d JOIN notifications n ON n.id = d.notification_id "
                "WHERE n.title='quiet'"
            )
        ).one()
    assert st == ("pending", True)

    # Removing a channel deletes its sealed credentials too.
    with clean_db.begin() as conn:
        n_secrets = conn.execute(text("SELECT count(*) FROM secrets")).scalar()
    assert (await client.delete(f"/api/v1/channels/{hid}")).status_code == 204
    with clean_db.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM secrets")).scalar() == n_secrets - 1
