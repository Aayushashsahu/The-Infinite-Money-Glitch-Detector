"""Market factor extraction, transformation, and frequency alignment.

Extracts canonical macro-financial factors from historical DataObservation collections,
computes economically defensible transformations (log returns, basis point changes),
and constructs calendar-aligned factor panels without look-ahead bias, synthetic data,
or cross-series substitutions.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
import math

import numpy as np

from data.schemas import DataClassification, DataObservation, Frequency, ObservationKind
from simulation.monte_carlo.schemas import (
    FactorCategory,
    FactorObservation,
    FactorPanel,
    FactorRowProvenance,
    MarketFactor,
    MissingDataTreatment,
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
    - Uses joint trading days where FX rates and all required Treasury rates are genuinely observed (Option A: Common Complete Panel).
    - Never uses cross-series substitution (e.g. NEVER substitutes DGS1MO for missing DGS3MO).
    - Represents ECB policy rate as prevailing rate on joint trading days (piecewise-constant without future look-ahead).
    - Deterministically resolves duplicates and revisions.
    """
    audit_log: list[str] = []

    # 1. Filter observations by date window and valid classifications
    valid_obs = [
        o for o in observations
        if start_date <= o.observation_date <= end_date
        and not o.is_synthetic
        and o.classification in (DataClassification.REAL_VERIFIED, DataClassification.REAL_RETROSPECTIVE)
    ]
    audit_log.append(f"Filtered {len(valid_obs)} valid real observations between {start_date} and {end_date}.")

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

    # 4. Align raw level series across common trading dates
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

    for d in common_dates:
        # Prevailing borrowing rate on or strictly before date d (no future look-ahead)
        prior_dates = [bd for bd in all_borrowing_dates if bd <= d]
        if not prior_dates:
            continue
        prevailing_borrowing_obs = borrowing_obs_by_date[prior_dates[-1]]

        aligned_dates.append(d)
        fx_o = fx_obs_by_date[d]
        invest_o = invest_obs_by_date[d]

        fx_raw.append(fx_o.value)
        borrowing_raw.append(prevailing_borrowing_obs.value)
        invest_raw.append(invest_o.value)

        fx_aligned_obs.append(fx_o)
        borrowing_aligned_obs.append(prevailing_borrowing_obs)
        invest_aligned_obs.append(invest_o)

        if has_sovereign:
            sov_o = sov_obs_by_date[d]
            sov_raw.append(sov_o.value)
            sov_aligned_obs.append(sov_o)

    if len(aligned_dates) < 2:
        raise ValueError("Insufficient dates to compute factor differences.")

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
    )
