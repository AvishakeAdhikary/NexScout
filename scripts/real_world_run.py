"""M17 real-world run: one person's real CV and preferences through NexScout, end to end.

    NEXSCOUT_REAL_RUN_DIR=<career-ops folder>  NEXSCOUT_RUN_EMAIL=<login email> \
    NEXSCOUT_NIM_API_KEY=<key, only for the "provider" phase> \
    uv run --project backend python scripts/real_world_run.py <phase> [<phase> ...]

Phases (run in order; each is resumable): setup sources sync research provider draft apply report

- Talks to a running NexScout over HTTP like the web app does (default
  http://127.0.0.1:3300, NEXSCOUT_RUN_BASE_URL), so it exercises the real stack.
- Reads the person's files from NEXSCOUT_REAL_RUN_DIR (cv.md, config/profile.yml, portals.yml).
  Writes state and the report to NEXSCOUT_RUN_OUT (default: a folder outside the repository).
  Nothing personal is written into the repository.
- The NVIDIA NIM key is read from the environment only, sent once to NexScout (which stores it
  sealed) and never printed or saved here.
- Never approves a submission. Applications stop at "waiting for your approval"; the person
  approves (or not) in the app. The only approvals this script gives are the "share my profile
  with the AI model" consents for drafting, which the person asked for by supplying the key.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

BASE = os.environ.get("NEXSCOUT_RUN_BASE_URL", "http://127.0.0.1:3300").rstrip("/")
RUN_DIR = Path(os.environ.get("NEXSCOUT_REAL_RUN_DIR", ""))
OUT = Path(os.environ.get("NEXSCOUT_RUN_OUT", Path.home() / "nexscout-real-run"))
NIM = "https://integrate.api.nvidia.com/v1"
TIMEZONE = os.environ.get("NEXSCOUT_RUN_TIMEZONE", "UTC")  # the person's IANA zone
CASE_NAME = "Europe: AI/ML/CV (jobs + PhD)"
UNKNOWN_BOARDS = {
    "Duunitori": "https://duunitori.fi/tyopaikat",
    "Work in Finland": "https://www.workinfinland.com/en/jobs",
    "Jobs in Finland": "https://www.jobsinfinland.fi",
}
TERMINAL = {"succeeded", "failed", "cancelled"}


def say(*parts: Any) -> None:
    print(*parts, flush=True)


class State:
    def __init__(self) -> None:
        self.path = OUT / "state.json"
        self.data: dict[str, Any] = (
            json.loads(self.path.read_text("utf-8")) if self.path.exists() else {}
        )

    def __getitem__(self, k: str) -> Any:
        return self.data[k]

    def get(self, k: str, default: Any = None) -> Any:
        return self.data.get(k, default)

    def set(self, k: str, v: Any) -> None:
        self.data[k] = v
        self.path.write_text(json.dumps(self.data, indent=2, default=str), "utf-8")


class Api:
    def __init__(self) -> None:
        self.http = httpx.Client(base_url=f"{BASE}/api/v1", timeout=120.0)

    def _csrf(self) -> dict[str, str]:
        return {"X-CSRF-Token": self.http.cookies.get("nexscout_csrf") or ""}

    def call(
        self, method: str, path: str, ok: tuple[int, ...] = (200, 201, 202, 204), **kw: Any
    ) -> Any:
        headers = kw.pop("headers", {}) | ({} if method == "GET" else self._csrf())
        r = self.http.request(method, path, headers=headers, **kw)
        if r.status_code not in ok:
            raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:500]}")
        if r.status_code == 204 or not r.content:
            return None
        return r.json() if "json" in r.headers.get("content-type", "") else r.text

    def get(self, path: str, **kw: Any) -> Any:
        return self.call("GET", path, **kw)

    def post(self, path: str, body: Any = None, **kw: Any) -> Any:
        return self.call("POST", path, json=body, **kw)

    def wait(
        self, run_id: str, timeout_s: float = 1800, approve_share: bool = False
    ) -> dict[str, Any]:
        """Poll a run to the end. Gives only drafting consents when asked; never submissions."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            d = self.get(f"/runs/{run_id}")
            status = d["run"]["status"]
            if status in TERMINAL:
                return dict(d)
            if status == "waiting_approval":
                pending = [a for a in d.get("approvals", []) if a["status"] == "pending"]
                share = [a for a in pending if a["action_kind"] == "share_profile_with_model"]
                if approve_share and share:
                    for a in share:
                        self.post(
                            f"/approvals/{a['id']}/decision",
                            {
                                "approve": True,
                                "note": "Real-world run: drafting with the user's own NIM key.",
                            },
                        )
                    continue
                if pending:
                    return dict(d)  # anything else waits for the person
                # Just decided: the worker hasn't resumed the run yet.
            time.sleep(3)
        raise TimeoutError(f"run {run_id} still running after {timeout_s:.0f} s")


def need(path: Path) -> Path:
    if not path.is_file():
        sys.exit(f"Missing {path}. Set NEXSCOUT_REAL_RUN_DIR to the career-ops folder.")
    return path


def login(api: Api, st: State) -> None:
    email = os.environ.get("NEXSCOUT_RUN_EMAIL") or st.get("email")
    if not email:
        sys.exit("Set NEXSCOUT_RUN_EMAIL (the address you'll sign in with).")
    password = st.get("password")
    if password:
        api.post("/auth/login", {"email": email, "password": password, "timezone": TIMEZONE})
        return
    profile = yaml.safe_load(need(RUN_DIR / "config/profile.yml").read_text("utf-8"))
    name = profile.get("candidate", {}).get("full_name") or "NexScout user"
    password = secrets.token_urlsafe(18)
    api.post(
        "/auth/register",
        {"email": email, "password": password, "display_name": name, "timezone": TIMEZONE},
    )
    st.set("email", email)
    st.set("password", password)  # kept in OUT (outside the repo) so the person can sign in
    say(f"Account created for {email}. Password saved in {st.path}.")


# --------------------------------------------------------------------------------- phases
def phase_setup(api: Api, st: State) -> None:
    profile = yaml.safe_load(need(RUN_DIR / "config/profile.yml").read_text("utf-8"))
    cases = api.get("/cases")
    case = next((c for c in cases if c["name"] == CASE_NAME), None) or api.post(
        "/cases", {"name": CASE_NAME}
    )
    case = (
        api.call(
            "PATCH",
            f"/cases/{case['id']}",
            json={"version": case["version"], "career_path": "both"},
        )
        if case.get("career_path") != "both"
        else case
    )
    st.set("case_id", case["id"])
    cid = case["id"]

    if not st.get("cv_document_id"):
        cv = need(RUN_DIR / "cv.md")
        up = api.call(
            "POST",
            f"/cases/{cid}/documents",
            files={"file": ("cv.md", cv.read_bytes(), "text/markdown")},
            data={"purpose": "cv"},
        )
        st.set("cv_document_id", up["document"]["id"])
        run = api.wait(up["run_id"], 600)
        say("CV read:", run["run"]["status"], run["run"].get("error") or "")
    facts = api.get(f"/cases/{cid}/facts")
    pending = [f["id"] for f in facts if f["review_state"] == "pending" and f["evidence_count"] > 0]
    # Every pending entry quotes the person's own CV (evidence spans). They asked for the full run.
    if pending:
        changed = api.post(f"/cases/{cid}/facts/review", {"accept": pending[:500]})["changed"]
        say(f"Accepted {changed} profile entries extracted from the CV (each quotes the CV).")
    st.set("facts", {"total": len(facts), "accepted_now": len(pending)})

    loc = profile.get("location", {})
    comp = profile.get("compensation", {})
    prefs = api.get(f"/cases/{cid}/preferences")
    data = {
        **prefs["data"],
        "countries": ["EUROPE"],
        "countries_exclude": [],
        "willing_to_relocate": True,
        "remote": "any",
        "experience_mode": "flexible",
        "needs_visa_sponsorship": bool(loc.get("needs_sponsorship", True)),
        "funding": "preferred",
        "funding_required": None,
        "languages": [profile.get("language", {}).get("output", "en")],
        "max_upfront_cost": 150_000,
        "budget_currency": "INR",
        "search_keywords": [
            "machine learning",
            "ml engineer",
            "ai engineer",
            "computer vision",
            "deep learning",
            "llm",
            "artificial intelligence",
            "data scientist",
            "mlops",
            "nlp",
        ],
        "exclude_keywords": ["intern", "internship", "werkstudent", "working student"],
        "job_titles": list(profile.get("target_roles", {}).get("primary", []))[:20],
        "research_areas": [
            "machine learning",
            "computer vision",
            "deep learning",
            "natural language processing",
        ],
        "salary_min": 47_500 if str(comp.get("currency", "")).upper() == "EUR" else None,
        "salary_currency": "EUR" if str(comp.get("currency", "")).upper() == "EUR" else None,
        "sensitive": {
            **prefs["data"].get("sensitive", {}),
            "work_authorization": list(loc.get("authorized_in", ["India"])),
            "use_for_eligibility": True,
        },
    }
    saved = api.call(
        "PUT", f"/cases/{cid}/preferences", json={"version": prefs["version"], "data": data}
    )
    say(
        "Preferences saved:",
        {
            k: saved["data"][k]
            for k in ("countries", "funding", "max_upfront_cost", "budget_currency")
        },
    )


def phase_sources(api: Api, st: State) -> None:
    listed = api.get("/sources")
    catalog = [s["key"] for s in listed if s["origin"] == "catalog"]
    demo = [s["key"] for s in listed if s["is_demo_data"]]
    if demo:
        api.post("/sources/bulk", {"keys": demo, "enabled": False})
    api.post("/sources/bulk", {"keys": catalog, "enabled": True})
    report: dict[str, Any] = {"catalog_enabled": len(catalog)}
    portals = RUN_DIR / "portals.yml"
    if portals.is_file():
        rep = api.post("/sources/import", {"content": portals.read_text("utf-8")})
        report["import"] = {
            "enabled_catalog": len(rep["enabled_catalog"]),
            "added": len(rep["added"]),
            "unsupported": len(rep["unsupported"]),
            "unsupported_reasons": sorted({u["reason"] for u in rep["unsupported"]}),
        }
    unknown = {}
    for name, url in UNKNOWN_BOARDS.items():
        r = api.http.post("/sources", json={"url": url, "name": name}, headers=api._csrf())
        unknown[name] = {"status": r.status_code, "answer": r.json() if r.content else None}
    report["unknown_boards"] = unknown
    report["manual_only"] = [m["name"] for m in api.get("/sources/manual")]
    st.set("sources", report)
    say(json.dumps(report, indent=2, default=str)[:4000])


def phase_sync(api: Api, st: State) -> None:
    cid = st["case_id"]
    started = time.monotonic()
    run = api.post(f"/cases/{cid}/opportunities/sync", {})
    done = api.wait(run["run_id"], 3600)
    result = done["run"].get("result") or {}
    per = result.get("sources", [])
    summary = {
        "status": done["run"]["status"],
        "error": done["run"].get("error"),
        "seconds": round(time.monotonic() - started),
        "sources": len(per),
        # Sync counters: "fetched" = kept and stored, "filtered" = read but outside the case's
        # countries or keywords (dropped before storage).
        "kept": sum(s.get("fetched", 0) for s in per),
        "dropped_by_filters": sum(s.get("filtered", 0) for s in per),
        "failed": sorted(
            (s["source_key"], s.get("skipped_reason")) for s in per if s.get("skipped_reason")
        ),
        "top_sources_kept": sorted(
            ((s["source_key"], s.get("fetched", 0)) for s in per if s.get("fetched")),
            key=lambda x: -x[1],
        )[:25],
    }
    st.set("sync", summary)
    say(json.dumps(summary, indent=2, default=str)[:6000])


def _ranked(api: Api, cid: str, academic: bool) -> list[dict[str, Any]]:
    items = api.get(f"/cases/{cid}/opportunities?academic={'true' if academic else 'false'}")
    return sorted((o for o in items if o["eligible"]), key=lambda o: -o["score"])


def phase_research(api: Api, st: State) -> None:
    cid = st["case_id"]
    picked = {"jobs": _ranked(api, cid, False)[:5], "phd": _ranked(api, cid, True)[:5]}
    out: dict[str, Any] = {}
    for group, opps in picked.items():
        for o in opps:
            r = api.post(f"/cases/{cid}/opportunities/{o['id']}/research", {})
            d = api.wait(r["run_id"], 900)
            res = api.get(f"/cases/{cid}/opportunities/{o['id']}/research")
            out[o["id"]] = {
                "group": group,
                "title": o["title"],
                "status": d["run"]["status"],
                "error": d["run"].get("error"),
                "findings": len(res["findings"]),
                "sources": len(res["sources"]),
            }
            say(group, o["title"][:70], d["run"]["status"], len(res["findings"]), "findings")
    st.set("research", out)


def phase_provider(api: Api, st: State) -> None:
    key = os.environ.get("NEXSCOUT_NIM_API_KEY", "")
    if not key:
        sys.exit("Set NEXSCOUT_NIM_API_KEY for this phase (it is never printed or saved here).")
    models = httpx.get(
        f"{NIM}/models", headers={"Authorization": f"Bearer {key}"}, timeout=60
    ).json()
    ids = [m["id"] for m in models.get("data", [])]
    # /v1/models lists models an account may not be able to call (404 "Function ... not found
    # for account"), so each candidate is tried with a one-word prompt (no personal data).
    prefer = (
        "nvidia/nemotron-3-super-120b-a12b",
        "google/gemma-4-31b-it",
        "mistralai/mistral-large-2-instruct",
        "nvidia/llama-3.1-nemotron-70b-instruct",
    )

    def callable_model(m: str) -> bool:
        r = httpx.post(
            f"{NIM}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": m,
                "messages": [{"role": "user", "content": "Say OK."}],
                "max_tokens": 8,
            },
            timeout=120,
        )
        return r.status_code == 200

    model = next((m for m in prefer if m in ids and callable_model(m)), None)
    if not model:
        sys.exit(f"None of {prefer} can be called with this key ({len(ids)} models listed).")
    existing = next((p for p in api.get("/providers") if p["name"] == "NVIDIA NIM"), None)
    body = {
        "name": "NVIDIA NIM",
        "kind": "openai_compatible",
        "model": model,
        "base_url": NIM,
        "api_key": key,
        "context_window": 32768,
        "max_output_tokens": 2048,
        "supports_json_schema": False,
        "is_default": True,
    }
    if existing:
        p = api.call(
            "PATCH",
            f"/providers/{existing['id']}",
            json={"version": existing["version"], **{k: v for k, v in body.items() if k != "kind"}},
        )
    else:
        p = api.post("/providers", body)
    check = api.post(f"/providers/{p['id']}/verify")
    st.set("provider", {"id": p["id"], "model": model, "models_listed": len(ids), "verify": check})
    say(
        "Provider:",
        model,
        "verify:",
        {k: check.get(k) for k in ("ok", "latency_ms", "schema_mode", "repairs", "error")},
    )


def phase_draft(api: Api, st: State) -> None:
    cid = st["case_id"]
    plan = [(o, ("resume", "cover_letter")) for o in _ranked(api, cid, False)[:3]]
    plan += [(o, ("sop", "academic_cv")) for o in _ranked(api, cid, True)[:2]]
    out = []
    for o, kinds in plan:
        for kind in kinds:
            r = api.post(
                f"/cases/{cid}/generated-documents", {"doc_type": kind, "opportunity_id": o["id"]}
            )
            d = api.wait(r["run_id"], 1200, approve_share=True)
            res = d["run"].get("result") or {}
            out.append(
                {
                    "opportunity": o["title"],
                    "doc_type": kind,
                    "status": d["run"]["status"],
                    "error": d["run"].get("error"),
                    "document_id": res.get("document_id"),
                    "placeholders": res.get("placeholders"),
                    "unsupported_claims": res.get("unsupported_claims"),
                }
            )
            say(kind, o["title"][:60], d["run"]["status"], d["run"].get("error") or "")
    st.set("drafts", out)


def phase_apply(api: Api, st: State) -> None:
    """Start applications for the drafted jobs and let NexScout fill them. Submitting is the
    person's call: each one stops at an approval in the app."""
    cid = st["case_id"]
    docs: dict[str, list[str]] = {}
    for d in st.get("drafts", []):
        if d.get("document_id") and d["status"] == "succeeded":
            docs.setdefault(d["opportunity"], []).append(d["document_id"])
    out = []
    existing = {a["opportunity_id"] for a in api.get(f"/cases/{cid}/applications")}
    for o in _ranked(api, cid, False)[:3] + _ranked(api, cid, True)[:2]:
        if o["id"] in existing:
            continue
        app = api.post(
            f"/cases/{cid}/applications",
            {"opportunity_id": o["id"], "document_ids": docs.get(o["title"], [])[:10]},
        )
        entry: dict[str, Any] = {
            "title": o["title"],
            "application_id": app["id"],
            "status": app["status"],
        }
        r = api.http.post(f"/applications/{app['id']}/browser", json={}, headers=api._csrf())
        if r.status_code in (200, 201, 202):
            run_id = r.json().get("run_id")
            d = api.wait(run_id, 1200) if run_id else None
            entry["fill"] = d["run"]["status"] if d else None
            entry["error"] = d["run"].get("error") if d else None
            entry["waiting_for_you"] = [
                a["title"] for a in (d or {}).get("approvals", []) if a["status"] == "pending"
            ]
        else:
            entry["fill"] = f"not started ({r.status_code}): {r.text[:300]}"
        out.append(entry)
        say(
            o["title"][:60],
            entry.get("fill"),
            entry.get("waiting_for_you") or entry.get("error") or "",
        )
    st.set("applications", out)


def phase_report(api: Api, st: State) -> None:
    cid = st["case_id"]
    lines = ["# NexScout real-world run", "", f"Stack: {BASE}  ·  case: {CASE_NAME}", ""]
    for key in ("facts", "sources", "sync", "provider", "research", "drafts", "applications"):
        lines += [
            f"## {key}",
            "```json",
            json.dumps(st.get(key), indent=2, default=str)[:20000],
            "```",
            "",
        ]
    for academic in (False, True):
        items = api.get(f"/cases/{cid}/opportunities?academic={'true' if academic else 'false'}")
        ok = [o for o in items if o["eligible"]]
        lines += [
            f"## {'PhD/research' if academic else 'Jobs'}: {len(ok)} eligible of {len(items)}",
            "",
        ]
        for o in sorted(ok, key=lambda o: -o["score"])[:25]:
            d = o["data"]
            where = d.get("location_text") or d.get("location_country") or "?"
            gaps = "; ".join(g["message"] for g in o.get("gaps", [])[:4])
            org = o["organization_name"]
            lines.append(f"- **{o['title']}** — {org} · {where} · fit {o['score']} · {gaps}")
        lines.append("")
    path = OUT / "report.md"
    path.write_text("\n".join(lines), "utf-8")
    say(f"Report: {path}")


PHASES = {
    "setup": phase_setup,
    "sources": phase_sources,
    "sync": phase_sync,
    "research": phase_research,
    "provider": phase_provider,
    "draft": phase_draft,
    "apply": phase_apply,
    "report": phase_report,
}


def main() -> None:
    wanted = sys.argv[1:] or list(PHASES)
    unknown = [p for p in wanted if p not in PHASES]
    if unknown:
        sys.exit(f"Unknown phase(s): {unknown}. Choose from {list(PHASES)}.")
    OUT.mkdir(parents=True, exist_ok=True)
    st, api = State(), Api()
    login(api, st)
    for p in wanted:
        say(f"== {p}")
        PHASES[p](api, st)


if __name__ == "__main__":
    main()
