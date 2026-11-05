"""Historical Information Firewall: Point-in-Time Data Access Layer.

Ensures that at every simulation timestamp T, the strategy, valuation,
and execution modules have access ONLY to information genuinely available by T.

Explicitly distinguishes:
- Observation date: when the economic fact occurred.
- Publication date: when the source officially published the data.
- Retrieval date: when our system ingested the data.
- Estimated availability date: observation date + conservative availability lag.
- Actual verified availability: boolean, True only when publication date is verified.

Supports three policies:
1. STRICT: Only verified publication dates <= T are eligible. Unknown publication
   dates are rejected.
2. ESTIMATED_LAG: Observations without publication dates are admitted using
   conservative frequency-based lags, strictly flagged as unverified.
3. RESEARCH_ONLY: Retrospective research mode (observation_date <= T). Unsuitable
   for executable trading.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Sequence

import pandas as pd

from data.schemas import DataObservation, Frequency, ObservationKind
from schemas.backtest import AvailabilityPolicy, DataAvailabilityConfig


CURRENCY_ENTITY_MAP: dict[str, list[str]] = {
    "EUR": ["EUR", "ECB_EA", "EMU"],
    "USD": ["USD", "FED_USA", "USA"],
    "GBP": ["GBP", "GBR", "BOE"],
    "JPY": ["JPY", "JPN", "BOJ"],
    "BRL": ["BRL", "BRA", "BCB"],
    "TRY": ["TRY", "TUR", "TCMB"],
}


@dataclass(frozen=True)
class PointInTimeRecord:
    """A single economic observation with resolved point-in-time metadata."""

    observation: DataObservation
    is_available: bool
    is_verified_availability: bool
    availability_date: date
    is_stale: bool
    stale_days: int
    policy_applied: AvailabilityPolicy
    status_note: str


class PointInTimeFirewall:
    """Historical Information Firewall protecting against look-ahead bias."""

    def __init__(self, config: DataAvailabilityConfig | None = None):
        self.config = config or DataAvailabilityConfig()

    def resolve_availability_date(
        self, obs: DataObservation
    ) -> tuple[date | None, bool, str]:
        """Compute the effective availability date and verified status.

        Returns:
            (availability_date, is_verified, reason_note)
        """
        # Strict mode: requires verified publication_date
        if self.config.policy == AvailabilityPolicy.STRICT:
            if obs.publication_date is not None:
                return obs.publication_date, True, "verified_publication_date"
            return None, False, "missing_publication_date_rejected_in_strict_mode"

        # Estimated-lag mode
        if self.config.policy == AvailabilityPolicy.ESTIMATED_LAG:
            if obs.publication_date is not None:
                return obs.publication_date, True, "verified_publication_date"
            
            # Check for custom indicator lag first
            lag_days: int | None = None
            if obs.indicator_id and obs.indicator_id in self.config.custom_indicator_lags:
                lag_days = self.config.custom_indicator_lags[obs.indicator_id]
            else:
                lag_days = self.config.default_lags_days.get(obs.frequency, 30)

            est_date = obs.observation_date + timedelta(days=lag_days)
            return est_date, False, f"estimated_lag_{lag_days}d_unverified"

        # Research-only mode
        if self.config.policy == AvailabilityPolicy.RESEARCH_ONLY:
            return (
                obs.observation_date,
                False,
                "research_only_retrospective_observation_date",
            )

        raise ValueError(f"Unknown availability policy: {self.config.policy}")

    def filter_available(
        self,
        observations: Sequence[DataObservation],
        as_of: date,
    ) -> list[PointInTimeRecord]:
        """Filter a collection of observations to those strictly available as of timestamp T.

        Observations published or estimated to become available after T are
        strictly blocked.
        """
        records: list[PointInTimeRecord] = []
        for obs in observations:
            if not self.config.allow_synthetic and obs.is_synthetic:
                continue

            avail_date, is_verified, note = self.resolve_availability_date(obs)
            if avail_date is None or avail_date > as_of:
                continue  # Future information blocked by firewall

            # Check staleness (respecting market calendar when stale_by_trading_days is True)
            if getattr(self.config, "stale_by_trading_days", True) and as_of >= obs.observation_date:
                from backtesting.calendar import DEFAULT_FX_CALENDAR
                days_old = DEFAULT_FX_CALENDAR.trading_days_lag(obs.observation_date, as_of)
            else:
                days_old = (as_of - obs.observation_date).days

            # For daily exchange rates or market interest rates, apply max_stale_days
            is_stale = False
            if obs.frequency == Frequency.DAILY and days_old > self.config.max_stale_days:
                is_stale = True

            records.append(
                PointInTimeRecord(
                    observation=obs,
                    is_available=True,
                    is_verified_availability=is_verified,
                    availability_date=avail_date,
                    is_stale=is_stale,
                    stale_days=days_old,
                    policy_applied=self.config.policy,
                    status_note=note,
                )
            )

        return records

    def get_latest_observation(
        self,
        observations: Sequence[DataObservation],
        as_of: date,
        kind: ObservationKind | None = None,
        entity_code: str | None = None,
        indicator_id: str | None = None,
        allow_stale: bool = False,
    ) -> PointInTimeRecord | None:
        """Find the most recent available observation as of timestamp T for a given series.

        Selects the highest observation_date (and latest revision) available by T.
        If allow_stale is False and the quote is stale, returns None.
        """
        allowed_entities = [entity_code] if entity_code else None
        if entity_code and entity_code.upper() in CURRENCY_ENTITY_MAP:
            allowed_entities = list(set(CURRENCY_ENTITY_MAP[entity_code.upper()] + [entity_code]))

        candidates: list[tuple[DataObservation, date, bool, str]] = []
        for obs in observations:
            if not self.config.allow_synthetic and obs.is_synthetic:
                continue
            if kind is not None and obs.kind != kind:
                continue
            if allowed_entities is not None and obs.entity_code not in allowed_entities:
                continue
            if indicator_id is not None and obs.indicator_id != indicator_id:
                continue

            avail_date, is_verified, note = self.resolve_availability_date(obs)
            if avail_date is None or avail_date > as_of:
                continue
            candidates.append((obs, avail_date, is_verified, note))

        if not candidates:
            return None

        # Sort by observation_date ascending, revision ascending and pick latest
        candidates.sort(key=lambda x: (x[0].observation_date, x[0].revision))
        latest_obs, avail_date, is_verified, note = candidates[-1]

        # Check staleness strictly for the latest observation
        if getattr(self.config, "stale_by_trading_days", True) and as_of >= latest_obs.observation_date:
            from backtesting.calendar import DEFAULT_FX_CALENDAR
            days_old = DEFAULT_FX_CALENDAR.trading_days_lag(latest_obs.observation_date, as_of)
        else:
            days_old = (as_of - latest_obs.observation_date).days

        is_stale = False
        if latest_obs.frequency == Frequency.DAILY and days_old > self.config.max_stale_days:
            is_stale = True

        if is_stale and not allow_stale:
            return None

        return PointInTimeRecord(
            observation=latest_obs,
            is_available=True,
            is_verified_availability=is_verified,
            availability_date=avail_date,
            is_stale=is_stale,
            stale_days=days_old,
            policy_applied=self.config.policy,
            status_note=note,
        )


class PointInTimeDataStore:
    """In-memory or repository-backed point-in-time data access interface."""

    def __init__(
        self,
        observations: Sequence[DataObservation],
        firewall: PointInTimeFirewall | None = None,
    ):
        self._observations = list(observations)
        self.firewall = firewall or PointInTimeFirewall()

    def add_observations(self, observations: Sequence[DataObservation]) -> None:
        self._observations.extend(observations)

    def get_rate(
        self,
        pair_code: str,
        as_of: date,
        allow_stale: bool = False,
    ) -> float | None:
        """Retrieve executable spot exchange rate for pair_code as of date."""
        record = self.firewall.get_latest_observation(
            self._observations,
            as_of=as_of,
            kind=ObservationKind.EXCHANGE_RATE,
            entity_code=pair_code,
            allow_stale=allow_stale,
        )
        if record is None:
            return None
        return record.observation.value

    def get_forward_rate(
        self,
        pair_code: str,
        tenor_days: int,
        as_of: date,
        allow_stale: bool = False,
    ) -> float | None:
        """Retrieve executable market forward exchange rate for pair_code and tenor.

        Never substitutes theoretical CIP. Returns None if actual quote is unavailable.
        """
        indicator = f"FWD_{tenor_days}D"
        record = self.firewall.get_latest_observation(
            self._observations,
            as_of=as_of,
            kind=ObservationKind.EXCHANGE_RATE,
            entity_code=pair_code,
            indicator_id=indicator,
            allow_stale=allow_stale,
        )
        if record is None:
            return None
        return record.observation.value

    def get_interest_rate(
        self,
        currency_or_entity: str,
        as_of: date,
        indicator_id: str | None = None,
        allow_stale: bool = False,
    ) -> float | None:
        """Retrieve annualized interest or policy rate (as a fraction, e.g. 0.05 for 5%)."""
        record = self.firewall.get_latest_observation(
            self._observations,
            as_of=as_of,
            kind=ObservationKind.INTEREST_RATE,
            entity_code=currency_or_entity,
            indicator_id=indicator_id,
            allow_stale=allow_stale,
        )
        if record is None:
            return None
        val = record.observation.value
        # If rate is given in percent (e.g. 5.0), convert to fraction 0.05
        if record.observation.unit.lower() in ("percent", "%", "pct"):
            val = val / 100.0
        return val

    def get_record(
        self,
        kind: ObservationKind,
        entity_code: str,
        as_of: date,
        indicator_id: str | None = None,
        allow_stale: bool = False,
    ) -> PointInTimeRecord | None:
        return self.firewall.get_latest_observation(
            self._observations,
            as_of=as_of,
            kind=kind,
            entity_code=entity_code,
            indicator_id=indicator_id,
            allow_stale=allow_stale,
        )
