"""M21: the AI assistant (tool loop, allow-list, consent per conversation) and AI skill
discovery (verified suggestions, one choice, added with evidence). Mock and fake-remote models
only: nothing leaves this machine."""

from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.helpers import create_case, register, upload

pytestmark = pytest.mark.db
PERSONAS = Path(__file__).parent.parent / "fixtures" / "personas"


async def _case(client: httpx.AsyncClient, worker: Any) -> str:
    await register(client)
    case_id = str((await create_case(client, "Jobs"))["id"])
    await client.patch(f"/api/v1/cases/{case_id}", json={"version": 1, "career_path": "both"})
    await client.post(f"/api/v1/cases/{case_id}/opportunities/sync", json={})
    await worker.run_until_idle()
    return case_id


async def _ask(
    client: httpx.AsyncClient, worker: Any, case_id: str, conversation: str, text: str, **kw: Any
) -> dict[str, Any]:
    r = await client.post(
        f"/api/v1/cases/{case_id}/chat/ai",
        json={"message": text, "conversation_id": conversation, **kw},
    )
    assert r.status_code == 202, r.text
    await worker.run_until_idle()
    run: dict[str, Any] = (await client.get(f"/api/v1/runs/{r.json()['run_id']}")).json()
    return run


async def test_the_assistant_looks_things_up_and_never_submits(
    client: httpx.AsyncClient, worker: Any
) -> None:
    case_id = await _case(client, worker)
    conv = (await client.get(f"/api/v1/cases/{case_id}/chat/conversation")).json()

    run = await _ask(client, worker, case_id, conv["id"], "What are my best job matches?")
    assert run["run"]["status"] == "succeeded", run["run"]
    assert run["approvals"] == []  # the local mock model needs no consent
    msgs = (await client.get(f"/api/v1/cases/{case_id}/chat")).json()
    reply = msgs[-1]
    assert reply["role"] == "assistant"
    assert reply["content"].startswith("[Mock reply, not written by AI] Your best matches: ")
    assert any(a["href"].startswith(f"/cases/{case_id}/jobs/") for a in reply["actions"])

    # Asked to submit: the model proposes it, plain code refuses, nothing is submitted.
    run = await _ask(client, worker, case_id, conv["id"], "Please submit my application now")
    assert run["run"]["status"] == "succeeded"
    reply = (await client.get(f"/api/v1/cases/{case_id}/chat")).json()[-1]
    assert "never available" in reply["content"]
    apps = (await client.get(f"/api/v1/cases/{case_id}/applications")).json()
    assert apps == []

    # The rule-based assistant still works, in the same conversation.
    r = await client.post(f"/api/v1/cases/{case_id}/chat", json={"message": "help"})
    assert r.status_code == 200
    assert all(m["conversation_id"] == conv["id"] for m in r.json())


async def test_an_online_model_asks_once_per_conversation(
    client: httpx.AsyncClient, worker: Any
) -> None:
    case_id = await _case(client, worker)
    remote = (
        await client.post(
            "/api/v1/providers",
            json={
                "name": "Remote test model",
                "kind": "openai_compatible",
                "model": "x",
                "base_url": "https://api.example.com/v1",
                "api_key": "sk-test-1234567890",
            },
        )
    ).json()
    conv = (await client.get(f"/api/v1/cases/{case_id}/chat/conversation")).json()

    # Declined: nothing is sent, and the reply says so.
    run = await _ask(client, worker, case_id, conv["id"], "hello", provider_id=remote["id"])
    assert run["run"]["status"] == "waiting_approval"
    approval = run["approvals"][0]
    assert approval["action_kind"] == "share_conversation_with_model"
    await client.post(f"/api/v1/approvals/{approval['id']}/decision", json={"approve": False})
    await worker.run_until_idle()
    reply = (await client.get(f"/api/v1/cases/{case_id}/chat")).json()[-1]
    assert "nothing was sent" in reply["content"]

    # Agreed in a new conversation: asked once; the next message there doesn't ask again.
    conv2 = (await client.post(f"/api/v1/cases/{case_id}/chat/conversations")).json()
    assert conv2["consented"] is False
    run = await _ask(client, worker, case_id, conv2["id"], "hello", provider_id=remote["id"])
    await client.post(
        f"/api/v1/approvals/{run['approvals'][0]['id']}/decision", json={"approve": True}
    )
    await worker.run_until_idle()  # the fake address can't answer: this turn fails
    current = (await client.get(f"/api/v1/cases/{case_id}/chat/conversation")).json()
    assert current == {**conv2, "consented": True}
    run = await _ask(client, worker, case_id, conv2["id"], "again", provider_id=remote["id"])
    assert run["approvals"] == []  # not asked twice in one conversation

    # Clearing the conversation removes its messages; the next one starts fresh.
    assert (await client.delete(f"/api/v1/chat/conversations/{conv2['id']}")).status_code == 204
    fresh = (await client.get(f"/api/v1/cases/{case_id}/chat/conversation")).json()
    assert fresh["id"] == conv["id"]  # the older conversation is the newest one left


async def test_skills_found_with_ai_are_added_only_as_chosen(
    client: httpx.AsyncClient, worker: Any
) -> None:
    await register(client)
    case_id = str((await create_case(client, "Rohan"))["id"])
    up = await upload(client, case_id, (PERSONAS / "rohan_cv.md").read_bytes(), "cv.md")
    assert up.status_code == 201, up.text
    await worker.run_until_idle()  # the CV is read (its entries wait for review)
    r = await client.post(f"/api/v1/cases/{case_id}/runs", json={"kind": "skill_discovery"})
    assert r.status_code == 201, r.text
    await worker.run_until_idle()
    run = (await client.get(f"/api/v1/runs/{r.json()['id']}")).json()["run"]
    assert run["status"] == "succeeded", run
    found = run["result"]["skills"]
    names = [s["name"] for s in found]
    assert "Quantum Basket Weaving" not in names  # invented by the mock: dropped
    assert any(d["name"] == "Quantum Basket Weaving" for d in run["result"]["dropped"])
    assert all(s["source_label"] for s in found)
    # The CV reader already suggested Python (pending): not suggested again.
    assert "Python" not in names
    assert {"MediaPipe", "LSTM"} <= set(names)

    added = await client.post(
        f"/api/v1/cases/{case_id}/facts/bulk-create",
        json={"run_id": run["id"], "names": ["MediaPipe", "Not Suggested"]},
    )
    assert added.status_code == 201, added.text
    facts = added.json()
    assert [f["label"] for f in facts] == ["MediaPipe"]  # only what was suggested and chosen
    assert facts[0]["review_state"] == "accepted"
    assert facts[0]["meta"]["method"] == "ai_v1"
    evidence = (await client.get(f"/api/v1/facts/{facts[0]['id']}/evidence")).json()
    assert "MediaPipe" in evidence[0]["excerpt"]  # the quote, from the CV
    assert evidence[0]["document_id"]
    again = await client.post(
        f"/api/v1/cases/{case_id}/facts/bulk-create",
        json={"run_id": run["id"], "names": ["MediaPipe"]},
    )
    assert again.json() == []  # already there
