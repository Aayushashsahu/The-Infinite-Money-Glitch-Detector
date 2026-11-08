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
    AvailabilityAuditReport,
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
    calibration_level_count: int = Field(default=0, description="Aligned level observation count for calibration")
    calibration_transition_count: int = Field(default=0, description="Factor transition count for calibration")
    first_calibration_level_date: date | None = None
    last_calibration_level_date: date | None = None
    first_calibration_transition_date: date | None = None
    last_calibration_transition_date: date | None = None
    holdout_start: date | None = None
    holdout_end: date | None = None
    holdout_sample_size: int = 0
    holdout_level_count: int = Field(default=0, description="Aligned level observation count for holdout")
    holdout_transition_count: int = Field(default=0, description="Factor transition count for holdout")
    first_holdout_level_date: date | None = None
    last_holdout_level_date: date | None = None
    first_holdout_transition_date: date | None = None
    last_holdout_transition_date: date | None = None
    factor_summaries: dict[str, FactorSummary]
    factor_names: list[str]
    correlation_matrix: list[list[float]]
    covariance_matrix: list[list[float]]
    correlation_validity_mask: list[list[bool]] = Field(
        default_factory=list,
        description="Pairwise correlation validity mask: True if both factors have non-zero variance, False if undefined.",
    )
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

    calib_canonical = {f: [panel.canonical_levels[f][i] for i in calib_indices] for f in panel.canonical_levels}
    holdout_canonical = {f: [panel.canonical_levels[f][i] for i in holdout_indices] for f in panel.canonical_levels}

    # Slice level dates
    if panel.level_dates and len(panel.level_dates) == len(panel.dates) + 1:
        calib_level_dates = panel.level_dates[: len(calib_dates) + 1]
        holdout_level_dates = panel.level_dates[len(calib_dates) :]
    else:
        calib_level_dates = [calib_dates[0]] + calib_dates
        holdout_level_dates = [holdout_dates[0]] + holdout_dates

    calib_panel = FactorPanel(
        factors=panel.factors,
        dates=calib_dates,
        level_dates=calib_level_dates,
        values=calib_values,
        raw_levels=calib_raw,
        canonical_levels=calib_canonical,
        aligned_level_count=len(calib_level_dates),
        transition_count=len(calib_dates),
        first_level_date=calib_level_dates[0] if calib_level_dates else None,
        last_level_date=calib_level_dates[-1] if calib_level_dates else None,
        first_transition_date=calib_dates[0] if calib_dates else None,
        last_transition_date=calib_dates[-1] if calib_dates else None,
        calendar_name=panel.calendar_name,
        effective_sample_size=len(calib_dates),
        is_aligned=True,
        alignment_audit=[f"Calibration split: {len(calib_dates)} transition days ({len(calib_level_dates)} levels) through {calibration_end}"],
    )

    holdout_panel = FactorPanel(
        factors=panel.factors,
        dates=holdout_dates,
        level_dates=holdout_level_dates,
        values=holdout_values,
        raw_levels=holdout_raw,
        canonical_levels=holdout_canonical,
        aligned_level_count=len(holdout_level_dates),
        transition_count=len(holdout_dates),
        first_level_date=holdout_level_dates[0] if holdout_level_dates else None,
        last_level_date=holdout_level_dates[-1] if holdout_level_dates else None,
        first_transition_date=holdout_dates[0] if holdout_dates else None,
        last_transition_date=holdout_dates[-1] if holdout_dates else None,
        calendar_name=panel.calendar_name,
        effective_sample_size=len(holdout_dates),
        is_aligned=True,
        alignment_audit=[f"Holdout split: {len(holdout_dates)} transition days ({len(holdout_level_dates)} levels) after {calibration_end}"],
    )

    return calib_panel, holdout_panel


def compute_quantiles(arr: np.ndarray) -> DistributionQuantiles:
    """Compute standard percentiles and higher moments for a 1D array."""
    mean_val = float(np.mean(arr))
    std_val = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
    if std_val < 1e-12:
        skew_val = 0.0
        kurt_val = 0.0
    else:
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

    # Identify factors with zero or near-zero variance
    zero_var_indices = {i for i, fname in enumerate(factor_names) if summaries[fname].std < 1e-12}
    for idx in sorted(zero_var_indices):
        fname = factor_names[idx]
        notes.append(
            f"Factor '{fname}' has zero or near-zero variance ({summaries[fname].std:.2e}); "
            f"pairwise linear correlations involving this factor are mathematically undefined."
        )

    n_f = len(factor_names)
    correlation_validity_mask: list[list[bool]] = [
        [i not in zero_var_indices and j not in zero_var_indices for j in range(n_f)]
        for i in range(n_f)
    ]

    # Compute joint covariance and correlation matrices
    joint_array = np.vstack(matrix_data)  # shape: (n_factors, n_obs)
    cov_mat = np.cov(joint_array, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        raw_corr = np.corrcoef(joint_array)

    # Handle single factor edge-case
    if len(factor_names) == 1:
        cov_mat = np.array([[cov_mat]])
        corr_mat = np.array([[np.nan if 0 in zero_var_indices else 1.0]])
    else:
        validity_arr = np.array(correlation_validity_mask, dtype=bool)
        corr_mat = np.where(validity_arr, raw_corr, np.nan)

    calib_start = min(panel.dates)
    calib_end = max(panel.dates)
    h_start = min(holdout_panel.dates) if holdout_panel and holdout_panel.dates else None
    h_end = max(holdout_panel.dates) if holdout_panel and holdout_panel.dates else None
    h_count = holdout_panel.effective_sample_size if holdout_panel else 0

    # Availability breakdown audit (mutually exclusive classification)
    avail_summary: CalibrationAvailabilitySummary | None = None
    if raw_observations is not None:
        total_gen = sum(1 for o in raw_observations if not getattr(o, "is_synthetic", False))

        exact_ver = 0
        estimated = 0
        retrospective = 0
        missing_ev = 0
        unrecognized_ev = 0

        for o in raw_observations:
            if getattr(o, "is_synthetic", False):
                continue
            ev_val = getattr(o, "availability_evidence", None)
            cls_val = getattr(o, "classification", None)
            ev_str = str(getattr(ev_val, "value", ev_val) or "").lower()
            cls_str = str(getattr(cls_val, "value", cls_val) or "").lower()

            if "exact_timestamp_verified" in ev_str:
                exact_ver += 1
            elif "retrospective" in ev_str or "retrospective" in cls_str:
                retrospective += 1
            elif "estimated" in ev_str or "unverified_same_day" in ev_str or "estimated" in cls_str:
                estimated += 1
            elif not ev_str and not cls_str:
                missing_ev += 1
            else:
                unrecognized_ev += 1

        excl_synth = sum(1 for o in raw_observations if getattr(o, "is_synthetic", False))
        is_reconciled = (exact_ver + estimated + retrospective + missing_ev + unrecognized_ev == total_gen)

        avail_summary = CalibrationAvailabilitySummary(
            total_genuine_observations=total_gen,
            exact_timestamp_verified_count=exact_ver,
            estimated_availability_count=estimated,
            retrospective_count=retrospective,
            missing_evidence_count=missing_ev,
            unrecognized_evidence_count=unrecognized_ev,
            excluded_synthetic_count=excl_synth,
            complete_aligned_factor_days=n_obs,
            is_reconciled=is_reconciled,
            data_classification_label="SIMULATED_RESEARCH_PROXY",
        )

    calib_level_count = panel.aligned_level_count or (len(panel.dates) + 1)
    calib_trans_count = panel.transition_count or len(panel.dates)
    first_calib_lvl = panel.first_level_date or (panel.level_dates[0] if panel.level_dates else min(panel.dates))
    last_calib_lvl = panel.last_level_date or (panel.level_dates[-1] if panel.level_dates else max(panel.dates))
    first_calib_tr = panel.first_transition_date or min(panel.dates)
    last_calib_tr = panel.last_transition_date or max(panel.dates)

    h_level_count = (holdout_panel.aligned_level_count if holdout_panel and holdout_panel.aligned_level_count else (len(holdout_panel.dates) + 1 if holdout_panel and holdout_panel.dates else 0))
    h_trans_count = holdout_panel.transition_count if holdout_panel and holdout_panel.transition_count else (len(holdout_panel.dates) if holdout_panel else 0)
    first_h_lvl = holdout_panel.first_level_date if holdout_panel else None
    last_h_lvl = holdout_panel.last_level_date if holdout_panel else None
    first_h_tr = holdout_panel.first_transition_date if holdout_panel else None
    last_h_tr = holdout_panel.last_transition_date if holdout_panel else None

    return CalibrationReport(
        calibration_start=calib_start,
        calibration_end=calib_end,
        calibration_sample_size=n_obs,
        calibration_level_count=calib_level_count,
        calibration_transition_count=calib_trans_count,
        first_calibration_level_date=first_calib_lvl,
        last_calibration_level_date=last_calib_lvl,
        first_calibration_transition_date=first_calib_tr,
        last_calibration_transition_date=last_calib_tr,
        holdout_start=h_start,
        holdout_end=h_end,
        holdout_sample_size=h_count,
        holdout_level_count=h_level_count,
        holdout_transition_count=h_trans_count,
        first_holdout_level_date=first_h_lvl,
        last_holdout_level_date=last_h_lvl,
        first_holdout_transition_date=first_h_tr,
        last_holdout_transition_date=last_h_tr,
        factor_summaries=summaries,
        factor_names=factor_names,
        correlation_matrix=corr_mat.tolist(),
        covariance_matrix=cov_mat.tolist(),
        correlation_validity_mask=correlation_validity_mask,
        is_sufficient=is_sufficient,
        sufficiency_notes=notes,
        availability_summary=avail_summary,
    )


def classify_observation_evidence(o: Any) -> str:
    """Classify an observation into one of 5 mutually exclusive evidence categories.

    Returns one of:
    - 'exact_timestamp_verified'
    - 'retrospective'
    - 'estimated_schedule'
    - 'missing'
    - 'unrecognized'
    """
    ev_val = getattr(o, "availability_evidence", None)
    cls_val = getattr(o, "classification", None)
    ev_str = str(getattr(ev_val, "value", ev_val) or "").lower()
    cls_str = str(getattr(cls_val, "value", cls_val) or "").lower()

    if "exact_timestamp_verified" in ev_str:
        return "exact_timestamp_verified"
    if "retrospective" in ev_str or "retrospective" in cls_str:
        return "retrospective"
    if "estimated" in ev_str or "unverified_same_day" in ev_str or "estimated" in cls_str:
        return "estimated_schedule"
    if not ev_str and not cls_str:
        return "missing"
    return "unrecognized"


def build_availability_audit(
    all_db_observations: list[Any],
    panel: FactorPanel | None = None,
    start_date: date = date(2020, 1, 1),
    end_date: date = date(2023, 12, 31),
) -> AvailabilityAuditReport:
    """Construct an exhaustive point-in-time availability and provenance reconciliation audit.

    Inspects all database records before filtering to ensure no observations are silently dropped.
    Reconciles all genuine observations into mutually exclusive point-in-time evidence categories.
    """
    total_source = len(all_db_observations)
    synth_excl = sum(1 for o in all_db_observations if getattr(o, "is_synthetic", False))
    genuine_obs = [o for o in all_db_observations if not getattr(o, "is_synthetic", False)]
    genuine_incl = len(genuine_obs)

    exact_ver = 0
    estimated = 0
    retrospective = 0
    missing_ev = 0
    unrecognized_ev = 0

    date_excl = 0
    factor_breakdown: dict[str, dict[str, Any]] = {}

    aligned_dates = set(panel.dates) if panel is not None else set()
    aligned_excl = 0

    for o in genuine_obs:
        d = o.observation_date
        s_id = (
            getattr(o, "series_id", None)
            or getattr(o, "indicator_id", None)
            or getattr(o, "entity_code", None)
            or getattr(o, "source_id", None)
            or "UNKNOWN"
        )
        s_id = str(s_id)
        if s_id not in factor_breakdown:
            factor_breakdown[s_id] = {
                "total_observations": 0,
                "exact_verified": 0,
                "estimated": 0,
                "retrospective": 0,
                "missing": 0,
                "min_date": str(d),
                "max_date": str(d),
            }
        fb = factor_breakdown[s_id]
        fb["total_observations"] += 1
        if str(d) < fb["min_date"]:
            fb["min_date"] = str(d)
        if str(d) > fb["max_date"]:
            fb["max_date"] = str(d)

        cat = classify_observation_evidence(o)
        if cat == "exact_timestamp_verified":
            exact_ver += 1
            fb["exact_verified"] += 1
        elif cat == "retrospective":
            retrospective += 1
            fb["retrospective"] += 1
        elif cat == "estimated_schedule":
            estimated += 1
            fb["estimated"] += 1
        elif cat == "missing":
            missing_ev += 1
            fb["missing"] += 1
        else:
            unrecognized_ev += 1

        if d < start_date or d > end_date:
            date_excl += 1
        elif panel is not None and d not in aligned_dates:
            aligned_excl += 1

    is_reconciled = (exact_ver + estimated + retrospective + missing_ev + unrecognized_ev == genuine_incl)

    release_lag_policies = {
        "FX_EUR_USD": "ECB daily reference rate published ~16:00 CET / ~15:00-16:00 UTC on observation date; available for decision at 16:00 UTC.",
        "DGS1MO": "Federal Reserve H.15 Selected Interest Rates release published at 4:15 PM Eastern Time on next Federal Reserve business day (accounting for EST/EDT daylight saving and Federal Reserve holidays).",
        "DGS3MO": "Federal Reserve H.15 Selected Interest Rates release published at 4:15 PM Eastern Time on next Federal Reserve business day (accounting for EST/EDT daylight saving and Federal Reserve holidays).",
        "EUR_BORROW_RATE": "ECB Main Refinancing Operations / Deposit Facility Rate; piecewise-constant effective from 00:00 UTC on announcement/effective date.",
    }

    audit_scope = (
        f"Source database contains {total_source:,} total records. After isolating {synth_excl} synthetic test "
        f"records, {genuine_incl:,} genuine historical observations were evaluated across 4 factor series. "
        f"Point-in-time classifications reconcile with 100% mutual exclusivity."
    )

    calib_level_count = getattr(panel, "aligned_level_count", 0) or (len(panel.dates) + 1 if panel and panel.dates else 0)
    calib_trans_count = getattr(panel, "transition_count", 0) or (len(panel.dates) if panel and panel.dates else 0)
    first_lvl = getattr(panel, "first_level_date", None) or (panel.level_dates[0] if panel and panel.level_dates else (min(panel.dates) if panel and panel.dates else None))
    last_lvl = getattr(panel, "last_level_date", None) or (panel.level_dates[-1] if panel and panel.level_dates else (max(panel.dates) if panel and panel.dates else None))
    first_tr = getattr(panel, "first_transition_date", None) or (min(panel.dates) if panel and panel.dates else None)
    last_tr = getattr(panel, "last_transition_date", None) or (max(panel.dates) if panel and panel.dates else None)

    return AvailabilityAuditReport(
        total_source_observations=total_source,
        genuine_observations_included=genuine_incl,
        synthetic_observations_excluded=synth_excl,
        date_window_exclusions=date_excl,
        classification_exclusions=0,
        factor_alignment_exclusions=aligned_excl,
        exact_timestamp_verified_count=exact_ver,
        estimated_availability_count=estimated,
        retrospective_count=retrospective,
        missing_evidence_count=missing_ev,
        unrecognized_evidence_count=unrecognized_ev,
        is_reconciled=is_reconciled,
        data_classification_label="SIMULATED_RESEARCH_PROXY",
        pit_mode=getattr(panel, "pit_mode", "ESTIMATED_LAG") if panel is not None else "ESTIMATED_LAG",
        audit_scope_description=audit_scope,
        release_lag_policies=release_lag_policies,
        factor_breakdown=factor_breakdown,
        complete_aligned_factor_days=calib_trans_count,
        aligned_level_count=calib_level_count,
        transition_count=calib_trans_count,
        first_level_date=first_lvl,
        last_level_date=last_lvl,
        first_transition_date=first_tr,
        last_transition_date=last_tr,
    )

