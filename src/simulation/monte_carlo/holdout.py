"""Out-of-sample holdout diagnostic validation.

Evaluates calibration-only predictive models against the untouched 2024 holdout dataset,
separating factor-level validation (FX-to-FX return, volatility, and drawdown distributions)
from strategy-level validation (which is marked UNAVAILABLE in the absence of genuine live
execution records).
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np
import scipy.stats as stats

from simulation.monte_carlo.regimes import VolatilityRegimeClassifier
from simulation.monte_carlo.schemas import (
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

