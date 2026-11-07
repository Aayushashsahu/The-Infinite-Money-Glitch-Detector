"""Convergence analysis and stability tracking for Monte Carlo simulation.

Evaluates metric stability (mean return, VaR, loss probability) across
increasing simulation path sample sizes.
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
    """Evaluate convergence behavior at sequential path sample count checkpoints."""
    total_paths = len(evaluations)
    if total_paths == 0:
        raise ValueError("Cannot evaluate convergence on 0 evaluations.")

    if checkpoints is None:
        # Default logarithmic-scale checkpoints
        candidates = [25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000]
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

        mean_ret = float(np.mean(returns))
        med_ret = float(np.median(returns))
        std_ret = float(np.std(returns, ddof=1)) if k > 1 else 0.0

        p_loss = float(np.mean(losses))
        se_loss = math.sqrt((p_loss * (1.0 - p_loss)) / k) if k > 1 else 0.0

        var_95 = float(np.percentile(returns, 5))
        tail = returns[returns <= var_95]
        cvar_95 = float(np.mean(tail)) if len(tail) > 0 else var_95

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
            )
        )

    final_se = records[-1].prob_loss_se

    # Check stability between last two checkpoints
    is_converged = True
    notes = "Estimates demonstrated stable asymptotic convergence."
    if len(records) >= 2:
        penultimate = records[-2]
        ultimate = records[-1]
        diff_mean = abs(ultimate.mean_return - penultimate.mean_return)
        diff_loss = abs(ultimate.prob_loss - penultimate.prob_loss)
        if diff_mean > 0.02 or diff_loss > 0.05:
            is_converged = False
            notes = f"Warning: Estimates shifted materially between N={penultimate.sample_size} and N={ultimate.sample_size} (delta_mean={diff_mean:.4f}, delta_loss={diff_loss:.4f})."

    return ConvergenceReport(
        checkpoints=records,
        is_converged=is_converged,
        final_standard_error=final_se,
        convergence_notes=notes,
    )
