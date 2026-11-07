"""Distributional risk metrics and Monte Carlo standard error calculations.

Computes empirical quantiles, VaR, CVaR, loss probabilities with standard errors,
and aggregates double-entry cash ledger attribution across simulated paths.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from simulation.monte_carlo.calibration import compute_quantiles
from simulation.monte_carlo.schemas import (
    DistributionMetrics,
    PathEvaluationResult,
)


def calculate_distribution_metrics(
    evaluations: Sequence[PathEvaluationResult],
    horizon_steps: int = 252,
) -> DistributionMetrics:
    """Aggregate path evaluation results into comprehensive distributional risk metrics."""
    n = len(evaluations)
    if n == 0:
        raise ValueError("Cannot calculate distribution metrics from 0 path evaluations.")

    equities = np.array([e.terminal_equity for e in evaluations], dtype=np.float64)
    returns = np.array([e.total_return for e in evaluations], dtype=np.float64)
    ann_returns = np.array([e.annualized_return for e in evaluations], dtype=np.float64)
    drawdowns = np.array([e.max_drawdown for e in evaluations], dtype=np.float64)
    volatilities = np.array([e.annualized_volatility for e in evaluations], dtype=np.float64)

    # Quantiles
    q_equity = compute_quantiles(equities)
    q_ret = compute_quantiles(returns)
    q_ann_ret = compute_quantiles(ann_returns)
    q_dd = compute_quantiles(drawdowns)
    q_vol = compute_quantiles(volatilities)

    # VaR & CVaR (95% confidence level, empirical 5th percentile)
    var_95 = float(np.percentile(returns, 5))
    tail_returns = returns[returns <= var_95]
    cvar_95 = float(np.mean(tail_returns)) if len(tail_returns) > 0 else var_95

    # Probability of loss & Monte Carlo standard error
    losses = np.array([1.0 if e.is_loss else 0.0 for e in evaluations])
    p_loss = float(np.mean(losses))
    se_loss = math.sqrt((p_loss * (1.0 - p_loss)) / n) if n > 1 else 0.0
    ci_loss_lower = max(0.0, p_loss - 1.96 * se_loss)
    ci_loss_upper = min(1.0, p_loss + 1.96 * se_loss)

    # Drawdown breach probabilities & SEs
    dd_05 = np.array([1.0 if e.breached_drawdown_5pct else 0.0 for e in evaluations])
    p_dd_05 = float(np.mean(dd_05))
    se_dd_05 = math.sqrt((p_dd_05 * (1.0 - p_dd_05)) / n) if n > 1 else 0.0

    dd_10 = np.array([1.0 if e.breached_drawdown_10pct else 0.0 for e in evaluations])
    p_dd_10 = float(np.mean(dd_10))
    se_dd_10 = math.sqrt((p_dd_10 * (1.0 - p_dd_10)) / n) if n > 1 else 0.0

    dd_20 = np.array([1.0 if e.breached_drawdown_20pct else 0.0 for e in evaluations])
    p_dd_20 = float(np.mean(dd_20))
    se_dd_20 = math.sqrt((p_dd_20 * (1.0 - p_dd_20)) / n) if n > 1 else 0.0

    # Double-entry ledger attribution means
    mean_pure_gross = float(np.mean([e.pure_gross_gain_a for e in evaluations]))
    mean_fx_gain = float(np.mean([e.fx_translation_gain_a for e in evaluations]))
    mean_yield_gain = float(np.mean([e.investment_yield_gain_a for e in evaluations]))
    mean_financing = float(np.mean([e.total_financing_costs_a for e in evaluations]))
    mean_frictions = float(np.mean([e.total_frictions_a for e in evaluations]))
    mean_cash_int = float(np.mean([e.total_cash_interest_a for e in evaluations]))
    mean_net_profit = float(np.mean([e.cumulative_net_profit_a for e in evaluations]))
    mean_residual = float(np.mean([e.reconciliation_residual_a for e in evaluations]))

    all_exact = all(e.reconciliation_exact for e in evaluations)

    return DistributionMetrics(
        num_paths=n,
        horizon_steps=horizon_steps,
        terminal_equity=q_equity,
        total_return=q_ret,
        annualized_return=q_ann_ret,
        max_drawdown=q_dd,
        annualized_volatility=q_vol,
        var_95=var_95,
        cvar_95=cvar_95,
        prob_loss=p_loss,
        prob_loss_se=se_loss,
        prob_loss_ci_lower=ci_loss_lower,
        prob_loss_ci_upper=ci_loss_upper,
        prob_drawdown_5pct=p_dd_05,
        prob_drawdown_5pct_se=se_dd_05,
        prob_drawdown_10pct=p_dd_10,
        prob_drawdown_10pct_se=se_dd_10,
        prob_drawdown_20pct=p_dd_20,
        prob_drawdown_20pct_se=se_dd_20,
        mean_pure_gross_gain_a=mean_pure_gross,
        mean_fx_translation_gain_a=mean_fx_gain,
        mean_investment_yield_gain_a=mean_yield_gain,
        mean_financing_costs_a=mean_financing,
        mean_frictions_a=mean_frictions,
        mean_cash_interest_a=mean_cash_int,
        mean_net_profit_a=mean_net_profit,
        mean_reconciliation_residual_a=mean_residual,
        all_paths_reconciled=all_exact,
    )
