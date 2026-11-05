"""Alembic environment: DATABASE_URL env var (or alembic.ini) as target.

PostgreSQL is the production target; the sqlite default exists so the
migrations can be exercised locally without a server.
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, pool

from data.db import models  # noqa: F401 - imported for metadata registration
from data.db.engine import Base

config = context.config


def _database_url() -> str:
    return (
        os.environ.get("DATABASE_URL")
        or config.get_main_option("sqlalchemy.url")
        or "sqlite:///data/processed/gmdb.db"
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
