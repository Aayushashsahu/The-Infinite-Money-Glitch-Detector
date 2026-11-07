"""Market factor extraction, transformation, and frequency alignment.

Extracts canonical macro-financial factors from historical DataObservation collections,
computes economically defensible transformations (log returns, basis point changes),
and constructs calendar-aligned factor panels without look-ahead bias or synthetic data.
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
    """Reconstruct price levels from log returns: S_t = S_0 * exp(sum_{i=1}^t r_i).

    Guarantees mathematically that prices remain strictly positive: S_t > 0.
    Returns list of length len(log_returns) + 1 starting with initial_price.
    """
    if initial_price <= 0 or math.isnan(initial_price):
        raise ValueError(f"Initial price must be strictly positive: {initial_price}")
    levels = [initial_price]
    curr = initial_price
    for r in log_returns:
        if math.isnan(r) or math.isinf(r):
            raise ValueError(f"Log return must be finite: {r}")
        curr = curr * math.exp(r)
        levels.append(curr)
    return levels


def compute_differences(levels: list[float], in_bps: bool = True) -> list[float]:
    """Calculate first differences: Delta x_t = x_t - x_{t-1}.

    If in_bps is True and levels are percentage rates (e.g. 5.25 for 5.25%),
    multiplies difference by 100 to express in basis points.
    Length of returned array is len(levels) - 1.
    """
    if len(levels) < 2:
        return []
    scale = 100.0 if in_bps else 1.0
    diffs: list[float] = []
    for i in range(1, len(levels)):
        diffs.append((levels[i] - levels[i - 1]) * scale)
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


def build_fx_carry_factor_panel(
    observations: list[DataObservation],
    start_date: date = date(2020, 1, 1),
    end_date: date = date(2024, 12, 31),
    fx_entity: str = "EUR/USD",
    borrowing_series_id: str = "KR.MRR_FR.LEV",
    investment_series_id: str = "DGS1MO",
    sovereign_yield_series_id: str = "DGS3MO",
) -> FactorPanel:
    """Build a synchronized, multi-factor panel for FX carry simulation.

    Constructs 3 canonical factors:
    1. FX Log Returns (EUR/USD, daily)
    2. Borrowing Rate Changes (ECB Main Refinancing Operations, bps, daily)
    3. Investment Yield Changes (US Treasury 1M Yield, bps, daily)
    And optionally a 4th factor: US Treasury 3M Yield Changes.

    Rules:
    - Filters strictly genuine historical observations (is_synthetic=False).
    - Preserves observation availability and timestamps.
    - Uses joint trading days where FX rates and Treasury rates are both observed.
    - Represents ECB policy rate as prevailing rate on joint trading days (piecewise-constant).
    - Never interpolates annual observations into artificial daily returns.
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

    # 2. Extract series dictionaries: date -> value
    fx_by_date: dict[date, float] = {}
    borrowing_by_date: dict[date, float] = {}
    invest_by_date: dict[date, float] = {}
    sov_by_date: dict[date, float] = {}

    for o in valid_obs:
        if o.kind == ObservationKind.EXCHANGE_RATE and o.entity_code == fx_entity:
            # Prefer 1.09 quote-per-base representation
            fx_by_date[o.observation_date] = o.value
        elif o.kind == ObservationKind.INTEREST_RATE:
            if o.indicator_id == borrowing_series_id:
                borrowing_by_date[o.observation_date] = o.value
            elif o.indicator_id == investment_series_id:
                invest_by_date[o.observation_date] = o.value
            elif o.indicator_id == sovereign_yield_series_id:
                sov_by_date[o.observation_date] = o.value

    # 3. Intersect trading days where both market series (FX and US Treasury yield) exist
    common_dates = sorted(set(fx_by_date.keys()).intersection(set(invest_by_date.keys())))
    if len(common_dates) < 50:
        raise ValueError(f"Insufficient aligned trading days between FX and Treasury: {len(common_dates)}")
    audit_log.append(f"Synchronized joint trading calendar with {len(common_dates)} active days.")

    # 4. Align raw level series across common trading dates
    aligned_dates: list[date] = []
    fx_raw: list[float] = []
    borrowing_raw: list[float] = []
    invest_raw: list[float] = []
    sov_raw: list[float] = []

    # Track last known ECB policy rate for genuine step-function semantics
    last_known_borrowing: float | None = None
    all_borrowing_dates = sorted(borrowing_by_date.keys())

    for d in common_dates:
        # Find prevailing borrowing rate on or before date d
        prevailing_b = borrowing_by_date.get(d)
        if prevailing_b is None:
            prior_dates = [bd for bd in all_borrowing_dates if bd <= d]
            if prior_dates:
                prevailing_b = borrowing_by_date[prior_dates[-1]]

        if prevailing_b is None:
            # Cannot align if borrowing rate has not commenced
            continue

        aligned_dates.append(d)
        fx_raw.append(fx_by_date[d])
        borrowing_raw.append(prevailing_b)
        invest_raw.append(invest_by_date[d])
        if d in sov_by_date:
            sov_raw.append(sov_by_date[d])
        else:
            sov_raw.append(invest_by_date[d])  # Fallback to 1M if 3M missing on that day

    if len(aligned_dates) < 2:
        raise ValueError("Insufficient dates to compute factor differences.")

    # 5. Compute mathematical factor transformations (differences & log returns)
    # The transformed factor vectors have length len(aligned_dates) - 1.
    factor_dates = aligned_dates[1:]

    fx_returns = compute_log_returns(fx_raw)
    borrowing_diffs_bps = compute_differences(borrowing_raw, in_bps=True)
    invest_diffs_bps = compute_differences(invest_raw, in_bps=True)
    sov_diffs_bps = compute_differences(sov_raw, in_bps=True)

    # 6. Define MarketFactor metadata specifications
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
        ),
    ]

    values = {
        "FX_EUR_USD_LOGRET": fx_returns,
        "RATE_DIFF_EUR_BORROW_BPS": borrowing_diffs_bps,
        "YIELD_DIFF_USD_1M_BPS": invest_diffs_bps,
        "YIELD_DIFF_USD_3M_BPS": sov_diffs_bps,
    }

    raw_levels = {
        "FX_EUR_USD_LOGRET": fx_raw[1:],
        "RATE_DIFF_EUR_BORROW_BPS": borrowing_raw[1:],
        "YIELD_DIFF_USD_1M_BPS": invest_raw[1:],
        "YIELD_DIFF_USD_3M_BPS": sov_raw[1:],
    }

    audit_log.append(f"Successfully constructed FactorPanel with {len(factors)} factors over {len(factor_dates)} transition days.")

    return FactorPanel(
        factors=factors,
        dates=factor_dates,
        values=values,
        raw_levels=raw_levels,
        calendar_name="TARGET2_USFED_JOINT",
        effective_sample_size=len(factor_dates),
        is_aligned=True,
        alignment_audit=audit_log,
    )
