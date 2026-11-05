"""Tests for Portfolio Accounting, Capital Allocation, and Position Limits.

Verifies:
- Capital allocation limits: prevent allocating the same principal to multiple simultaneous positions
- Max leverage constraints
- Maximum active concurrent positions cap
- Cash balance and realized PnL updates
- Mark-to-market portfolio snapshotting
"""

from __future__ import annotations

from datetime import date
import pytest

from backtesting.execution import ExecutionEngine
from backtesting.portfolio import Portfolio
from schemas.backtest import (
    ExecutionConfig,
    PositionSizingConfig,
    PositionSizingMethod,
    TradeStatus,
)
from schemas.strategy import CurrencyPair


def test_prevent_double_allocation_and_max_positions():
    """When max_active_positions=1, a second simultaneous trade cannot allocate capital."""
    sizing_cfg = PositionSizingConfig(
        method=PositionSizingMethod.FIXED_AMOUNT,
        fixed_amount=50_000.0,
        max_active_positions=1,
        max_leverage=1.0,
    )
    portfolio = Portfolio(initial_capital_a=100_000.0, sizing_config=sizing_cfg)
    exec_engine = ExecutionEngine()
    pair = CurrencyPair(borrowing_currency="USD", investment_currency="EUR")

    # Trade 1
    t1_sizing = portfolio.calculate_position_size()
    assert t1_sizing.is_allowed is True
    assert t1_sizing.allocated_amount_a == 50_000.0

    t1 = exec_engine.open_trade(
        trade_id="TRD_1",
        strategy_name="Carry",
        currency_pair=pair,
        entry_date=date(2024, 1, 1),
        tenor_days=30,
        principal_borrowed_a=t1_sizing.allocated_amount_a,
        borrowing_rate=0.03,
        investment_rate=0.07,
        spot_mid_entry=1.10,
    )
    assert portfolio.register_open_trade(t1) is True
    assert len(portfolio.open_trades) == 1

    # Attempt Trade 2 while Trade 1 is still open
    t2_sizing = portfolio.calculate_position_size()
    assert t2_sizing.is_allowed is False
    assert "Max active positions reached" in (t2_sizing.rejection_reason or "")


def test_leverage_limit_enforcement():
    """Capital cannot be borrowed beyond equity * max_leverage."""
    sizing_cfg = PositionSizingConfig(
        method=PositionSizingMethod.FIXED_AMOUNT,
        fixed_amount=60_000.0,
        max_active_positions=3,
        max_leverage=1.0,  # Max total exposure = 100k
    )
    portfolio = Portfolio(initial_capital_a=100_000.0, sizing_config=sizing_cfg)
    exec_engine = ExecutionEngine()
    pair = CurrencyPair(borrowing_currency="USD", investment_currency="EUR")

    # First trade: 60k
    s1 = portfolio.calculate_position_size()
    assert s1.allocated_amount_a == 60_000.0
    t1 = exec_engine.open_trade(
        "T1", "Carry", pair, date(2024, 1, 1), 30, s1.allocated_amount_a, 0.03, 0.07, 1.10
    )
    portfolio.register_open_trade(t1)

    # Second trade: remaining capacity is 40k (100k - 60k)
    s2 = portfolio.calculate_position_size()
    assert s2.is_allowed is True
    assert s2.allocated_amount_a == 40_000.0  # Capped at remaining capacity!
    t2 = exec_engine.open_trade(
        "T2", "Carry", pair, date(2024, 1, 1), 30, s2.allocated_amount_a, 0.03, 0.07, 1.10
    )
    portfolio.register_open_trade(t2)

    # Third trade: 0 capacity remaining
    s3 = portfolio.calculate_position_size()
    assert s3.is_allowed is False
    assert "Borrowing capacity exhausted" in (s3.rejection_reason or "")


def test_cash_accounting_on_trade_closure():
    """Closing a profitable trade credits cash and realizes profit."""
    portfolio = Portfolio(initial_capital_a=100_000.0)
    exec_engine = ExecutionEngine(
        ExecutionConfig(bid_ask_spread_bps=0.0, slippage_bps=0.0, variable_fee_bps=0.0)
    )
    pair = CurrencyPair(borrowing_currency="USD", investment_currency="EUR")

    t = exec_engine.open_trade(
        "T1", "Carry", pair, date(2024, 1, 1), 365, 100_000.0, 0.02, 0.10, 1.00
    )
    portfolio.register_open_trade(t)

    # Close at spot 1.00: investment grew by 10% (10k), borrowing cost 2% (2k) -> Net profit = +8k
    closed = exec_engine.close_trade(t, exit_date=date(2024, 12, 31), spot_mid_exit=1.00)
    assert closed.net_profit_a == pytest.approx(8000.0, rel=1e-5)

    portfolio.register_closed_trade(closed)
    assert len(portfolio.open_trades) == 0
    assert len(portfolio.closed_trades) == 1
    assert portfolio.realized_pnl_a == pytest.approx(8000.0, rel=1e-5)
    assert portfolio.cash_a == pytest.approx(108_000.0, rel=1e-5)


def test_mark_to_market_snapshot():
    """Snapshot accurately marks open positions, accrued liabilities, and equity."""
    portfolio = Portfolio(initial_capital_a=100_000.0)
    exec_engine = ExecutionEngine(
        ExecutionConfig(bid_ask_spread_bps=0.0, slippage_bps=0.0, variable_fee_bps=0.0)
    )
    pair = CurrencyPair(borrowing_currency="USD", investment_currency="EUR")

    t = exec_engine.open_trade(
        "T1", "Carry", pair, date(2024, 1, 1), 365, 50_000.0, 0.04, 0.08, 1.00
    )
    portfolio.register_open_trade(t)

    # Snapshot on day 180 at spot 1.02
    snap = portfolio.snapshot(
        as_of=date(2024, 6, 29),
        current_spot_rates={"USD/EUR": 1.02},
    )

    assert snap.active_positions_count == 1
    assert snap.total_borrowed_a == 50_000.0
    assert snap.total_obligations_a > 50_000.0  # Accrued interest added
    assert snap.positions_value_a > 50_000.0
    assert snap.equity_a > 100_000.0  # Profitable intermediate move
