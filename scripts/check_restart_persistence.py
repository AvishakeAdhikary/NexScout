"""Verify persistence across a real API process restart (M2 acceptance).

Starts the API on :8200 against the dev database, writes data, hard-kills the process tree,
restarts it, and checks that everything is still there. Windows-only (uses taskkill).

    cd backend && uv run python ../scripts/check_restart_persistence.py
"""

import random
import subprocess
import sys
import time
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[1] / "backend"
PORT = 8200
BASE = f"http://127.0.0.1:{PORT}"


def start() -> subprocess.Popen[bytes]:
    proc = subprocess.Popen(
        ["uv", "run", "nexscout", "serve", "--port", str(PORT)],
        cwd=BACKEND, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    for _ in range(60):
        try:
            if httpx.get(f"{BASE}/readyz", timeout=2).status_code == 200:
                return proc
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise SystemExit("API did not become ready")


def stop(proc: subprocess.Popen[bytes]) -> None:
    # Kill the whole process tree (uv -> python) the hard way, like a crash.
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    proc.wait(timeout=20)
    try:
        httpx.get(f"{BASE}/healthz", timeout=2)
        raise SystemExit("API still answering after kill")
    except httpx.HTTPError:
        print("API process killed; port no longer answers")


proc = start()
client = httpx.Client(base_url=BASE, timeout=60)
email = f"restart-{random.randint(0, 10**9)}@example.com"
r = client.post("/api/v1/auth/register", json={
    "email": email, "password": "correct horse battery staple", "display_name": "R"})
r.raise_for_status()
client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
case_id = client.post("/api/v1/cases", json={"name": "Restart test"}).json()["id"]
cv = (BACKEND / "tests/fixtures/personas/ada_example_cv.md").read_bytes()
up = client.post(f"/api/v1/cases/{case_id}/documents",
                 files={"file": ("ada.md", cv)}, data={"purpose": "cv"}).json()
facts = client.get(f"/api/v1/cases/{case_id}/facts").json()
first = facts[0]
client.patch(f"/api/v1/facts/{first['id']}", json={"version": first["version"],
                                                    "review_state": "accepted"}).raise_for_status()
print(f"before: facts_created={up['facts_created']} facts={len(facts)}")
stop(proc)

proc = start()
after = client.get(f"/api/v1/cases/{case_id}/facts").json()
docs = client.get(f"/api/v1/cases/{case_id}/documents").json()
blob = client.get(f"/api/v1/documents/{docs[0]['id']}/content").content
accepted = [f for f in after if f["review_state"] == "accepted"]
print(f"after restart: facts={len(after)} accepted={len(accepted)} documents={len(docs)} "
      f"original_bytes_match={blob == cv}")
ok = len(after) == len(facts) and len(accepted) == 1 and blob == cv
stop(proc)
print("PERSISTENCE CHECK:", "PASSED" if ok else "FAILED")
sys.exit(0 if ok else 1)
