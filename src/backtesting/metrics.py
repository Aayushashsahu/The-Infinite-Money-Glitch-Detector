"""Comprehensive Performance and Risk Metrics for Historical Backtesting.

Reuses core mathematical risk primitives from `models.risk`:
- `historical_volatility`
- `max_drawdown`
- `historical_var`
- `historical_cvar`
- `sharpe_ratio`
And unit conversions from `core.conversions`:
- `annualized_return`

Adds:
- Sortino ratio (downside deviation)
- Calmar ratio
- Win rate, average win, average loss, profit factor
- Capital utilization and maximum borrowed exposure
- Benchmark-relative excess returns and alpha
- Explicit documentation of metric formulas and conventions
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from core.conversions import annualized_return
from models.risk import (
    historical_cvar,
    historical_var,
    historical_volatility,
    max_drawdown,
    sharpe_ratio,
)
from schemas.backtest import PerformanceMetrics, PortfolioSnapshot, TradeRecord, TradeStatus
from schemas.strategy import InterestConvention
from backtesting.benchmarks import BenchmarkSeries
from backtesting.financing import days_to_years


METRIC_ASSUMPTIONS_DOC: dict[str, str] = {
    "cumulative_net_profit": "Sum of realized net profits in borrowing currency A across all closed trades.",
    "total_return": "Cumulative net profit divided by initial portfolio capital.",
    "annualized_return": "Compounded constant annual rate equivalent to total return over actual calendar years.",
    "annualized_volatility": "Sample standard deviation (ddof=1) of periodic portfolio returns annualized by sqrt(periods_per_year).",
    "sharpe_ratio": "(Annualized mean return - risk-free rate) / annualized volatility.",
    "sortino_ratio": "(Annualized mean return - risk-free rate) / annualized downside deviation (penalizing only returns below risk-free).",
    "max_drawdown": "Largest peak-to-trough decline of the portfolio equity curve as a negative fraction.",
    "calmar_ratio": "Annualized return divided by absolute maximum drawdown.",
    "win_rate": "Count of trades with net_profit > 0 divided by total closed trades.",
    "profit_factor": "Gross realized profits from winning trades divided by absolute gross losses from losing trades.",
    "var_95": "Historical (empirical) 95% Value at Risk (lower quantile) of periodic returns.",
    "cvar_95": "Expected shortfall: arithmetic mean of returns at or below the 95% VaR threshold.",
    "capital_utilization": "Average ratio of active borrowed exposure to total portfolio equity.",
    "alpha": "Strategy annualized return minus benchmark annualized return.",
}


def calculate_sortino_ratio(
    returns: Sequence[float],
    risk_free_rate_annual: float | None = 0.0,
    periods_per_year: float = 252.0,
    periodic_risk_free_rates: Sequence[float] | None = None,
    return_dates: Sequence[Any] | None = None,
    periodic_risk_free_dates: Sequence[Any] | None = None,
) -> float | None:
    """Annualized Sortino ratio.

    Penalizes only downside deviations below the per-period risk-free rate.
    """
    if risk_free_rate_annual is None and periodic_risk_free_rates is None:
        return None
    arr = np.asarray(returns, dtype=float)
    if arr.size < 2:
        return None
    if return_dates is not None and periodic_risk_free_dates is not None:
        if list(return_dates) != list(periodic_risk_free_dates):
            return None
    if periodic_risk_free_rates is not None:
        rf_arr = np.asarray(periodic_risk_free_rates, dtype=float)
        if len(rf_arr) != len(arr):
            return None
        excess = arr - rf_arr
    else:
        per_period_rf = (risk_free_rate_annual or 0.0) / periods_per_year
        excess = arr - per_period_rf

    downside = np.minimum(excess, 0.0)
    downside_sq = np.sum(downside ** 2) / max(1, len(arr) - 1)
    downside_std = math.sqrt(downside_sq)

    if downside_std == 0:
        return None  # No downside risk
    mean_excess = float(np.mean(excess))
    return float((mean_excess / downside_std) * math.sqrt(periods_per_year))


def calculate_performance_metrics(
    trades: Sequence[TradeRecord],
    snapshots: Sequence[PortfolioSnapshot],
    initial_capital_a: float,
    risk_free_rate_annual: float | None = 0.0,
    benchmark: BenchmarkSeries | None = None,
    interest_convention: InterestConvention = InterestConvention.COMPOUND,
    periods_per_year: float = 252.0,
    cash_interest_earned: float = 0.0,
    periodic_risk_free_rates: Sequence[float] | None = None,
    periodic_risk_free_dates: Sequence[date] | None = None,
) -> PerformanceMetrics:
    """Calculate standardized performance and risk statistics for a completed backtest.

    Args:
        trades: Full history of closed and open trades.
        snapshots: Periodic mark-to-market portfolio snapshots.
        initial_capital_a: Starting capital in currency A.
        risk_free_rate_annual: Annualized risk-free rate benchmark. If None, Sharpe and Sortino are None.
        benchmark: Optional comparative benchmark series.
        interest_convention: Compounding rule.
        periods_per_year: Observation frequency (252 for daily snapshots, 12 for monthly).
        periodic_risk_free_rates: Optional time-varying periodic risk-free rates.
        periodic_risk_free_dates: Optional observation dates corresponding to periodic_risk_free_rates.
    """
    closed = [t for t in trades if t.status == TradeStatus.CLOSED and t.net_profit_a is not None]
    total_trades = len(closed)
    
    winning = [t for t in closed if (t.net_profit_a or 0.0) > 0]
    losing = [t for t in closed if (t.net_profit_a or 0.0) < 0]
    breakeven = [t for t in closed if (t.net_profit_a or 0.0) == 0]

    win_rate = len(winning) / total_trades if total_trades > 0 else 0.0
    cum_net_profit = sum((t.net_profit_a or 0.0) for t in closed) + cash_interest_earned
    tot_return = cum_net_profit / initial_capital_a if initial_capital_a > 0 else 0.0

    # Determine horizon in years from snapshots or trades
    if len(snapshots) >= 2:
        total_days = (snapshots[-1].as_of - snapshots[0].as_of).days
    elif closed:
        total_days = (closed[-1].exit_date - closed[0].entry_date).days if closed[-1].exit_date else 1
    else:
        total_days = 1
    total_years = max(1.0 / periods_per_year, days_to_years(total_days))

    # Annualized return
    try:
        ann_return = annualized_return(tot_return, total_years, interest_convention)
    except ValueError:
        ann_return = tot_return / total_years

    # Trade stats
    avg_win = float(np.mean([t.net_profit_a for t in winning])) if winning else 0.0
    avg_loss = float(np.mean([t.net_profit_a for t in losing])) if losing else 0.0

    gross_profit = sum(t.net_profit_a for t in winning) if winning else 0.0
    gross_loss = abs(sum(t.net_profit_a for t in losing)) if losing else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (None if gross_profit == 0 else 999.0)

    # Periodic returns from equity snapshots
    equity_curve = [s.equity_a for s in snapshots] if snapshots else [initial_capital_a, initial_capital_a + cum_net_profit]
    period_returns: list[float] = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]
        if prev > 0:
            period_returns.append((equity_curve[i] / prev) - 1.0)
        else:
            period_returns.append(0.0)

    # Date alignment verification for risk-free benchmark series
    ret_dates = [s.as_of for s in snapshots[1:]] if len(snapshots) >= 2 else None
    if periodic_risk_free_rates is not None:
        if periodic_risk_free_dates is not None and ret_dates is not None:
            if list(periodic_risk_free_dates) != ret_dates:
                periodic_risk_free_rates = None
        elif benchmark is not None and len(benchmark.dates) >= 2 and ret_dates is not None:
            if list(benchmark.dates[1:]) != ret_dates:
                periodic_risk_free_rates = None

    # Risk metrics from periodic returns
    if len(period_returns) >= 2:
        vol = historical_volatility(period_returns, periods_per_year=periods_per_year)
        if risk_free_rate_annual is None and periodic_risk_free_rates is None:
            sharpe = None
            sortino = None
        else:
            try:
                sharpe = sharpe_ratio(
                    period_returns,
                    risk_free_rate_annual=risk_free_rate_annual,
                    periods_per_year=periods_per_year,
                    periodic_risk_free_rates=periodic_risk_free_rates,
                    return_dates=ret_dates,
                    periodic_risk_free_dates=periodic_risk_free_dates,
                )
            except ValueError:
                sharpe = None

            sortino = calculate_sortino_ratio(
                period_returns,
                risk_free_rate_annual=risk_free_rate_annual,
                periods_per_year=periods_per_year,
                periodic_risk_free_rates=periodic_risk_free_rates,
                return_dates=ret_dates,
                periodic_risk_free_dates=periodic_risk_free_dates,
            )

        try:
            mdd = max_drawdown(period_returns)
        except ValueError:
            mdd = -1.0

        v95 = historical_var(period_returns, confidence=0.95)
        cv95 = historical_cvar(period_returns, confidence=0.95)
    else:
        vol = 0.0
        sharpe = None
        sortino = None
        mdd = 0.0
        v95 = 0.0
        cv95 = 0.0

    # Calmar ratio
    calmar: float | None = None
    if mdd < 0:
        calmar = ann_return / abs(mdd)

    # Capital exposure and utilization
    utilizations = [s.capital_utilization for s in snapshots] if snapshots else [0.0]
    avg_util = float(np.mean(utilizations))
    max_exp = max((s.total_borrowed_a for s in snapshots), default=0.0)

    # Benchmark comparison
    bm_name: str | None = None
    bm_tot: float | None = None
    bm_ann: float | None = None
    bm_sharpe: float | None = None
    alpha: float | None = None

    if benchmark is not None:
        bm_name = benchmark.name
        bm_tot = benchmark.total_return
        bm_ann = benchmark.annualized_return
        bm_sharpe = benchmark.sharpe_ratio
        alpha = (ann_return - benchmark.annualized_return) if len(closed) > 0 else None

    # Exact double-entry return attribution decomposition
    pure_gross_profit_a = sum((t.pure_gross_gain_a or 0.0) for t in closed)
    total_financing_costs_a = sum((t.interest_paid_a or 0.0) for t in closed)
    total_frictions_a = sum((t.total_frictions_a or 0.0) for t in closed)
    total_cash_interest_a = cash_interest_earned

    # Itemized spread, slippage, and gain decomposition
    observed_spread_cost_a = sum((t.observed_spread_cost_a or 0.0) for t in closed)
    modelled_spread_cost_a = sum((t.modelled_spread_cost_a or 0.0) for t in closed)
    slippage_cost_a = sum((t.slippage_cost_a or 0.0) for t in closed)
    fx_translation_gain_a = sum((t.fx_translation_gain_a or 0.0) for t in closed)
    investment_yield_gain_a = sum((t.investment_yield_gain_a or 0.0) for t in closed)

    reconciliation_residual_a = abs(
        cum_net_profit - (pure_gross_profit_a - total_financing_costs_a - total_frictions_a + total_cash_interest_a)
    )
    reconciliation_exact = reconciliation_residual_a <= 1e-10

    gross_ret = pure_gross_profit_a / initial_capital_a if initial_capital_a > 0 else 0.0
    fin_drag = total_financing_costs_a / initial_capital_a if initial_capital_a > 0 else 0.0
    tx_drag = total_frictions_a / initial_capital_a if initial_capital_a > 0 else 0.0
    cash_yield_ret = total_cash_interest_a / initial_capital_a if initial_capital_a > 0 else 0.0

    observed_spread_drag = observed_spread_cost_a / initial_capital_a if initial_capital_a > 0 else 0.0
    modelled_spread_drag = modelled_spread_cost_a / initial_capital_a if initial_capital_a > 0 else 0.0
    slippage_drag = slippage_cost_a / initial_capital_a if initial_capital_a > 0 else 0.0
    pure_fx_return = fx_translation_gain_a / initial_capital_a if initial_capital_a > 0 else 0.0
    investment_yield_return = investment_yield_gain_a / initial_capital_a if initial_capital_a > 0 else 0.0

    # Benchmark excess returns
    ann_excess = (ann_return - bm_ann) if bm_ann is not None else None
    cum_excess = (tot_return - bm_tot) if bm_tot is not None else None

    # Position-level volatility (on deployed capital rather than diluted portfolio equity)
    trade_rocs = [t.return_on_capital for t in closed if t.return_on_capital is not None]
    if len(trade_rocs) >= 2:
        pos_vol = float(np.std(trade_rocs, ddof=1) * math.sqrt(max(1.0, len(trade_rocs) / total_years)))
    else:
        pos_vol = None

    return PerformanceMetrics(
        total_trades=total_trades,
        winning_trades=len(winning),
        losing_trades=len(losing),
        break_even_trades=len(breakeven),
        win_rate=win_rate,
        cumulative_net_profit=cum_net_profit,
        total_return=tot_return,
        annualized_return=ann_return,
        annualized_volatility=vol,
        position_annualized_volatility=pos_vol,
        gross_trade_return=gross_ret,
        financing_cost_drag=fin_drag,
        transaction_cost_drag=tx_drag,
        cash_yield_return=cash_yield_ret,
        pure_gross_profit_a=pure_gross_profit_a,
        total_financing_costs_a=total_financing_costs_a,
        total_frictions_a=total_frictions_a,
        total_cash_interest_a=total_cash_interest_a,
        observed_spread_cost_a=observed_spread_cost_a,
        modelled_spread_cost_a=modelled_spread_cost_a,
        slippage_cost_a=slippage_cost_a,
        fx_translation_gain_a=fx_translation_gain_a,
        investment_yield_gain_a=investment_yield_gain_a,
        observed_spread_drag=observed_spread_drag,
        modelled_spread_drag=modelled_spread_drag,
        slippage_drag=slippage_drag,
        pure_fx_return=pure_fx_return,
        investment_yield_return=investment_yield_return,
        reconciliation_residual_a=reconciliation_residual_a,
        reconciliation_exact=reconciliation_exact,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        max_drawdown=mdd,
        calmar_ratio=calmar,
        avg_winning_trade=avg_win,
        avg_losing_trade=avg_loss,
        profit_factor=profit_factor,
        var_95=v95,
        cvar_95=cv95,
        avg_capital_utilization=avg_util,
        max_exposure_a=max_exp,
        benchmark_name=bm_name,
        benchmark_total_return=bm_tot,
        benchmark_annualized_return=bm_ann,
        benchmark_sharpe_ratio=bm_sharpe,
        alpha=alpha,
        annualized_excess_return=ann_excess,
        cumulative_excess_return=cum_excess,
        metric_assumptions=dict(METRIC_ASSUMPTIONS_DOC),
    )
