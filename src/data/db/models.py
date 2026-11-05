"""Canonical SQLAlchemy data model.

Design rules (Phase 2 requirements):

- raw vs normalized separation: ``raw_record`` stores payloads exactly
  as received; ``data_observation`` stores normalized rows.
- duplicate prevention: a unique constraint over the natural key.
- revision preservation: re-ingesting a *changed* value inserts a new
  revision row; originals are never overwritten or deleted.
- publication vs observation dates are distinct columns: queries must
  filter by ``publication_date`` for look-ahead-safe backtests.
- synthetic data is permanently flagged as such.

Note: the attribute name ``metadata`` collides with SQLAlchemy's
declarative Base, so the JSON column is exposed as ``extra_metadata``
(mapped to a physical column named ``metadata``).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for the whole data layer."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_run_id() -> str:
    return uuid.uuid4().hex


class DataSource(Base):
    """Registered source adapter (World Bank, IMF, ...)."""

    __tablename__ = "data_source"

    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    license: Mapped[str | None] = mapped_column(String(256), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Currency(Base):
    __tablename__ = "currency"

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)


class CurrencyPairTable(Base):
    """Registry of quoted pairs. Convention: rate = units of quote per base."""

    __tablename__ = "currency_pair"

    pair_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    base_code: Mapped[str] = mapped_column(String(3), ForeignKey("currency.code"))
    quote_code: Mapped[str] = mapped_column(String(3), ForeignKey("currency.code"))

    __table_args__ = (UniqueConstraint("base_code", "quote_code", name="uq_pair_direction"),)


class Country(Base):
    __tablename__ = "country"

    iso3: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    currency_code: Mapped[str | None] = mapped_column(String(3), ForeignKey("currency.code"), nullable=True)


class EconomicIndicator(Base):
    """Source-scoped indicator catalog (composite PK with its source)."""

    __tablename__ = "economic_indicator"

    source_id: Mapped[str] = mapped_column(String(64), ForeignKey("data_source.source_id"), primary_key=True)
    indicator_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    unit: Mapped[str] = mapped_column(String(64))
    frequency: Mapped[str] = mapped_column(String(16))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)


class IngestionRun(Base):
    """One ingestion execution. Failures are recorded, never hidden."""

    __tablename__ = "ingestion_run"

    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), ForeignKey("data_source.source_id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|ok|partial|failed
    observations_in: Mapped[int] = mapped_column(Integer, default=0)
    observations_new: Mapped[int] = mapped_column(Integer, default=0)
    duplicates_skipped: Mapped[int] = mapped_column(Integer, default=0)
    revisions_added: Mapped[int] = mapped_column(Integer, default=0)
    errors_seen: Mapped[int] = mapped_column(Integer, default=0)
    error_log: Mapped[list | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class DataObservation(Base):
    """Canonical normalized economic observation."""

    __tablename__ = "data_observation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(64))
    indicator_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    entity_code: Mapped[str] = mapped_column(String(64))
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(64))
    frequency: Mapped[str] = mapped_column(String(16))
    observation_date: Mapped[date] = mapped_column(Date)
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    classification: Mapped[str] = mapped_column(String(32), default="real_verified")
    extra_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    quality_flags: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # NOTE: no direct relationship to data_source on purpose - integrity of
    # (source_id, indicator_id) is enforced via the composite FK to the
    # indicator catalog above; a bare source_id alone may legitimately differ
    # from the catalog's source (e.g. FX style individu indicators). If a
    # plain FK to data_source is ever added, add the relationship back with
    # explicit primaryjoin.
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "indicator_id"],
            ["economic_indicator.source_id", "economic_indicator.indicator_id"],
            name="fk_obs_in_indicator_catalog",
        ),
        UniqueConstraint(
            "source_id",
            "kind",
            "entity_code",
            "indicator_id",
            "frequency",
            "observation_date",
            "revision",
            name="uq_observation_natural_key",
        ),
        Index("ix_obs_series", "kind", "entity_code", "indicator_id", "observation_date"),
        Index("ix_obs_publication", "publication_date"),
        Index("ix_obs_synthetic", "is_synthetic"),
    )


class RawRecord(Base):
    """Archived original source payload (raw store)."""

    __tablename__ = "raw_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(64), ForeignKey("data_source.source_id"))
    run_id: Mapped[str] = mapped_column(String(32), ForeignKey("ingestion_run.run_id"))
    url: Mapped[str] = mapped_column(String(1024))
    payload: Mapped[Any] = mapped_column(JSON)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("source_id", "run_id", "payload_sha256", name="uq_raw_record"),
        Index("ix_raw_run", "run_id"),
    )
