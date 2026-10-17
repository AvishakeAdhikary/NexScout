"""Upgrade path: data written at the first revisions survives every later migration, and the
whole chain downgrades to base and back. Leaves the test database at head."""

import uuid

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Engine

from nexscout.infrastructure.db.migrations import alembic_config
from tests.conftest import TEST_MIGRATION_DB_URL

pytestmark = pytest.mark.db


def test_data_survives_step_by_step_upgrades(migrated_db: Engine) -> None:
    cfg = alembic_config(TEST_MIGRATION_DB_URL)
    revisions = [
        r.revision for r in reversed(list(ScriptDirectory.from_config(cfg).walk_revisions()))
    ]
    assert revisions[0] == "0001"
    assert len(revisions) >= 8

    with migrated_db.begin() as conn:  # start from scratch
        conn.execute(text("TRUNCATE users CASCADE"))
    command.downgrade(cfg, "base")
    user, case, fact = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    try:
        for rev in revisions:
            command.upgrade(cfg, rev)
            with migrated_db.begin() as conn:
                if rev == "0001":
                    conn.execute(
                        text(
                            "INSERT INTO users (id, email, password_hash, display_name, is_active) "
                            "VALUES (:u, 'old@example.com', 'x', 'Old User', true)"
                        ),
                        {"u": user},
                    )
                    conn.execute(
                        text(
                            "INSERT INTO candidate_cases (id, owner_user_id, name, career_path, "
                            "status, version) VALUES (:c, :u, 'Old case', 'phd', 'active', 1)"
                        ),
                        {"c": case, "u": user},
                    )
                if rev == "0002":
                    conn.execute(
                        text(
                            "INSERT INTO profile_facts (id, owner_user_id, case_id, section, data, "
                            "label, status, review_state, is_private, meta, version) VALUES "
                            "(:f, :u, :c, 'skill', '{\"name\": \"Python\"}', 'Python', "
                            "'user_entered', 'accepted', false, '{}', 1)"
                        ),
                        {"f": fact, "u": user, "c": case},
                    )
                # Every revision keeps what earlier ones stored.
                assert (
                    conn.execute(
                        text("SELECT count(*) FROM users WHERE id = :u"), {"u": user}
                    ).scalar()
                    == 1
                )
                if rev >= "0002":
                    label = conn.execute(
                        text("SELECT label FROM profile_facts WHERE id = :f"), {"f": fact}
                    ).scalar()
                    assert label == "Python", rev
        with migrated_db.begin() as conn:
            head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert head == revisions[-1]
        command.downgrade(cfg, "base")
    finally:
        command.upgrade(cfg, "head")  # leave the database usable for other tests
        with migrated_db.begin() as conn:
            conn.execute(text("TRUNCATE users CASCADE"))
