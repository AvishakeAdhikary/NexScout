"""M4 acceptance: durable runs survive worker loss, honour pause/cancel/approvals, and never
repeat a completed side effect."""

import asyncio
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.helpers import create_case, register

pytestmark = pytest.mark.db


async def _case(client: httpx.AsyncClient) -> str:
    await register(client)
    return str((await create_case(client))["id"])


async def _start(client: httpx.AsyncClient, case_id: str, **params: Any) -> dict[str, Any]:
    resp = await client.post(
        f"/api/v1/cases/{case_id}/runs", json={"kind": "system_check", "params": params}
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


async def _run(client: httpx.AsyncClient, run_id: str) -> dict[str, Any]:
    resp = await client.get(f"/api/v1/runs/{run_id}")
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


async def _control(
    client: httpx.AsyncClient, run_id: str, action: str, node: str | None = None
) -> httpx.Response:
    return await client.post(
        f"/api/v1/runs/{run_id}/control", json={"action": action, "node": node}
    )


async def _wait_for(
    client: httpx.AsyncClient,
    run_id: str,
    *,
    node: str | None = None,
    status: str | None = None,
    timeout_s: float = 15,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        d = await _run(client, run_id)
        if status and d["run"]["status"] == status:
            return d
        if node and any(s["node"] == node and s["status"] == "running" for s in d["steps"]):
            return d
        await asyncio.sleep(0.1)
    raise AssertionError(f"timeout waiting for node={node} status={status}")


def _nodes(detail: dict[str, Any], status: str = "succeeded") -> list[str]:
    return [s["node"] for s in detail["steps"] if s["status"] == status]


async def test_run_completes_with_steps_events_and_result(
    client: httpx.AsyncClient, worker: Any
) -> None:
    case_id = await _case(client)
    run = await _start(client, case_id)
    assert run["status"] == "pending"
    await worker.run_until_idle()
    d = await _run(client, run["id"])
    assert d["run"]["status"] == "succeeded", d["run"]
    assert _nodes(d) == ["prepare", "wait", "approve", "effect", "finish"]
    assert d["run"]["result"]["steps"][-1] == "finish"
    assert d["run"]["steps_completed"] == 5
    types = [e["type"] for e in d["events"]]
    assert types[0] == "run_created"
    assert "run_running" in types
    assert types[-1] == "run_succeeded"
    prep = next(s for s in d["steps"] if s["node"] == "prepare")
    assert "Database access OK" in prep["summary"]["notes"][0]


async def test_approval_gate_blocks_until_user_decides(
    client: httpx.AsyncClient, worker: Any, clean_db: Engine
) -> None:
    case_id = await _case(client)
    run = await _start(client, case_id, require_approval=True)
    await worker.run_until_idle()
    d = await _run(client, run["id"])
    assert d["run"]["status"] == "waiting_approval"
    assert "effect" not in _nodes(d)  # the gated step has not run
    with clean_db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM tool_executions")).scalar() == 0
    approvals = (await client.get(f"/api/v1/cases/{case_id}/approvals")).json()
    assert len(approvals) == 1
    assert approvals[0]["status"] == "pending"

    # Running the worker again does nothing until a human decides.
    await worker.run_until_idle()
    assert (await _run(client, run["id"]))["run"]["status"] == "waiting_approval"

    resp = await client.post(
        f"/api/v1/approvals/{approvals[0]['id']}/decision", json={"approve": True, "note": "fine"}
    )
    assert resp.status_code == 200
    again = await client.post(
        f"/api/v1/approvals/{approvals[0]['id']}/decision", json={"approve": False}
    )
    assert again.status_code == 409  # decisions are final
    await worker.run_until_idle()
    d = await _run(client, run["id"])
    assert d["run"]["status"] == "succeeded"
    assert d["run"]["result"]["approved"] is True
    assert "effect" in _nodes(d)


async def test_rejection_skips_the_gated_action(client: httpx.AsyncClient, worker: Any) -> None:
    case_id = await _case(client)
    run = await _start(client, case_id, require_approval=True)
    await worker.run_until_idle()
    approval = (await client.get(f"/api/v1/cases/{case_id}/approvals")).json()[0]
    await client.post(f"/api/v1/approvals/{approval['id']}/decision", json={"approve": False})
    await worker.run_until_idle()
    d = await _run(client, run["id"])
    assert d["run"]["status"] == "succeeded"
    assert d["run"]["result"]["approved"] is False
    assert "effect:skipped (not approved)" in d["run"]["result"]["steps"]


async def test_pause_stops_at_step_boundary_and_resume_continues(
    client: httpx.AsyncClient, worker: Any
) -> None:
    case_id = await _case(client)
    run = await _start(client, case_id, wait_s=1.5)
    job = asyncio.create_task(worker.run_until_idle())
    await _wait_for(client, run["id"], node="wait")
    resp = await _control(client, run["id"], "pause")
    assert resp.json()["status"] == "pausing"
    await job
    d = await _run(client, run["id"])
    assert d["run"]["status"] == "paused"
    assert _nodes(d) == ["prepare", "wait"]  # the started step finished; nothing after it ran

    assert (await _control(client, run["id"], "resume")).json()["status"] == "pending"
    await worker.run_until_idle()
    d = await _run(client, run["id"])
    assert d["run"]["status"] == "succeeded"
    assert _nodes(d).count("prepare") == 1
    assert _nodes(d).count("wait") == 1  # completed steps are not repeated


async def test_cancel_interrupts_a_running_step(client: httpx.AsyncClient, worker: Any) -> None:
    case_id = await _case(client)
    run = await _start(client, case_id, wait_s=8)
    job = asyncio.create_task(worker.run_until_idle())
    await _wait_for(client, run["id"], node="wait")
    started = time.monotonic()
    assert (await _control(client, run["id"], "cancel")).json()["status"] == "cancelling"
    await worker._heartbeat_once()  # the heartbeat observes the request and cancels in-flight
    await job
    d = await _run(client, run["id"])
    assert d["run"]["status"] == "cancelled"
    assert time.monotonic() - started < 5  # did not wait for the 8 s step
    assert "cancelled" in [s["status"] for s in d["steps"] if s["node"] == "wait"]
    assert (await _control(client, run["id"], "resume")).status_code == 409


async def test_crashed_worker_is_recovered_without_repeating_side_effects(
    client: httpx.AsyncClient, worker: Any, clean_db: Engine, tmp_path: Path, storage_dir: Path
) -> None:
    from nexscout.agent_runtime.worker import Worker
    from tests.conftest import make_settings

    marker = tmp_path / "marker.txt"
    case_id = await _case(client)
    run = await _start(client, case_id, wait_s=1, marker_file=str(marker))
    job = asyncio.create_task(worker.run_until_idle())
    await _wait_for(client, run["id"], node="wait")
    # Simulate a hard crash: abandon the task without cleanup (lease stays "running").
    for flight in list(worker._inflight.values()):
        flight.cancel_reason = "lease_lost"
        flight.job.cancel()
    await asyncio.gather(job, return_exceptions=True)
    assert (await _run(client, run["id"]))["run"]["status"] == "running"
    with clean_db.begin() as conn:  # the lease expires
        conn.execute(
            text(
                "UPDATE tasks SET lease_expires_at = now() - interval '1 second' "
                "WHERE status = 'running'"
            )
        )

    second = Worker(make_settings(storage_dir=storage_dir), worker_id="test-worker-2")
    await second.open()
    try:
        await second.run_until_idle()
    finally:
        await second.close()
    d = await _run(client, run["id"])
    assert d["run"]["status"] == "succeeded", d["run"]
    assert _nodes(d).count("prepare") == 1  # resumed from the checkpoint
    assert "run_recovering" in [e["type"] for e in d["events"]]
    assert marker.read_text().splitlines() == [run["id"]]  # side effect happened exactly once


async def test_uncertain_side_effect_is_never_retried_silently(
    client: httpx.AsyncClient, worker: Any, clean_db: Engine
) -> None:
    case_id = await _case(client)
    run = await _start(client, case_id, require_approval=True)
    await worker.run_until_idle()
    with clean_db.begin() as conn:  # a previous attempt started the effect, then crashed
        conn.execute(
            text(
                "INSERT INTO tool_executions (id, owner_user_id, run_id, tool, idempotency_key, "
                "status, request_digest) SELECT gen_random_uuid(), owner_user_id, id, "
                "'system_check.marker', id::text || :suffix, 'started', 'x' "
                "FROM workflow_runs WHERE id = :r"
            ),
            {"r": run["id"], "suffix": ":system_check.marker:final"},
        )
    approval = (await client.get(f"/api/v1/cases/{case_id}/approvals")).json()[0]
    await client.post(f"/api/v1/approvals/{approval['id']}/decision", json={"approve": True})
    await worker.run_until_idle()
    d = await _run(client, run["id"])
    assert d["run"]["status"] == "failed"
    assert "may or may not have completed" in d["run"]["error"]
    with clean_db.connect() as conn:
        assert conn.execute(text("SELECT status FROM tool_executions")).scalar() == "uncertain"


async def test_retry_resumes_failed_step(
    client: httpx.AsyncClient, worker: Any, tmp_path: Path
) -> None:
    missing_dir = tmp_path / "not-yet"
    case_id = await _case(client)
    run = await _start(client, case_id, marker_file=str(missing_dir / "m.txt"))
    await worker.run_until_idle()
    d = await _run(client, run["id"])
    assert d["run"]["status"] == "failed"
    assert "FileNotFoundError" in d["run"]["error"]
    missing_dir.mkdir()
    assert (await _control(client, run["id"], "retry")).json()["status"] == "pending"
    await worker.run_until_idle()
    d = await _run(client, run["id"])
    assert d["run"]["status"] == "succeeded"
    assert _nodes(d).count("prepare") == 1
    assert _nodes(d, "failed") == ["effect"]


async def test_skip_optional_step_and_rerun_step(client: httpx.AsyncClient, worker: Any) -> None:
    case_id = await _case(client)
    run = await _start(client, case_id, wait_s="not a number")
    await worker.run_until_idle()
    d = await _run(client, run["id"])
    assert d["run"]["status"] == "failed"
    bad = await _control(client, run["id"], "skip", "effect")
    assert bad.status_code == 422  # required steps can't be skipped
    assert (await _control(client, run["id"], "skip", "wait")).status_code == 200
    await worker.run_until_idle()
    d = await _run(client, run["id"])
    assert d["run"]["status"] == "succeeded"
    assert "step_skipped" in [e["type"] for e in d["events"]]

    assert (await _control(client, run["id"], "rerun", "finish")).status_code == 200
    await worker.run_until_idle()
    d = await _run(client, run["id"])
    assert d["run"]["status"] == "succeeded"
    assert _nodes(d).count("finish") == 2
    assert _nodes(d).count("prepare") == 1


async def test_graceful_shutdown_requeues_and_another_worker_finishes(
    client: httpx.AsyncClient, clean_db: Engine, storage_dir: Path
) -> None:
    from nexscout.agent_runtime.worker import Worker
    from tests.conftest import make_settings

    case_id = await _case(client)
    run = await _start(client, case_id, wait_s=1)
    first = Worker(make_settings(storage_dir=storage_dir), worker_id="w-shutdown")
    forever = asyncio.create_task(first.run_forever())
    await _wait_for(client, run["id"], node="wait")
    first.request_stop()
    await forever
    d = await _run(client, run["id"])
    assert d["run"]["status"] == "pending"
    assert "run_requeued" in [e["type"] for e in d["events"]]

    second = Worker(make_settings(storage_dir=storage_dir), worker_id="w-next")
    await second.open()
    try:
        await second.run_until_idle()
    finally:
        await second.close()
    d = await _run(client, run["id"])
    assert d["run"]["status"] == "succeeded"
    assert _nodes(d).count("wait") == 1


async def test_step_budget_stops_runaway_runs(
    client: httpx.AsyncClient, worker: Any, clean_db: Engine
) -> None:
    case_id = await _case(client)
    run = await _start(client, case_id)
    with clean_db.begin() as conn:
        conn.execute(
            text("UPDATE workflow_runs SET step_budget = 2 WHERE id = :r"), {"r": run["id"]}
        )
    await worker.run_until_idle()
    d = await _run(client, run["id"])
    assert d["run"]["status"] == "failed"
    assert "limit of 2 steps" in d["run"]["error"]


async def test_event_stream_replays_backlog(client: httpx.AsyncClient, worker: Any) -> None:
    case_id = await _case(client)
    run = await _start(client, case_id)
    await worker.run_until_idle()
    resp = await client.get(f"/api/v1/cases/{case_id}/events", params={"once": "true"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    body = resp.text
    assert "event: run_created" in body
    assert "event: run_succeeded" in body
    assert run["id"] in body
    last_id = max(int(line[4:]) for line in body.splitlines() if line.startswith("id: "))
    resp = await client.get(
        f"/api/v1/cases/{case_id}/events", params={"once": "true", "after": last_id}
    )
    assert "event:" not in resp.text  # nothing new after the cursor


async def test_unknown_workflow_and_bad_params_rejected(client: httpx.AsyncClient) -> None:
    case_id = await _case(client)
    resp = await client.post(f"/api/v1/cases/{case_id}/runs", json={"kind": "rm_rf"})
    assert resp.status_code == 422
    resp = await client.post(
        f"/api/v1/cases/{case_id}/runs", json={"kind": "system_check", "params": {"shell": "ls"}}
    )
    assert resp.status_code == 422
