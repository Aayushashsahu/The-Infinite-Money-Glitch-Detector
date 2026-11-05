"""Engine and session factory for the analytical store.

Target database is PostgreSQL (``DATABASE_URL`` env var, e.g.
``postgresql+psycopg2://user:pass@host:5432/gmdb``). SQLite is used for
the automated test suite and small local demos: both are first-class
through SQLAlchemy, and no dialect-specific SQL is used in the data
layer except for the PostgreSQL upsert optimization.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from data.db.models import Base  # noqa: F401  (re-exported)


_DEFAULT_SQLITE = "sqlite:///data/processed/gmdb.db"


def make_engine(url: str | None = None) -> Engine:
    """Create an engine from ``url`` or ``DATABASE_URL``.

    Falls back to a local SQLite file only when no DATABASE_URL is set;
    the fallback is intended for demos, never for multi-user production.
    """
    effective = url or os.environ.get("DATABASE_URL") or _DEFAULT_SQLITE
    if effective.startswith("sqlite://"):
        kwargs = {"connect_args": {"check_same_thread": False}}
        if effective == "sqlite://":
            kwargs["poolclass"] = StaticPool
        engine = create_engine(effective, **kwargs)

        @event.listens_for(engine, "connect")
        def _enable_sqlite_fk(dbapi_connection, _connection_record):  # pragma: no cover - sqlite only
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
        return engine
    return create_engine(effective, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker:
    """Session factory bound to ``engine``."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
