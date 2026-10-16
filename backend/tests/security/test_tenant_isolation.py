"""M1 acceptance: user B can't see or change user A's case (API wall + RLS wall)."""

import uuid

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from tests.conftest import TEST_DB_URL
from tests.helpers import create_case, register

pytestmark = pytest.mark.db

INSERT_CASE = "INSERT INTO candidate_cases (id, owner_user_id, name, career_path, status, version)"


async def test_api_cross_tenant_access_returns_404(
    client: httpx.AsyncClient, other_client: httpx.AsyncClient
) -> None:
    await register(client, "a@example.com", "User A")
    case = await create_case(client, "A's private case")
    await register(other_client, "b@example.com", "User B")

    url = f"/api/v1/cases/{case['id']}"
    assert (await other_client.get(url)).status_code == 404
    assert (await other_client.patch(url, json={"version": 1, "name": "pwned"})).status_code == 404
    assert (await other_client.delete(url)).status_code == 404
    assert (await other_client.get("/api/v1/cases")).json() == []

    # A's data is untouched.
    still = (await client.get(url)).json()
    assert still["name"] == "A's private case"
    assert still["version"] == 1


async def test_same_case_name_allowed_across_tenants(
    client: httpx.AsyncClient, other_client: httpx.AsyncClient
) -> None:
    await register(client, "a@example.com", "User A")
    await register(other_client, "b@example.com", "User B")
    await create_case(client, "Jobs")
    await create_case(other_client, "Jobs")


@pytest.fixture
def app_role_engine(clean_db: Engine) -> Engine:
    engine = create_engine(TEST_DB_URL)
    yield engine  # type: ignore[misc]
    engine.dispose()


def _seed_two_users_with_case(owner: Engine) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    a, b, case = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with owner.begin() as conn:
        for uid, email in ((a, "a@x.test"), (b, "b@x.test")):
            conn.execute(
                text(
                    "INSERT INTO users (id, email, password_hash, display_name, is_active) "
                    "VALUES (:id, :e, 'x', 'n', true)"
                ),
                {"id": uid, "e": email},
            )
        conn.execute(
            text(f"{INSERT_CASE} VALUES (:id, :o, 'secret', 'phd', 'active', 1)"),
            {"id": case, "o": a},
        )
    return a, b, case


def test_rls_blocks_raw_sql_for_other_tenant(clean_db: Engine, app_role_engine: Engine) -> None:
    a, b, case = _seed_two_users_with_case(clean_db)
    with app_role_engine.begin() as conn:
        # No tenant bound: nothing is visible.
        assert conn.execute(text("SELECT count(*) FROM candidate_cases")).scalar() == 0
    with app_role_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(b)})
        assert conn.execute(text("SELECT count(*) FROM candidate_cases")).scalar() == 0
        updated = conn.execute(
            text("UPDATE candidate_cases SET name='pwned' WHERE id=:id"), {"id": case}
        )
        assert updated.rowcount == 0
    with app_role_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(a)})
        assert conn.execute(text("SELECT name FROM candidate_cases")).scalar() == "secret"


def test_rls_rejects_insert_for_another_owner(clean_db: Engine, app_role_engine: Engine) -> None:
    a, b, _ = _seed_two_users_with_case(clean_db)
    with app_role_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(b)})
        planted = text(f"{INSERT_CASE} VALUES (:id, :o, 'planted', 'phd', 'active', 1)")
        with pytest.raises(Exception, match="row-level security"):
            conn.execute(planted, {"id": uuid.uuid4(), "o": a})


def test_tenant_setting_does_not_leak_across_transactions(
    clean_db: Engine, app_role_engine: Engine
) -> None:
    a, _, _ = _seed_two_users_with_case(clean_db)
    with app_role_engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(a)})
            assert conn.execute(text("SELECT count(*) FROM candidate_cases")).scalar() == 1
        with conn.begin():  # same pooled connection, new transaction
            assert conn.execute(text("SELECT count(*) FROM candidate_cases")).scalar() == 0


def test_app_role_cannot_read_audit_log(clean_db: Engine, app_role_engine: Engine) -> None:
    with pytest.raises(Exception, match="permission denied"), app_role_engine.begin() as conn:
        conn.execute(text("SELECT * FROM audit_events"))
