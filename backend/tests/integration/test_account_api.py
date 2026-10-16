import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.fixtures.documents import ada_cv_text
from tests.helpers import DEFAULT_PASSWORD, create_case, register, upload

pytestmark = pytest.mark.db


async def test_export_contains_data_and_original_files(client: httpx.AsyncClient) -> None:
    await register(client)
    case_id = (await create_case(client))["id"]
    await upload(client, case_id, ada_cv_text().encode(), "ada.md")
    resp = await client.get("/api/v1/me/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        data = json.loads(zf.read("data.json"))
        names = zf.namelist()
    assert data["user"]["email"] == "ada@example.com"
    assert len(data["cases"]) == 1
    assert len(data["profile_facts"]) > 10
    assert "password_hash" not in json.dumps(data)
    assert any(n.endswith("/ada.md") for n in names)


async def test_account_deletion_removes_everything(
    client: httpx.AsyncClient, clean_db: Engine, storage_dir: Path
) -> None:
    await register(client)
    case_id = (await create_case(client))["id"]
    await upload(client, case_id, ada_cv_text().encode(), "ada.md")

    wrong = await client.post("/api/v1/me/delete", json={"password": "not my password"})
    assert wrong.status_code == 401
    resp = await client.post("/api/v1/me/delete", json={"password": DEFAULT_PASSWORD})
    assert resp.status_code == 204
    assert (await client.get("/api/v1/auth/me")).status_code == 401

    with clean_db.connect() as conn:
        for table in (
            "users",
            "candidate_cases",
            "documents",
            "profile_facts",
            "fact_evidence",
            "sessions",
        ):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0, table  # noqa: S608
        # The deletion itself is audited, without keeping a link to the deleted user row.
        assert (
            conn.execute(
                text("SELECT count(*) FROM audit_events WHERE action='account.deleted'")
            ).scalar()
            == 1
        )
    assert not any(p.is_file() for p in storage_dir.rglob("*"))
