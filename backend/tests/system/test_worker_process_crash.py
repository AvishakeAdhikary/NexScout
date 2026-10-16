"""M4 acceptance with real processes: hard-kill the worker mid-step, start a new worker
process, and the run finishes from its checkpoint with the side effect performed once."""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.conftest import TEST_DB_URL, TEST_SYSTEM_DB_URL
from tests.helpers import create_case, register

pytestmark = pytest.mark.db
BACKEND = Path(__file__).resolve().parents[2]


def _spawn_worker(storage: Path, log: Path) -> subprocess.Popen[bytes]:
    env = {
        **os.environ,
        "NEXSCOUT_ENV": "test",
        "NEXSCOUT_DATABASE_URL": TEST_DB_URL,
        "NEXSCOUT_SYSTEM_DATABASE_URL": TEST_SYSTEM_DB_URL,
        "NEXSCOUT_STORAGE_DIR": str(storage),
        "NEXSCOUT_WORKER_LEASE_S": "5",
        "NEXSCOUT_WORKER_POLL_S": "0.3",
        "NEXSCOUT_LOG_JSON": "true",
    }
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    return subprocess.Popen(
        [sys.executable, "-m", "nexscout.cli", "worker"],
        cwd=BACKEND,
        env=env,
        stdout=log.open("wb"),
        stderr=subprocess.STDOUT,
        creationflags=flags,
    )


def _hard_kill(proc: subprocess.Popen[bytes]) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
    else:
        proc.kill()
    proc.wait(timeout=20)


async def _detail(client: httpx.AsyncClient, run_id: str) -> dict[str, Any]:
    body: dict[str, Any] = (await client.get(f"/api/v1/runs/{run_id}")).json()
    return body


async def test_worker_process_killed_mid_step_is_recovered(
    client: httpx.AsyncClient, tmp_path: Path, storage_dir: Path
) -> None:
    await register(client)
    case_id = (await create_case(client))["id"]
    marker = tmp_path / "marker.txt"
    resp = await client.post(
        f"/api/v1/cases/{case_id}/runs",
        json={"kind": "system_check", "params": {"wait_s": 4, "marker_file": str(marker)}},
    )
    run_id = resp.json()["id"]

    first = _spawn_worker(storage_dir, tmp_path / "worker1.log")
    try:
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            d = await _detail(client, run_id)
            if any(s["node"] == "wait" and s["status"] == "running" for s in d["steps"]):
                break
            await asyncio.sleep(0.2)
        else:
            raise AssertionError(
                "worker never reached the wait step: "
                + (tmp_path / "worker1.log").read_text(errors="replace")[-2000:]
            )
    finally:
        _hard_kill(first)  # no graceful shutdown: lease and "running" state are left behind
    assert (await _detail(client, run_id))["run"]["status"] == "running"

    second = _spawn_worker(storage_dir, tmp_path / "worker2.log")
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            d = await _detail(client, run_id)
            if d["run"]["status"] in ("succeeded", "failed"):
                break
            await asyncio.sleep(0.3)
    finally:
        _hard_kill(second)

    d = await _detail(client, run_id)
    assert d["run"]["status"] == "succeeded", (
        d["run"],
        (tmp_path / "worker2.log").read_text(errors="replace")[-2000:],
    )
    done = [s["node"] for s in d["steps"] if s["status"] == "succeeded"]
    assert done.count("prepare") == 1  # resumed from the checkpoint, not restarted
    assert "run_recovering" in [e["type"] for e in d["events"]]
    assert marker.read_text().splitlines() == [run_id]  # side effect exactly once
