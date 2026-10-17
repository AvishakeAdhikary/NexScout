"""Cross-tenant sweep: user B must get 404 on every route that names one of user A's resources.

When a route with a path parameter is added, it must be covered here.
`test_every_id_route_is_covered` fails if a new route isn't (routes are enumerated from the
OpenAPI document, which is stable across FastAPI's internal router representations).
"""

import re
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from nexscout.infrastructure.db.models import OWNED_TABLES
from tests.fixtures.documents import ada_cv_text
from tests.helpers import create_case, facts, register, sync, upload

pytestmark = pytest.mark.db

# Routes with path parameters that don't name a user-owned resource.
EXEMPT = {
    ("PUT", "/api/v1/sources/{source_key}"): "Source registry key; config is stored per user.",
}


async def _seed_owner(client: httpx.AsyncClient, worker: Any) -> dict[str, str]:
    await register(client, "owner@example.com", "Owner")
    case_id = str((await create_case(client, "Owner case"))["id"])
    await client.patch(f"/api/v1/cases/{case_id}", json={"version": 1, "career_path": "both"})
    doc = (await upload(client, case_id, ada_cv_text().encode(), "ada.md")).json()["document"]
    fact = (await facts(client, case_id))[0]
    await client.post(f"/api/v1/cases/{case_id}/facts/review", json={"accept": [fact["id"]]})
    fact = (await client.get(f"/api/v1/facts/{fact['id']}")).json()
    link = (
        await client.post(
            f"/api/v1/cases/{case_id}/social-profiles", json={"url": "https://github.com/owner"}
        )
    ).json()
    aff = (
        await client.post(
            f"/api/v1/cases/{case_id}/affiliations",
            json={"organization": "Org", "relationship_type": "alumnus"},
        )
    ).json()
    await client.post(f"/api/v1/cases/{case_id}/snapshots", json={})
    await client.post(f"/api/v1/cases/{case_id}/snapshots", json={})
    await sync(client, case_id)
    opp = (await client.get(f"/api/v1/cases/{case_id}/opportunities")).json()[0]
    run = (
        await client.post(
            f"/api/v1/cases/{case_id}/runs",
            json={"kind": "system_check", "params": {"require_approval": True}},
        )
    ).json()
    await worker.run_until_idle()
    approval = (await client.get(f"/api/v1/cases/{case_id}/approvals")).json()[0]
    provider = (
        await client.post(
            "/api/v1/providers",
            json={"name": "Mine", "kind": "mock", "model": "nexscout-mock-1"},
        )
    ).json()
    await client.post(f"/api/v1/cases/{case_id}/opportunities/{opp['id']}/research")
    gen = await client.post(
        f"/api/v1/cases/{case_id}/generated-documents", json={"doc_type": "academic_cv"}
    )
    assert gen.status_code == 202, gen.text
    await worker.run_until_idle()
    gen_doc = (await client.get(f"/api/v1/cases/{case_id}/generated-documents")).json()[0]
    application = (
        await client.post(
            f"/api/v1/cases/{case_id}/applications",
            json={"opportunity_id": opp["id"], "document_ids": [gen_doc["id"]]},
        )
    ).json()
    app_event = (await client.get(f"/api/v1/applications/{application['id']}")).json()["events"][0]
    reminder = (
        await client.post(
            f"/api/v1/cases/{case_id}/reminders", json={"title": "Mine", "due_on": "2026-01-01"}
        )
    ).json()
    await worker.maintenance_once()  # notifications for the pending approval and the reminder
    note = (await client.get("/api/v1/notifications")).json()["items"][0]
    token = (await client.post("/api/v1/me/tokens", json={"name": "mine"})).json()
    channel = (
        await client.post(
            "/api/v1/channels",
            json={"kind": "webhook", "name": "Mine", "secrets": {"url": "http://127.0.0.1:9/h"}},
        )
    ).json()["channel"]
    answer = (
        await client.post(
            f"/api/v1/cases/{case_id}/answers", json={"question": "Salary?", "answer": "Mine"}
        )
    ).json()
    return {
        "answer_id": answer["id"],
        "channel_id": channel["id"],
        "token_id": token["id"],
        "reminder_id": reminder["id"],
        "notification_id": note["id"],
        "application_id": application["id"],
        "app_event_id": app_event["id"],
        "app_version": str(application["version"]),
        "gen_document_id": gen_doc["id"],
        "version_number": "1",
        "fmt": "pdf",
        "provider_id": provider["id"],
        "run_id": run["id"],
        "approval_id": approval["id"],
        "case_id": case_id,
        "document_id": doc["id"],
        "fact_id": fact["id"],
        "link_id": link["id"],
        "affiliation_id": aff["id"],
        "opportunity_id": opp["id"],
        "node_key": f"fact:{fact['id']}",
        "fact_version": str(fact["version"]),
        "aff_version": str(aff["version"]),
        "opp_version": str(opp["match_version"]),
    }


def _requests(ids: dict[str, str]) -> list[tuple[str, str, dict[str, Any] | None]]:
    r, apr, pv = ids["run_id"], ids["approval_id"], ids["provider_id"]
    ch = ids["channel_id"]
    c, d, f, link, a, o, n = (
        ids["case_id"],
        ids["document_id"],
        ids["fact_id"],
        ids["link_id"],
        ids["affiliation_id"],
        ids["opportunity_id"],
        ids["node_key"],
    )
    g, vn, fmt = ids["gen_document_id"], ids["version_number"], ids["fmt"]
    ap, ev, av = ids["application_id"], ids["app_event_id"], int(ids["app_version"])
    rem, note = ids["reminder_id"], ids["notification_id"]
    return [
        ("DELETE", f"/api/v1/me/tokens/{ids['token_id']}", None),
        ("POST", f"/api/v1/notifications/{note}/read", None),
        ("GET", f"/api/v1/cases/{c}/reminders", None),
        ("POST", f"/api/v1/cases/{c}/reminders", {"title": "x", "due_on": "2026-01-01"}),
        ("PATCH", f"/api/v1/reminders/{rem}", {"done": True}),
        ("DELETE", f"/api/v1/reminders/{rem}", None),
        ("GET", f"/api/v1/cases/{c}/dashboard", None),
        ("GET", f"/api/v1/cases/{c}/chat", None),
        ("POST", f"/api/v1/cases/{c}/chat", {"message": "what needs me?"}),
        (
            "POST",
            f"/api/v1/cases/{c}/applications/bulk-status",
            {"ids": [ap], "status": "cancelled"},
        ),
        ("GET", f"/api/v1/cases/{c}/applications/export.csv", None),
        ("POST", f"/api/v1/cases/{c}/applications", {"opportunity_id": o, "document_ids": []}),
        ("GET", f"/api/v1/cases/{c}/applications", None),
        ("GET", f"/api/v1/applications/{ap}", None),
        ("PATCH", f"/api/v1/applications/{ap}", {"version": av, "notes": "pwned"}),
        ("POST", f"/api/v1/applications/{ap}/status", {"version": av, "status": "withdrawn"}),
        ("POST", f"/api/v1/applications/{ap}/resolve", {"submitted": True}),
        ("POST", f"/api/v1/applications/{ap}/browser", None),
        ("GET", f"/api/v1/applications/{ap}/events/{ev}/screenshot", None),
        ("GET", f"/api/v1/cases/{c}/opportunities/{o}/research", None),
        ("GET", f"/api/v1/cases/{c}/opportunities/{o}/referrals", None),
        ("GET", f"/api/v1/cases/{c}/opportunities/{o}/document-format", None),
        ("POST", f"/api/v1/cases/{c}/opportunities/{o}/research", None),
        ("POST", f"/api/v1/cases/{c}/generated-documents", {"doc_type": "academic_cv"}),
        ("GET", f"/api/v1/cases/{c}/generated-documents", None),
        ("GET", f"/api/v1/generated-documents/{g}", None),
        ("GET", f"/api/v1/generated-documents/{g}/versions/{vn}", None),
        ("POST", f"/api/v1/generated-documents/{g}/versions", {"markdown": "x", "base_version": 1}),
        ("POST", f"/api/v1/generated-documents/{g}/render", {}),
        ("GET", f"/api/v1/generated-documents/{g}/versions/{vn}/files/{fmt}", None),
        ("DELETE", f"/api/v1/generated-documents/{g}", None),
        ("GET", f"/api/v1/cases/{c}", None),
        ("PATCH", f"/api/v1/cases/{c}", {"version": 1, "name": "pwned"}),
        ("DELETE", f"/api/v1/cases/{c}", None),
        ("GET", f"/api/v1/cases/{c}/facts", None),
        ("POST", f"/api/v1/cases/{c}/facts", {"section": "skill", "data": {"name": "x"}}),
        ("POST", f"/api/v1/cases/{c}/facts/review", {"accept": [f]}),
        ("POST", f"/api/v1/cases/{c}/facts/merge", {"keep_id": f, "merge_ids": [f]}),
        ("GET", f"/api/v1/cases/{c}/profile/gaps", None),
        ("POST", f"/api/v1/cases/{c}/snapshots", {}),
        ("GET", f"/api/v1/cases/{c}/snapshots", None),
        ("GET", f"/api/v1/cases/{c}/snapshots/compare?from_number=1&to_number=2", None),
        ("GET", f"/api/v1/facts/{f}", None),
        ("PATCH", f"/api/v1/facts/{f}", {"version": int(ids["fact_version"]), "is_private": True}),
        ("DELETE", f"/api/v1/facts/{f}", None),
        ("GET", f"/api/v1/facts/{f}/evidence", None),
        ("GET", f"/api/v1/cases/{c}/documents", None),
        ("POST", f"/api/v1/cases/{c}/documents", None),  # multipart handled separately
        ("GET", f"/api/v1/documents/{d}", None),
        ("GET", f"/api/v1/documents/{d}/text", None),
        ("GET", f"/api/v1/documents/{d}/content", None),
        ("DELETE", f"/api/v1/documents/{d}", None),
        ("GET", f"/api/v1/cases/{c}/preferences", None),
        ("PUT", f"/api/v1/cases/{c}/preferences", {"version": 0, "data": {}}),
        ("GET", f"/api/v1/cases/{c}/social-profiles", None),
        ("POST", f"/api/v1/cases/{c}/social-profiles", {"url": "https://example.com"}),
        ("DELETE", f"/api/v1/social-profiles/{link}", None),
        ("GET", f"/api/v1/cases/{c}/affiliations", None),
        (
            "POST",
            f"/api/v1/cases/{c}/affiliations",
            {"organization": "X", "relationship_type": "alumnus"},
        ),
        (
            "PATCH",
            f"/api/v1/affiliations/{a}",
            {"version": int(ids["aff_version"]), "notes": "pwned"},
        ),
        ("DELETE", f"/api/v1/affiliations/{a}", None),
        ("GET", f"/api/v1/cases/{c}/mindmap", None),
        ("PUT", f"/api/v1/cases/{c}/mindmap/nodes/{n}", {"hidden": True}),
        ("DELETE", f"/api/v1/cases/{c}/mindmap/nodes/{n}", None),
        ("DELETE", f"/api/v1/cases/{c}/mindmap/overrides", None),
        ("POST", f"/api/v1/cases/{c}/opportunities/sync", {}),
        ("POST", f"/api/v1/cases/{c}/opportunities/rescore", None),
        ("GET", f"/api/v1/cases/{c}/opportunities", None),
        ("GET", f"/api/v1/cases/{c}/opportunities/{o}", None),
        (
            "PATCH",
            f"/api/v1/cases/{c}/opportunities/{o}",
            {"status": "dismissed", "version": int(ids.get("opp_version", "1"))},
        ),
        ("POST", f"/api/v1/cases/{c}/opportunities/{o}/reports", {"kind": "wrong_merge"}),
        ("POST", f"/api/v1/cases/{c}/runs", {"kind": "system_check"}),
        ("GET", f"/api/v1/cases/{c}/runs", None),
        ("GET", f"/api/v1/runs/{r}", None),
        ("POST", f"/api/v1/runs/{r}/control", {"action": "cancel"}),
        ("GET", f"/api/v1/cases/{c}/approvals", None),
        ("GET", f"/api/v1/approvals/{apr}", None),
        ("POST", f"/api/v1/approvals/{apr}/decision", {"approve": True}),
        ("PATCH", f"/api/v1/channels/{ch}", {"version": 1, "paused": True}),
        ("POST", f"/api/v1/channels/{ch}/pair", {"code": "ABCDEF12"}),
        ("POST", f"/api/v1/channels/{ch}/test", None),
        ("GET", f"/api/v1/channels/{ch}/deliveries", None),
        ("DELETE", f"/api/v1/channels/{ch}", None),
        ("GET", f"/api/v1/cases/{c}/autopilot", None),
        ("PUT", f"/api/v1/cases/{c}/autopilot", {"version": 0, "enabled": True}),
        ("POST", f"/api/v1/cases/{c}/autopilot/run", None),
        ("GET", f"/api/v1/cases/{c}/answers", None),
        ("POST", f"/api/v1/cases/{c}/answers", {"question": "q", "answer": "a"}),
        ("DELETE", f"/api/v1/answers/{ids['answer_id']}", None),
        ("POST", f"/api/v1/notifications/{note}/answer", {"answer": "x"}),
        ("POST", f"/api/v1/applications/{ap}/assist", None),
        ("GET", f"/api/v1/cases/{c}/events?once=true", None),
        ("POST", f"/api/v1/providers/{pv}/verify", None),
        ("DELETE", f"/api/v1/providers/{pv}", None),
    ]


async def test_other_user_gets_404_everywhere(
    client: httpx.AsyncClient, other_client: httpx.AsyncClient, worker: Any
) -> None:
    ids = await _seed_owner(client, worker)
    await register(other_client, "intruder@example.com", "Intruder")
    for method, url, body in _requests(ids):
        if method == "POST" and url.endswith("/documents"):
            resp = await upload(other_client, ids["case_id"], b"hello")
        else:
            resp = await other_client.request(method, url, json=body)
        assert resp.status_code == 404, f"{method} {url} -> {resp.status_code}: {resp.text}"
    # Owner's data is intact afterwards.
    assert (await client.get(f"/api/v1/cases/{ids['case_id']}")).json()["name"] == "Owner case"
    assert (await client.get(f"/api/v1/documents/{ids['document_id']}/content")).status_code == 200
    assert (await client.get(f"/api/v1/facts/{ids['fact_id']}")).json()["is_private"] is False
    opp = (
        await client.get(f"/api/v1/cases/{ids['case_id']}/opportunities/{ids['opportunity_id']}")
    ).json()
    assert opp["match_status"] == "new"
    run = (await client.get(f"/api/v1/runs/{ids['run_id']}")).json()
    assert run["run"]["status"] == "waiting_approval"  # intruder could not cancel or approve
    assert run["approvals"][0]["status"] == "pending"
    assert [p["name"] for p in (await client.get("/api/v1/providers")).json()] == ["Mine"]
    assert [t["revoked"] for t in (await client.get("/api/v1/me/tokens")).json()] == [False]
    chans = (await client.get("/api/v1/channels")).json()
    assert [(c["name"], c["status"]) for c in chans] == [("Mine", "active")]
    bank = (await client.get(f"/api/v1/cases/{ids['case_id']}/answers")).json()
    assert [(a["question"], a["answer"]) for a in bank] == [("Salary?", "Mine")]
    pilot = (await client.get(f"/api/v1/cases/{ids['case_id']}/autopilot")).json()
    assert pilot["policy"]["enabled"] is False
    notes = (await client.get("/api/v1/notifications")).json()
    assert notes["unread"] >= 1  # intruder could not mark them read
    rems = (await client.get(f"/api/v1/cases/{ids['case_id']}/reminders")).json()
    assert [r["done"] for r in rems if r["title"] == "Mine"] == [False]
    owned = (await client.get(f"/api/v1/applications/{ids['application_id']}")).json()
    assert owned["status"] == "preparing"
    assert owned["notes"] is None
    gen = (await client.get(f"/api/v1/generated-documents/{ids['gen_document_id']}")).json()
    assert gen["current_version"] == 1  # intruder could not edit or delete it
    pdf = await client.get(
        f"/api/v1/generated-documents/{ids['gen_document_id']}/versions/1/files/pdf"
    )
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")


def _template(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path.split("?")[0])


def test_every_id_route_is_covered(app: Any) -> None:
    """Guard: every route with a path parameter is either swept above or explicitly exempt."""
    sentinel = {
        k: f"{{{k}}}"
        for k in (
            "run_id",
            "approval_id",
            "provider_id",
            "case_id",
            "document_id",
            "fact_id",
            "link_id",
            "affiliation_id",
            "opportunity_id",
            "node_key",
            "gen_document_id",
            "application_id",
            "app_event_id",
            "reminder_id",
            "notification_id",
            "token_id",
            "channel_id",
            "answer_id",
        )
    }
    sentinel["app_version"] = "1"
    sentinel.update({"version_number": "{number}", "fmt": "{fmt}"})
    sentinel.update({"fact_version": "1", "aff_version": "1", "opp_version": "1"})
    covered = {(m, _template(u)) for m, u, _ in _requests(sentinel)}
    exempt = {(m, _template(p)) for m, p in EXEMPT}
    paths = app.openapi()["paths"]
    checked = 0
    missing = []
    for path, ops in paths.items():
        if "{" not in path:
            continue
        for method in ops:
            key = (method.upper(), _template(path))
            checked += 1
            if key not in covered and key not in exempt:
                missing.append(f"{method.upper()} {path}")
    assert checked >= 20, f"Route enumeration looks broken (only {checked} ID routes found)"
    assert missing == [], f"Add these routes to the IDOR sweep: {missing}"


def test_all_owned_tables_have_forced_rls(migrated_db: Engine) -> None:
    with migrated_db.connect() as conn:
        for table in OWNED_TABLES:
            row = conn.execute(
                text(
                    "SELECT c.relrowsecurity, c.relforcerowsecurity, "
                    "(SELECT count(*) FROM pg_policies p WHERE p.tablename = c.relname) "
                    "FROM pg_class c WHERE c.relname = :t"
                ),
                {"t": table},
            ).one()
            assert tuple(row) == (True, True, 1), f"{table}: {tuple(row)}"
