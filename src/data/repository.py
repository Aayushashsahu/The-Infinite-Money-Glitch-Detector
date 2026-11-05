"""Persistence layer: idempotent, revision-preserving observation store.

Semantics (the heart of Phase 2):

- **Idempotency**: re-running ingestion with identical data inserts
  nothing (counted as ``duplicates_skipped``). No error, no change.
- **Revision preservation**: the same natural key re-appearing with a
  *different* value inserts a NEW row (``revision = latest + 1``) and is
  flagged as a revision change; the original row is never overwritten
  or deleted.
- **Synthetic separation**: rows store ``is_synthetic``; loading helpers
  exclude them by default so synthetic test data can never contaminate
  real history.
- **Point-in-time access**: :meth:`Repository.point_in_time` returns
  only what was published at/before ``as_of``. When ``publication_date``
  is unknown the default is to EXCLUDE the observation (conservative
  look-ahead-bias stance); callers may relax that explicitly.

No dialect-specific SQL: PostgreSQL (production target) and SQLite
(tests/demos) both work through the same ORM operations.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from data.db.models import Base, RawRecord
from data.db.models import DataObservation as ObsRow
from data.db.models import DataSource, EconomicIndicator, IngestionRun
from data.db.models import Country, Currency, CurrencyPairTable
from data.schemas import DataObservation as ObsSchema
from data.schemas import CountryInfo, CurrencyPairInfo, IndicatorInfo, ObservationKind, QualityFlag, RawRecordInfo

_VALUE_TOLERANCE = 1e-12  # relative tolerance for "same value" comparisons


@dataclass
class InsertStats:
    """Outcome of inserting a batch of observations."""

    inserted: int = 0
    duplicates_skipped: int = 0
    revisions_added: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return len(self.errors)


class Repository:
    """Catalog maintenance + idempotent observation persistence."""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    # ---------------------- catalog ensure methods ------------------------

    def ensure_source(self, source_id: str, name: str, **details: Any) -> None:
        with self._session() as session:
            if not session.get(DataSource, source_id):
                session.add(DataSource(source_id=source_id, name=name, **details))
            session.commit()

    def ensure_source_info(self, source: Any) -> None:
        """Register a :class:`data.schemas.SourceInfo` (idempotent)."""
        self.ensure_source(
            source.source_id,
            source.name,
            base_url=source.base_url,
            license=source.license,
            notes=source.notes,
        )

    def ensure_indicator(self, source_id: str, indicator_id: str, name: str, unit: str, frequency: str) -> None:
        with self._session() as session:
            stmt = select(EconomicIndicator).where(
                EconomicIndicator.source_id == source_id,
                EconomicIndicator.indicator_id == indicator_id,
            )
            if session.scalars(stmt).first() is None:
                session.add(
                    EconomicIndicator(
                        source_id=source_id,
                        indicator_id=indicator_id,
                        name=name,
                        unit=unit,
                        frequency=frequency,
                    )
                )
            session.commit()

    def ensure_currency(self, code: str, name: str | None = None) -> None:
        with self._session() as session:
            if not session.get(Currency, code):
                session.add(Currency(code=code, name=name))
            session.commit()

    def ensure_pair(self, base: str, quote: str) -> str:
        """Register a pair and its currencies; returns the canonical code."""
        pair = f"{base}/{quote}"
        with self._session() as session:
            for code, name in ((base, None), (quote, None)):
                if not session.get(Currency, code):
                    session.add(Currency(code=code, name=name))
            if not session.get(CurrencyPairTable, pair):
                session.add(CurrencyPairTable(pair_code=pair, base_code=base, quote_code=quote))
            session.commit()
        return pair

    def ensure_country(self, iso3: str, name: str, currency_code: str | None = None) -> None:
        with self._session() as session:
            existing = session.get(Country, iso3)
            if existing is None:
                session.add(Country(iso3=iso3, name=name, currency_code=currency_code))
            elif existing.name != name:
                existing.name = name  # reference metadata updates are explicit and logged by caller
            session.commit()

    def ensure_catalog(
        self,
        indicators: list[IndicatorInfo] | None = None,
        countries: list[CountryInfo] | None = None,
        pairs: list[CurrencyPairInfo] | None = None,
    ) -> None:
        """Register catalog entities before observation insertion (idempotent)."""
        for ind in indicators or []:
            self.ensure_indicator(ind.source_id, ind.indicator_id, ind.name, ind.unit, ind.frequency.value)
        for c in countries or []:
            self.ensure_country(c.iso3, c.name, c.currency_code)
        for p in pairs or []:
            self.ensure_pair(p.base_code, p.quote_code)

    # ---------------------- observations -----------------------------------

    def insert_observations(self, observations: list[ObsSchema]) -> InsertStats:
        """Insert observations with idempotent, revision-aware semantics.

        Same natural key + same value + same publication date => duplicate,
        skipped. Same key with a different (or newer-revision) value => new
        revision row; history is preserved. Row-level failures are caught,
        counted, and reported without aborting the whole batch.
        """
        stats = InsertStats()
        with self._session() as session:
            for obs in observations:
                try:
                    with session.begin_nested():  # savepoint isolates row errors
                        existing = session.scalars(
                            select(ObsRow)
                            .where(
                                ObsRow.kind == obs.kind.value,
                                ObsRow.source_id == obs.source_id,
                                ObsRow.entity_code == obs.entity_code,
                                ObsRow.indicator_id == obs.indicator_id,
                                ObsRow.frequency == obs.frequency.value,
                                ObsRow.observation_date == obs.observation_date,
                            )
                            .order_by(ObsRow.revision.desc())
                            .limit(1)
                        ).first()

                        if existing is None:
                            session.add(_to_row(obs))
                            session.flush()  # visible to the next row's duplicate check
                            stats.inserted += 1
                            continue

                        if obs.revision < existing.revision:
                            stats.duplicates_skipped += 1  # stale replay of an older revision
                            continue

                        same_value = abs(obs.value - existing.value) <= _VALUE_TOLERANCE * max(
                            1.0, abs(existing.value)
                        )
                        same_pub = obs.publication_date == existing.publication_date
                        if obs.revision == existing.revision and same_value and same_pub:
                            stats.duplicates_skipped += 1
                            continue

                        flags = [f for f in obs.quality_flags]
                        if QualityFlag.REVISION_CHANGE not in flags:
                            flags.append(QualityFlag.REVISION_CHANGE)
                        session.add(
                            _to_row(
                                obs.model_copy(
                                    update={
                                        "revision": existing.revision + 1,
                                        "quality_flags": flags,
                                    }
                                )
                            )
                        )
                        session.flush()  # visible to the next row's duplicate check
                        stats.revisions_added += 1
                except IntegrityError as exc:
                    stats.errors.append(f"{_obs_label(obs)}: {exc.orig}")
                except SQLAlchemyError as exc:
                    stats.errors.append(f"{_obs_label(obs)}: {exc}")
            session.commit()
        return stats

    # ---------------------- retrieval --------------------------------------

    def load_observations(
        self,
        kind: ObservationKind | None = None,
        entity_code: str | None = None,
        indicator_id: str | None = None,
        source_id: str | None = None,
        include_synthetic: bool = False,
    ) -> pd.DataFrame:
        """Load observations into a tidy DataFrame (synthetic excluded by default)."""
        query = select(ObsRow)
        if kind is not None:
            query = query.where(ObsRow.kind == kind.value)
        if entity_code is not None:
            query = query.where(ObsRow.entity_code == entity_code)
        if indicator_id is not None:
            query = query.where(ObsRow.indicator_id == indicator_id)
        if source_id is not None:
            query = query.where(ObsRow.source_id == source_id)
        if not include_synthetic:
            query = query.where(ObsRow.is_synthetic == False)  # noqa: E712 (explicit boolean filter)
        with self._session() as session:
            rows = session.scalars(query).all()
        frame = pd.DataFrame(
            [
                {
                    "kind": r.kind,
                    "source_id": r.source_id,
                    "indicator_id": r.indicator_id,
                    "entity_code": r.entity_code,
                    "value": r.value,
                    "unit": r.unit,
                    "frequency": r.frequency,
                    "observation_date": r.observation_date,
                    "publication_date": r.publication_date,
                    "observation_timestamp": r.observation_timestamp,
                    "publication_timestamp": r.publication_timestamp,
                    "effective_timestamp": r.effective_timestamp,
                    "retrieved_at": r.retrieved_at,
                    "revision": r.revision,
                    "is_synthetic": r.is_synthetic,
                    "classification": getattr(r, "classification", "real_verified"),
                    "availability_evidence": getattr(r, "availability_evidence", None),
                    "rate_role": getattr(r, "rate_role", None),
                    "quality_flags": r.quality_flags or [],
                }
                for r in rows
            ]
        )
        if not frame.empty:
            frame = frame.sort_values(
                ["entity_code", "indicator_id", "observation_date", "revision"],
                ignore_index=True,
            )
        return frame

    def load_observation_objects(
        self,
        kind: ObservationKind | None = None,
        entity_code: str | None = None,
        indicator_id: str | None = None,
        source_id: str | None = None,
        include_synthetic: bool = False,
    ) -> list[ObsSchema]:
        """Load observations directly as Pydantic DataObservation schema objects."""
        stmt = select(ObsRow)
        if kind is not None:
            stmt = stmt.where(ObsRow.kind == kind.value)
        if entity_code is not None:
            stmt = stmt.where(ObsRow.entity_code == entity_code)
        if indicator_id is not None:
            stmt = stmt.where(ObsRow.indicator_id == indicator_id)
        if source_id is not None:
            stmt = stmt.where(ObsRow.source_id == source_id)
        if not include_synthetic:
            stmt = stmt.where(ObsRow.is_synthetic == False)  # noqa: E712

        with self._session() as session:
            rows = session.scalars(stmt).all()
            from data.schemas import (
                AvailabilityEvidence,
                DataClassification,
                Frequency,
                ObservationKind,
                QualityFlag,
                RateRole,
            )
            obs_list: list[ObsSchema] = []
            for r in rows:
                cls_str = getattr(r, "classification", "real_verified")
                try:
                    cls_enum = DataClassification(cls_str)
                except ValueError:
                    cls_enum = DataClassification.REAL_VERIFIED

                ev_str = getattr(r, "availability_evidence", None)
                ev_enum = None
                if ev_str:
                    try:
                        ev_enum = AvailabilityEvidence(ev_str)
                    except ValueError:
                        ev_enum = None

                rr_str = getattr(r, "rate_role", None)
                rr_enum = None
                if rr_str:
                    try:
                        rr_enum = RateRole(rr_str)
                    except ValueError:
                        rr_enum = None

                from data.schemas import PriceType
                pt_val = getattr(r, "price_type", None) or (r.extra_metadata or {}).get("price_type")
                pt_enum = None
                if pt_val:
                    try:
                        pt_enum = PriceType(pt_val)
                    except ValueError:
                        pt_enum = None

                obs_list.append(
                    ObsSchema(
                        kind=ObservationKind(r.kind),
                        source_id=r.source_id,
                        indicator_id=r.indicator_id,
                        entity_code=r.entity_code,
                        value=r.value,
                        unit=r.unit,
                        frequency=Frequency(r.frequency),
                        observation_date=r.observation_date,
                        publication_date=r.publication_date,
                        observation_timestamp=getattr(r, "observation_timestamp", None),
                        publication_timestamp=getattr(r, "publication_timestamp", None),
                        effective_timestamp=getattr(r, "effective_timestamp", None),
                        retrieved_at=r.retrieved_at,
                        revision=r.revision,
                        is_synthetic=r.is_synthetic,
                        classification=cls_enum,
                        availability_evidence=ev_enum,
                        rate_role=rr_enum,
                        price_type=pt_enum,
                        quality_flags=[QualityFlag(f) for f in (r.quality_flags or []) if f in QualityFlag._value2member_map_],
                        metadata=r.extra_metadata,
                    )
                )
            return obs_list

    def point_in_time(
        self,
        as_of: date,
        kind: ObservationKind | None = None,
        entity_code: str | None = None,
        indicator_id: str | None = None,
        source_id: str | None = None,
        allow_unknown_publication: bool = False,
        include_synthetic: bool = False,
    ) -> pd.DataFrame:
        """Look-ahead-safe slice: only observations published by ``as_of``.

        Default policy excludes observations with unknown
        ``publication_date`` (many sources do not publish that metadata);
        ``allow_unknown_publication=True`` opts into treating them as
        available at their observation date, which the caller must justify
        per source.
        """
        frame = self.load_observations(
            kind=kind,
            entity_code=entity_code,
            indicator_id=indicator_id,
            source_id=source_id,
            include_synthetic=include_synthetic,
        )
        if frame.empty:
            return frame
        known = frame[frame["publication_date"].notna() & (frame["publication_date"] <= as_of)]
        known = known.copy()
        if allow_unknown_publication:
            unknown = frame[frame["publication_date"].isna() & (frame["observation_date"] <= as_of)]
            known = pd.concat([known, unknown], ignore_index=True)
        if known.empty:
            return known
        latest_revision = known.groupby(
            ["kind", "source_id", "entity_code", "indicator_id", "frequency", "observation_date"],
            dropna=False,
        )["revision"].max().reset_index()
        return known.merge(
            latest_revision,
            on=["kind", "source_id", "entity_code", "indicator_id", "frequency", "observation_date", "revision"],
            how="inner",
        )

    # ---------------------- raw store & runs --------------------------------

    def create_run(self, source_id: str) -> str:
        run = IngestionRun(run_id=_new_run_id(), source_id=source_id, started_at=datetime.now(timezone.utc))
        with self._session() as session:
            session.add(run)
            session.commit()
        return run.run_id

    def finish_run(self, run_id: str, status: str, notes: str | None = None) -> None:
        with self._session() as session:
            run = session.get(IngestionRun, run_id)
            if run is not None:
                run.finished_at = datetime.now(timezone.utc)
                run.status = status
                run.notes = notes
            session.commit()

    def archive_raw_records(self, run_id: str, source_id: str, records: list[RawRecordInfo]) -> int:
        """Archive raw payloads (deduplicated within the run by content hash)."""
        count = 0
        with self._session() as session:
            for rec in records:
                digest = hashlib.sha256(
                    json.dumps(rec.payload, sort_keys=True, default=str).encode("utf-8")
                ).hexdigest()
                exists = session.scalars(
                    select(RawRecord).where(
                        RawRecord.source_id == source_id,
                        RawRecord.run_id == run_id,
                        RawRecord.payload_sha256 == digest,
                    )
                ).first()
                if exists is not None:
                    continue
                session.add(
                    RawRecord(
                        source_id=source_id,
                        run_id=run_id,
                        url=rec.url,
                        payload=rec.payload,
                        payload_sha256=digest,
                        retrieved_at=rec.retrieved_at or datetime.now(timezone.utc),
                    )
                )
                session.flush()  # autoflush is off: make the row visible to the next dedup check
                count += 1
            session.commit()
        return count

    def record_run_stats(self, run_id: str, stats: InsertStats, warnings: list[str] | None = None) -> None:
        with self._session() as session:
            run = session.get(IngestionRun, run_id)
            if run is not None:
                run.observations_in = stats.inserted + stats.duplicates_skipped + stats.revisions_added
                run.observations_new = stats.inserted + stats.revisions_added
                run.duplicates_skipped = stats.duplicates_skipped
                run.revisions_added = stats.revisions_added
                run.errors_seen = stats.error_count
                run.error_log = ((stats.errors or []) + (warnings or [])) or None
            session.commit()

    def get_run(self, run_id: str) -> IngestionRun | None:
        with self._session() as session:
            return session.get(IngestionRun, run_id)

    # ---------------------- schema bootstrap ---------------------------------

    def create_all(self) -> None:
        """Create all tables (idempotent; production should use Alembic)."""
        engine = self._session_factory.kw["bind"]
        Base.metadata.create_all(engine)

    def drop_all(self) -> None:
        """Drop all tables (test/demo helper only)."""
        engine = self._session_factory.kw["bind"]
        Base.metadata.drop_all(engine)

    # ---------------------- internals ---------------------------------------

    def _session(self):
        return self._session_factory()


def _new_run_id() -> str:
    from data.db.models import new_run_id

    return new_run_id()


def _obs_label(obs: ObsSchema) -> str:
    """Natural-key label for row-level error messages (names the catalog key)."""
    indicator = obs.indicator_id or obs.entity_code
    return f"{obs.source_id}:{indicator}@{obs.observation_date}"


def _to_row(obs: ObsSchema) -> ObsRow:
    """Pydantic observation -> ORM row (explicit, no magic)."""
    meta = dict(obs.metadata) if obs.metadata else {}
    if obs.price_type:
        meta["price_type"] = obs.price_type.value

    return ObsRow(
        kind=obs.kind.value,
        source_id=obs.source_id,
        indicator_id=obs.indicator_id,
        entity_code=obs.entity_code,
        value=obs.value,
        unit=obs.unit,
        frequency=obs.frequency.value,
        observation_date=obs.observation_date,
        publication_date=obs.publication_date,
        observation_timestamp=obs.observation_timestamp,
        publication_timestamp=obs.publication_timestamp,
        effective_timestamp=obs.effective_timestamp,
        retrieved_at=obs.retrieved_at,
        revision=obs.revision,
        is_synthetic=obs.is_synthetic,
        classification=obs.classification.value if obs.classification else ("synthetic" if obs.is_synthetic else "real_verified"),
        availability_evidence=obs.availability_evidence.value if obs.availability_evidence else None,
        rate_role=obs.rate_role.value if obs.rate_role else None,
        extra_metadata=meta or None,
        quality_flags=[f.value for f in obs.quality_flags],
    )
