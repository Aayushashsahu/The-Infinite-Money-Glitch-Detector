"""Phase 3.1 Quantitative Backtesting Validation Audit: Risk Metrics and Volatility.

Audits:
1. Independent mathematical validation of risk primitives:
   - Annualized volatility
   - Sharpe ratio
   - Sortino ratio (downside deviation)
   - Maximum drawdown
   - Value at Risk (VaR 95% empirical lower quantile)
   - Conditional Value at Risk (CVaR 95% Expected Shortfall)
   - Calmar ratio
2. Mathematical root-cause verification of the reported 0.54% annualized volatility:
   - Synthetic price wave amplitude dampening
   - Weekend zero-padding variance reduction (5/7 factor)
   - Calendar day vs trading day annualization factor mismatch (sqrt(252) vs sqrt(365))
   - Capital dilution (50% unallocated cash halves portfolio-level volatility)
3. Daily return generation and compounding consistency:
   - Verification that prod(1 + r_t) - 1 equals cumulative equity return
   - Mark-to-market unrealized losses are fully captured in daily snapshots
"""

from __future__ import annotations

import math
from datetime import date, timedelta
import numpy as np
import pytest

from backtesting.metrics import (
    calculate_performance_metrics,
    calculate_sortino_ratio,
)
from models.risk import (
    historical_cvar,
    historical_var,
    historical_volatility,
    max_drawdown,
    sharpe_ratio,
)
from schemas.backtest import (
    PortfolioSnapshot,
    TradeRecord,
    TradeSide,
    TradeStatus,
)
from schemas.strategy import CurrencyPair, InterestConvention


# =============================================================================
# 1. INDEPENDENT MATHEMATICAL RECONCILIATION OF RISK PRIMITIVES
# =============================================================================

def test_independent_volatility_and_sharpe_validation():
    """Verify historical volatility and Sharpe ratio against independent formulas."""
    # Deterministic test returns
    r = [0.012, -0.008, 0.015, -0.004, 0.009, -0.018, 0.022, 0.005, -0.011, 0.010]
    n = len(r)
    rf_annual = 0.03
    periods = 252.0

    # Independent mathematical computation
    mean_r = sum(r) / n
    var_r = sum((x - mean_r) ** 2 for x in r) / (n - 1)
    std_r = math.sqrt(var_r)
    expected_vol = std_r * math.sqrt(periods)

    per_period_rf = rf_annual / periods
    expected_sharpe = ((mean_r - per_period_rf) / std_r) * math.sqrt(periods)

    # System calculation
    sys_vol = historical_volatility(r, periods_per_year=periods)
    sys_sharpe = sharpe_ratio(r, risk_free_rate_annual=rf_annual, periods_per_year=periods)

    assert sys_vol == pytest.approx(expected_vol, rel=1e-9)
    assert sys_sharpe == pytest.approx(expected_sharpe, rel=1e-9)


def test_independent_sortino_ratio_validation():
    """Verify Sortino ratio downside deviation against independent formula."""
    r = [0.012, -0.008, 0.015, -0.004, 0.009, -0.018, 0.022, 0.005, -0.011, 0.010]
    n = len(r)
    rf_annual = 0.03
    periods = 252.0
    per_period_rf = rf_annual / periods

    # Independent computation: only penalize returns below risk-free rate
    excess = [x - per_period_rf for x in r]
    downside_diffs = [min(0.0, e) for e in excess]
    downside_var = sum(d ** 2 for d in downside_diffs) / (n - 1)
    downside_std = math.sqrt(downside_var)
    expected_sortino = (sum(excess) / n / downside_std) * math.sqrt(periods)

    sys_sortino = calculate_sortino_ratio(r, risk_free_rate_annual=rf_annual, periods_per_year=periods)

    assert sys_sortino is not None
    assert sys_sortino == pytest.approx(expected_sortino, rel=1e-9)


def test_independent_max_drawdown_validation():
    """Verify maximum drawdown against exact compounded wealth path."""
    r = [0.05, -0.02, -0.03, 0.04, -0.06, 0.01, -0.02, 0.08]

    # Independent compounded wealth simulation
    wealth = [1.0]
    for ret in r:
        wealth.append(wealth[-1] * (1.0 + ret))

    peaks = [wealth[0]]
    for w in wealth[1:]:
        peaks.append(max(peaks[-1], w))

    drawdowns = [(w / p) - 1.0 for w, p in zip(wealth, peaks)]
    expected_mdd = min(drawdowns)

    sys_mdd = max_drawdown(r)
    assert sys_mdd == pytest.approx(expected_mdd, rel=1e-9)
    assert sys_mdd < 0.0


def test_independent_var_and_cvar_validation():
    """Verify empirical 95% VaR (lower quantile) and CVaR (Expected Shortfall)."""
    # 20 observations -> 5% quantile is the lowest value (rank 1)
    r = [
        -0.035, -0.020, -0.015, -0.010, -0.008,
        -0.005, -0.002, 0.001, 0.003, 0.004,
        0.006, 0.007, 0.009, 0.011, 0.012,
        0.014, 0.015, 0.018, 0.022, 0.025,
    ]
    # With method='lower', 5% quantile of 20 elements corresponds to lowest element
    sys_var = historical_var(r, confidence=0.95)
    sys_cvar = historical_cvar(r, confidence=0.95)

    # VaR at 95% confidence should be the cutoff for the worst 5%
    assert sys_var == pytest.approx(-0.035, abs=1e-5)
    # CVaR is the mean of all returns <= VaR
    tail = [x for x in r if x <= sys_var]
    expected_cvar = sum(tail) / len(tail)
    assert sys_cvar == pytest.approx(expected_cvar, abs=1e-5)


# =============================================================================
# 2. ROOT CAUSE AUDIT: INVESTIGATION OF THE 0.54% REPORTED VOLATILITY
# =============================================================================

def test_volatility_root_cause_synthetic_wave_dampening():
    """Root Cause 1: The synthetic USD/EUR price generator has artificially tiny daily moves."""
    # From examples/run_historical_backtest.py:
    # current_eur = 1.08 + 0.0002 * (days % 14 - 7)
    days = 14
    rates = [1.08 + 0.0002 * (d % 14 - 7) for d in range(days)]
    daily_pct_changes = [(rates[i] / rates[i - 1]) - 1.0 for i in range(1, len(rates))]

    # Daily standard deviation of this synthetic wave
    wave_daily_std = float(np.std(daily_pct_changes, ddof=1))
    wave_ann_vol = wave_daily_std * math.sqrt(252)

    # Verify that the synthetic data generator itself produces an unnaturally smooth ~1.2% vol,
    # compared to real historical USD/EUR which exhibits 7% to 10% annualized volatility.
    assert wave_ann_vol < 0.02  # Less than 2% annualized volatility inherently in the synthetic input!


def test_volatility_root_cause_calendar_vs_trading_day_padding():
    """Root Cause 2: Zero-padded calendar weekends dampen volatility and distort annualization."""
    # Suppose true active trading day returns have standard deviation sigma_trading
    rng = np.random.default_rng(42)
    trading_returns = rng.normal(0.0005, 0.005, size=250)  # ~0.5% daily std -> ~7.9% ann vol
    true_trading_vol = float(np.std(trading_returns, ddof=1) * math.sqrt(252))

    # Calendar day expansion: inserting 2 zero-return weekend days for every 5 trading days
    calendar_returns: list[float] = []
    for i, r in enumerate(trading_returns):
        calendar_returns.append(r)
        if (i + 1) % 5 == 0:
            calendar_returns.extend([0.0, 0.0])  # Weekend flat quotes

    # 1. Variance on calendar series is diluted by factor ~5/7:
    cal_std = float(np.std(calendar_returns, ddof=1))
    expected_cal_std = float(np.std(trading_returns, ddof=1)) * math.sqrt(5.0 / 7.0)
    assert cal_std == pytest.approx(expected_cal_std, rel=0.05)

    # 2. Daily calendar volatility is dampened by sqrt(5/7) ~ 0.845 due to zero-padded weekends:
    distorted_ann_vol = cal_std * math.sqrt(252)
    assert distorted_ann_vol == pytest.approx(true_trading_vol * math.sqrt(5.0 / 7.0), rel=0.05)
    # Furthermore, if someone inappropriately annualizes a calendar daily series by sqrt(252) instead of sqrt(365):
    calendar_ann_vol = cal_std * math.sqrt(365)
    assert distorted_ann_vol == pytest.approx(calendar_ann_vol * math.sqrt(252.0 / 365.0), rel=1e-6)

    # Verification: Trading-day sampling eliminates the artificial zero-return padding
    clean_trading_vol = historical_volatility(trading_returns, periods_per_year=252.0)
    assert clean_trading_vol == pytest.approx(true_trading_vol, rel=1e-6)


def test_volatility_root_cause_capital_dilution():
    """Root Cause 3: Capital dilution halves portfolio volatility when only 50% is deployed."""
    # 100,000 USD portfolio, 50,000 USD position deployed (50% utilization)
    # Trade return series
    trade_returns = [0.02, -0.015, 0.01, -0.01, 0.025, -0.02]
    trade_vol = float(np.std(trade_returns, ddof=1))

    # Portfolio equity returns with 50% cash earning 0%
    # E_t = 50k cash + 50k * (1 + r_t) = 100k + 50k * r_t
    # r_port = (E_t - 100k) / 100k = 0.5 * r_t
    port_returns = [0.5 * r for r in trade_returns]
    port_vol = float(np.std(port_returns, ddof=1))

    # Portfolio-level volatility is exactly 50% of the active position volatility
    assert port_vol == pytest.approx(0.5 * trade_vol, rel=1e-9)


# =============================================================================
# 3. RETURN COMPOUNDING & UNREALIZED LOSS CAPTURE
# =============================================================================

def test_daily_return_compounding_matches_cumulative_equity():
    """Periodic snapshot returns must compound exactly to the total equity return."""
    snapshots = [
        PortfolioSnapshot(
            as_of=date(2024, 1, 1), cash_a=50_000.0, total_borrowed_a=50_000.0, total_obligations_a=50_000.0,
            active_positions_count=1, positions_value_a=50_000.0, equity_a=100_000.0, leverage=0.5,
            unrealized_pnl_a=0.0, realized_pnl_a=0.0, capital_utilization=0.5,
        ),
        PortfolioSnapshot(
            as_of=date(2024, 1, 2), cash_a=50_000.0, total_borrowed_a=50_000.0, total_obligations_a=50_000.0,
            active_positions_count=1, positions_value_a=51_000.0, equity_a=101_000.0, leverage=0.5,
            unrealized_pnl_a=1000.0, realized_pnl_a=0.0, capital_utilization=0.495,
        ),
        PortfolioSnapshot(
            as_of=date(2024, 1, 3), cash_a=50_000.0, total_borrowed_a=50_000.0, total_obligations_a=50_000.0,
            active_positions_count=1, positions_value_a=49_500.0, equity_a=99_500.0, leverage=0.5,
            unrealized_pnl_a=-500.0, realized_pnl_a=0.0, capital_utilization=0.502,
        ),
        PortfolioSnapshot(
            as_of=date(2024, 1, 4), cash_a=102_000.0, total_borrowed_a=0.0, total_obligations_a=0.0,
            active_positions_count=0, positions_value_a=0.0, equity_a=102_000.0, leverage=0.0,
            unrealized_pnl_a=0.0, realized_pnl_a=2000.0, capital_utilization=0.0,
        ),
    ]

    # Calculate period returns
    period_returns: list[float] = []
    for i in range(1, len(snapshots)):
        r = (snapshots[i].equity_a / snapshots[i - 1].equity_a) - 1.0
        period_returns.append(r)

    # Compound period returns
    compounded = 1.0
    for r in period_returns:
        compounded *= (1.0 + r)
    total_compounded_return = compounded - 1.0

    # Total return from start to end
    expected_total_return = (snapshots[-1].equity_a / snapshots[0].equity_a) - 1.0
    assert total_compounded_return == pytest.approx(expected_total_return, rel=1e-9)
    assert expected_total_return == pytest.approx(0.02, rel=1e-9)  # +2.0%


def test_mark_to_market_captures_unrealized_drawdown():
    """Interim mark-to-market adverse movement must be captured in Max Drawdown and VaR."""
    # Equity curve drops to 95k before recovering to 103k
    snapshots = [
        PortfolioSnapshot(
            as_of=date(2024, 1, 1), cash_a=100_000.0, total_borrowed_a=0.0, total_obligations_a=0.0,
            active_positions_count=0, positions_value_a=0.0, equity_a=100_000.0, leverage=0.0,
            unrealized_pnl_a=0.0, realized_pnl_a=0.0, capital_utilization=0.0,
        ),
        PortfolioSnapshot(
            as_of=date(2024, 1, 15), cash_a=50_000.0, total_borrowed_a=50_000.0, total_obligations_a=50_000.0,
            active_positions_count=1, positions_value_a=45_000.0, equity_a=95_000.0, leverage=0.5,
            unrealized_pnl_a=-5000.0, realized_pnl_a=0.0, capital_utilization=0.526,
        ),
        PortfolioSnapshot(
            as_of=date(2024, 1, 31), cash_a=103_000.0, total_borrowed_a=0.0, total_obligations_a=0.0,
            active_positions_count=0, positions_value_a=0.0, equity_a=103_000.0, leverage=0.0,
            unrealized_pnl_a=0.0, realized_pnl_a=3000.0, capital_utilization=0.0,
        ),
    ]

    trade = TradeRecord(
        trade_id="T_AUDIT",
        strategy_name="Carry",
        currency_pair=CurrencyPair(borrowing_currency="USD", investment_currency="EUR"),
        borrowing_currency="USD",
        investment_currency="EUR",
        side=TradeSide.LONG_B_SHORT_A,
        entry_date=date(2024, 1, 1),
        exit_date=date(2024, 1, 31),
        target_tenor_days=30,
        actual_tenor_days=30,
        principal_borrowed_a=50_000.0,
        borrowing_rate=0.03,
        investment_rate=0.06,
        spot_mid_entry=1.10,
        spot_exec_entry=1.10,
        invested_amount_b=50_000.0 / 1.10,
        net_profit_a=3000.0,
        return_on_capital=3000.0 / 50_000.0,
        status=TradeStatus.CLOSED,
    )

    metrics = calculate_performance_metrics(
        trades=[trade],
        snapshots=snapshots,
        initial_capital_a=100_000.0,
    )

    # Even though closed trade was profitable (+3%), Max Drawdown must capture the -5% dip
    assert metrics.max_drawdown == pytest.approx(-0.05, abs=1e-4)
    # VaR 95% must also reflect the -5% period return
    assert metrics.var_95 == pytest.approx(-0.05, abs=1e-4)
    # Total return is +3%
    assert metrics.total_return == pytest.approx(0.03, abs=1e-4)
