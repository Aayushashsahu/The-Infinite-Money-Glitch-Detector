"""Calibration and sample sufficiency verification.

Performs chronological calibration/holdout splitting, computes empirical
distributional statistics, verifies sample sufficiency, and calculates
cross-factor covariance and correlation matrices.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import scipy.stats as stats
from pydantic import BaseModel, Field

from simulation.monte_carlo.schemas import (
    CalibrationAvailabilitySummary,
    DistributionQuantiles,
    FactorPanel,
)


class FactorSummary(BaseModel):
    """Empirical distribution summary for a single market factor."""

    factor_id: str
    count: int
    mean: float
    std: float
    skewness: float
    excess_kurtosis: float
    min_val: float
    max_val: float
    quantiles: DistributionQuantiles


class CalibrationReport(BaseModel):
    """Statistical summary of historical calibration data."""

    calibration_start: date
    calibration_end: date
    calibration_sample_size: int
    holdout_start: date | None = None
    holdout_end: date | None = None
    holdout_sample_size: int = 0
    factor_summaries: dict[str, FactorSummary]
    factor_names: list[str]
    correlation_matrix: list[list[float]]
    covariance_matrix: list[list[float]]
    is_sufficient: bool = True
    sufficiency_notes: list[str] = Field(default_factory=list)
    availability_summary: CalibrationAvailabilitySummary | None = None



def split_calibration_holdout(
    panel: FactorPanel,
    calibration_end: date = date(2023, 12, 31),
) -> tuple[FactorPanel, FactorPanel]:
    """Split factor panel chronologically into calibration and holdout panels.

    Preserves chronological order strictly. Never randomly shuffles time series.
    """
    calib_indices = [i for i, d in enumerate(panel.dates) if d <= calibration_end]
    holdout_indices = [i for i, d in enumerate(panel.dates) if d > calibration_end]

    if not calib_indices:
        raise ValueError(f"No observations on or before calibration_end: {calibration_end}")
    if not holdout_indices:
        raise ValueError(f"No observations after calibration_end: {calibration_end}")

    calib_dates = [panel.dates[i] for i in calib_indices]
    holdout_dates = [panel.dates[i] for i in holdout_indices]

    calib_values = {f: [panel.values[f][i] for i in calib_indices] for f in panel.values}
    holdout_values = {f: [panel.values[f][i] for i in holdout_indices] for f in panel.values}

    calib_raw = {f: [panel.raw_levels[f][i] for i in calib_indices] for f in panel.raw_levels}
    holdout_raw = {f: [panel.raw_levels[f][i] for i in holdout_indices] for f in panel.raw_levels}

    calib_panel = FactorPanel(
        factors=panel.factors,
        dates=calib_dates,
        values=calib_values,
        raw_levels=calib_raw,
        calendar_name=panel.calendar_name,
        effective_sample_size=len(calib_dates),
        is_aligned=True,
        alignment_audit=[f"Calibration split: {len(calib_dates)} days through {calibration_end}"],
    )

    holdout_panel = FactorPanel(
        factors=panel.factors,
        dates=holdout_dates,
        values=holdout_values,
        raw_levels=holdout_raw,
        calendar_name=panel.calendar_name,
        effective_sample_size=len(holdout_dates),
        is_aligned=True,
        alignment_audit=[f"Holdout split: {len(holdout_dates)} days after {calibration_end}"],
    )

    return calib_panel, holdout_panel


def compute_quantiles(arr: np.ndarray) -> DistributionQuantiles:
    """Compute standard percentiles and higher moments for a 1D array."""
    mean_val = float(np.mean(arr))
    std_val = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
    skew_val = float(stats.skew(arr)) if len(arr) > 2 else 0.0
    kurt_val = float(stats.kurtosis(arr)) if len(arr) > 3 else 0.0

    return DistributionQuantiles(
        p01=float(np.percentile(arr, 1)),
        p05=float(np.percentile(arr, 5)),
        p10=float(np.percentile(arr, 10)),
        p25=float(np.percentile(arr, 25)),
        p50=float(np.percentile(arr, 50)),
        p75=float(np.percentile(arr, 75)),
        p90=float(np.percentile(arr, 90)),
        p95=float(np.percentile(arr, 95)),
        p99=float(np.percentile(arr, 99)),
        mean=mean_val,
        std=std_val,
        skewness=skew_val,
        excess_kurtosis=kurt_val,
    )


def calibrate_factor_panel(
    panel: FactorPanel,
    holdout_panel: FactorPanel | None = None,
    raw_observations: list[Any] | None = None,
    min_observations: int = 250,
) -> CalibrationReport:
    """Calibrate empirical distribution and covariance models on historical factor panel."""
    notes: list[str] = []
    is_sufficient = True

    n_obs = panel.effective_sample_size
    if n_obs < min_observations:
        is_sufficient = False
        notes.append(f"Insufficient sample size: {n_obs} < minimum required {min_observations}.")
    else:
        notes.append(f"Sample size sufficient: {n_obs} observations (minimum required {min_observations}).")

    factor_names = list(panel.values.keys())
    summaries: dict[str, FactorSummary] = {}
    matrix_data: list[np.ndarray] = []

    for fname in factor_names:
        series = np.array(panel.values[fname], dtype=np.float64)
        if len(series) == 0:
            raise ValueError(f"Factor series {fname} is empty.")
        if np.std(series) < 1e-12:
            notes.append(f"Warning: Factor {fname} has near-zero variance ({np.std(series):.2e}).")

        q = compute_quantiles(series)
        summ = FactorSummary(
            factor_id=fname,
            count=len(series),
            mean=q.mean,
            std=q.std,
            skewness=q.skewness,
            excess_kurtosis=q.excess_kurtosis,
            min_val=float(np.min(series)),
            max_val=float(np.max(series)),
            quantiles=q,
        )
        summaries[fname] = summ
        matrix_data.append(series)

    # Compute joint covariance and correlation matrices
    joint_array = np.vstack(matrix_data)  # shape: (n_factors, n_obs)
    cov_mat = np.cov(joint_array, ddof=1)
    corr_mat = np.corrcoef(joint_array)

    # Handle single factor edge-case
    if len(factor_names) == 1:
        cov_mat = np.array([[cov_mat]])
        corr_mat = np.array([[1.0]])

    calib_start = min(panel.dates)
    calib_end = max(panel.dates)
    h_start = min(holdout_panel.dates) if holdout_panel and holdout_panel.dates else None
    h_end = max(holdout_panel.dates) if holdout_panel and holdout_panel.dates else None
    h_count = holdout_panel.effective_sample_size if holdout_panel else 0

    # Availability breakdown audit
    avail_summary: CalibrationAvailabilitySummary | None = None
    if raw_observations is not None:
        total_gen = sum(1 for o in raw_observations if not getattr(o, "is_synthetic", False))
        def _ev_matches(val: Any, key: str) -> bool:
            if val is None:
                return False
            s = str(getattr(val, "value", val)).lower()
            return key.lower() in s

        exact_ver = sum(
            1 for o in raw_observations
            if not getattr(o, "is_synthetic", False)
            and _ev_matches(getattr(o, "availability_evidence", None), "exact_timestamp_verified")
        )
        estimated = sum(
            1 for o in raw_observations
            if not getattr(o, "is_synthetic", False)
            and _ev_matches(getattr(o, "availability_evidence", None), "estimated_schedule")
        )
        retrospective = sum(
            1 for o in raw_observations
            if not getattr(o, "is_synthetic", False)
            and str(getattr(o, "classification", "")).endswith("retrospective")
        )
        missing_ev = sum(
            1 for o in raw_observations
            if not getattr(o, "is_synthetic", False)
            and getattr(o, "availability_evidence", None) is None
        )
        excl_synth = sum(1 for o in raw_observations if getattr(o, "is_synthetic", False))

        avail_summary = CalibrationAvailabilitySummary(
            total_genuine_observations=total_gen,
            exact_timestamp_verified_count=exact_ver,
            estimated_availability_count=estimated,
            retrospective_count=retrospective,
            missing_evidence_count=missing_ev,
            excluded_synthetic_count=excl_synth,
            complete_aligned_factor_days=n_obs,
            data_classification_label="SIMULATED_RESEARCH_PROXY",
        )

    return CalibrationReport(
        calibration_start=calib_start,
        calibration_end=calib_end,
        calibration_sample_size=n_obs,
        holdout_start=h_start,
        holdout_end=h_end,
        holdout_sample_size=h_count,
        factor_summaries=summaries,
        factor_names=factor_names,
        correlation_matrix=corr_mat.tolist(),
        covariance_matrix=cov_mat.tolist(),
        is_sufficient=is_sufficient,
        sufficiency_notes=notes,
        availability_summary=avail_summary,
    )
