"""Convergence analysis and stability tracking for Monte Carlo simulation.

Evaluates metric stability (mean return, median return, loss probability, VaR, CVaR,
and maximum drawdown) across increasing simulation path sample sizes.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from simulation.monte_carlo.schemas import (
    ConvergenceCheckpoint,
    ConvergenceReport,
    PathEvaluationResult,
)


def evaluate_convergence(
    evaluations: Sequence[PathEvaluationResult],
    checkpoints: Sequence[int] | None = None,
) -> ConvergenceReport:
    """Evaluate convergence behavior at sequential path sample count checkpoints.

    Tracks convergence separately for:
    - Mean return
    - Median return
    - Probability of loss
    - VaR 95%
    - CVaR 95%
    - Median maximum drawdown
    - Probability of drawdown >= 10%
    """
    total_paths = len(evaluations)
    if total_paths == 0:
        raise ValueError("Cannot evaluate convergence on 0 evaluations.")

    if checkpoints is None:
        candidates = [25, 50, 100, 250, 500, 1000, 2500, 5000, 10000]
        pts = [c for c in candidates if c < total_paths]
        if not pts or pts[-1] != total_paths:
            pts.append(total_paths)
    else:
        pts = sorted(set([c for c in checkpoints if 1 <= c <= total_paths]))
        if not pts or pts[-1] != total_paths:
            pts.append(total_paths)

    records: list[ConvergenceCheckpoint] = []

    for k in pts:
        sub = evaluations[:k]
        returns = np.array([e.total_return for e in sub], dtype=np.float64)
        losses = np.array([1.0 if e.is_loss else 0.0 for e in sub])
        drawdowns = np.array([e.max_drawdown for e in sub], dtype=np.float64)
        dd10_breaches = np.array([1.0 if e.breached_drawdown_10pct else 0.0 for e in sub])

        mean_ret = float(np.mean(returns))
        med_ret = float(np.median(returns))
        std_ret = float(np.std(returns, ddof=1)) if k > 1 else 0.0

        p_loss = float(np.mean(losses))
        se_loss = math.sqrt((p_loss * (1.0 - p_loss)) / k) if k > 1 else 0.0

        var_95 = float(np.percentile(returns, 5))
        tail = returns[returns <= var_95]
        cvar_95 = float(np.mean(tail)) if len(tail) > 0 else var_95
        tail_size = len(tail)

        # Non-parametric standard error for 5th percentile via bootstrap or normal approximation
        var_se = (std_ret / math.sqrt(k)) * math.sqrt((0.05 * 0.95) / (stats_norm_pdf(1.645) ** 2)) if k > 10 else 0.0
        cvar_se = (std_ret / math.sqrt(max(1, tail_size))) if tail_size > 1 else 0.0

        med_dd = float(np.median(drawdowns))
        p_dd10 = float(np.mean(dd10_breaches))

        records.append(
            ConvergenceCheckpoint(
                sample_size=k,
                mean_return=mean_ret,
                median_return=med_ret,
                prob_loss=p_loss,
                prob_loss_se=se_loss,
                var_95=var_95,
                cvar_95=cvar_95,
                std_return=std_ret,
                max_drawdown_median=med_dd,
                prob_drawdown_10pct=p_dd10,
                tail_sample_size=tail_size,
                var_95_se=var_se,
                cvar_95_se=cvar_se,
            )
        )

    final_se = records[-1].prob_loss_se
    final_tail = records[-1].tail_sample_size

    # Check stability between last two checkpoints across all metrics
    conv_mean = True
    conv_median = True
    conv_loss = True
    conv_var = True
    conv_cvar = True
    conv_dd = True

    notes_list: list[str] = []

    if len(records) >= 2:
        p_rec = records[-2]
        u_rec = records[-1]

        diff_mean = abs(u_rec.mean_return - p_rec.mean_return)
        diff_med = abs(u_rec.median_return - p_rec.median_return)
        diff_loss = abs(u_rec.prob_loss - p_rec.prob_loss)
        diff_var = abs(u_rec.var_95 - p_rec.var_95)
        diff_cvar = abs(u_rec.cvar_95 - p_rec.cvar_95)
        diff_dd = abs(u_rec.max_drawdown_median - p_rec.max_drawdown_median)

        conv_mean = diff_mean <= 0.005  # <= 50 bps shift
        conv_median = diff_med <= 0.005
        conv_loss = diff_loss <= 0.02   # <= 2.0% loss probability shift
        conv_var = diff_var <= 0.01     # <= 100 bps VaR shift
        conv_cvar = diff_cvar <= 0.01   # <= 100 bps CVaR shift
        conv_dd = diff_dd <= 0.01

        if not conv_mean:
            notes_list.append(f"Mean return shifted by {diff_mean:.4f} (> 0.005 tolerance).")
        if not conv_loss:
            notes_list.append(f"Loss probability shifted by {diff_loss:.4f} (> 0.02 tolerance).")
        if not conv_var:
            notes_list.append(f"VaR (95%) shifted by {diff_var:.4f} (> 0.01 tolerance).")
        if not conv_cvar:
            notes_list.append(f"CVaR (95%) shifted by {diff_cvar:.4f} (> 0.01 tolerance).")

    is_overall_converged = all([conv_mean, conv_median, conv_loss, conv_var, conv_cvar, conv_dd])
    if is_overall_converged:
        notes = (
            f"All risk and return metrics demonstrated asymptotic convergence at N={records[-1].sample_size}. "
            f"Tail sample size: {final_tail} observations below 5th percentile."
        )
    else:
        notes = "Warning: Some tail risk metrics have not fully stabilized: " + "; ".join(notes_list)

    return ConvergenceReport(
        checkpoints=records,
        is_converged=is_overall_converged,
        final_standard_error=final_se,
        convergence_notes=notes,
        is_converged_mean=conv_mean,
        is_converged_median=conv_median,
        is_converged_prob_loss=conv_loss,
        is_converged_var_95=conv_var,
        is_converged_cvar_95=conv_cvar,
        is_converged_drawdown=conv_dd,
        tail_sample_size_final=final_tail,
    )


def stats_norm_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)
