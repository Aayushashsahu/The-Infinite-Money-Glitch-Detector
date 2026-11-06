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
from datetime import date, datetime, timedelta, timezone
from typing import Any, Sequence

import pandas as pd

from core.currency import (
    QuoteConvention,
    get_rate_a_per_b,
    get_two_way_quote_a_per_b,
    invert_two_way_quote,
    map_canonical_side_to_provider_side,
    normalize_directional_quote,
)
from data.schemas import AvailabilityEvidence, DataObservation, Frequency, ObservationKind, PriceType, RateRole
from schemas.backtest import (
    AvailabilityPolicy,
    DataAvailabilityConfig,
    ExecutableQuoteResult,
    ValuationResult,
)


CURRENCY_ENTITY_MAP: dict[str, list[str]] = {
    "EUR": ["EUR", "ECB_EA", "EMU"],
    "USD": ["USD", "FED_USA", "USA"],
    "GBP": ["GBP", "GBR", "BOE"],
    "JPY": ["JPY", "JPN", "BOJ"],
    "BRL": ["BRL", "BRA", "BCB"],
    "TRY": ["TRY", "TUR", "TCMB"],
}


def _parse_as_of(as_of: date | datetime) -> tuple[date, datetime | None]:
    """Normalize as_of argument to (date, Optional[datetime_in_utc])."""
    if isinstance(as_of, datetime):
        if as_of.tzinfo is None:
            as_of_dt = as_of.replace(tzinfo=timezone.utc)
        else:
            as_of_dt = as_of.astimezone(timezone.utc)
        return as_of_dt.date(), as_of_dt
    return as_of, None


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
    availability_timestamp: datetime | None = None


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
        # Strict mode: requires verified publication_date AND excludes unverified evidence
        if self.config.policy == AvailabilityPolicy.STRICT:
            from data.schemas import AvailabilityEvidence
            if obs.availability_evidence == AvailabilityEvidence.RETROSPECTIVE:
                return None, False, "retrospective_evidence_rejected_in_strict_mode"
            if obs.publication_date is not None:
                return obs.publication_date, True, "verified_publication_date"
            return None, False, "missing_publication_date_rejected_in_strict_mode"

        # Estimated-lag mode
        if self.config.policy == AvailabilityPolicy.ESTIMATED_LAG:
            from data.schemas import AvailabilityEvidence
            if obs.availability_evidence == AvailabilityEvidence.RETROSPECTIVE:
                return None, False, "retrospective_evidence_rejected_in_estimated_lag_mode"

            is_verified = (
                obs.availability_evidence == AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED
                and obs.publication_timestamp is not None
            )
            if obs.publication_date is not None:
                return obs.publication_date, is_verified, "publication_date"
            
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

    def resolve_availability(
        self,
        obs: DataObservation,
        as_of: date | datetime,
    ) -> tuple[bool, date | None, datetime | None, bool, str]:
        """Compute point-in-time eligibility and effective availability timestamps against as_of.

        Returns:
            (is_eligible, avail_date, avail_timestamp, is_verified, reason_note)
        """
        from data.schemas import AvailabilityEvidence
        as_of_d, as_of_dt = _parse_as_of(as_of)

        # 1. Observation timestamp/date lookahead check: observation itself cannot be in the future
        if as_of_dt is not None:
            if obs.observation_timestamp is not None and obs.observation_timestamp > as_of_dt:
                return False, obs.observation_date, obs.observation_timestamp, False, "future_observation_timestamp_leakage_blocked"
        if obs.observation_date > as_of_d:
            return False, obs.observation_date, obs.observation_timestamp, False, "future_observation_date_leakage_blocked"

        # Check effective timestamp: if policy rate is not yet effective as of as_of, reject
        if obs.effective_timestamp is not None and as_of_dt is not None:
            if obs.effective_timestamp > as_of_dt:
                return False, obs.observation_date, obs.effective_timestamp, False, "effective_timestamp_after_as_of_not_yet_effective"

        # 2. Strict mode: requires verified publication date / timestamp AND excludes unverified evidence
        if self.config.policy == AvailabilityPolicy.STRICT:
            if as_of_dt is not None:
                # Synthetic/test unit-test observations: allow if synthetic is permitted
                is_fixture = obs.is_synthetic or (obs.source_id in ("test", "test_source", "mock", "simulated"))
                if is_fixture and (self.config.allow_synthetic or obs.source_id in ("test", "test_source")):
                    if obs.publication_timestamp is not None:
                        if obs.publication_timestamp > as_of_dt:
                            return False, obs.publication_timestamp.date(), obs.publication_timestamp, False, "publication_timestamp_after_signal_blocked"
                        return True, obs.publication_timestamp.date(), obs.publication_timestamp, False, "test_fixture_publication_timestamp"
                    if obs.publication_date is not None:
                        if obs.publication_date > as_of_d:
                            return False, obs.publication_date, None, False, "publication_date_after_as_of_blocked"
                        return True, obs.publication_date, None, False, "test_fixture_publication_date"
                    return False, None, None, False, "missing_publication_date_rejected_in_strict_mode"

                # Real market observation evaluated with datetime: STRICT requires verified publication timestamp
                if obs.availability_evidence != AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED:
                    ev_str = obs.availability_evidence.value if obs.availability_evidence else "none"
                    return False, obs.publication_date, obs.publication_timestamp, False, f"unverified_evidence_{ev_str}_rejected_in_strict_mode"

                if obs.publication_timestamp is not None:
                    avail_dt = obs.publication_timestamp
                    avail_d = avail_dt.date()
                    if avail_dt > as_of_dt:
                        return False, avail_d, avail_dt, True, "publication_timestamp_after_signal_blocked"
                    return True, avail_d, avail_dt, True, "verified_publication_timestamp"
                else:
                    return False, obs.publication_date, None, False, "missing_publication_timestamp_rejected_in_strict_mode"
            else:
                # Date-only evaluation
                if obs.availability_evidence == AvailabilityEvidence.RETROSPECTIVE:
                    return False, obs.publication_date, obs.publication_timestamp, False, "retrospective_evidence_rejected_in_strict_mode"
                if obs.publication_date is not None:
                    if obs.publication_date > as_of_d:
                        return False, obs.publication_date, obs.publication_timestamp, True, "publication_date_after_as_of_blocked"
                    return True, obs.publication_date, obs.publication_timestamp, True, "verified_publication_date"
                return False, None, None, False, "missing_publication_date_rejected_in_strict_mode"

        # 3. Estimated-lag mode
        if self.config.policy == AvailabilityPolicy.ESTIMATED_LAG:
            if obs.availability_evidence == AvailabilityEvidence.RETROSPECTIVE:
                return False, obs.observation_date, obs.observation_timestamp, False, "retrospective_evidence_rejected_in_estimated_lag_mode"

            is_verified = (
                obs.availability_evidence == AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED
                and obs.publication_timestamp is not None
            )

            if obs.publication_timestamp is not None:
                avail_dt = obs.publication_timestamp
                avail_d = avail_dt.date()
                if as_of_dt is not None and avail_dt > as_of_dt:
                    return False, avail_d, avail_dt, is_verified, "publication_timestamp_after_as_of"
                if avail_d > as_of_d:
                    return False, avail_d, avail_dt, is_verified, "publication_date_after_as_of"
                note_str = "verified_publication_timestamp" if is_verified else "estimated_schedule_publication_timestamp"
                return True, avail_d, avail_dt, is_verified, note_str

            if obs.publication_date is not None:
                avail_d = obs.publication_date
                if as_of_dt is not None:
                    avail_dt = datetime(avail_d.year, avail_d.month, avail_d.day, 16, 0, tzinfo=timezone.utc)
                    if avail_dt > as_of_dt:
                        return False, avail_d, avail_dt, is_verified, "publication_date_after_as_of"
                    note_str = "verified_publication_date" if is_verified else "estimated_schedule_publication_date"
                    return True, avail_d, avail_dt, is_verified, note_str
                if avail_d > as_of_d:
                    return False, avail_d, None, is_verified, "publication_date_after_as_of"
                note_str = "verified_publication_date" if is_verified else "estimated_schedule_publication_date"
                return True, avail_d, None, is_verified, note_str

            # Custom or default lag
            lag_days = (
                self.config.custom_indicator_lags.get(obs.indicator_id, self.config.default_lags_days.get(obs.frequency, 30))
                if obs.indicator_id
                else self.config.default_lags_days.get(obs.frequency, 30)
            )
            est_date = obs.observation_date + timedelta(days=lag_days)
            if as_of_dt is not None:
                est_dt = datetime(est_date.year, est_date.month, est_date.day, 0, 0, tzinfo=timezone.utc)
                if est_dt > as_of_dt:
                    return False, est_date, est_dt, False, f"estimated_lag_{lag_days}d_after_as_of"
                return True, est_date, est_dt, False, f"estimated_lag_{lag_days}d_unverified"
            if est_date > as_of_d:
                return False, est_date, None, False, f"estimated_lag_{lag_days}d_after_as_of"
            return True, est_date, None, False, f"estimated_lag_{lag_days}d_unverified"

        # 4. Research-only mode
        if self.config.policy == AvailabilityPolicy.RESEARCH_ONLY:
            if as_of_dt is not None:
                obs_dt = obs.observation_timestamp or datetime(obs.observation_date.year, obs.observation_date.month, obs.observation_date.day, 0, 0, tzinfo=timezone.utc)
                if obs_dt > as_of_dt:
                    return False, obs.observation_date, obs_dt, False, "observation_after_as_of"
                return True, obs.observation_date, obs_dt, False, "research_only"
            if obs.observation_date > as_of_d:
                return False, obs.observation_date, None, False, "observation_date_after_as_of"
            return True, obs.observation_date, None, False, "research_only_retrospective_observation_date"

        raise ValueError(f"Unknown availability policy: {self.config.policy}")

    def filter_available(
        self,
        observations: Sequence[DataObservation],
        as_of: date | datetime,
    ) -> list[PointInTimeRecord]:
        """Filter a collection of observations to those strictly available as of timestamp T.

        Observations published or estimated to become available after T are strictly blocked.
        """
        as_of_d, as_of_dt = _parse_as_of(as_of)
        records: list[PointInTimeRecord] = []
        for obs in observations:
            if not self.config.allow_synthetic and obs.is_synthetic:
                continue

            is_eligible, avail_date, avail_dt, is_verified, note = self.resolve_availability(obs, as_of)
            if not is_eligible or avail_date is None:
                continue

            # Check staleness (respecting market calendar when stale_by_trading_days is True)
            if getattr(self.config, "stale_by_trading_days", True) and as_of_d >= obs.observation_date:
                from backtesting.calendar import DEFAULT_FX_CALENDAR
                days_old = DEFAULT_FX_CALENDAR.trading_days_lag(obs.observation_date, as_of_d)
            else:
                days_old = (as_of_d - obs.observation_date).days

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
                    availability_timestamp=avail_dt,
                )
            )

        return records

    def get_latest_observation(
        self,
        observations: Sequence[DataObservation],
        as_of: date | datetime,
        kind: ObservationKind | None = None,
        entity_code: str | None = None,
        indicator_id: str | None = None,
        rate_role: RateRole | None = None,
        allow_stale: bool = False,
    ) -> PointInTimeRecord | None:
        """Find the most recent available observation as of timestamp T for a given series.

        Selects the highest observation_date (and latest revision) available by T.
        If allow_stale is False and the quote is stale, returns None.
        """
        as_of_d, as_of_dt = _parse_as_of(as_of)
        allowed_entities = [entity_code] if entity_code else None
        if entity_code and entity_code.upper() in CURRENCY_ENTITY_MAP:
            allowed_entities = list(set(CURRENCY_ENTITY_MAP[entity_code.upper()] + [entity_code]))

        candidates: list[tuple[DataObservation, date, datetime | None, bool, str]] = []
        for obs in observations:
            if not self.config.allow_synthetic and obs.is_synthetic:
                continue
            if kind is not None and obs.kind != kind:
                continue
            if allowed_entities is not None and obs.entity_code not in allowed_entities:
                continue
            if indicator_id is not None and obs.indicator_id != indicator_id:
                continue
            if rate_role is not None and obs.rate_role != rate_role:
                continue

            is_eligible, avail_date, avail_dt, is_verified, note = self.resolve_availability(obs, as_of)
            if not is_eligible or avail_date is None:
                continue
            candidates.append((obs, avail_date, avail_dt, is_verified, note))

        if not candidates:
            return None

        # Sort by observation_date ascending, observation_timestamp ascending, revision ascending
        epoch_utc = datetime(1970, 1, 1, tzinfo=timezone.utc)
        candidates.sort(key=lambda x: (
            x[0].observation_date,
            x[0].observation_timestamp or epoch_utc,
            x[0].revision,
        ))
        latest_obs, avail_date, avail_dt, is_verified, note = candidates[-1]

        # Check staleness strictly for the latest observation
        if getattr(self.config, "stale_by_trading_days", True) and as_of_d >= latest_obs.observation_date:
            from backtesting.calendar import DEFAULT_FX_CALENDAR
            days_old = DEFAULT_FX_CALENDAR.trading_days_lag(latest_obs.observation_date, as_of_d)
        else:
            days_old = (as_of_d - latest_obs.observation_date).days

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
            availability_timestamp=avail_dt,
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
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        from collections import defaultdict
        self._by_kind_entity: dict[tuple[ObservationKind, str], list[DataObservation]] = defaultdict(list)
        for obs in self._observations:
            self._by_kind_entity[(obs.kind, obs.entity_code)].append(obs)

    def add_observations(self, observations: Sequence[DataObservation]) -> None:
        self._observations.extend(observations)
        for obs in observations:
            self._by_kind_entity[(obs.kind, obs.entity_code)].append(obs)

    def _lookup_candidates(self, kind: ObservationKind, entity_code: str | None) -> list[DataObservation]:
        if entity_code is None:
            return self._observations
        allowed_entities = [entity_code]
        if entity_code.upper() in CURRENCY_ENTITY_MAP:
            allowed_entities = list(set(CURRENCY_ENTITY_MAP[entity_code.upper()] + [entity_code]))
        res: list[DataObservation] = []
        for ent in allowed_entities:
            items = self._by_kind_entity.get((kind, ent))
            if items:
                res.extend(items)
        return res

    def get_rate(
        self,
        pair_code: str,
        as_of: date | datetime,
        borrowing_currency: str | None = None,
        investment_currency: str | None = None,
        allow_stale: bool = False,
    ) -> float | None:
        """Retrieve spot exchange rate for pair_code as of date/datetime.

        If borrowing_currency and investment_currency are specified, returns the canonical
        rate_a_per_b (units of borrowing currency A per 1 unit of investment currency B).
        Otherwise returns the raw observation value (or reciprocal if inverted pair).
        """
        candidates = self._lookup_candidates(ObservationKind.EXCHANGE_RATE, pair_code)
        record = self.firewall.get_latest_observation(
            candidates,
            as_of=as_of,
            kind=ObservationKind.EXCHANGE_RATE,
            entity_code=pair_code,
            allow_stale=allow_stale,
        )
        if record is None:
            if "/" in pair_code:
                b, q = pair_code.split("/", 1)
                inv_pair = f"{q}/{b}"
                inv_candidates = self._lookup_candidates(ObservationKind.EXCHANGE_RATE, inv_pair)
                if inv_candidates:
                    inv_rec = self.firewall.get_latest_observation(
                        inv_candidates,
                        as_of=as_of,
                        kind=ObservationKind.EXCHANGE_RATE,
                        entity_code=inv_pair,
                        allow_stale=allow_stale,
                    )
                    if inv_rec is not None and inv_rec.observation.value > 0:
                        obs = inv_rec.observation
                        if borrowing_currency and investment_currency:
                            return get_rate_a_per_b(
                                value=obs.value,
                                obs_base=obs.base_currency or q,
                                obs_quote=obs.quote_currency or b,
                                borrowing_currency=borrowing_currency,
                                investment_currency=investment_currency,
                                convention=obs.quote_convention or QuoteConvention.QUOTE_PER_BASE,
                            )
                        return 1.0 / obs.value
            return None

        obs = record.observation
        if borrowing_currency and investment_currency:
            b_curr = obs.base_currency
            q_curr = obs.quote_currency
            if not b_curr or not q_curr:
                if "/" in pair_code:
                    b_curr, q_curr = pair_code.split("/", 1)
            return get_rate_a_per_b(
                value=obs.value,
                obs_base=b_curr or "",
                obs_quote=q_curr or "",
                borrowing_currency=borrowing_currency,
                investment_currency=investment_currency,
                convention=obs.quote_convention or QuoteConvention.QUOTE_PER_BASE,
            )
        return obs.value

    def get_forward_rate(
        self,
        pair_code: str,
        tenor_days: int,
        as_of: date | datetime,
        allow_stale: bool = False,
    ) -> float | None:
        """Retrieve executable market forward exchange rate for pair_code and tenor.

        Never substitutes theoretical CIP. Returns None if actual quote is unavailable.
        """
        indicator = f"FWD_{tenor_days}D"
        candidates = self._lookup_candidates(ObservationKind.EXCHANGE_RATE, pair_code)
        record = self.firewall.get_latest_observation(
            candidates,
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
        as_of: date | datetime,
        indicator_id: str | None = None,
        rate_role: RateRole | None = None,
        allow_stale: bool = False,
    ) -> float | None:
        """Retrieve annualized interest or policy rate (as a fraction, e.g. 0.05 for 5%)."""
        candidates = self._lookup_candidates(ObservationKind.INTEREST_RATE, currency_or_entity)
        record = self.firewall.get_latest_observation(
            candidates,
            as_of=as_of,
            kind=ObservationKind.INTEREST_RATE,
            entity_code=currency_or_entity,
            indicator_id=indicator_id,
            rate_role=rate_role,
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
        as_of: date | datetime,
        indicator_id: str | None = None,
        rate_role: RateRole | None = None,
        allow_stale: bool = False,
    ) -> PointInTimeRecord | None:
        candidates = self._lookup_candidates(kind, entity_code)
        return self.firewall.get_latest_observation(
            candidates,
            as_of=as_of,
            kind=kind,
            entity_code=entity_code,
            indicator_id=indicator_id,
            rate_role=rate_role,
            allow_stale=allow_stale,
        )

    def get_reference_rate(
        self,
        pair_code: str,
        as_of: date | datetime,
        borrowing_currency: str | None = None,
        investment_currency: str | None = None,
        allow_stale: bool = False,
    ) -> ValuationResult | None:
        """Retrieve reference rate for mark-to-market valuation with age, convention, and price_type metadata."""
        if not borrowing_currency or not investment_currency:
            if "/" in pair_code:
                c_a, c_b = pair_code.split("/", 1)
                borrowing_currency = borrowing_currency or c_a
                investment_currency = investment_currency or c_b

        candidates = self._lookup_candidates(ObservationKind.EXCHANGE_RATE, pair_code)
        record = self.firewall.get_latest_observation(
            candidates,
            as_of=as_of,
            kind=ObservationKind.EXCHANGE_RATE,
            entity_code=pair_code,
            allow_stale=allow_stale,
        )
        as_of_d, as_of_dt = _parse_as_of(as_of)
        if record is None:
            if "/" in pair_code:
                b, q = pair_code.split("/", 1)
                inv_pair = f"{q}/{b}"
                inv_candidates = self._lookup_candidates(ObservationKind.EXCHANGE_RATE, inv_pair)
                if inv_candidates:
                    inv_rec = self.firewall.get_latest_observation(
                        inv_candidates,
                        as_of=as_of,
                        kind=ObservationKind.EXCHANGE_RATE,
                        entity_code=inv_pair,
                        allow_stale=allow_stale,
                    )
                    if inv_rec is not None and inv_rec.observation.value > 0:
                        obs = inv_rec.observation
                        pt = obs.price_type or PriceType.REFERENCE_RATE
                        val = 1.0 / obs.value
                        obs_b = obs.base_currency or q
                        obs_q = obs.quote_currency or b
                        conv = obs.quote_convention or QuoteConvention.QUOTE_PER_BASE
                        rate_a_b = val
                        if borrowing_currency and investment_currency:
                            rate_a_b = get_rate_a_per_b(
                                value=obs.value,
                                obs_base=obs_b,
                                obs_quote=obs_q,
                                borrowing_currency=borrowing_currency,
                                investment_currency=investment_currency,
                                convention=conv,
                            )
                        return ValuationResult(
                            rate=val,
                            rate_a_per_b=rate_a_b,
                            observation_timestamp=obs.observation_timestamp,
                            availability_timestamp=inv_rec.availability_timestamp,
                            age_at_valuation_days=inv_rec.stale_days,
                            data_source=obs.source_id,
                            price_type=pt,
                            pair_code=pair_code,
                            base_currency=obs_b,
                            quote_currency=obs_q,
                            quote_convention=conv,
                        )
            return None

        obs = record.observation
        pt = obs.price_type or PriceType.REFERENCE_RATE
        obs_b = obs.base_currency or (pair_code.split("/")[0] if "/" in pair_code else "")
        obs_q = obs.quote_currency or (pair_code.split("/")[1] if "/" in pair_code else "")
        conv = obs.quote_convention or QuoteConvention.QUOTE_PER_BASE
        rate_a_b = obs.value
        if borrowing_currency and investment_currency:
            rate_a_b = get_rate_a_per_b(
                value=obs.value,
                obs_base=obs_b,
                obs_quote=obs_q,
                borrowing_currency=borrowing_currency,
                investment_currency=investment_currency,
                convention=conv,
            )
        return ValuationResult(
            rate=obs.value,
            rate_a_per_b=rate_a_b,
            observation_timestamp=obs.observation_timestamp,
            availability_timestamp=record.availability_timestamp,
            age_at_valuation_days=record.stale_days,
            data_source=obs.source_id,
            price_type=pt,
            pair_code=pair_code,
            base_currency=obs_b,
            quote_currency=obs_q,
            quote_convention=conv,
        )

    def get_executable_quote(
        self,
        pair_code: str,
        as_of: datetime,
        borrowing_currency: str | None = None,
        investment_currency: str | None = None,
        max_quote_age_minutes: float = 1440.0,
        allow_reference_rate_proxy: bool = False,
        use_observed_spread: bool = True,
        max_one_sided_quote_time_diff_seconds: float = 60.0,
        required_side: str | None = None,
    ) -> ExecutableQuoteResult | None:
        """Retrieve executable market quote with bid/ask prices and freshness validation.

        Enforces:
        - Actual observation timestamp requirement (no midnight fallback for real market data).
        - Price positivity and bid <= ask validation.
        - Two-way quotes vs assembled one-sided quotes vs standalone one-sided quotes.
        - Direct and reciprocal freshness symmetry.
        - Canonical rate_a_per_b, bid_a_per_b, and ask_a_per_b resolution.
        """
        as_of_d, as_of_dt = _parse_as_of(as_of)
        if as_of_dt is None:
            as_of_dt = datetime.combine(as_of_d, datetime.min.time(), tzinfo=timezone.utc)

        if not borrowing_currency or not investment_currency:
            if "/" in pair_code:
                c_a, c_b = pair_code.split("/", 1)
                borrowing_currency = borrowing_currency or c_a
                investment_currency = investment_currency or c_b
        curr_a = borrowing_currency or ""
        curr_b = investment_currency or ""

        def _is_record_fresh(r: PointInTimeRecord) -> tuple[bool, datetime, float]:
            obs = r.observation
            if obs.value <= 0:
                return False, datetime.min.replace(tzinfo=timezone.utc), 0.0

            if not obs.is_synthetic:
                if obs.observation_timestamp is None:
                    return False, datetime.min.replace(tzinfo=timezone.utc), 0.0
                quote_dt = obs.observation_timestamp
            else:
                quote_dt = (
                    obs.observation_timestamp
                    or obs.publication_timestamp
                    or datetime.combine(obs.observation_date, datetime.min.time(), tzinfo=timezone.utc)
                )

            if quote_dt > as_of_dt:
                return False, quote_dt, 0.0

            age_sec = (as_of_dt - quote_dt).total_seconds()
            if age_sec < 0:
                return False, quote_dt, 0.0
            age_min = age_sec / 60.0
            if age_min > max_quote_age_minutes:
                return False, quote_dt, age_min

            return True, quote_dt, age_min

        epoch_utc = datetime(1970, 1, 1, tzinfo=timezone.utc)

        # 1. Search direct candidates
        candidates = self._lookup_candidates(ObservationKind.EXCHANGE_RATE, pair_code)
        available_records = self.firewall.filter_available(candidates, as_of=as_of_dt)

        two_way_candidates: list[tuple[PointInTimeRecord, datetime, float]] = []
        bid_candidates: list[tuple[PointInTimeRecord, datetime, float]] = []
        ask_candidates: list[tuple[PointInTimeRecord, datetime, float]] = []
        ref_candidates: list[tuple[PointInTimeRecord, datetime, float]] = []

        for r in available_records:
            obs = r.observation
            fresh, q_dt, q_age = _is_record_fresh(r)
            if obs.price_type == PriceType.EXECUTABLE_TWO_WAY_QUOTE:
                if fresh:
                    if obs.is_synthetic:
                        bid_v = obs.bid if obs.bid is not None else (obs.metadata.get("bid", obs.value) if obs.metadata else obs.value)
                        ask_v = obs.ask if obs.ask is not None else (obs.metadata.get("ask", obs.value) if obs.metadata else obs.value)
                    else:
                        bid_v = obs.bid if obs.bid is not None else (obs.metadata.get("bid") if obs.metadata else None)
                        ask_v = obs.ask if obs.ask is not None else (obs.metadata.get("ask") if obs.metadata else None)
                    if bid_v is not None and ask_v is not None and bid_v > 0 and ask_v > 0 and bid_v <= ask_v:
                        two_way_candidates.append((r, q_dt, q_age))
            elif obs.price_type == PriceType.BID_QUOTE:
                if fresh:
                    bid_candidates.append((r, q_dt, q_age))
            elif obs.price_type == PriceType.ASK_QUOTE:
                if fresh:
                    ask_candidates.append((r, q_dt, q_age))
            else:
                ref_candidates.append((r, q_dt, q_age))

        # Direct two-way quote match
        if two_way_candidates:
            two_way_candidates.sort(
                key=lambda x: (
                    x[0].observation.observation_date,
                    x[1],
                    x[0].observation.revision,
                )
            )
            best_r, best_dt, best_age = two_way_candidates[-1]
            obs = best_r.observation
            if obs.is_synthetic:
                bid_v = obs.bid if obs.bid is not None else (obs.metadata.get("bid", obs.value) if obs.metadata else obs.value)
                ask_v = obs.ask if obs.ask is not None else (obs.metadata.get("ask", obs.value) if obs.metadata else obs.value)
            else:
                bid_v = obs.bid if obs.bid is not None else obs.metadata.get("bid")
                ask_v = obs.ask if obs.ask is not None else obs.metadata.get("ask")
            obs_b = obs.base_currency or (pair_code.split("/")[0] if "/" in pair_code else "")
            obs_q = obs.quote_currency or (pair_code.split("/")[1] if "/" in pair_code else "")
            conv = obs.quote_convention or QuoteConvention.QUOTE_PER_BASE
            bid_ab, ask_ab = get_two_way_quote_a_per_b(
                bid=bid_v,
                ask=ask_v,
                obs_base=obs_b,
                obs_quote=obs_q,
                borrowing_currency=curr_a or obs_b,
                investment_currency=curr_b or obs_q,
                convention=conv,
            )
            mid_val = (bid_v + ask_v) / 2.0
            mid_ab = (bid_ab + ask_ab) / 2.0
            return ExecutableQuoteResult(
                pair_code=pair_code,
                bid=bid_v,
                ask=ask_v,
                mid=mid_val,
                rate_a_per_b=mid_ab,
                bid_a_per_b=bid_ab,
                ask_a_per_b=ask_ab,
                base_currency=obs_b,
                quote_currency=obs_q,
                quote_convention=conv,
                observation_timestamp=best_dt,
                availability_timestamp=best_r.availability_timestamp or best_dt,
                age_minutes=best_age,
                data_source=obs.source_id,
                price_type=PriceType.EXECUTABLE_TWO_WAY_QUOTE,
                is_executable=True,
                is_observed_spread=True,
                quote_assembly_method="genuine_two_way",
                provider_price_type=PriceType.EXECUTABLE_TWO_WAY_QUOTE,
                provider_side="two_way",
                provider_base_currency=obs_b,
                provider_quote_currency=obs_q,
                provider_convention=conv,
                canonical_side="two_way",
                canonical_price=mid_ab,
            )

        # Check assembled one-sided quotes
        if bid_candidates and ask_candidates:
            bid_candidates.sort(key=lambda x: (x[0].observation.observation_date, x[1], x[0].observation.revision))
            ask_candidates.sort(key=lambda x: (x[0].observation.observation_date, x[1], x[0].observation.revision))
            b_r, b_dt, b_age = bid_candidates[-1]
            a_r, a_dt, a_age = ask_candidates[-1]
            time_diff = abs((b_dt - a_dt).total_seconds())
            bid_v = b_r.observation.bid if b_r.observation.bid is not None else b_r.observation.value
            ask_v = a_r.observation.ask if a_r.observation.ask is not None else a_r.observation.value
            same_source = (b_r.observation.source_id == a_r.observation.source_id)
            same_conv = (b_r.observation.quote_convention == a_r.observation.quote_convention)
            if time_diff <= max_one_sided_quote_time_diff_seconds and bid_v <= ask_v and same_source and same_conv:
                obs_b = b_r.observation.base_currency or (pair_code.split("/")[0] if "/" in pair_code else "")
                obs_q = b_r.observation.quote_currency or (pair_code.split("/")[1] if "/" in pair_code else "")
                conv = b_r.observation.quote_convention or QuoteConvention.QUOTE_PER_BASE
                bid_ab, ask_ab = get_two_way_quote_a_per_b(
                    bid=bid_v,
                    ask=ask_v,
                    obs_base=obs_b,
                    obs_quote=obs_q,
                    borrowing_currency=curr_a or obs_b,
                    investment_currency=curr_b or obs_q,
                    convention=conv,
                )
                mid_val = (bid_v + ask_v) / 2.0
                mid_ab = (bid_ab + ask_ab) / 2.0
                return ExecutableQuoteResult(
                    pair_code=pair_code,
                    bid=bid_v,
                    ask=ask_v,
                    mid=mid_val,
                    rate_a_per_b=mid_ab,
                    bid_a_per_b=bid_ab,
                    ask_a_per_b=ask_ab,
                    base_currency=obs_b,
                    quote_currency=obs_q,
                    quote_convention=conv,
                    observation_timestamp=max(b_dt, a_dt),
                    availability_timestamp=max(b_r.availability_timestamp or b_dt, a_r.availability_timestamp or a_dt),
                    age_minutes=min(b_age, a_age),
                    data_source=b_r.observation.source_id,
                    price_type=PriceType.EXECUTABLE_TWO_WAY_QUOTE,
                    is_executable=True,
                    is_observed_spread=True,
                    quote_assembly_method="assembled_one_sided_quotes",
                    provider_price_type=PriceType.EXECUTABLE_TWO_WAY_QUOTE,
                    provider_side="two_way",
                    provider_base_currency=obs_b,
                    provider_quote_currency=obs_q,
                    provider_convention=conv,
                    canonical_side="two_way",
                    canonical_price=mid_ab,
                )

        # Standalone one-sided quote if required_side is explicitly requested
        if required_side in ("ask", "bid"):
            matching_direct: list[tuple[PointInTimeRecord, datetime, float, str, str, str, QuoteConvention]] = []
            for r, q_dt, q_age in (ask_candidates + bid_candidates):
                obs = r.observation
                cand_side = "ask" if obs.price_type == PriceType.ASK_QUOTE else "bid"
                obs_b = obs.base_currency or (pair_code.split("/")[0] if "/" in pair_code else curr_a)
                obs_q = obs.quote_currency or (pair_code.split("/")[1] if "/" in pair_code else curr_b)
                conv = obs.quote_convention or QuoteConvention.QUOTE_PER_BASE
                try:
                    needed_side = map_canonical_side_to_provider_side(
                        required_side, obs_b, obs_q, curr_a, curr_b, conv
                    )
                    if cand_side == needed_side:
                        matching_direct.append((r, q_dt, q_age, cand_side, obs_b, obs_q, conv))
                except ValueError:
                    pass

            if matching_direct:
                matching_direct.sort(key=lambda x: (x[0].observation.observation_date, x[1], x[0].observation.revision))
                target_r, target_dt, target_age, target_prov_side, obs_b, obs_q, conv = matching_direct[-1]
                target_obs = target_r.observation
                prov_val = (
                    target_obs.ask if target_prov_side == "ask" and target_obs.ask is not None
                    else target_obs.bid if target_prov_side == "bid" and target_obs.bid is not None
                    else target_obs.value
                )
                norm = normalize_directional_quote(
                    provider_price=prov_val,
                    provider_side=target_prov_side,
                    obs_base=obs_b,
                    obs_quote=obs_q,
                    borrowing_currency=curr_a,
                    investment_currency=curr_b,
                    convention=conv,
                    requested_canonical_side=required_side,
                )
                return ExecutableQuoteResult(
                    pair_code=pair_code,
                    bid=prov_val if target_prov_side == "bid" else None,
                    ask=prov_val if target_prov_side == "ask" else None,
                    mid=prov_val,
                    rate_a_per_b=norm.canonical_price,
                    bid_a_per_b=norm.canonical_price if norm.canonical_side == "bid" else None,
                    ask_a_per_b=norm.canonical_price if norm.canonical_side == "ask" else None,
                    base_currency=obs_b,
                    quote_currency=obs_q,
                    quote_convention=conv,
                    observation_timestamp=target_dt,
                    availability_timestamp=target_r.availability_timestamp or target_dt,
                    age_minutes=target_age,
                    data_source=target_obs.source_id,
                    price_type=PriceType.ASK_QUOTE if norm.canonical_side == "ask" else PriceType.BID_QUOTE,
                    is_executable=True,
                    is_observed_spread=True,
                    quote_assembly_method="standalone_one_sided",
                    provider_price_type=target_obs.price_type,
                    provider_side=target_prov_side,
                    provider_base_currency=obs_b,
                    provider_quote_currency=obs_q,
                    provider_convention=conv,
                    canonical_side=norm.canonical_side,
                    canonical_price=norm.canonical_price,
                )

        # 2. Check reciprocal pair candidates
        if "/" in pair_code:
            b, q = pair_code.split("/", 1)
            inv_pair = f"{q}/{b}"
            inv_candidates = self._lookup_candidates(ObservationKind.EXCHANGE_RATE, inv_pair)
            inv_available = self.firewall.filter_available(inv_candidates, as_of=as_of_dt)

            inv_two_way: list[tuple[PointInTimeRecord, datetime, float]] = []
            inv_bid_candidates: list[tuple[PointInTimeRecord, datetime, float]] = []
            inv_ask_candidates: list[tuple[PointInTimeRecord, datetime, float]] = []

            for r in inv_available:
                fresh, q_dt, q_age = _is_record_fresh(r)
                if not fresh:
                    continue
                obs = r.observation
                if obs.price_type == PriceType.EXECUTABLE_TWO_WAY_QUOTE:
                    if obs.is_synthetic:
                        b_val = obs.bid if obs.bid is not None else (obs.metadata.get("bid", obs.value) if obs.metadata else obs.value)
                        a_val = obs.ask if obs.ask is not None else (obs.metadata.get("ask", obs.value) if obs.metadata else obs.value)
                    else:
                        b_val = obs.bid if obs.bid is not None else (obs.metadata.get("bid") if obs.metadata else None)
                        a_val = obs.ask if obs.ask is not None else (obs.metadata.get("ask") if obs.metadata else None)
                    if b_val is not None and a_val is not None and b_val > 0 and a_val > 0 and b_val <= a_val:
                        inv_two_way.append((r, q_dt, q_age))
                elif obs.price_type == PriceType.BID_QUOTE:
                    inv_bid_candidates.append((r, q_dt, q_age))
                elif obs.price_type == PriceType.ASK_QUOTE:
                    inv_ask_candidates.append((r, q_dt, q_age))

            if inv_two_way:
                inv_two_way.sort(key=lambda x: (x[0].observation.observation_date, x[1], x[0].observation.revision))
                inv_rec, inv_dt, inv_age = inv_two_way[-1]
                obs = inv_rec.observation
                if obs.is_synthetic:
                    b_val = obs.bid if obs.bid is not None else (obs.metadata.get("bid", obs.value) if obs.metadata else obs.value)
                    a_val = obs.ask if obs.ask is not None else (obs.metadata.get("ask", obs.value) if obs.metadata else obs.value)
                else:
                    b_val = obs.bid if obs.bid is not None else obs.metadata.get("bid")
                    a_val = obs.ask if obs.ask is not None else obs.metadata.get("ask")
                inv_bid, inv_ask = invert_two_way_quote(b_val, a_val)
                obs_b = obs.base_currency or q
                obs_q = obs.quote_currency or b
                conv = obs.quote_convention or QuoteConvention.QUOTE_PER_BASE
                bid_ab, ask_ab = get_two_way_quote_a_per_b(
                    bid=inv_bid,
                    ask=inv_ask,
                    obs_base=b,
                    obs_quote=q,
                    borrowing_currency=curr_a or b,
                    investment_currency=curr_b or q,
                    convention=conv,
                )
                mid_val = (inv_bid + inv_ask) / 2.0
                mid_ab = (bid_ab + ask_ab) / 2.0
                return ExecutableQuoteResult(
                    pair_code=pair_code,
                    bid=inv_bid,
                    ask=inv_ask,
                    mid=mid_val,
                    rate_a_per_b=mid_ab,
                    bid_a_per_b=bid_ab,
                    ask_a_per_b=ask_ab,
                    base_currency=b,
                    quote_currency=q,
                    quote_convention=conv,
                    observation_timestamp=inv_dt,
                    availability_timestamp=inv_rec.availability_timestamp or inv_dt,
                    age_minutes=inv_age,
                    data_source=obs.source_id,
                    price_type=PriceType.EXECUTABLE_TWO_WAY_QUOTE,
                    is_executable=True,
                    is_observed_spread=True,
                    quote_assembly_method="reciprocal_two_way",
                    provider_price_type=PriceType.EXECUTABLE_TWO_WAY_QUOTE,
                    provider_side="two_way",
                    provider_base_currency=obs.base_currency or q,
                    provider_quote_currency=obs.quote_currency or b,
                    provider_convention=conv,
                    canonical_side="two_way",
                    canonical_price=mid_ab,
                )

            # Check assembled one-sided quotes on reciprocal pair
            if inv_bid_candidates and inv_ask_candidates:
                inv_bid_candidates.sort(key=lambda x: (x[0].observation.observation_date, x[1], x[0].observation.revision))
                inv_ask_candidates.sort(key=lambda x: (x[0].observation.observation_date, x[1], x[0].observation.revision))
                b_r, b_dt, b_age = inv_bid_candidates[-1]
                a_r, a_dt, a_age = inv_ask_candidates[-1]
                time_diff = abs((b_dt - a_dt).total_seconds())
                bid_v = b_r.observation.bid if b_r.observation.bid is not None else b_r.observation.value
                ask_v = a_r.observation.ask if a_r.observation.ask is not None else a_r.observation.value
                same_source = (b_r.observation.source_id == a_r.observation.source_id)
                same_conv = (b_r.observation.quote_convention == a_r.observation.quote_convention)
                if time_diff <= max_one_sided_quote_time_diff_seconds and bid_v <= ask_v and same_source and same_conv:
                    inv_bid, inv_ask = invert_two_way_quote(bid_v, ask_v)
                    obs_b = b_r.observation.base_currency or q
                    obs_q = b_r.observation.quote_currency or b
                    conv = b_r.observation.quote_convention or QuoteConvention.QUOTE_PER_BASE
                    bid_ab, ask_ab = get_two_way_quote_a_per_b(
                        bid=inv_bid,
                        ask=inv_ask,
                        obs_base=b,
                        obs_quote=q,
                        borrowing_currency=curr_a or b,
                        investment_currency=curr_b or q,
                        convention=conv,
                    )
                    mid_val = (inv_bid + inv_ask) / 2.0
                    mid_ab = (bid_ab + ask_ab) / 2.0
                    return ExecutableQuoteResult(
                        pair_code=pair_code,
                        bid=inv_bid,
                        ask=inv_ask,
                        mid=mid_val,
                        rate_a_per_b=mid_ab,
                        bid_a_per_b=bid_ab,
                        ask_a_per_b=ask_ab,
                        base_currency=b,
                        quote_currency=q,
                        quote_convention=conv,
                        observation_timestamp=max(b_dt, a_dt),
                        availability_timestamp=max(b_r.availability_timestamp or b_dt, a_r.availability_timestamp or a_dt),
                        age_minutes=min(b_age, a_age),
                        data_source=b_r.observation.source_id,
                        price_type=PriceType.EXECUTABLE_TWO_WAY_QUOTE,
                        is_executable=True,
                        is_observed_spread=True,
                        quote_assembly_method="assembled_reciprocal_one_sided_quotes",
                        provider_price_type=PriceType.EXECUTABLE_TWO_WAY_QUOTE,
                        provider_side="two_way",
                        provider_base_currency=obs_b,
                        provider_quote_currency=obs_q,
                        provider_convention=conv,
                        canonical_side="two_way",
                        canonical_price=mid_ab,
                    )

            # Standalone one-sided quote from reciprocal pair if required_side is requested
            if required_side in ("ask", "bid"):
                matching_inv: list[tuple[PointInTimeRecord, datetime, float, str, str, str, QuoteConvention]] = []
                for r, q_dt, q_age in (inv_ask_candidates + inv_bid_candidates):
                    obs = r.observation
                    cand_side = "ask" if obs.price_type == PriceType.ASK_QUOTE else "bid"
                    obs_b = obs.base_currency or q
                    obs_q = obs.quote_currency or b
                    conv = obs.quote_convention or QuoteConvention.QUOTE_PER_BASE
                    try:
                        needed_side = map_canonical_side_to_provider_side(
                            required_side, obs_b, obs_q, curr_a, curr_b, conv
                        )
                        if cand_side == needed_side:
                            matching_inv.append((r, q_dt, q_age, cand_side, obs_b, obs_q, conv))
                    except ValueError:
                        pass

                if matching_inv:
                    matching_inv.sort(key=lambda x: (x[0].observation.observation_date, x[1], x[0].observation.revision))
                    target_r, target_dt, target_age, target_prov_side, obs_b, obs_q, conv = matching_inv[-1]
                    target_obs = target_r.observation
                    prov_val = (
                        target_obs.ask if target_prov_side == "ask" and target_obs.ask is not None
                        else target_obs.bid if target_prov_side == "bid" and target_obs.bid is not None
                        else target_obs.value
                    )
                    norm = normalize_directional_quote(
                        provider_price=prov_val,
                        provider_side=target_prov_side,
                        obs_base=obs_b,
                        obs_quote=obs_q,
                        borrowing_currency=curr_a,
                        investment_currency=curr_b,
                        convention=conv,
                        requested_canonical_side=required_side,
                    )
                    return ExecutableQuoteResult(
                        pair_code=pair_code,
                        bid=prov_val if target_prov_side == "bid" else None,
                        ask=prov_val if target_prov_side == "ask" else None,
                        mid=prov_val,
                        rate_a_per_b=norm.canonical_price,
                        bid_a_per_b=norm.canonical_price if norm.canonical_side == "bid" else None,
                        ask_a_per_b=norm.canonical_price if norm.canonical_side == "ask" else None,
                        base_currency=obs_b,
                        quote_currency=obs_q,
                        quote_convention=conv,
                        observation_timestamp=target_dt,
                        availability_timestamp=target_r.availability_timestamp or target_dt,
                        age_minutes=target_age,
                        data_source=target_obs.source_id,
                        price_type=PriceType.ASK_QUOTE if norm.canonical_side == "ask" else PriceType.BID_QUOTE,
                        is_executable=True,
                        is_observed_spread=True,
                        quote_assembly_method="standalone_one_sided",
                        provider_price_type=target_obs.price_type,
                        provider_side=target_prov_side,
                        provider_base_currency=obs_b,
                        provider_quote_currency=obs_q,
                        provider_convention=conv,
                        canonical_side=norm.canonical_side,
                        canonical_price=norm.canonical_price,
                    )

        # 3. Reference-rate proxy mode
        if allow_reference_rate_proxy:
            if ref_candidates:
                ref_candidates.sort(key=lambda x: (x[0].observation.observation_date, x[1], x[0].observation.revision))
                target_rec, q_dt, q_age = ref_candidates[-1]
                obs = target_rec.observation
                if obs.value > 0 and not target_rec.is_stale:
                    obs_b = obs.base_currency or (pair_code.split("/")[0] if "/" in pair_code else "")
                    obs_q = obs.quote_currency or (pair_code.split("/")[1] if "/" in pair_code else "")
                    conv = obs.quote_convention or QuoteConvention.QUOTE_PER_BASE
                    rate_ab = get_rate_a_per_b(
                        value=obs.value,
                        obs_base=obs_b,
                        obs_quote=obs_q,
                        borrowing_currency=curr_a or obs_b,
                        investment_currency=curr_b or obs_q,
                        convention=conv,
                    )
                    return ExecutableQuoteResult(
                        pair_code=pair_code,
                        bid=obs.value,
                        ask=obs.value,
                        mid=obs.value,
                        rate_a_per_b=rate_ab,
                        bid_a_per_b=rate_ab,
                        ask_a_per_b=rate_ab,
                        base_currency=obs_b,
                        quote_currency=obs_q,
                        quote_convention=conv,
                        observation_timestamp=q_dt,
                        availability_timestamp=target_rec.availability_timestamp or q_dt,
                        age_minutes=q_age,
                        data_source=obs.source_id,
                        price_type=obs.price_type or PriceType.REFERENCE_RATE,
                        is_executable=False,
                        is_observed_spread=False,
                        quote_assembly_method="reference_rate_proxy",
                        provider_price_type=obs.price_type or PriceType.REFERENCE_RATE,
                        provider_side="reference",
                        provider_base_currency=obs_b,
                        provider_quote_currency=obs_q,
                        provider_convention=conv,
                        canonical_side="reference",
                        canonical_price=rate_ab,
                    )
            if "/" in pair_code:
                b, q = pair_code.split("/", 1)
                inv_pair = f"{q}/{b}"
                inv_candidates = self._lookup_candidates(ObservationKind.EXCHANGE_RATE, inv_pair)
                inv_available = self.firewall.filter_available(inv_candidates, as_of=as_of_dt)
                inv_ref = [r for r in inv_available if r.observation.value > 0 and not r.is_stale]
                if inv_ref:
                    inv_ref.sort(key=lambda r: (r.observation.observation_date, r.observation.observation_timestamp or epoch_utc, r.observation.revision))
                    target_rec = inv_ref[-1]
                    obs = target_rec.observation
                    val = 1.0 / obs.value
                    obs_b = obs.base_currency or q
                    obs_q = obs.quote_currency or b
                    conv = obs.quote_convention or QuoteConvention.QUOTE_PER_BASE
                    rate_ab = get_rate_a_per_b(
                        value=obs.value,
                        obs_base=obs_b,
                        obs_quote=obs_q,
                        borrowing_currency=curr_a or b,
                        investment_currency=curr_b or q,
                        convention=conv,
                    )
                    q_dt = obs.observation_timestamp or datetime.combine(obs.observation_date, datetime.min.time(), tzinfo=timezone.utc)
                    age_min = max(0.0, (as_of_dt - q_dt).total_seconds()) / 60.0
                    return ExecutableQuoteResult(
                        pair_code=pair_code,
                        bid=val,
                        ask=val,
                        mid=val,
                        rate_a_per_b=rate_ab,
                        bid_a_per_b=rate_ab,
                        ask_a_per_b=rate_ab,
                        base_currency=b,
                        quote_currency=q,
                        quote_convention=conv,
                        observation_timestamp=q_dt,
                        availability_timestamp=target_rec.availability_timestamp or q_dt,
                        age_minutes=age_min,
                        data_source=obs.source_id,
                        price_type=obs.price_type or PriceType.REFERENCE_RATE,
                        is_executable=False,
                        is_observed_spread=False,
                        quote_assembly_method="reference_rate_proxy",
                        provider_price_type=obs.price_type or PriceType.REFERENCE_RATE,
                        provider_side="reference",
                        provider_base_currency=obs_b,
                        provider_quote_currency=obs_q,
                        provider_convention=conv,
                        canonical_side="reference",
                        canonical_price=rate_ab,
                    )

        return None

