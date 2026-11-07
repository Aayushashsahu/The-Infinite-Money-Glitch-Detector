"""Market factor extraction, transformation, and frequency alignment.

Extracts canonical macro-financial factors from historical DataObservation collections,
computes economically defensible transformations (log returns, basis point changes),
and constructs calendar-aligned factor panels without look-ahead bias, synthetic data,
or cross-series substitutions.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
import math

import numpy as np

from data.schemas import (
    AvailabilityEvidence,
    DataClassification,
    DataObservation,
    Frequency,
    ObservationKind,
)
from simulation.monte_carlo.schemas import (
    FactorCategory,
    FactorObservation,
    FactorPanel,
    FactorRowProvenance,
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


def get_effective_availability_timestamp(obs: DataObservation) -> datetime | None:
    """Compute effective point-in-time availability timestamp for an observation.

    Applies documented release schedules:
    - Retrospective: returns None (no forward availability evidence).
    - Verified exact timestamp: uses publication_timestamp ONLY if availability_evidence
      is explicitly EXACT_TIMESTAMP_VERIFIED.
    - EUR/USD exchange rate (ECB reference): published ~16:00 CET, available 17:00 CET (16:00 UTC) on observation date.
    - US Treasury yields (DGS1MO, DGS3MO): published daily by FRED on NEXT business day at ~15:00 UTC (~09:00 ET).
    - ECB policy rate (KR.MRR_FR.LEV): effective on effective_timestamp or 00:00 UTC on observation date.
    - Fallback: 23:59:59 UTC on observation date.
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

    # 3. Exchange Rate (EUR/USD ECB reference rate)
    if obs.kind == ObservationKind.EXCHANGE_RATE or obs.entity_code == "EUR/USD" or obs.source_id in ("frankfurter", "ecb"):
        sched_ts = datetime(obs_d.year, obs_d.month, obs_d.day, 16, 0, 0, tzinfo=timezone.utc)
    # 4. US Treasury yields: published next business day at 15:00 UTC
    elif (
        obs.indicator_id in ("DGS1MO", "DGS3MO")
        or obs.entity_code in ("DGS1MO", "DGS3MO", "USD")
        or obs.source_id == "us_treasury"
    ):
        weekday = obs_d.weekday()
        # Friday (4) -> Monday (+3), Saturday (5) -> Monday (+2), Sunday (6) -> Monday (+1), Weekday -> +1
        delta_days = 3 if weekday == 4 else (2 if weekday == 5 else 1)
        next_bday = obs_d + timedelta(days=delta_days)
        sched_ts = datetime(next_bday.year, next_bday.month, next_bday.day, 15, 0, 0, tzinfo=timezone.utc)
    # 5. ECB Policy rate: effective date/time
    elif (
        obs.indicator_id in ("KR.MRR_FR.LEV", "DFR")
        or obs.entity_code in ("ECB_EA", "EUR", "DFR")
        or obs.source_id == "policy_rates"
    ):
        if obs.effective_timestamp is not None:
            ts = obs.effective_timestamp
            sched_ts = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)
        else:
            sched_ts = datetime(obs_d.year, obs_d.month, obs_d.day, 0, 0, 0, tzinfo=timezone.utc)
    else:
        sched_ts = datetime(obs_d.year, obs_d.month, obs_d.day, 23, 59, 59, tzinfo=timezone.utc)

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
                mode = PITMode.ESTIMATED_LAG
        else:
            mode = pit_mode

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
        if (
            obs.classification == DataClassification.REAL_RETROSPECTIVE
            or obs.availability_evidence == AvailabilityEvidence.RETROSPECTIVE
        ):
            return False, "retrospective_evidence_rejected_in_estimated_lag_mode"

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

    def _sort_key(o: DataObservation):
        rev = o.revision if o.revision is not None else 0
        ts = o.publication_timestamp or o.retrieved_at or datetime.min
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (rev, ts)

    return max(available_obs, key=_sort_key)



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

    # 2. Extract series dictionaries: date -> DataObservation with deterministic revision resolution
    fx_obs_by_date: dict[date, DataObservation] = {}
    borrowing_obs_by_date: dict[date, DataObservation] = {}
    invest_obs_by_date: dict[date, DataObservation] = {}
    sov_obs_by_date: dict[date, DataObservation] = {}

    for o in valid_obs:
        d = o.observation_date
        if o.kind == ObservationKind.EXCHANGE_RATE and o.entity_code == fx_entity:
            fx_obs_by_date[d] = _resolve_observation(fx_obs_by_date[d], o) if d in fx_obs_by_date else o
        elif o.kind == ObservationKind.INTEREST_RATE:
            if o.indicator_id == borrowing_series_id:
                borrowing_obs_by_date[d] = _resolve_observation(borrowing_obs_by_date[d], o) if d in borrowing_obs_by_date else o
            elif o.indicator_id == investment_series_id:
                invest_obs_by_date[d] = _resolve_observation(invest_obs_by_date[d], o) if d in invest_obs_by_date else o
            elif sovereign_yield_series_id is not None and o.indicator_id == sovereign_yield_series_id:
                sov_obs_by_date[d] = _resolve_observation(sov_obs_by_date[d], o) if d in sov_obs_by_date else o

    # 3. Complete common dates intersection across required series
    # Option A: Common complete panel if sovereign yield series has sufficient observations (>= 50)
    # Option B: Reduced 3-factor panel if sovereign yield series has insufficient observations
    # Never substitute missing values across series
    has_sovereign = sovereign_yield_series_id is not None and len(sov_obs_by_date) >= 50
    common_set = set(fx_obs_by_date.keys()).intersection(set(invest_obs_by_date.keys()))
    if has_sovereign:
        common_set = common_set.intersection(set(sov_obs_by_date.keys()))
        audit_log.append(f"Option A: Complete common panel with 4 factors (including {sovereign_yield_series_id}).")
    else:
        if sovereign_yield_series_id is not None:
            audit_log.append(
                f"Option B: Reduced research panel. Excluded optional factor '{sovereign_yield_series_id}' "
                f"due to insufficient observations ({len(sov_obs_by_date)} < 50). Retaining 3-factor panel without cross-series substitution."
            )

    common_dates = sorted(common_set)
    if len(common_dates) < 50:
        raise ValueError(f"Insufficient aligned trading days across complete factor panel: {len(common_dates)}")
    audit_log.append(f"Synchronized complete common trading calendar with {len(common_dates)} active days.")

    # 4. Align raw level series across common trading dates with point-in-time availability
    import bisect

    aligned_dates: list[date] = []
    fx_raw: list[float] = []
    borrowing_raw: list[float] = []
    invest_raw: list[float] = []
    sov_raw: list[float] = []

    # Keep track of corresponding DataObservation for provenance
    fx_aligned_obs: list[DataObservation] = []
    borrowing_aligned_obs: list[DataObservation] = []
    invest_aligned_obs: list[DataObservation] = []
    sov_aligned_obs: list[DataObservation] = []

    all_borrowing_dates = sorted(borrowing_obs_by_date.keys())

    # Build sorted availability index for fast O(log N) point-in-time resolution
    invest_eff_list = sorted(
        [(get_effective_availability_timestamp(o), o) for o in invest_obs_by_date.values() if get_effective_availability_timestamp(o) is not None],
        key=lambda x: x[0],  # type: ignore[arg-type,return-value]
    )
    invest_eff_times = [x[0] for x in invest_eff_list]

    sov_eff_list = sorted(
        [(get_effective_availability_timestamp(o), o) for o in sov_obs_by_date.values() if get_effective_availability_timestamp(o) is not None],
        key=lambda x: x[0],  # type: ignore[arg-type,return-value]
    )
    sov_eff_times = [x[0] for x in sov_eff_list]

    borrowing_eff_list = sorted(
        [(get_effective_availability_timestamp(o), o) for o in borrowing_obs_by_date.values() if get_effective_availability_timestamp(o) is not None],
        key=lambda x: x[0],  # type: ignore[arg-type,return-value]
    )
    borrowing_eff_times = [x[0] for x in borrowing_eff_list]

    for d in common_dates:
        as_of_dt = get_session_decision_timestamp(d, decision_time_utc)
        fx_o = fx_obs_by_date[d]

        # FX availability check
        is_fx_avail, _ = is_observation_available_as_of(fx_o, as_of_dt, strict_executable=(mode == PITMode.STRICT_VERIFIED), pit_mode=mode)
        if not is_fx_avail:
            continue

        # Prevailing borrowing rate (ECB)
        if mode == PITMode.RESEARCH_ONLY:
            prior_dates = [bd for bd in all_borrowing_dates if bd <= d]
            if not prior_dates:
                continue
            prevailing_borrowing_obs = borrowing_obs_by_date[prior_dates[-1]]
        else:
            b_idx = bisect.bisect_right(borrowing_eff_times, as_of_dt) - 1
            if b_idx < 0:
                continue
            prevailing_borrowing_obs = borrowing_eff_list[b_idx][1]

        # Investment rate (DGS1MO)
        if mode == PITMode.RESEARCH_ONLY:
            invest_o = invest_obs_by_date[d]
        else:
            i_idx = bisect.bisect_right(invest_eff_times, as_of_dt) - 1
            if i_idx < 0:
                continue
            invest_o = invest_eff_list[i_idx][1]

        # Sovereign yield (DGS3MO)
        if has_sovereign:
            if mode == PITMode.RESEARCH_ONLY:
                sov_o = sov_obs_by_date[d]
            else:
                s_idx = bisect.bisect_right(sov_eff_times, as_of_dt) - 1
                if s_idx < 0:
                    continue
                sov_o = sov_eff_list[s_idx][1]
        else:
            sov_o = None

        aligned_dates.append(d)
        fx_raw.append(fx_o.value)
        borrowing_raw.append(prevailing_borrowing_obs.value)
        invest_raw.append(invest_o.value)

        fx_aligned_obs.append(fx_o)
        borrowing_aligned_obs.append(prevailing_borrowing_obs)
        invest_aligned_obs.append(invest_o)

        if has_sovereign and sov_o is not None:
            sov_raw.append(sov_o.value)
            sov_aligned_obs.append(sov_o)

    if len(aligned_dates) < 50:
        raise ValueError(f"Insufficient aligned trading days across complete factor panel after PIT filtering: {len(aligned_dates)}")


    # 5. Compute mathematical factor transformations (differences & log returns)
    factor_dates = aligned_dates[1:]

    fx_returns = compute_log_returns(fx_raw)
    borrowing_diffs_bps = compute_differences(borrowing_raw, in_bps=True)
    invest_diffs_bps = compute_differences(invest_raw, in_bps=True)
    sov_diffs_bps = compute_differences(sov_raw, in_bps=True) if has_sovereign else []

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
                transformed_value=fx_returns[idx],
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
                transformed_value=borrowing_diffs_bps[idx],
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
                transformed_value=invest_diffs_bps[idx],
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
                    transformed_value=sov_diffs_bps[idx],
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

    audit_log.append(
        f"Successfully constructed FactorPanel with {len(factors)} factors over {len(factor_dates)} transition days without cross-series substitution."
    )

    return FactorPanel(
        factors=factors,
        dates=factor_dates,
        values=values,
        raw_levels=raw_levels,
        calendar_name="TARGET2_USFED_JOINT",
        effective_sample_size=len(factor_dates),
        is_aligned=True,
        alignment_audit=audit_log,
        row_provenance=dict(row_provenance),
        pit_mode=mode.value,
    )
