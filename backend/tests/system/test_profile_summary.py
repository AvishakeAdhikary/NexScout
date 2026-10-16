"""The first AI workflow: grounded summary drafting, consent before data leaves the device."""

from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.helpers import create_case, facts, register

pytestmark = pytest.mark.db


async def _case_with_profile(client: httpx.AsyncClient) -> str:
    await register(client)
    case_id = str((await create_case(client))["id"])
    for section, data in (
        ("employment", {"title": "ML Engineer", "organization": "Examplecorp", "start": "2021"}),
        ("education", {"institution": "University of Sampleford", "degree": "MSc"}),
        ("skill", {"name": "Python"}),
        ("skill", {"name": "SQL"}),
    ):
        await client.post(f"/api/v1/cases/{case_id}/facts", json={"section": section, "data": data})
    await client.post(
        f"/api/v1/cases/{case_id}/facts",
        json={"section": "reference", "data": {"name": "Dr. Private Person"}},
    )  # private by default
    return case_id


async def _run(client: httpx.AsyncClient, case_id: str, **params: Any) -> str:
    resp = await client.post(
        f"/api/v1/cases/{case_id}/runs", json={"kind": "profile_summary", "params": params}
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def test_mock_summary_is_grounded_pending_and_labelled(
    client: httpx.AsyncClient, worker: Any, clean_db: Engine
) -> None:
    case_id = await _case_with_profile(client)
    run_id = await _run(client, case_id)
    await worker.run_until_idle()
    d = (await client.get(f"/api/v1/runs/{run_id}")).json()
    assert d["run"]["status"] == "succeeded", d["run"]
    result = d["run"]["result"]
    assert result["status"] == "drafted"
    assert "Worked as ML Engineer at Examplecorp." in result["summary"]
    assert "Private Person" not in result["summary"]  # private entries are never used
    assert all(s["fact_ids"] for s in result["sentences"])
    assert d["approvals"] == []  # the local mock model needs no consent

    summary = list(await facts(client, case_id, section="summary"))
    assert len(summary) == 1
    assert summary[0]["status"] == "inferred"
    assert summary[0]["review_state"] == "pending"  # the user decides
    assert summary[0]["meta"]["generated"] is True
    assert summary[0]["meta"]["is_mock"] is True  # mock output is labelled as such
    assert result["model"]["is_mock"] is True
    with clean_db.connect() as conn:
        row = conn.execute(
            text("SELECT provider_kind, is_mock, input_tokens > 0 FROM usage_records")
        ).one()
    assert tuple(row) == ("mock", True, True)


async def test_external_model_requires_consent_and_rejection_sends_nothing(
    client: httpx.AsyncClient, worker: Any, clean_db: Engine
) -> None:
    case_id = await _case_with_profile(client)
    created = await client.post(
        "/api/v1/providers",
        json={
            "name": "Remote test model",
            "kind": "openai_compatible",
            "model": "x",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-test-1234567890",
        },
    )
    assert created.status_code == 201, created.text
    provider = created.json()
    assert provider["data_leaves_device"] is True
    assert provider["api_key_hint"] == "…7890"
    assert "sk-test" not in created.text  # the key is never returned

    run_id = await _run(client, case_id, provider_id=provider["id"])
    await worker.run_until_idle()
    d = (await client.get(f"/api/v1/runs/{run_id}")).json()
    assert d["run"]["status"] == "waiting_approval"
    approval = d["approvals"][0]
    assert approval["action_kind"] == "share_profile_with_model"
    assert "Remote test model" in approval["title"]
    assert "Dr. Private Person" not in str(approval["details"])

    await client.post(f"/api/v1/approvals/{approval['id']}/decision", json={"approve": False})
    await worker.run_until_idle()
    d = (await client.get(f"/api/v1/runs/{run_id}")).json()
    assert d["run"]["status"] == "succeeded"
    assert d["run"]["result"]["status"] == "not_sent"
    with clean_db.connect() as conn:  # no model call was made
        assert conn.execute(text("SELECT count(*) FROM usage_records")).scalar() == 0


async def test_no_confirmed_entries(client: httpx.AsyncClient, worker: Any) -> None:
    await register(client)
    case_id = str((await create_case(client))["id"])
    run_id = await _run(client, case_id)
    await worker.run_until_idle()
    d = (await client.get(f"/api/v1/runs/{run_id}")).json()
    assert d["run"]["result"]["status"] == "no_entries"


async def test_providers_api_validation_and_verify(client: httpx.AsyncClient) -> None:
    await register(client)
    bad = await client.post(
        "/api/v1/providers",
        json={
            "name": "Meta",
            "kind": "openai_compatible",
            "model": "x",
            "base_url": "http://169.254.169.254/v1",
        },
    )
    assert bad.status_code == 422
    local = await client.post(
        "/api/v1/providers",
        json={
            "name": "Ollama",
            "kind": "openai_compatible",
            "model": "llama3.1:8b",
            "base_url": "http://127.0.0.1:11434/v1",
            "is_default": True,
        },
    )
    assert local.status_code == 201
    assert local.json()["data_leaves_device"] is False
    mock = await client.post(
        "/api/v1/providers",
        json={
            "name": "Demo",
            "kind": "mock",
            "model": "nexscout-mock-1",
            "supports_json_schema": True,
        },
    )
    verified = await client.post(f"/api/v1/providers/{mock.json()['id']}/verify")
    assert verified.json()["ok"] is True
    listed = (await client.get("/api/v1/providers")).json()
    assert [p["name"] for p in listed if p["is_default"]] == ["Ollama"]
    other = await client.post(
        f"/api/v1/cases/{(await create_case(client))['id']}/runs",
        json={
            "kind": "profile_summary",
            "params": {"provider_id": "00000000-0000-0000-0000-000000000000"},
        },
    )
    assert other.status_code == 404
