"""Market factor extraction, transformation, and frequency alignment.

Extracts canonical macro-financial factors from historical DataObservation collections,
computes economically defensible transformations (log returns, basis point changes),
and constructs calendar-aligned factor panels without look-ahead bias, synthetic data,
or cross-series substitutions.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, time, timezone
import math

import numpy as np

from backtesting.calendar import FED_H15_CALENDAR
from core.currency import QuoteConvention
from data.schemas import (
    AvailabilityEvidence,
    DataClassification,
    DataObservation,
    Frequency,
    ObservationKind,
)
from simulation.monte_carlo.schemas import (
    FactorCategory,
    FactorPanel,
    FactorRowProvenance,
    InitialMarketLevelsReport,
    MarketFactor,
    MissingDataTreatment,
    PITMode,
    TransformationMethod,
)


def compute_log_returns(prices: list[float]) -> list[float]:
    """Calculate daily log returns r_t = ln(S_t / S_{t-1}).

    Length of returned array is len(prices) - 1.
    All prices must be finite and strictly positive.
    """
    if len(prices) < 2:
        return []
    returns: list[float] = []
    for i in range(1, len(prices)):
        p0 = prices[i - 1]
        p1 = prices[i]
        if p0 <= 0 or p1 <= 0 or math.isnan(p0) or math.isnan(p1):
            raise ValueError(f"Prices must be strictly positive and finite: p0={p0}, p1={p1}")
        returns.append(math.log(p1 / p0))
    return returns


def reconstruct_price_levels(initial_price: float, log_returns: list[float]) -> list[float]:
    """Reconstruct asset price levels from log returns: S_t = S_0 * exp(sum r_i).

    Returns list of length len(log_returns) + 1 starting with initial_price.
    Guarantees strictly positive price levels S_t > 0.
    """
    if initial_price <= 0:
        raise ValueError(f"Initial price must be strictly positive: {initial_price}")
    cum_returns = np.cumsum(log_returns)
    levels = [initial_price]
    for cr in cum_returns:
        levels.append(float(initial_price * math.exp(cr)))
    return levels


def compute_differences(rates: list[float], in_bps: bool = True) -> list[float]:
    """Calculate daily interest rate differences: Delta x_t = x_t - x_{t-1}.

    If in_bps is True, difference is multiplied by 10,000 for decimal percentages
    or 100 for percentage points.
    Length of returned array is len(rates) - 1.
    """
    if len(rates) < 2:
        return []
    scale = 100.0 if in_bps else 1.0  # Assumes rate levels are already in percent (e.g. 4.0 for 4%)
    diffs: list[float] = []
    for i in range(1, len(rates)):
        r0 = rates[i - 1]
        r1 = rates[i]
        diffs.append((r1 - r0) * scale)
    return diffs


def reconstruct_rate_levels(initial_rate: float, diffs: list[float], in_bps: bool = True) -> list[float]:
    """Reconstruct interest rate levels: x_t = x_0 + sum Delta x_i.

    Returns list of length len(diffs) + 1 starting with initial_rate.
    """
    scale = 100.0 if in_bps else 1.0
    levels = [initial_rate]
    curr = initial_rate
    for d in diffs:
        curr = curr + (d / scale)
        levels.append(curr)
    return levels


def get_session_decision_timestamp(
    session_date: date,
    decision_time_utc: time = time(16, 0),
) -> datetime:
    """Return explicit strategy decision timestamp for a given session date.

    Default is 16:00 UTC (17:00 CET), corresponding to daily European market close/rebalance.
    """
    return datetime(
        session_date.year,
        session_date.month,
        session_date.day,
        decision_time_utc.hour,
        decision_time_utc.minute,
        decision_time_utc.second,
        tzinfo=timezone.utc,
    )


def _normalize_rate_to_decimal(obs: DataObservation) -> float:
    """Convert an interest rate observation to decimal strictly via metadata."""
    unit_str = (obs.unit or "").strip().lower()
    if unit_str in ("percent", "percentage", "%", "pct"):
        return obs.value / 100.0
    elif unit_str in ("decimal", "fraction", "ratio", "rate"):
        return obs.value
    elif unit_str in ("basis_points", "bps"):
        return obs.value / 10000.0
    else:
        raise ValueError(
            f"Cannot determine rate unit conversion for series '{obs.indicator_id or obs.entity_code}' "
            f"with unknown unit '{obs.unit}'. Unit must be explicitly declared ('percent', 'decimal', etc.)."
        )


def _normalize_rate_to_percentage_points(obs: DataObservation) -> float:
    """Convert an interest rate observation to percentage points (e.g. 4.5 for 4.5%) strictly via metadata."""
    unit_str = (obs.unit or "").strip().lower()
    if unit_str in ("percent", "percentage", "%", "pct"):
        return obs.value
    elif unit_str in ("decimal", "fraction", "ratio", "rate"):
        return obs.value * 100.0
    elif unit_str in ("basis_points", "bps"):
        return obs.value / 100.0
    else:
        raise ValueError(
            f"Cannot determine rate unit conversion for series '{obs.indicator_id or obs.entity_code}' "
            f"with unknown unit '{obs.unit}'. Unit must be explicitly declared ('percent', 'decimal', etc.)."
        )


def _normalize_fx_quote_to_usd_per_eur(fx_obs: DataObservation) -> float:
    """Normalize FX quote to canonical provider quote convention (USD per EUR) strictly via metadata.

    Rules:
    - Platform quotation convention: BASE/QUOTE = units of QUOTE per BASE.
    - Declared unit 'usd_per_eur' / 'usd/eur' represents USD per 1 EUR (canonical); returns value as-is.
    - Declared unit 'eur_per_usd' / 'eur/usd' represents EUR per 1 USD (reciprocal); returns 1.0 / value.
    - Supports genuine provider metadata: unit="quote_per_base" with explicit base/quote currencies.
    - Rejects contradictory unit declarations (e.g. unit="EUR_per_USD" with base="EUR", quote="USD").
    - Rejects missing, ambiguous, or unsupported quote metadata (fails closed).
    - Never uses numerical magnitude heuristics.
    """
    unit_str = (fx_obs.unit or "").strip().lower()
    convention = fx_obs.quote_convention

    # Validate finite positivity
    if not math.isfinite(fx_obs.value) or fx_obs.value <= 0:
        raise ValueError(f"FX observation value must be finite and positive: {fx_obs.value}")

    # Resolve base and quote currencies
    base = fx_obs.base_currency
    quote = fx_obs.quote_currency
    if not base and not quote and "/" in fx_obs.entity_code:
        parts = fx_obs.entity_code.split("/", 1)
        base = parts[0].strip().upper()
        quote = parts[1].strip().upper()

    # Check for invalid / contradictory currencies if currencies are specified
    currencies = {c for c in (base, quote) if c}
    if currencies and not currencies.issubset({"USD", "EUR"}):
        raise ValueError(
            f"Contradictory FX currency metadata for {fx_obs.entity_code}: "
            f"currencies {currencies} do not match required EUR/USD factor pair."
        )
    if base and quote and base == quote:
        raise ValueError(
            f"Contradictory FX currency metadata for {fx_obs.entity_code}: "
            f"base_currency and quote_currency are identical ({base})."
        )

    # Enforce quotation convention: BASE/QUOTE = units of QUOTE per BASE
    # An explicit unit declaration contradictory to base/quote must fail closed
    if base and quote and convention != QuoteConvention.BASE_PER_QUOTE:
        if base == "EUR" and quote == "USD" and unit_str in ("eur_per_usd", "eur/usd", "eur per usd"):
            raise ValueError(
                f"Contradictory FX metadata for {fx_obs.entity_code}: explicit unit '{fx_obs.unit}' "
                f"contradicts base_currency='{base}' and quote_currency='{quote}'. "
                "Expected 'USD_per_EUR' under BASE/QUOTE convention."
            )
        if base == "USD" and quote == "EUR" and unit_str in ("usd_per_eur", "usd/eur", "usd per eur"):
            raise ValueError(
                f"Contradictory FX metadata for {fx_obs.entity_code}: explicit unit '{fx_obs.unit}' "
                f"contradicts base_currency='{base}' and quote_currency='{quote}'. "
                "Expected 'EUR_per_USD' under BASE/QUOTE convention."
            )

    # 1. Genuine provider metadata: unit="quote_per_base"
    if unit_str in ("quote_per_base", "quotation_per_base", "quote/base"):
        if not base or not quote:
            raise ValueError(
                f"Missing base or quote currency metadata for FX observation {fx_obs.entity_code} "
                f"with generic quote-per-base units '{fx_obs.unit}'. Fail closed."
            )
        if base == "EUR" and quote == "USD":
            return fx_obs.value
        elif base == "USD" and quote == "EUR":
            return 1.0 / fx_obs.value
        else:
            raise ValueError(
                f"Unsupported currency pair for FX normalization: base='{base}', quote='{quote}'."
            )

    # 2. Explicit unit metadata (already validated against base/quote)
    if unit_str in ("usd_per_eur", "usd/eur", "usd per eur"):
        return fx_obs.value
    if unit_str in ("eur_per_usd", "eur/usd", "eur per usd"):
        return 1.0 / fx_obs.value

    # 3. Quote convention and currencies when unit is absent or generic
    if convention == QuoteConvention.BASE_PER_QUOTE:
        if not base or not quote:
            raise ValueError(
                f"Missing base or quote currency metadata for BASE_PER_QUOTE observation {fx_obs.entity_code}."
            )
        if base == "EUR" and quote == "USD":
            return 1.0 / fx_obs.value
        elif base == "USD" and quote == "EUR":
            return fx_obs.value

    if base == "EUR" and quote == "USD":
        return fx_obs.value
    if base == "USD" and quote == "EUR":
        return 1.0 / fx_obs.value

    # 4. Canonical pair symbol fallback if currencies/units not specified
    if not unit_str:
        if fx_obs.entity_code == "EUR/USD":
            if convention == QuoteConvention.BASE_PER_QUOTE:
                return 1.0 / fx_obs.value
            return fx_obs.value
        elif fx_obs.entity_code == "USD/EUR":
            if convention == QuoteConvention.BASE_PER_QUOTE:
                return fx_obs.value
            return 1.0 / fx_obs.value

    raise ValueError(
        f"Cannot determine quote convention for FX observation {fx_obs.entity_code} "
        f"with unit='{fx_obs.unit}', quote_convention={fx_obs.quote_convention}, "
        f"base={base}, quote={quote}."
    )


def get_effective_availability_timestamp(obs: DataObservation) -> datetime | None:
    """Compute effective point-in-time availability timestamp for an observation.

    Applies documented release schedules:
    - Retrospective: returns None (no forward availability evidence).
    - Verified exact timestamp: uses publication_timestamp ONLY if availability_evidence
      is explicitly EXACT_TIMESTAMP_VERIFIED.
    - EUR/USD exchange rate (ECB reference midpoint): published ~16:00 CET, available 16:00 UTC on observation date.
    - US Treasury yields (DGS1MO, DGS3MO): published under Federal Reserve H.15 release calendar
      (4:15 PM Eastern Time on next Federal Reserve business day, skipping weekends and Fed holidays).
    - ECB policy rate (KR.MRR_FR.LEV, DFR): effective on effective_timestamp or 00:00 UTC on observation date.
    - Unmapped series: returns None (fail-closed, no fabricated availability timestamp).
    - Late publication: If an observation has a publication_timestamp later than the scheduled release,
      it cannot be available before it was actually published.
    """
    # 1. Retrospective observations have no forward availability
    if (
        obs.availability_evidence == AvailabilityEvidence.RETROSPECTIVE
        or obs.classification == DataClassification.REAL_RETROSPECTIVE
    ):
        return None

    # 2. Exact verified publication timestamp is trusted ONLY if evidence classification verifies it
    if (
        obs.availability_evidence == AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED
        and obs.publication_timestamp is not None
    ):
        ts = obs.publication_timestamp
        return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)

    obs_d = obs.observation_date

    # 3. Exchange Rate (EUR/USD ECB reference rate from Frankfurter or ECB)
    if obs.kind == ObservationKind.EXCHANGE_RATE and (
        obs.entity_code in ("EUR/USD", "USD/EUR")
        or obs.source_id in ("frankfurter", "ecb")
    ):
        sched_ts = datetime(obs_d.year, obs_d.month, obs_d.day, 16, 0, 0, tzinfo=timezone.utc)

    # 4. US Treasury yields: Federal Reserve H.15 release calendar (4:15 PM Eastern Time on next Fed business day)
    elif obs.kind == ObservationKind.INTEREST_RATE and (
        obs.indicator_id in ("DGS1MO", "DGS3MO", "USD_RATE")
        or obs.entity_code in ("DGS1MO", "DGS3MO")
        or obs.source_id == "us_treasury"
    ):
        sched_ts = FED_H15_CALENDAR.get_h15_release_timestamp(obs_d)

    # 5. ECB Policy rate: effective date/time
    elif obs.kind == ObservationKind.INTEREST_RATE and (
        obs.indicator_id in ("KR.MRR_FR.LEV", "DFR", "EUR_RATE")
        or obs.entity_code in ("ECB_EA", "EUR", "DFR")
        or obs.source_id in ("policy_rates", "ecb")
    ):
        if obs.effective_timestamp is not None:
            ts = obs.effective_timestamp
            sched_ts = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)
        else:
            sched_ts = datetime(obs_d.year, obs_d.month, obs_d.day, 0, 0, 0, tzinfo=timezone.utc)

    else:
        # Fail closed on unmapped series
        return None

    if obs.publication_timestamp is not None:
        pub = obs.publication_timestamp
        pub_utc = pub.replace(tzinfo=timezone.utc) if pub.tzinfo is None else pub.astimezone(timezone.utc)
        return max(sched_ts, pub_utc)

    return sched_ts


def is_observation_available_as_of(
    obs: DataObservation,
    as_of: datetime,
    strict_executable: bool = False,
    pit_mode: PITMode | str | None = None,
) -> tuple[bool, str]:
    """Check whether observation is genuinely available at decision timestamp as_of.

    Enforces explicit PIT policy modes:
    - STRICT_VERIFIED: Requires exact verified timestamp evidence (EXACT_TIMESTAMP_VERIFIED).
      Estimated schedules and retrospective data are strictly rejected.
    - ESTIMATED_LAG: Requires documented release schedule (ESTIMATED_SCHEDULE). Retrospective data rejected.
    - RESEARCH_ONLY: Preserves retrospective research proxy semantics with clear audit provenance.
    """
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    else:
        as_of = as_of.astimezone(timezone.utc)

    as_of_date = as_of.date()

    # Look-ahead check on observation date and observation timestamp
    if obs.observation_date > as_of_date:
        return False, "future_observation_date_leakage_blocked"
    if obs.observation_timestamp is not None:
        obs_ts = obs.observation_timestamp
        obs_ts_utc = obs_ts.replace(tzinfo=timezone.utc) if obs_ts.tzinfo is None else obs_ts.astimezone(timezone.utc)
        if obs_ts_utc > as_of:
            return False, "future_observation_timestamp_leakage_blocked"

    # Effective timestamp check (e.g. policy rate effective date)
    if obs.effective_timestamp is not None:
        eff_ts = obs.effective_timestamp
        eff_ts_utc = eff_ts.replace(tzinfo=timezone.utc) if eff_ts.tzinfo is None else eff_ts.astimezone(timezone.utc)
        if eff_ts_utc > as_of:
            return False, "policy_rate_not_yet_effective_at_as_of"

    mode = None
    if pit_mode is not None:
        if isinstance(pit_mode, str):
            try:
                mode = PITMode(pit_mode)
            except ValueError:
                raise ValueError(
                    f"Invalid pit_mode: '{pit_mode}'. Must be one of {[m.value for m in PITMode]}."
                )
        elif isinstance(pit_mode, PITMode):
            mode = pit_mode
        else:
            raise ValueError(f"Invalid pit_mode type: {type(pit_mode).__name__}.")
    else:
        mode = PITMode.RESEARCH_ONLY if not strict_executable else PITMode.STRICT_VERIFIED

    # Strict executable mode / Strict Verified checks
    if mode == PITMode.STRICT_VERIFIED or (mode is None and strict_executable):
        if (
            obs.classification == DataClassification.REAL_RETROSPECTIVE
            or obs.availability_evidence == AvailabilityEvidence.RETROSPECTIVE
        ):
            return False, "retrospective_evidence_rejected_in_strict_executable_mode"
        if obs.availability_evidence is None:
            return False, "missing_availability_evidence_rejected_in_strict_executable_mode"
        if mode == PITMode.STRICT_VERIFIED:
            if obs.availability_evidence != AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED:
                return False, "unverified_evidence_rejected_in_strict_verified_mode"
            if obs.publication_timestamp is None:
                return False, "missing_publication_timestamp_in_strict_verified_mode"

    if mode == PITMode.ESTIMATED_LAG:
        if obs.availability_evidence is None:
            return False, "missing_availability_evidence_rejected_in_estimated_lag_mode"
        if (
            obs.classification == DataClassification.REAL_RETROSPECTIVE
            or obs.availability_evidence == AvailabilityEvidence.RETROSPECTIVE
        ):
            return False, "retrospective_evidence_rejected_in_estimated_lag_mode"
        if obs.availability_evidence not in (
            AvailabilityEvidence.ESTIMATED_SCHEDULE,
            AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
        ):
            return False, f"unrecognized_or_unpermitted_evidence_{obs.availability_evidence}_in_estimated_lag_mode"

    avail_ts = get_effective_availability_timestamp(obs)
    if avail_ts is None:
        if strict_executable or mode in (PITMode.STRICT_VERIFIED, PITMode.ESTIMATED_LAG):
            return False, "no_valid_availability_timestamp_in_strict_executable_mode"
        return True, "retrospective_research_proxy_admitted"

    if avail_ts > as_of:
        return False, f"release_timestamp_{avail_ts.isoformat()}_after_as_of_{as_of.isoformat()}_blocked"

    return True, "available"


def resolve_observation_as_of(
    observations: list[DataObservation],
    as_of: datetime,
    strict_executable: bool = False,
    pit_mode: PITMode | str | None = None,
) -> DataObservation | None:
    """Deterministically resolve the authoritative observation as of a decision timestamp.

    - Filters candidate observations by point-in-time availability as of timestamp as_of.
    - Excludes future leakage, late revisions, and future effective dates.
    - Selects the candidate with the highest revision number.
    - Breaks ties by latest publication timestamp or retrieved_at.
    """
    available_obs = [
        o for o in observations
        if is_observation_available_as_of(o, as_of, strict_executable=strict_executable, pit_mode=pit_mode)[0]
    ]
    if not available_obs:
        return None

    max_date = max(o.observation_date for o in available_obs)
    date_obs = [o for o in available_obs if o.observation_date == max_date]

    def _sort_key(o: DataObservation):
        rev = o.revision if o.revision is not None else 0
        ts = o.publication_timestamp or o.retrieved_at or datetime.min
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (rev, ts)

    return max(date_obs, key=_sort_key)



def _resolve_observation(existing: DataObservation, candidate: DataObservation) -> DataObservation:
    """Deterministically resolve duplicate observations for the same date and series.

    Higher revision number wins; if revisions are equal, the latest retrieved_at timestamp wins.
    """
    ex_rev = existing.revision or 0
    cand_rev = candidate.revision or 0
    if cand_rev > ex_rev:
        return candidate
    elif cand_rev < ex_rev:
        return existing

    ex_ret = existing.retrieved_at or datetime.min
    cand_ret = candidate.retrieved_at or datetime.min
    if cand_ret > ex_ret:
        return candidate
    return existing


def build_fx_carry_factor_panel(
    observations: list[DataObservation],
    start_date: date = date(2020, 1, 1),
    end_date: date = date(2024, 12, 31),
    fx_entity: str = "EUR/USD",
    borrowing_series_id: str = "KR.MRR_FR.LEV",
    investment_series_id: str = "DGS1MO",
    sovereign_yield_series_id: str | None = "DGS3MO",
    strict_pit: bool = False,
    pit_mode: PITMode | str = PITMode.ESTIMATED_LAG,
    decision_time_utc: time = time(16, 0),
    min_observations: int = 50,
) -> FactorPanel:
    """Build a synchronized, multi-factor panel for FX carry simulation.

    Constructs 3 canonical factors:
    1. FX Log Returns (EUR/USD, daily)
    2. Borrowing Rate Changes (ECB Main Refinancing Operations, bps, daily)
    3. Investment Yield Changes (US Treasury 1M Yield, bps, daily)
    And optionally a 4th factor: US Treasury 3M Yield Changes.

    Rules:
    - Filters strictly genuine historical observations (is_synthetic=False).
    - Preserves observation availability and timestamps with row-level provenance.
    - If pit_mode=STRICT_VERIFIED (or strict_pit=True), requires verified timestamps and rejects estimated/retrospective.
      Fails clearly if verified observations are insufficient.
    - If pit_mode=ESTIMATED_LAG, enforces documented release schedules.
    - Uses joint trading days where FX rates and all required Treasury rates are genuinely observed (Option A: Common Complete Panel).
    - Never uses cross-series substitution (e.g. NEVER substitutes DGS1MO for missing DGS3MO).
    - Represents ECB policy rate as prevailing rate on joint trading days (piecewise-constant without future look-ahead).
    - Deterministically resolves duplicates and revisions.
    """
    audit_log: list[str] = []

    if strict_pit and pit_mode == PITMode.ESTIMATED_LAG:
        mode = PITMode.STRICT_VERIFIED
    elif isinstance(pit_mode, str):
        mode = PITMode(pit_mode)
    else:
        mode = pit_mode

    # 1. Enforce strict verified availability data sufficiency
    if mode == PITMode.STRICT_VERIFIED:
        verified_count = sum(
            1 for o in observations
            if not getattr(o, "is_synthetic", False)
            and start_date <= o.observation_date <= end_date
            and o.availability_evidence == AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED
            and o.publication_timestamp is not None
        )
        if verified_count < 50:
            raise ValueError(
                f"Strict verified PIT mode requested, but dataset contains {verified_count} verified observations. "
                f"Strict verified PIT cannot support a genuine historical experiment with this dataset. "
                f"Use PITMode.ESTIMATED_LAG for estimated-PIT research or PITMode.RESEARCH_ONLY for retrospective research."
            )
        allowed_classifications = (DataClassification.REAL_VERIFIED,)
    elif mode == PITMode.ESTIMATED_LAG:
        allowed_classifications = (
            DataClassification.REAL_VERIFIED,
            DataClassification.REAL_ESTIMATED_AVAILABILITY,
        )
    else:  # RESEARCH_ONLY
        allowed_classifications = (
            DataClassification.REAL_VERIFIED,
            DataClassification.REAL_ESTIMATED_AVAILABILITY,
            DataClassification.REAL_RETROSPECTIVE,
        )

    valid_obs = [
        o for o in observations
        if start_date <= o.observation_date <= end_date
        and not o.is_synthetic
        and o.classification in allowed_classifications
        and (mode == PITMode.RESEARCH_ONLY or o.availability_evidence != AvailabilityEvidence.RETROSPECTIVE)
        and (mode != PITMode.STRICT_VERIFIED or o.availability_evidence == AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED)
    ]
    audit_log.append(
        f"Filtered {len(valid_obs)} valid real observations between {start_date} and {end_date} (pit_mode={mode.value})."
    )

    # 2. Extract series candidate pools preserving all revisions
    fx_candidates_by_date: dict[date, list[DataObservation]] = defaultdict(list)
    borrowing_candidates: list[DataObservation] = []
    invest_candidates_by_date: dict[date, list[DataObservation]] = defaultdict(list)
    sov_candidates_by_date: dict[date, list[DataObservation]] = defaultdict(list)
    all_invest_candidates: list[DataObservation] = []
    all_sov_candidates: list[DataObservation] = []

    fx_target_codes = {fx_entity, fx_entity.replace("/", "_"), fx_entity.replace("_", "/")}
    if "/" in fx_entity:
        p1, p2 = fx_entity.split("/", 1)
        fx_target_codes.update({f"{p2}/{p1}", f"{p2}_{p1}"})
    elif "_" in fx_entity:
        p1, p2 = fx_entity.split("_", 1)
        fx_target_codes.update({f"{p2}_{p1}", f"{p2}/{p1}"})
    for o in valid_obs:
        d = o.observation_date
        if o.kind == ObservationKind.EXCHANGE_RATE and (o.entity_code in fx_target_codes or getattr(o, "pair", None) in fx_target_codes):
            fx_candidates_by_date[d].append(o)
        elif o.kind == ObservationKind.INTEREST_RATE:
            if o.indicator_id == borrowing_series_id:
                borrowing_candidates.append(o)
            elif o.indicator_id == investment_series_id:
                invest_candidates_by_date[d].append(o)
                all_invest_candidates.append(o)
            elif sovereign_yield_series_id is not None and o.indicator_id == sovereign_yield_series_id:
                sov_candidates_by_date[d].append(o)
                all_sov_candidates.append(o)

    # 3. Complete common dates intersection across candidate series
    # Option A: Common complete panel if sovereign yield series has sufficient observations (>= min_observations)
    # Option B: Reduced 3-factor panel if sovereign yield series has insufficient observations
    # Never substitute missing values across series
    has_sovereign = sovereign_yield_series_id is not None and len(sov_candidates_by_date) >= min_observations
    common_set = set(fx_candidates_by_date.keys()).intersection(set(invest_candidates_by_date.keys()))
    if has_sovereign:
        common_set = common_set.intersection(set(sov_candidates_by_date.keys()))
        audit_log.append(f"Option A: Complete common panel with 4 factors (including {sovereign_yield_series_id}).")
    else:
        if sovereign_yield_series_id is not None:
            audit_log.append(
                f"Option B: Reduced research panel. Excluded optional factor '{sovereign_yield_series_id}' "
                f"due to insufficient observations ({len(sov_candidates_by_date)} < {min_observations}). Retaining 3-factor panel without cross-series substitution."
            )

    common_dates = sorted(common_set)
    if len(common_dates) < min_observations:
        raise ValueError(f"Insufficient aligned trading days across complete factor panel: {len(common_dates)}")
    audit_log.append(f"Synchronized complete common trading calendar with {len(common_dates)} active days.")

    # 4. Align raw level series across common trading dates with decision-time aware point-in-time availability
    aligned_dates: list[date] = []
    fx_raw: list[float] = []
    fx_canonical: list[float] = []
    borrowing_raw: list[float] = []
    borrowing_pts: list[float] = []
    invest_raw: list[float] = []
    invest_pts: list[float] = []
    sov_raw: list[float] = []
    sov_pts: list[float] = []

    # Keep track of corresponding DataObservation for provenance
    fx_aligned_obs: list[DataObservation] = []
    borrowing_aligned_obs: list[DataObservation] = []
    invest_aligned_obs: list[DataObservation] = []
    sov_aligned_obs: list[DataObservation] = []

    for d in common_dates:
        as_of_dt = get_session_decision_timestamp(d, decision_time_utc)

        # FX availability check with decision-time revision resolution
        fx_o = resolve_observation_as_of(
            fx_candidates_by_date[d],
            as_of=as_of_dt,
            strict_executable=(mode == PITMode.STRICT_VERIFIED),
            pit_mode=mode,
        )
        if fx_o is None:
            continue

        # Prevailing borrowing rate (ECB) as of decision timestamp
        borrow_subset = [o for o in borrowing_candidates if o.observation_date <= d]
        prevailing_borrowing_obs = resolve_observation_as_of(
            borrow_subset,
            as_of=as_of_dt,
            strict_executable=(mode == PITMode.STRICT_VERIFIED),
            pit_mode=mode,
        )
        if prevailing_borrowing_obs is None:
            continue

        # Investment rate (DGS1MO) as of decision timestamp
        if mode == PITMode.RESEARCH_ONLY:
            invest_o = resolve_observation_as_of(
                invest_candidates_by_date[d],
                as_of=as_of_dt,
                strict_executable=False,
                pit_mode=mode,
            )
        else:
            invest_subset = [o for o in all_invest_candidates if o.observation_date <= d]
            invest_o = resolve_observation_as_of(
                invest_subset,
                as_of=as_of_dt,
                strict_executable=(mode == PITMode.STRICT_VERIFIED),
                pit_mode=mode,
            )
        if invest_o is None:
            continue

        # Sovereign yield (DGS3MO) as of decision timestamp
        if has_sovereign:
            if mode == PITMode.RESEARCH_ONLY:
                sov_o = resolve_observation_as_of(
                    sov_candidates_by_date[d],
                    as_of=as_of_dt,
                    strict_executable=False,
                    pit_mode=mode,
                )
            else:
                sov_subset = [o for o in all_sov_candidates if o.observation_date <= d]
                sov_o = resolve_observation_as_of(
                    sov_subset,
                    as_of=as_of_dt,
                    strict_executable=(mode == PITMode.STRICT_VERIFIED),
                    pit_mode=mode,
                )
            if sov_o is None:
                continue
        else:
            sov_o = None

        fx_canon_val = _normalize_fx_quote_to_usd_per_eur(fx_o)
        borrowing_pts_val = _normalize_rate_to_percentage_points(prevailing_borrowing_obs)
        invest_pts_val = _normalize_rate_to_percentage_points(invest_o)

        aligned_dates.append(d)
        fx_raw.append(fx_o.value)
        fx_canonical.append(fx_canon_val)
        borrowing_raw.append(prevailing_borrowing_obs.value)
        borrowing_pts.append(borrowing_pts_val)
        invest_raw.append(invest_o.value)
        invest_pts.append(invest_pts_val)

        fx_aligned_obs.append(fx_o)
        borrowing_aligned_obs.append(prevailing_borrowing_obs)
        invest_aligned_obs.append(invest_o)

        if has_sovereign and sov_o is not None:
            sov_pts_val = _normalize_rate_to_percentage_points(sov_o)
            sov_raw.append(sov_o.value)
            sov_pts.append(sov_pts_val)
            sov_aligned_obs.append(sov_o)

    if len(aligned_dates) < min_observations:
        raise ValueError(f"Insufficient aligned trading days across complete factor panel after PIT filtering: {len(aligned_dates)}")


    # 5. Compute mathematical factor transformations (differences & log returns)
    factor_dates = aligned_dates[1:]

    # Log returns computed strictly from canonical USD per EUR levels
    fx_returns = compute_log_returns(fx_canonical)
    # Basis point differences computed from validated percentage points
    borrowing_diffs_bps = compute_differences(borrowing_pts, in_bps=True)
    invest_diffs_bps = compute_differences(invest_pts, in_bps=True)
    sov_diffs_bps = compute_differences(sov_pts, in_bps=True) if has_sovereign else []

    # 6. Build row-level provenance records
    row_provenance: dict[str, list[FactorRowProvenance]] = defaultdict(list)
    for idx, d in enumerate(factor_dates):
        # Index in aligned series is idx + 1
        i = idx + 1
        fx_o = fx_aligned_obs[i]
        row_provenance["FX_EUR_USD_LOGRET"].append(
            FactorRowProvenance(
                observation_date=d,
                observation_timestamp=fx_o.observation_timestamp,
                publication_timestamp=fx_o.publication_timestamp,
                source_id=fx_o.source_id,
                series_id=fx_o.entity_code,
                raw_value=fx_raw[i],
                raw_unit=fx_o.unit,
                quote_convention=fx_o.quote_convention.value if fx_o.quote_convention else None,
                normalized_level=fx_canonical[i],
                transformed_value=fx_returns[idx],
                pair=fx_o.entity_code,
                base_currency=fx_o.base_currency,
                quote_currency=fx_o.quote_currency,
                data_classification=fx_o.classification,
                availability_evidence=fx_o.availability_evidence,
                revision=fx_o.revision,
            )
        )

        b_o = borrowing_aligned_obs[i]
        row_provenance["RATE_DIFF_EUR_BORROW_BPS"].append(
            FactorRowProvenance(
                observation_date=d,
                observation_timestamp=b_o.observation_timestamp,
                publication_timestamp=b_o.publication_timestamp,
                source_id=b_o.source_id,
                series_id=b_o.indicator_id or borrowing_series_id,
                raw_value=borrowing_raw[i],
                raw_unit=b_o.unit,
                normalized_level=borrowing_pts[i],
                transformed_value=borrowing_diffs_bps[idx],
                pair=None,
                base_currency="EUR",
                quote_currency=None,
                data_classification=b_o.classification,
                availability_evidence=b_o.availability_evidence,
                revision=b_o.revision,
            )
        )

        inv_o = invest_aligned_obs[i]
        row_provenance["YIELD_DIFF_USD_1M_BPS"].append(
            FactorRowProvenance(
                observation_date=d,
                observation_timestamp=inv_o.observation_timestamp,
                publication_timestamp=inv_o.publication_timestamp,
                source_id=inv_o.source_id,
                series_id=inv_o.indicator_id or investment_series_id,
                raw_value=invest_raw[i],
                raw_unit=inv_o.unit,
                normalized_level=invest_pts[i],
                transformed_value=invest_diffs_bps[idx],
                pair=None,
                base_currency="USD",
                quote_currency=None,
                data_classification=inv_o.classification,
                availability_evidence=inv_o.availability_evidence,
                revision=inv_o.revision,
            )
        )

        if has_sovereign:
            s_o = sov_aligned_obs[i]
            row_provenance["YIELD_DIFF_USD_3M_BPS"].append(
                FactorRowProvenance(
                    observation_date=d,
                    observation_timestamp=s_o.observation_timestamp,
                    publication_timestamp=s_o.publication_timestamp,
                    source_id=s_o.source_id,
                    series_id=s_o.indicator_id or sovereign_yield_series_id,
                    raw_value=sov_raw[i],
                    raw_unit=s_o.unit,
                    normalized_level=sov_pts[i],
                    transformed_value=sov_diffs_bps[idx],
                    pair=None,
                    base_currency="USD",
                    quote_currency=None,
                    data_classification=s_o.classification,
                    availability_evidence=s_o.availability_evidence,
                    revision=s_o.revision,
                )
            )

    # 7. Define MarketFactor metadata specifications
    factors = [
        MarketFactor(
            factor_id="FX_EUR_USD_LOGRET",
            category=FactorCategory.FX_RETURN,
            asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY,
            original_unit="USD_per_EUR",
            normalized_unit="log_return",
            source_id="frankfurter",
            series_id="ECB_REFERENCE",
            transformation=TransformationMethod.LOG_RETURN,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
            calibration_start=start_date,
            calibration_end=end_date,
            description="Daily log returns of EUR/USD exchange rate",
        ),
        MarketFactor(
            factor_id="RATE_DIFF_EUR_BORROW_BPS",
            category=FactorCategory.BORROWING_RATE_CHANGE,
            asset_or_currency="EUR",
            frequency=Frequency.DAILY,
            original_unit="percent",
            normalized_unit="basis_points",
            source_id="ecb",
            series_id=borrowing_series_id,
            transformation=TransformationMethod.FIRST_DIFFERENCE_BPS,
            missing_data_treatment=MissingDataTreatment.PIECEWISE_CONSTANT,
            calibration_start=start_date,
            calibration_end=end_date,
            description="Daily changes in ECB Main Refinancing Operations rate (bps)",
        ),
        MarketFactor(
            factor_id="YIELD_DIFF_USD_1M_BPS",
            category=FactorCategory.SOVEREIGN_YIELD_CHANGE,
            asset_or_currency="USD",
            frequency=Frequency.DAILY,
            original_unit="percent",
            normalized_unit="basis_points",
            source_id="us_treasury",
            series_id=investment_series_id,
            transformation=TransformationMethod.FIRST_DIFFERENCE_BPS,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
            calibration_start=start_date,
            calibration_end=end_date,
            description="Daily changes in US Treasury 1-Month Constant Maturity Yield (bps)",
        ),
    ]

    values = {
        "FX_EUR_USD_LOGRET": fx_returns,
        "RATE_DIFF_EUR_BORROW_BPS": borrowing_diffs_bps,
        "YIELD_DIFF_USD_1M_BPS": invest_diffs_bps,
    }

    raw_levels = {
        "FX_EUR_USD_LOGRET": fx_raw[1:],
        "RATE_DIFF_EUR_BORROW_BPS": borrowing_raw[1:],
        "YIELD_DIFF_USD_1M_BPS": invest_raw[1:],
    }

    canonical_levels = {
        "FX_EUR_USD_LOGRET": fx_canonical[1:],
        "RATE_DIFF_EUR_BORROW_BPS": borrowing_pts[1:],
        "YIELD_DIFF_USD_1M_BPS": invest_pts[1:],
    }

    if has_sovereign:
        factors.append(
            MarketFactor(
                factor_id="YIELD_DIFF_USD_3M_BPS",
                category=FactorCategory.SOVEREIGN_YIELD_CHANGE,
                asset_or_currency="USD",
                frequency=Frequency.DAILY,
                original_unit="percent",
                normalized_unit="basis_points",
                source_id="us_treasury",
                series_id=sovereign_yield_series_id,
                transformation=TransformationMethod.FIRST_DIFFERENCE_BPS,
                missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
                calibration_start=start_date,
                calibration_end=end_date,
                description="Daily changes in US Treasury 3-Month Constant Maturity Yield (bps)",
            )
        )
        values["YIELD_DIFF_USD_3M_BPS"] = sov_diffs_bps
        raw_levels["YIELD_DIFF_USD_3M_BPS"] = sov_raw[1:]
        canonical_levels["YIELD_DIFF_USD_3M_BPS"] = sov_pts[1:]

    audit_log.append(
        f"Successfully constructed FactorPanel with {len(factors)} factors over {len(factor_dates)} transition days ({len(aligned_dates)} aligned level days) without cross-series substitution."
    )

    return FactorPanel(
        factors=factors,
        dates=factor_dates,
        level_dates=aligned_dates,
        values=values,
        raw_levels=raw_levels,
        canonical_levels=canonical_levels,
        aligned_level_count=len(aligned_dates),
        transition_count=len(factor_dates),
        first_level_date=aligned_dates[0],
        last_level_date=aligned_dates[-1],
        first_transition_date=factor_dates[0],
        last_transition_date=factor_dates[-1],
        calendar_name="TARGET2_USFED_JOINT",
        effective_sample_size=len(factor_dates),
        is_aligned=True,
        alignment_audit=audit_log,
        row_provenance=dict(row_provenance),
        pit_mode=mode.value,
    )


def resolve_initial_market_levels(
    observations: Sequence[DataObservation],
    as_of_decision_timestamp: datetime = datetime(2024, 1, 2, 16, 0, 0, tzinfo=timezone.utc),
    pit_mode: PITMode | str = PITMode.ESTIMATED_LAG,
    fx_entity: str = "EUR/USD",
    borrowing_series_id: str = "KR.MRR_FR.LEV",
    investment_series_id: str = "DGS1MO",
) -> InitialMarketLevelsReport:
    """Ground simulation initial market conditions dynamically from latest valid historical observations.

    Resolves:
    1. Initial FX rate (provider quote currency per base, e.g. USD per EUR).
    2. Initial borrowing rate (annual decimal rate, e.g. 0.045 for 4.5%).
    3. Initial investment rate (annual decimal rate, e.g. 0.056 for 5.6%).

    Enforces the specified point-in-time policy as of as_of_decision_timestamp.
    """
    mode = PITMode(pit_mode) if isinstance(pit_mode, str) else pit_mode

    # 1. Resolve FX observation
    fx_cands = [
        o for o in observations
        if not getattr(o, "is_synthetic", False)
        and o.kind == ObservationKind.EXCHANGE_RATE
        and o.entity_code == fx_entity
        and is_observation_available_as_of(o, as_of=as_of_decision_timestamp, pit_mode=mode)[0]
    ]
    if not fx_cands:
        raise ValueError(
            f"No available FX observations for '{fx_entity}' as of {as_of_decision_timestamp} under pit_mode={mode.value}."
        )
    fx_max_date = max(o.observation_date for o in fx_cands)
    fx_obs = resolve_observation_as_of(
        [o for o in fx_cands if o.observation_date == fx_max_date],
        as_of=as_of_decision_timestamp,
        pit_mode=mode,
    )
    if fx_obs is None:
        raise ValueError(f"Failed to resolve FX observation for '{fx_entity}' as of {as_of_decision_timestamp}.")

    initial_fx = _normalize_fx_quote_to_usd_per_eur(fx_obs)

    # 2. Resolve borrowing rate observation
    b_cands = [
        o for o in observations
        if not getattr(o, "is_synthetic", False)
        and o.kind == ObservationKind.INTEREST_RATE
        and o.indicator_id == borrowing_series_id
        and is_observation_available_as_of(o, as_of=as_of_decision_timestamp, pit_mode=mode)[0]
    ]
    if not b_cands:
        raise ValueError(
            f"No available borrowing rate observations for '{borrowing_series_id}' as of {as_of_decision_timestamp} under pit_mode={mode.value}."
        )
    b_max_date = max(o.observation_date for o in b_cands)
    b_obs = resolve_observation_as_of(
        [o for o in b_cands if o.observation_date == b_max_date],
        as_of=as_of_decision_timestamp,
        pit_mode=mode,
    )
    if b_obs is None:
        raise ValueError(
            f"Failed to resolve borrowing rate observation for '{borrowing_series_id}' as of {as_of_decision_timestamp}."
        )

    initial_borrowing = _normalize_rate_to_decimal(b_obs)

    # 3. Resolve investment rate observation
    inv_cands = [
        o for o in observations
        if not getattr(o, "is_synthetic", False)
        and o.kind == ObservationKind.INTEREST_RATE
        and o.indicator_id == investment_series_id
        and is_observation_available_as_of(o, as_of=as_of_decision_timestamp, pit_mode=mode)[0]
    ]
    if not inv_cands:
        raise ValueError(
            f"No available investment yield observations for '{investment_series_id}' as of {as_of_decision_timestamp} under pit_mode={mode.value}."
        )
    inv_max_date = max(o.observation_date for o in inv_cands)
    inv_obs = resolve_observation_as_of(
        [o for o in inv_cands if o.observation_date == inv_max_date],
        as_of=as_of_decision_timestamp,
        pit_mode=mode,
    )
    if inv_obs is None:
        raise ValueError(
            f"Failed to resolve investment rate observation for '{investment_series_id}' as of {as_of_decision_timestamp}."
        )

    initial_investment = _normalize_rate_to_decimal(inv_obs)

    notes = [
        f"Grounded initial FX rate: {initial_fx:.6f} USD/EUR from {fx_obs.source_id} {fx_obs.entity_code} on {fx_obs.observation_date} (raw={fx_obs.value}, unit={fx_obs.unit}).",
        f"Grounded initial borrowing rate: {initial_borrowing:.4f} ({initial_borrowing*100:.2f}%) from {b_obs.source_id} {b_obs.indicator_id} on {b_obs.observation_date} (unit={b_obs.unit}).",
        f"Grounded initial investment rate: {initial_investment:.4f} ({initial_investment*100:.2f}%) from {inv_obs.source_id} {inv_obs.indicator_id} on {inv_obs.observation_date} (unit={inv_obs.unit}).",
        f"Resolved strictly point-in-time as of {as_of_decision_timestamp.isoformat()} under policy {mode.value}.",
    ]

    return InitialMarketLevelsReport(
        as_of_decision_timestamp=as_of_decision_timestamp,
        pit_mode=mode.value,
        initial_fx_rate=initial_fx,
        initial_borrowing_rate=initial_borrowing,
        initial_investment_rate=initial_investment,
        fx_observation_date=fx_obs.observation_date,
        fx_availability_timestamp=get_effective_availability_timestamp(fx_obs),
        fx_source_id=fx_obs.source_id,
        fx_entity_code=fx_obs.entity_code,
        fx_raw_value=fx_obs.value,
        borrowing_observation_date=b_obs.observation_date,
        borrowing_availability_timestamp=get_effective_availability_timestamp(b_obs),
        borrowing_source_id=b_obs.source_id,
        borrowing_indicator_id=b_obs.indicator_id or borrowing_series_id,
        borrowing_raw_value=b_obs.value,
        investment_observation_date=inv_obs.observation_date,
        investment_availability_timestamp=get_effective_availability_timestamp(inv_obs),
        investment_source_id=inv_obs.source_id,
        investment_indicator_id=inv_obs.indicator_id or investment_series_id,
        investment_raw_value=inv_obs.value,
        grounding_notes=notes,
    )

