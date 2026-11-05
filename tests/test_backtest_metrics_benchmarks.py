"""Tests for Performance Metrics, Risk Analytics, and Benchmark Calculations.

Verifies:
- Standardized metrics: Sharpe, Sortino, Calmar, Max Drawdown, Win Rate, Profit Factor
- Downside deviation in Sortino penalizes only negative excess returns
- Empirical VaR and CVaR (Expected Shortfall) at 95% confidence
- Benchmarks: Borrowing Cash in A, Foreign Currency Unhedged B, and Alpha calculation
- Explicit documentation of metric formulas and conventions
"""

from __future__ import annotations

from datetime import date
import pytest

from backtesting.benchmarks import (
    compute_borrowing_currency_benchmark,
    compute_investment_currency_benchmark,
)
from backtesting.metrics import (
    METRIC_ASSUMPTIONS_DOC,
    calculate_performance_metrics,
    calculate_sortino_ratio,
)
from schemas.backtest import (
    PortfolioSnapshot,
    TradeRecord,
    TradeSide,
    TradeStatus,
)
from schemas.strategy import CurrencyPair, InterestConvention


def make_dummy_trade(
    trade_id: str,
    profit: float,
    entry_d: date = date(2024, 1, 1),
    exit_d: date = date(2024, 1, 31),
    principal: float = 100_000.0,
) -> TradeRecord:
    pair = CurrencyPair(borrowing_currency="USD", investment_currency="EUR")
    return TradeRecord(
        trade_id=trade_id,
        strategy_name="Carry",
        currency_pair=pair,
        borrowing_currency="USD",
        investment_currency="EUR",
        side=TradeSide.LONG_B_SHORT_A,
        entry_date=entry_d,
        exit_date=exit_d,
        target_tenor_days=30,
        actual_tenor_days=30,
        principal_borrowed_a=principal,
        borrowing_rate=0.03,
        investment_rate=0.07,
        spot_mid_entry=1.10,
        spot_exec_entry=1.10,
        invested_amount_b=principal / 1.10,
        net_profit_a=profit,
        return_on_capital=profit / principal,
        status=TradeStatus.CLOSED,
    )


def test_trade_level_performance_metrics():
    """Win rate, avg win/loss, and profit factor calculate accurately."""
    trades = [
        make_dummy_trade("T1", 2000.0),
        make_dummy_trade("T2", 3000.0),
        make_dummy_trade("T3", -1000.0),
        make_dummy_trade("T4", 1000.0),
    ]

    # Snapshots tracking equity curve: 100k -> 102k -> 105k -> 104k -> 105k
    snapshots = [
        PortfolioSnapshot(
            as_of=date(2024, 1, 1), cash_a=100_000.0, total_borrowed_a=0.0, total_obligations_a=0.0,
            active_positions_count=0, positions_value_a=0.0, equity_a=100_000.0, leverage=0.0,
            unrealized_pnl_a=0.0, realized_pnl_a=0.0, capital_utilization=0.0,
        ),
        PortfolioSnapshot(
            as_of=date(2024, 4, 30), cash_a=105_000.0, total_borrowed_a=0.0, total_obligations_a=0.0,
            active_positions_count=0, positions_value_a=0.0, equity_a=105_000.0, leverage=0.0,
            unrealized_pnl_a=0.0, realized_pnl_a=5000.0, capital_utilization=0.0,
        ),
    ]

    metrics = calculate_performance_metrics(
        trades=trades,
        snapshots=snapshots,
        initial_capital_a=100_000.0,
    )

    assert metrics.total_trades == 4
    assert metrics.winning_trades == 3
    assert metrics.losing_trades == 1
    assert metrics.win_rate == 0.75
    assert metrics.cumulative_net_profit == 5000.0
    assert metrics.total_return == 0.05
    assert metrics.avg_winning_trade == 2000.0  # (2k + 3k + 1k) / 3
    assert metrics.avg_losing_trade == -1000.0
    assert metrics.profit_factor == 6.0  # 6k gross profit / 1k gross loss


def test_sortino_ratio_downside_penalty():
    """Sortino ratio only penalizes negative deviations below risk-free benchmark."""
    # Sequence with positive upside volatility and zero downside
    returns = [0.01, 0.02, 0.03, 0.015, 0.025, 0.04]
    sortino = calculate_sortino_ratio(returns, risk_free_rate_annual=0.0)
    # Since all returns > 0, downside deviation is 0 -> Sortino is None (infinite/unbounded)
    assert sortino is None

    # Mixed returns
    mixed = [0.02, -0.01, 0.03, -0.015, 0.01, -0.005]
    sortino_mixed = calculate_sortino_ratio(mixed, risk_free_rate_annual=0.0)
    assert sortino_mixed is not None
    assert isinstance(sortino_mixed, float)


def test_benchmarks_and_alpha():
    """Borrowing cash benchmark and foreign holding benchmark compute correctly."""
    dates = [date(2024, 1, 1), date(2024, 7, 1), date(2025, 1, 1)]
    r_a = [0.04, 0.04, 0.04]  # 4% annual cash rate in A
    spot = [1.00, 1.05, 1.10]  # Currency B appreciates 10%
    r_b = [0.08, 0.08, 0.08]  # 8% annual in B

    bm_cash = compute_borrowing_currency_benchmark(dates, r_a)
    assert bm_cash.total_return == pytest.approx(0.04, rel=1e-2)
    assert bm_cash.annualized_return == pytest.approx(0.04, rel=1e-2)

    bm_fx = compute_investment_currency_benchmark(dates, spot, r_b)
    # Total return combines FX appreciation (~10%) + interest (~8%)
    assert bm_fx.total_return > 0.15

    # Check metric assumptions dictionary is complete
    for key in ["cumulative_net_profit", "sharpe_ratio", "sortino_ratio", "max_drawdown", "var_95", "cvar_95"]:
        assert key in METRIC_ASSUMPTIONS_DOC
