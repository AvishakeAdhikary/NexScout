"""Shared helpers for Alembic migrations: RLS owner policies and app-role grants (ADR-0003)."""

from __future__ import annotations

from alembic import op

APP_ROLE = "nexscout_app"
CURRENT_USER_EXPR = "NULLIF(current_setting('app.user_id', true), '')::uuid"


def enable_owner_rls(table: str, owner_column: str = "owner_user_id") -> None:
    """Rows are visible/writable only when owner matches the transaction's app.user_id."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_owner_isolation ON {table} "
        f"USING ({owner_column} = {CURRENT_USER_EXPR}) "
        f"WITH CHECK ({owner_column} = {CURRENT_USER_EXPR})"
    )


def disable_owner_rls(table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS {table}_owner_isolation ON {table}")
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def grant_app(table: str, privileges: str = "SELECT, INSERT, UPDATE, DELETE") -> None:
    """Grant only if the app role exists, so migrations still run on bare databases."""
    op.execute(
        f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') "
        f"THEN EXECUTE 'GRANT {privileges} ON {table} TO {APP_ROLE}'; END IF; END $$"
    )
