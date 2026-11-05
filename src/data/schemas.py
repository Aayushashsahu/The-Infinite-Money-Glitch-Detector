"""Canonical data contracts for Phase 2 (Pydantic).

These schemas are the single source of truth for what enters the
database. Every observation carries BOTH an observation date and a
publication date (when the source provides one). The distinction is
mandatory: historical backtests must only see data that was published
by the simulated decision date.

Synthetic data (generated for tests and demos) is permanently marked
with ``is_synthetic=True`` and can never be confused with real history.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SOURCE_ID = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_INDICATOR_ID = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")
_ENTITY_CODE = re.compile(r"^[A-Za-z0-9_/\-:.]{1,64}$")


class ObservationKind(str, Enum):
    """What kind of economic fact an observation represents."""

    MACRO_INDICATOR = "macro_indicator"
    EXCHANGE_RATE = "exchange_rate"
    INTEREST_RATE = "interest_rate"


class Frequency(str, Enum):
    """Data frequency. Never mix frequencies within one series key."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class QualityFlag(str, Enum):
    """Quality-engine flags. Flags never destroy data: questionable
    observations keep their original source values, flagged for review."""

    MISSING_VALUE = "missing_value"
    DUPLICATE_IN_BATCH = "duplicate_in_batch"
    INVALID_CURRENCY = "invalid_currency"
    NEGATIVE_RATE = "negative_rate"
    SUSPICIOUS_JUMP = "suspicious_jump"
    FUTURE_DATE = "future_date"
    ORDER_INCONSISTENT = "order_inconsistent"
    FREQUENCY_INCONSISTENT = "frequency_inconsistent"
    UNIT_MISMATCH = "unit_mismatch"
    OUTLIER_SUSPECT = "outlier_suspect"
    REVISION_CHANGE = "revision_change"


class DataClassification(str, Enum):
    """Classification of data provenance and historical verification level."""

    REAL_VERIFIED = "real_verified"
    REAL_ESTIMATED_AVAILABILITY = "real_estimated_availability"
    REAL_RETROSPECTIVE = "real_retrospective"
    SYNTHETIC = "synthetic"
    MOCK = "mock"



class AvailabilityEvidence(str, Enum):
    """Evidence category for observation point-in-time availability."""

    EXACT_TIMESTAMP_VERIFIED = "exact_timestamp_verified"
    ESTIMATED_SCHEDULE = "estimated_schedule"
    UNVERIFIED_SAME_DAY = "unverified_same_day"
    RETROSPECTIVE = "retrospective"


class RateRole(str, Enum):
    """Economic role and instrument classification of an interest rate."""

    POLICY_RATE = "policy_rate"
    BORROWING_RATE = "borrowing_rate"
    DEPOSIT_RATE = "deposit_rate"
    RISK_FREE_RATE = "risk_free_rate"
    INVESTMENT_RETURN = "investment_return"


class StrategyExecutabilityStatus(str, Enum):
    """Executability and research validity status of a backtested strategy."""

    EXECUTABLE_VALIDATED = "EXECUTABLE_VALIDATED"
    RESEARCH_PROXY = "RESEARCH_PROXY"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    UNEXECUTABLE = "UNEXECUTABLE"
    NO_TRADES = "NO_TRADES"


class SourceInfo(BaseModel):
    """A data-source adapter's identity and presentation metadata."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(description="Stable identifier, e.g. 'world_bank'.")
    name: str
    base_url: str | None = None
    license: str | None = None
    notes: str | None = None

    @field_validator("source_id")
    @classmethod
    def _valid_source_id(cls, v: str) -> str:
        if not _SOURCE_ID.match(v):
            raise ValueError(f"Invalid source_id: {v!r} (expected lowercase slug, e.g. 'world_bank').")
        return v


class CurrencyInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(max_length=3)
    name: str | None = None

    @field_validator("code")
    @classmethod
    def _valid_code(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Za-z]{3}", v):
            raise ValueError(f"Invalid currency code: {v!r} (expected 3 letters).")
        return v.upper()


class CountryInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    iso3: str = Field(max_length=3)
    name: str
    currency_code: str | None = None

    @field_validator("iso3")
    @classmethod
    def _valid_iso3(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Za-z]{3}", v):
            raise ValueError(f"Invalid ISO3 country code: {v!r}.")
        return v.upper()


class CurrencyPairInfo(BaseModel):
    """A quoted currency pair.

    Convention (must be uniform across the whole platform):
    ``pair_code = '{BASE}/{QUOTE}'`` and the observed rate is *units of
    QUOTE per one unit of BASE*.
    """

    model_config = ConfigDict(extra="forbid")

    pair_code: str
    base_code: str
    quote_code: str

    @property
    def convention_sign(self) -> str:
        return f"units of {self.quote_code} per 1 {self.base_code}"


class IndicatorInfo(BaseModel):
    """Source-scoped indicator catalog entry (e.g. World Bank series)."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    indicator_id: str = Field(description="Source-native series code, e.g. 'FP.CPI.TOTL.ZG'.")
    name: str
    unit: str = Field(description="Measured unit, e.g. 'percent', 'index', 'rate'.")
    frequency: Frequency
    description: str | None = None
    category: str | None = None

    @field_validator("indicator_id")
    @classmethod
    def _valid_indicator_id(cls, v: str) -> str:
        if not _INDICATOR_ID.match(v):
            raise ValueError(f"Invalid indicator_id: {v!r}.")
        return v


class RawRecordInfo(BaseModel):
    """An archived original source payload (raw store, pre-normalization)."""

    model_config = ConfigDict(extra="forbid")

    url: str
    payload: Any = Field(description="Original JSON/CSV text exactly as received.")
    retrieved_at: datetime | None = None


class FetchResult(BaseModel):
    """What an adapter returns: normalized observations plus the raw
    payloads they were derived from, plus honest warnings (never silent)."""

    model_config = ConfigDict(extra="forbid")

    observations: list["DataObservation"] = Field(default_factory=list)
    raw_records: list[RawRecordInfo] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DataObservation(BaseModel):
    """One validated economic observation.

    Invariants:
    - ``publication_date`` (when known) is never before
      ``observation_date``.
    - ``value`` is a finite number; missing data is NOT encoded as NaN.
    - synthetic test data is permanently labeled ``is_synthetic=True``.
    """

    model_config = ConfigDict(extra="forbid")

    kind: ObservationKind
    source_id: str
    indicator_id: str | None = None
    entity_code: str = Field(description="ISO3 country, currency pair code, or bank/series identifier.")
    value: float
    unit: str
    frequency: Frequency
    observation_date: date
    publication_date: date | None = None
    observation_timestamp: datetime | None = None
    publication_timestamp: datetime | None = None
    effective_timestamp: datetime | None = None
    retrieved_at: datetime
    revision: int = Field(default=0, ge=0)
    is_synthetic: bool = False
    classification: DataClassification | None = None
    availability_evidence: AvailabilityEvidence | None = None
    rate_role: RateRole | None = None
    metadata: dict[str, Any] | None = None
    quality_flags: list[QualityFlag] = Field(default_factory=list)

    @field_validator(
        "observation_timestamp",
        "publication_timestamp",
        "effective_timestamp",
        "retrieved_at",
        mode="before",
    )
    @classmethod
    def _ensure_utc_datetime(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str):
            v = datetime.fromisoformat(v)
        if isinstance(v, datetime):
            if v.tzinfo is None:
                return v.replace(tzinfo=timezone.utc)
            return v.astimezone(timezone.utc)
        return v

    @field_validator("source_id")
    @classmethod
    def _valid_source_id(cls, v: str) -> str:
        if not _SOURCE_ID.match(v):
            raise ValueError(f"Invalid source_id: {v!r}.")
        return v

    @field_validator("entity_code")
    @classmethod
    def _valid_entity(cls, v: str) -> str:
        if not _ENTITY_CODE.match(v):
            raise ValueError(f"Invalid entity_code: {v!r}.")
        return v

    @field_validator("indicator_id")
    @classmethod
    def _valid_indicator(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not _INDICATOR_ID.match(v):
            raise ValueError(f"Invalid indicator_id: {v!r}.")
        return v

    @field_validator("value")
    @classmethod
    def _finite_value(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError(f"Observation value must be finite, got {v!r}. Missing data is never encoded as NaN.")
        return v

    @model_validator(mode="after")
    def _validate_observation_invariants(self) -> "DataObservation":
        if self.publication_date is not None and self.publication_date < self.observation_date:
            raise ValueError(
                f"publication_date {self.publication_date} is before observation_date "
                f"{self.observation_date}; impossible for the same source revision."
            )
        if self.publication_timestamp is not None and self.observation_timestamp is not None:
            if self.publication_timestamp < self.observation_timestamp:
                raise ValueError(
                    f"publication_timestamp {self.publication_timestamp} is before "
                    f"observation_timestamp {self.observation_timestamp}."
                )

        if self.publication_date is None and self.publication_timestamp is not None:
            self.publication_date = self.publication_timestamp.date()

        # Automatic classification resolution preserving explicit tags
        if self.classification is None:
            if self.is_synthetic:
                self.classification = DataClassification.SYNTHETIC
            elif self.availability_evidence == AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED:
                self.classification = DataClassification.REAL_VERIFIED
            elif self.availability_evidence == AvailabilityEvidence.ESTIMATED_SCHEDULE:
                self.classification = DataClassification.REAL_ESTIMATED_AVAILABILITY
            elif self.availability_evidence == AvailabilityEvidence.UNVERIFIED_SAME_DAY:
                self.classification = DataClassification.REAL_ESTIMATED_AVAILABILITY
            elif self.availability_evidence == AvailabilityEvidence.RETROSPECTIVE:
                self.classification = DataClassification.REAL_RETROSPECTIVE
            elif self.publication_timestamp is not None:
                self.classification = DataClassification.REAL_VERIFIED
            elif self.publication_date is not None:
                self.classification = DataClassification.REAL_VERIFIED
            else:
                self.classification = DataClassification.REAL_RETROSPECTIVE
        elif self.classification in (DataClassification.SYNTHETIC, DataClassification.MOCK):
            self.is_synthetic = True

        if self.availability_evidence is None:
            if self.is_synthetic:
                self.availability_evidence = None
            elif self.classification == DataClassification.REAL_VERIFIED and self.publication_timestamp is not None:
                self.availability_evidence = AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED
            elif self.publication_date is not None:
                self.availability_evidence = AvailabilityEvidence.ESTIMATED_SCHEDULE
            else:
                self.availability_evidence = AvailabilityEvidence.RETROSPECTIVE
        return self


FetchResult.model_rebuild()
