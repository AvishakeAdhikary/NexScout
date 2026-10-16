"""Alembic environment. Runs migrations synchronously as the schema-owner role."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from nexscout.config import get_settings
from nexscout.infrastructure.db import models  # noqa: F401  (register tables on metadata)
from nexscout.infrastructure.db.base import Base
from nexscout.infrastructure.db.migrations import include_object

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    url = config.attributes.get("database_url")
    if url:
        return str(url)
    return get_settings().migration_database_url.get_secret_value()


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
