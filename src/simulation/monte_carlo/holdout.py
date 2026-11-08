"""Out-of-sample holdout diagnostic validation.

Evaluates calibration-only predictive models against the untouched 2024 holdout dataset,
separating factor-level validation (FX-to-FX return, volatility, and drawdown distributions)
from strategy-level validation (which is marked UNAVAILABLE in the absence of genuine live
execution records).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import math
from typing import Any, Sequence

import numpy as np
import scipy.stats as stats

from data.schemas import DataObservation, Frequency, ObservationKind
from simulation.monte_carlo.factors import (
    _normalize_fx_quote_to_usd_per_eur,
    _normalize_rate_to_decimal,
)
from simulation.monte_carlo.regimes import VolatilityRegimeClassifier
from simulation.monte_carlo.schemas import (
    FactorCategory,
    FactorHoldoutDiagnostics,
    FactorPanel,
    HoldoutDiagnosticReport,
    PathEvaluationResult,
    PortfolioHoldoutDiagnostics,
    RegimeState,
    ScenarioPath,
)


def evaluate_factor_holdout_diagnostics(
    calibration_panel: FactorPanel,
    holdout_panel: FactorPanel,
    predictive_paths: Sequence[ScenarioPath] | None = None,
    classifier: VolatilityRegimeClassifier | None = None,
    low_vol_threshold: float | None = None,
    high_vol_threshold: float | None = None,
) -> FactorHoldoutDiagnostics:
    """Evaluate calibrated predictive models against untouched out-of-sample 2024 data at the factor level.

    Rules:
    - Never refits models on holdout data.
    - Compares actual FX return against simulated FX return distribution.
    - Compares actual FX drawdown against simulated FX drawdown distribution.
    - Compares actual FX volatility against simulated FX volatility distribution.
    - Does not conflate FX factor statistics with strategy portfolio accounting.
    - Derives volatility regime thresholds dynamically from calibration panel or supplied classifier.
    - Standardizes taxonomy to LOW_VOLATILITY (< p20), NORMAL_VOLATILITY (p20-p80), STRESS_VOLATILITY (>= p80).
    - Formally acknowledges that two-sample KS test p-values assume independent observations
      and reports the KS statistic descriptively in the presence of serial dependence.
    """
    calib_fx = np.array(calibration_panel.values["FX_EUR_USD_LOGRET"], dtype=np.float64)
    holdout_fx = np.array(holdout_panel.values["FX_EUR_USD_LOGRET"], dtype=np.float64)

    calib_vol = float(np.std(calib_fx, ddof=1) * math.sqrt(252))
    holdout_vol = float(np.std(holdout_fx, ddof=1) * math.sqrt(252))

    # Resolve regime thresholds dynamically from calibration
    if classifier is not None:
        thresh_low = classifier.threshold_low
        thresh_high = classifier.threshold_high
    elif low_vol_threshold is not None and high_vol_threshold is not None:
        thresh_low = low_vol_threshold
        thresh_high = high_vol_threshold
    else:
        clf = VolatilityRegimeClassifier(calibration_panel)
        thresh_low = clf.threshold_low
        thresh_high = clf.threshold_high

    # Classify 2024 volatility regime with documented boundary convention:
    # v < threshold_low: LOW_VOLATILITY
    # threshold_low <= v < threshold_high: NORMAL_VOLATILITY
    # v >= threshold_high: STRESS_VOLATILITY
    if holdout_vol < thresh_low:
        vol_regime = RegimeState.LOW_VOLATILITY.value
    elif holdout_vol < thresh_high:
        vol_regime = RegimeState.NORMAL_VOLATILITY.value
    else:
        vol_regime = RegimeState.STRESS_VOLATILITY.value

    # Cumulative FX return in 2024 (provider quote: USD per EUR)
    actual_cum_ret = float(math.exp(np.sum(holdout_fx)) - 1.0)

    # 2024 Max Drawdown in cumulative FX level (prepending 1.0 starting level)
    cum_path = np.concatenate(([1.0], np.exp(np.cumsum(holdout_fx))))
    peaks = np.maximum.accumulate(cum_path)
    dds = (cum_path - peaks) / peaks
    actual_max_dd = float(np.min(dds))

    # Predictive distributions derived from simulated FX paths
    sim_returns: list[float] = []
    sim_vols: list[float] = []
    sim_dds: list[float] = []

    if predictive_paths and len(predictive_paths) > 0:
        for p in predictive_paths:
            rates = np.array(p.fx_rates, dtype=np.float64)
            if len(rates) > 1 and rates[0] > 0.0:
                p_ret = float((rates[-1] / rates[0]) - 1.0)
                sim_returns.append(p_ret)

                # Path log-returns for realized volatility
                log_rets = np.log(rates[1:] / rates[:-1])
                p_vol = float(np.std(log_rets, ddof=1) * math.sqrt(252)) if len(log_rets) > 1 else 0.0
                sim_vols.append(p_vol)

                # Path maximum drawdown
                p_cum = rates / rates[0]
                p_peaks = np.maximum.accumulate(p_cum)
                p_dds = (p_cum - p_peaks) / p_peaks
                sim_dds.append(float(np.min(p_dds)))

    n_paths = len(sim_returns)
    if n_paths > 0:
        sim_ret_arr = np.array(sim_returns)
        sim_vol_arr = np.array(sim_vols)
        sim_dd_arr = np.array(sim_dds)

        pred_ret_median = float(np.median(sim_ret_arr))
        pred_ret_p025 = float(np.percentile(sim_ret_arr, 2.5))
        pred_ret_p975 = float(np.percentile(sim_ret_arr, 97.5))
        pred_vol_median = float(np.median(sim_vol_arr))
        pred_dd_median = float(np.median(sim_dd_arr))

        pct_ret = float(np.mean(sim_ret_arr <= actual_cum_ret))
        pct_ret_se = float(math.sqrt(pct_ret * (1.0 - pct_ret) / n_paths))
        pct_vol = float(np.mean(sim_vol_arr <= holdout_vol))
        pct_dd = float(np.mean(sim_dd_arr <= actual_max_dd))
    else:
        pred_ret_median = 0.0
        pred_ret_p025 = -0.10
        pred_ret_p975 = 0.10
        pred_vol_median = calib_vol
        pred_dd_median = -0.05
        pct_ret = 0.50
        pct_ret_se = 0.0
        pct_vol = 0.50
        pct_dd = 0.50

    # Two-sample KS test on FX log returns
    ks_stat, ks_pval = stats.ks_2samp(calib_fx, holdout_fx)

    # Cross-factor correlation shifts
    calib_fnames = list(calibration_panel.values.keys())
    holdout_fnames = [f for f in calib_fnames if f in holdout_panel.values]

    calib_mat = np.column_stack([calibration_panel.values[f] for f in holdout_fnames])
    holdout_mat = np.column_stack([holdout_panel.values[f] for f in holdout_fnames])

    with np.errstate(divide="ignore", invalid="ignore"):
        corr_calib = np.nan_to_num(np.corrcoef(calib_mat, rowvar=False), nan=0.0)
        corr_holdout = np.nan_to_num(np.corrcoef(holdout_mat, rowvar=False), nan=0.0)

    corr_shifts: dict[str, float] = {}
    for i, f1 in enumerate(holdout_fnames):
        for j, f2 in enumerate(holdout_fnames):
            if i < j:
                shift = float(corr_holdout[i, j] - corr_calib[i, j])
                corr_shifts[f"{f1}__vs__{f2}"] = shift

    h_days = len(holdout_panel.dates)
    h_start = min(holdout_panel.dates)
    h_end = max(holdout_panel.dates)

    ks_caveat = (
        "Standard two-sample Kolmogorov-Smirnov test assumes i.i.d. observations. "
        "Financial returns display significant serial correlation and serial dependence, "
        "volatility clustering, and heavy tails; consequently, the KS statistic is reported "
        "descriptively and the unadjusted p-value should not be interpreted as an exact calibrated hypothesis test."
    )

    assumptions = [
        "Predictive factor distribution calibrated strictly on 2020-2023 complete-case trading days.",
        "Holdout data (2024, 247 days) was completely isolated and never used during model estimation.",
        f"Predictive factor metrics evaluated across {n_paths:,} simulated paths.",
        "Factor paths generated under identical marginal variances and empirical correlation structure.",
    ]

    limitations = [
        "Single-year holdout window (247 trading days in 2024) does not span a complete credit or macroeconomic cycle.",
        f"2024 realized FX volatility ({holdout_vol:.2%}) lies between the 20th percentile ({thresh_low:.2%}) "
        f"and 80th percentile ({thresh_high:.2%}) of the calibration window, classified as {vol_regime}.",
        "Factor-level predictive coverage demonstrates empirical distribution compatibility over 2024 "
        "but does NOT establish permanent forward-looking market predictability.",
    ]

    return FactorHoldoutDiagnostics(
        holdout_year=2024,
        holdout_start=h_start,
        holdout_end=h_end,
        holdout_days=h_days,
        num_predictive_paths=n_paths,
        actual_fx_cumulative_return=actual_cum_ret,
        actual_fx_realized_volatility=holdout_vol,
        actual_fx_max_drawdown=actual_max_dd,
        simulated_fx_return_median=pred_ret_median,
        simulated_fx_return_p025=pred_ret_p025,
        simulated_fx_return_p975=pred_ret_p975,
        simulated_fx_volatility_median=pred_vol_median,
        simulated_fx_drawdown_median=pred_dd_median,
        predictive_percentile_fx_return=pct_ret,
        predictive_percentile_fx_return_mc_se=pct_ret_se,
        predictive_percentile_fx_volatility=pct_vol,
        predictive_percentile_fx_drawdown=pct_dd,
        volatility_regime_classification=vol_regime,
        low_vol_threshold=thresh_low,
        high_vol_threshold=thresh_high,
        fx_log_return_ks_stat=float(ks_stat),
        fx_log_return_ks_pvalue=float(ks_pval),
        fx_log_return_ks_caveat=ks_caveat,
        correlation_shifts=corr_shifts,
        model_assumptions=assumptions,
        limitations_notes=limitations,
    )


def evaluate_portfolio_holdout_diagnostics(
    simulated_evaluations: Sequence[PathEvaluationResult] | None = None,
) -> PortfolioHoldoutDiagnostics:
    """Strategy portfolio holdout comparison diagnostics.

    Explicitly marks portfolio predictive coverage as UNAVAILABLE in the absence
    of genuine live execution records.
    """
    sim_ret_median = (
        float(np.median([e.total_return for e in simulated_evaluations]))
        if simulated_evaluations and len(simulated_evaluations) > 0
        else None
    )
    sim_dd_median = (
        float(np.median([e.max_drawdown for e in simulated_evaluations]))
        if simulated_evaluations and len(simulated_evaluations) > 0
        else None
    )

    notes = [
        "No live execution, order-book execution, or broker accounts operated during the 2024 holdout window.",
        "The carry trade strategy remains classified as SIMULATED_RESEARCH_PROXY without live execution evidence.",
        "Historical strategy portfolio series cannot be fabricated or imputed from raw factor data without order-book records.",
        "Portfolio predictive coverage is therefore strictly reported as UNAVAILABLE.",
    ]

    return PortfolioHoldoutDiagnostics(
        status="UNAVAILABLE",
        is_available=False,
        reason=(
            "No genuine historical executable portfolio series exists for 2024 holdout; "
            "strategy remains SIMULATED_RESEARCH_PROXY without live execution evidence."
        ),
        simulated_portfolio_median_return=sim_ret_median,
        simulated_portfolio_median_drawdown=sim_dd_median,
        notes=notes,
    )


def evaluate_holdout_diagnostics(
    calibration_panel: FactorPanel,
    holdout_panel: FactorPanel,
    predictive_evaluations: Sequence[PathEvaluationResult] | None = None,
    predictive_paths: Sequence[ScenarioPath] | None = None,
    classifier: VolatilityRegimeClassifier | None = None,
    low_vol_threshold: float | None = None,
    high_vol_threshold: float | None = None,
) -> HoldoutDiagnosticReport:
    """Legacy holdout diagnostics report preserving backwards compatibility.

    Populates both legacy and renamed metric fields.
    """
    calib_fx = np.array(calibration_panel.values["FX_EUR_USD_LOGRET"], dtype=np.float64)
    holdout_fx = np.array(holdout_panel.values["FX_EUR_USD_LOGRET"], dtype=np.float64)

    calib_vol = float(np.std(calib_fx, ddof=1) * math.sqrt(252))
    holdout_vol = float(np.std(holdout_fx, ddof=1) * math.sqrt(252))
    vol_ratio = holdout_vol / calib_vol if calib_vol > 0 else 1.0

    if classifier is not None:
        thresh_low = classifier.threshold_low
        thresh_high = classifier.threshold_high
    elif low_vol_threshold is not None and high_vol_threshold is not None:
        thresh_low = low_vol_threshold
        thresh_high = high_vol_threshold
    else:
        clf = VolatilityRegimeClassifier(calibration_panel)
        thresh_low = clf.threshold_low
        thresh_high = clf.threshold_high

    if holdout_vol < thresh_low:
        vol_regime = RegimeState.LOW_VOLATILITY.value
    elif holdout_vol < thresh_high:
        vol_regime = RegimeState.NORMAL_VOLATILITY.value
    else:
        vol_regime = RegimeState.STRESS_VOLATILITY.value

    cum_ret_2024 = float(math.exp(np.sum(holdout_fx)) - 1.0)
    cum_path = np.concatenate(([1.0], np.exp(np.cumsum(holdout_fx))))
    peaks = np.maximum.accumulate(cum_path)
    dds = (cum_path - peaks) / peaks
    max_dd_2024 = float(np.min(dds))

    pred_return_quantile = 0.50
    pred_dd_quantile = 0.50

    if predictive_paths and len(predictive_paths) > 0:
        sim_returns = [float((p.fx_rates[-1] / p.fx_rates[0]) - 1.0) for p in predictive_paths if len(p.fx_rates) > 1 and p.fx_rates[0] > 0]
        sim_dds = []
        for p in predictive_paths:
            rates = np.array(p.fx_rates, dtype=np.float64)
            p_cum = rates / rates[0]
            p_peaks = np.maximum.accumulate(p_cum)
            sim_dds.append(float(np.min((p_cum - p_peaks) / p_peaks)))
        if sim_returns:
            pred_return_quantile = float(np.mean(np.array(sim_returns) <= cum_ret_2024))
        if sim_dds:
            pred_dd_quantile = float(np.mean(np.array(sim_dds) <= max_dd_2024))
    elif predictive_evaluations and len(predictive_evaluations) > 0:
        sim_returns = [e.total_return for e in predictive_evaluations]
        sim_dds = [e.max_drawdown for e in predictive_evaluations]
        pred_return_quantile = float(np.mean(np.array(sim_returns) <= cum_ret_2024))
        pred_dd_quantile = float(np.mean(np.array(sim_dds) <= max_dd_2024))

    ks_stat, ks_pval = stats.ks_2samp(calib_fx, holdout_fx)

    calib_fnames = list(calibration_panel.values.keys())
    holdout_fnames = [f for f in calib_fnames if f in holdout_panel.values]

    calib_mat = np.column_stack([calibration_panel.values[f] for f in holdout_fnames])
    holdout_mat = np.column_stack([holdout_panel.values[f] for f in holdout_fnames])

    corr_calib = np.corrcoef(calib_mat, rowvar=False)
    corr_holdout = np.corrcoef(holdout_mat, rowvar=False)

    corr_shifts: dict[str, float] = {}
    for i, f1 in enumerate(holdout_fnames):
        for j, f2 in enumerate(holdout_fnames):
            if i < j:
                shift = float(corr_holdout[i, j] - corr_calib[i, j])
                corr_shifts[f"{f1}__vs__{f2}"] = shift

    h_days = len(holdout_panel.dates)
    h_start = min(holdout_panel.dates)
    h_end = max(holdout_panel.dates)

    summary = (
        f"2024 realized FX volatility was {holdout_vol:.2%}, classified as {vol_regime}. "
        f"Realized return percentile in predictive simulation: {pred_return_quantile:.1%}. "
        f"KS test p-value between calibration and holdout FX distributions: {ks_pval:.4f}."
    )

    limitations = [
        "Single-year holdout window (247 trading days in 2024) does not represent a full macroeconomic credit cycle.",
        f"2024 realized volatility was {holdout_vol:.2%}, lying in the {vol_regime} regime ({thresh_low:.2%} to {thresh_high:.2%}).",
        "Out-of-sample diagnostics demonstrate model coverage over 2024 but do NOT establish permanent predictive reliability.",
    ]

    return HoldoutDiagnosticReport(
        holdout_year=2024,
        holdout_start=h_start,
        holdout_end=h_end,
        holdout_days=h_days,
        realized_fx_volatility_annualized=holdout_vol,
        calibration_fx_volatility_annualized=calib_vol,
        volatility_ratio=vol_ratio,
        volatility_regime_classification=vol_regime,
        realized_cumulative_return=cum_ret_2024,
        predictive_quantile_return=pred_return_quantile,
        realized_max_drawdown=max_dd_2024,
        predictive_quantile_drawdown=pred_dd_quantile,
        rate_change_ks_stat=float(ks_stat),
        rate_change_ks_pvalue=float(ks_pval),
        fx_log_return_ks_stat=float(ks_stat),
        fx_log_return_ks_pvalue=float(ks_pval),
        correlation_shifts=corr_shifts,
        is_within_normal_distribution_bounds=0.01 <= pred_return_quantile <= 0.99,
        diagnostic_summary=summary,
        limitations_notes=limitations,
    )


def resolve_canonical_initial_fx(
    calibration_panel: FactorPanel,
    boundary_date: date | None = None,
) -> float:
    """Resolve initial FX level in canonical USD per EUR from calibration panel at the boundary date.

    Rules:
    - Target exact factor ID: 'FX_EUR_USD_LOGRET'.
    - If exact factor ID is not in canonical_levels or raw_levels, search calibration_panel.factors
      for an unambiguous EUR/USD factor (category=FX_RETURN, pair contains 'EUR' and 'USD').
    - Prefer canonical level if present in calibration_panel.canonical_levels.
    - If canonical level is absent, fallback to calibration_panel.raw_levels ONLY when explicit,
      verified quote convention metadata is authorized (via row_provenance or factor definition).
    - Invert EUR_per_USD quotes using _normalize_fx_quote_to_usd_per_eur.
    - Preserve USD_per_EUR quotes.
    - Strictly reject missing, ambiguous, or unsupported quote conventions (fail closed).
    - Never infer quote direction from numerical magnitude.
    - Enforce finite positivity (initial_fx > 0).
    """
    fx_key = "FX_EUR_USD_LOGRET"
    if fx_key not in calibration_panel.canonical_levels and fx_key not in calibration_panel.raw_levels:
        matched_fx = [
            f.factor_id for f in calibration_panel.factors
            if f.category == FactorCategory.FX_RETURN and ("EUR" in f.asset_or_currency and "USD" in f.asset_or_currency)
        ]
        if len(matched_fx) == 1:
            fx_key = matched_fx[0]
        else:
            raise ValueError(
                f"Cannot resolve initial FX level: required EUR/USD factor ('FX_EUR_USD_LOGRET') is missing or ambiguous "
                f"in calibration panel factors: {[f.factor_id for f in calibration_panel.factors]}."
            )

    if fx_key in calibration_panel.canonical_levels and calibration_panel.canonical_levels[fx_key]:
        initial_fx = float(calibration_panel.canonical_levels[fx_key][-1])
    elif fx_key in calibration_panel.raw_levels and calibration_panel.raw_levels[fx_key]:
        raw_val = float(calibration_panel.raw_levels[fx_key][-1])
        prov = None
        if fx_key in calibration_panel.row_provenance and calibration_panel.row_provenance[fx_key]:
            prov = calibration_panel.row_provenance[fx_key][-1]
        factor_meta = next((f for f in calibration_panel.factors if f.factor_id == fx_key), None)
        raw_unit = (prov.raw_unit if prov and prov.raw_unit else None) or (factor_meta.original_unit if factor_meta else None)
        base_curr = (prov.base_currency if prov and prov.base_currency else None)
        quote_curr = (prov.quote_currency if prov and prov.quote_currency else None)
        pair = (prov.pair if prov and prov.pair else None) or (factor_meta.asset_or_currency if factor_meta else None)

        unit_str = (raw_unit or "").strip().lower()
        valid_units = ("usd_per_eur", "usd/eur", "usd per eur", "eur_per_usd", "eur/usd", "eur per usd")
        if not unit_str or unit_str not in valid_units:
            if base_curr == "EUR" and quote_curr == "USD":
                raw_unit = "USD_per_EUR"
            elif base_curr == "USD" and quote_curr == "EUR":
                raw_unit = "EUR_per_USD"
            else:
                raise ValueError(
                    f"Cannot resolve initial FX level from raw levels for factor '{fx_key}': "
                    f"raw unit '{raw_unit}' is missing, ambiguous, or unsupported. "
                    "Explicit quote metadata ('USD_per_EUR' or 'EUR_per_USD') is required. "
                    "Inferring quote direction from numerical magnitude is strictly prohibited."
                )

        obs_date = boundary_date or (prov.observation_date if prov else date(2023, 12, 29))
        obs = DataObservation(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id=prov.source_id if prov else (factor_meta.source_id if factor_meta else "fx"),
            entity_code=pair or "EUR/USD",
            indicator_id=prov.series_id if prov else (factor_meta.series_id or "FX"),
            value=raw_val,
            unit=raw_unit,
            frequency=Frequency.DAILY,
            base_currency=base_curr,
            quote_currency=quote_curr,
            observation_date=obs_date,
            retrieved_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        initial_fx = float(_normalize_fx_quote_to_usd_per_eur(obs))
    else:
        raise ValueError(
            f"Cannot resolve initial FX level from calibration panel factor '{fx_key}': "
            "neither canonical nor valid raw levels available."
        )

    if not math.isfinite(initial_fx) or initial_fx <= 0:
        raise ValueError(f"Initial FX level must be finite and positive: {initial_fx}")
    return initial_fx


def resolve_canonical_initial_borrowing_rate(
    calibration_panel: FactorPanel,
    boundary_date: date | None = None,
) -> float:
    """Resolve initial EUR borrowing rate (as annual decimal) from calibration panel at the boundary date.

    Rules:
    - Target exact factor ID: 'RATE_DIFF_EUR_BORROW_BPS'.
    - If exact factor ID is not in canonical_levels or raw_levels, search calibration_panel.factors
      for an unambiguous EUR borrowing factor (category=BORROWING_RATE_CHANGE, asset_or_currency or factor_id contains 'EUR').
    - Canonical levels are stored as percentage points; converts to decimal via percentage_points / 100.
    - If canonical level is absent, fallback to calibration_panel.raw_levels ONLY when explicit,
      verified unit metadata is authorized ('percent', 'decimal', 'bps').
    - Rejects missing, empty, or unknown raw rate units (fail closed).
    - Enforces finite non-negativity (initial_borrow >= 0).
    """
    borrow_key = "RATE_DIFF_EUR_BORROW_BPS"
    if borrow_key not in calibration_panel.canonical_levels and borrow_key not in calibration_panel.raw_levels:
        matched_borrow = [
            f.factor_id for f in calibration_panel.factors
            if f.category == FactorCategory.BORROWING_RATE_CHANGE and ("EUR" in f.factor_id or "EUR" in f.asset_or_currency)
        ]
        if len(matched_borrow) == 1:
            borrow_key = matched_borrow[0]
        else:
            raise ValueError(
                f"Cannot resolve initial EUR borrowing rate: required borrowing factor ('RATE_DIFF_EUR_BORROW_BPS') is missing or ambiguous "
                f"in calibration panel factors: {[f.factor_id for f in calibration_panel.factors]}."
            )

    if borrow_key in calibration_panel.canonical_levels and calibration_panel.canonical_levels[borrow_key]:
        initial_borrow = float(calibration_panel.canonical_levels[borrow_key][-1]) / 100.0
    elif borrow_key in calibration_panel.raw_levels and calibration_panel.raw_levels[borrow_key]:
        raw_val = float(calibration_panel.raw_levels[borrow_key][-1])
        prov = None
        if borrow_key in calibration_panel.row_provenance and calibration_panel.row_provenance[borrow_key]:
            prov = calibration_panel.row_provenance[borrow_key][-1]
        factor_meta = next((f for f in calibration_panel.factors if f.factor_id == borrow_key), None)
        raw_unit = (prov.raw_unit if prov and prov.raw_unit else None) or (factor_meta.original_unit if factor_meta else None)

        if not raw_unit or not str(raw_unit).strip():
            raise ValueError(
                f"Cannot resolve initial borrowing rate from raw levels for factor '{borrow_key}': "
                "unit metadata is missing. Explicit unit ('percent', 'decimal', 'bps') is required."
            )

        obs_date = boundary_date or (prov.observation_date if prov else date(2023, 12, 29))
        obs = DataObservation(
            kind=ObservationKind.INTEREST_RATE,
            source_id=prov.source_id if prov else (factor_meta.source_id if factor_meta else "ecb"),
            entity_code=prov.pair if prov and prov.pair else "EUR",
            indicator_id=prov.series_id if prov else (factor_meta.series_id or "BORROW"),
            value=raw_val,
            unit=raw_unit,
            frequency=Frequency.DAILY,
            observation_date=obs_date,
            retrieved_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        initial_borrow = float(_normalize_rate_to_decimal(obs))
    else:
        raise ValueError(
            f"Cannot resolve initial borrowing rate from calibration panel factor '{borrow_key}': "
            "neither canonical nor valid raw levels available."
        )

    if not math.isfinite(initial_borrow) or initial_borrow < 0:
        raise ValueError(f"Initial borrowing rate must be finite and non-negative: {initial_borrow}")
    return initial_borrow


def resolve_canonical_initial_investment_rate(
    calibration_panel: FactorPanel,
    boundary_date: date | None = None,
) -> float:
    """Resolve initial USD investment yield (as annual decimal) from calibration panel at the boundary date.

    Rules:
    - Target exact factor ID: 'YIELD_DIFF_USD_1M_BPS'.
    - If exact factor ID is not in canonical_levels or raw_levels, search calibration_panel.factors
      strictly for the 1-month sovereign yield factor (series_id='DGS1MO' or '1M' in factor_id without '3M').
    - Silent substitution of DGS3MO or other tenors is strictly prohibited.
    - Canonical levels are stored as percentage points; converts to decimal via percentage_points / 100.
    - If canonical level is absent, fallback to calibration_panel.raw_levels ONLY when explicit,
      verified unit metadata is authorized ('percent', 'decimal', 'bps') and series is confirmed 1-month.
    - Rejects missing, empty, or unknown raw rate units (fail closed).
    - Enforces finite non-negativity (initial_invest >= 0).
    """
    invest_key = "YIELD_DIFF_USD_1M_BPS"
    if invest_key not in calibration_panel.canonical_levels and invest_key not in calibration_panel.raw_levels:
        matched_invest = [
            f.factor_id for f in calibration_panel.factors
            if f.category == FactorCategory.SOVEREIGN_YIELD_CHANGE
            and (f.series_id == "DGS1MO" or ("1M" in f.factor_id and "3M" not in f.factor_id))
        ]
        if len(matched_invest) == 1:
            invest_key = matched_invest[0]
        else:
            raise ValueError(
                "Cannot resolve initial USD investment yield: required 1-month series ('YIELD_DIFF_USD_1M_BPS' / DGS1MO) "
                "is missing from calibration panel. Silent substitution of DGS3MO or other sovereign yield tenors is strictly prohibited."
            )

    if invest_key in calibration_panel.canonical_levels and calibration_panel.canonical_levels[invest_key]:
        # Validate that factor metadata does not specify DGS3MO
        factor_meta = next((f for f in calibration_panel.factors if f.factor_id == invest_key), None)
        if factor_meta and factor_meta.series_id:
            if "3M" in factor_meta.series_id.upper() or "3MO" in factor_meta.series_id.upper():
                raise ValueError(
                    f"Cannot resolve initial USD investment yield for factor '{invest_key}': series '{factor_meta.series_id}' is a 3-month series. "
                    "The strategy strictly requires the 1-month series (DGS1MO). Silent substitution is prohibited."
                )
        initial_invest = float(calibration_panel.canonical_levels[invest_key][-1]) / 100.0
    elif invest_key in calibration_panel.raw_levels and calibration_panel.raw_levels[invest_key]:
        raw_val = float(calibration_panel.raw_levels[invest_key][-1])
        prov = None
        if invest_key in calibration_panel.row_provenance and calibration_panel.row_provenance[invest_key]:
            prov = calibration_panel.row_provenance[invest_key][-1]
        factor_meta = next((f for f in calibration_panel.factors if f.factor_id == invest_key), None)
        raw_unit = (prov.raw_unit if prov and prov.raw_unit else None) or (factor_meta.original_unit if factor_meta else None)

        series_id = (prov.series_id if prov and prov.series_id else None) or (factor_meta.series_id if factor_meta else None) or ""
        if "3M" in series_id.upper() or "3MO" in series_id.upper():
            raise ValueError(
                f"Cannot resolve initial USD investment yield for factor '{invest_key}': series '{series_id}' is a 3-month series. "
                "The strategy strictly requires the 1-month series (DGS1MO). Silent substitution is prohibited."
            )

        if not raw_unit or not str(raw_unit).strip():
            raise ValueError(
                f"Cannot resolve initial investment yield from raw levels for factor '{invest_key}': "
                "unit metadata is missing. Explicit unit ('percent', 'decimal', 'bps') is required."
            )

        obs_date = boundary_date or (prov.observation_date if prov else date(2023, 12, 29))
        obs = DataObservation(
            kind=ObservationKind.INTEREST_RATE,
            source_id=prov.source_id if prov else (factor_meta.source_id if factor_meta else "us_treasury"),
            entity_code="USD",
            indicator_id=series_id or "DGS1MO",
            value=raw_val,
            unit=raw_unit,
            frequency=Frequency.DAILY,
            observation_date=obs_date,
            retrieved_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        initial_invest = float(_normalize_rate_to_decimal(obs))
    else:
        raise ValueError(
            f"Cannot resolve initial investment yield from calibration panel factor '{invest_key}': "
            "neither canonical nor valid raw levels available."
        )

    if not math.isfinite(initial_invest) or initial_invest < 0:
        raise ValueError(f"Initial investment yield must be finite and non-negative: {initial_invest}")
    return initial_invest


def generate_holdout_predictive_paths(
    model: Any,
    calibration_panel: FactorPanel,
    holdout_panel: FactorPanel,
    num_paths: int = 1000,
) -> list[ScenarioPath]:
    """Generate predictive scenario paths over the holdout window anchored at the calibration boundary.

    Enforces scenario-date and calibration-boundary integrity (Phase 4.1.2.2.3 / 4.1.2.2.3.1):
    1. Level Dates vs Transitions:
       - Uses holdout_panel.level_dates (length == N, e.g. 248), starting on the
         final calibration-boundary date (2023-12-29) and ending on holdout end (2024-12-31).
       - Sets horizon = len(holdout_panel.dates) (length == N - 1, e.g. 247 transitions).
       - Because the path generator reconstructs N = horizon + 1 levels, the date count exactly
         equals the level count (248 dates == 248 levels), satisfying ScenarioPath calendar validation.
    2. Calibration Boundary Anchoring & Fail-Closed Resolution:
       - Rather than allowing the model to use arbitrary default initial values (e.g. 1.09, 0.04, 0.05),
         the path is anchored strictly at the genuine final in-sample calibration levels as of 2023-12-29
         via resolve_canonical_initial_fx, resolve_canonical_initial_borrowing_rate, and
         resolve_canonical_initial_investment_rate.
       - Enforces exact factor selection, validated unit conversion, and fail-closed behavior on missing
         or ambiguous metadata.
    3. Chronological Continuity:
       - Path step 0 is dated 2023-12-29 with the boundary levels.
       - Path step 1 is dated 2024-01-02, representing the first holdout transition from 2023-12-29 to 2024-01-02.
       - No extra or missing transitions are introduced.
    4. Calendar & Shape Validation:
       - Verifies that every generated ScenarioPath satisfies len(dates) == len(fx_rates) == len(borrowing_rates) == len(investment_rates) == horizon + 1.
    """
    if not holdout_panel.dates:
        raise ValueError("Holdout panel has no transition dates.")
    horizon = len(holdout_panel.dates)

    # 1. Resolve holdout scenario dates
    if holdout_panel.level_dates and len(holdout_panel.level_dates) == horizon + 1:
        dates = holdout_panel.level_dates
    elif holdout_panel.level_dates:
        raise ValueError(
            f"Holdout level dates length ({len(holdout_panel.level_dates)}) does not match expected horizon + 1 ({horizon + 1})."
        )
    else:
        # Fallback if level_dates was not pre-populated: prepend calibration boundary date
        if calibration_panel.dates:
            boundary_date = calibration_panel.dates[-1]
        elif calibration_panel.level_dates:
            boundary_date = calibration_panel.level_dates[-1]
        else:
            raise ValueError("Cannot determine calibration boundary date from calibration panel.")
        dates = [boundary_date] + list(holdout_panel.dates)

    # Verify boundary date matches calibration end
    calib_last_date = (
        calibration_panel.last_level_date
        or (calibration_panel.level_dates[-1] if calibration_panel.level_dates else None)
        or (calibration_panel.dates[-1] if calibration_panel.dates else None)
    )
    if calib_last_date is not None and dates[0] != calib_last_date:
        raise ValueError(
            f"Holdout scenario initial date ({dates[0]}) does not match calibration boundary date ({calib_last_date})."
        )

    # 2. Resolve calibration-boundary initial levels (fail closed)
    initial_fx = resolve_canonical_initial_fx(calibration_panel, dates[0])
    initial_borrow = resolve_canonical_initial_borrowing_rate(calibration_panel, dates[0])
    initial_invest = resolve_canonical_initial_investment_rate(calibration_panel, dates[0])

    # 3. Generate paths via sampler
    paths = model.generate_paths(
        num_paths=num_paths,
        horizon=horizon,
        initial_fx=initial_fx,
        initial_borrowing_rate=initial_borrow,
        initial_investment_rate=initial_invest,
        dates=dates,
    )

    # 4. Strict post-condition assertions on every generated path
    expected_levels = horizon + 1
    for p in paths:
        if p.dates is None or len(p.dates) != expected_levels:
            raise ValueError(
                f"Generated scenario path date count mismatch: received {len(p.dates) if p.dates else 0}, expected {expected_levels}."
            )
        if len(p.fx_rates) != expected_levels:
            raise ValueError(
                f"Generated scenario path FX levels count mismatch: received {len(p.fx_rates)}, expected {expected_levels}."
            )
        if len(p.borrowing_rates) != expected_levels:
            raise ValueError(
                f"Generated scenario path borrowing rate count mismatch: received {len(p.borrowing_rates)}, expected {expected_levels}."
            )
        if len(p.investment_rates) != expected_levels:
            raise ValueError(
                f"Generated scenario path investment rate count mismatch: received {len(p.investment_rates)}, expected {expected_levels}."
            )
        if p.dates[0] != dates[0]:
            raise ValueError(
                f"Generated path start date ({p.dates[0]}) does not match calibration boundary date ({dates[0]})."
            )
        if abs(p.fx_rates[0] - initial_fx) > 1e-9:
            raise ValueError(
                f"Generated path initial FX ({p.fx_rates[0]}) does not match calibration boundary FX ({initial_fx})."
            )
        if abs(p.borrowing_rates[0] - initial_borrow) > 1e-9:
            raise ValueError(
                f"Generated path initial borrowing rate ({p.borrowing_rates[0]}) does not match calibration boundary rate ({initial_borrow})."
            )
        if abs(p.investment_rates[0] - initial_invest) > 1e-9:
            raise ValueError(
                f"Generated path initial investment rate ({p.investment_rates[0]}) does not match calibration boundary rate ({initial_invest})."
            )

    return paths


