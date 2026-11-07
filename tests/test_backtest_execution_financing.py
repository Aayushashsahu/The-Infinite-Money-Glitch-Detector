"""Tests for Execution Engine, Bid/Ask Spreads, Slippage, Fees, and Financing.

Verifies:
- Bid/ask spread: Ask rate is paid at entry, Bid rate received at exit
- Slippage: Adverse impact on entry and exit
- Proportional and fixed transaction costs
- Fixed and variable financing calculations matching core math
- Loan repayment and accrued intermediate liabilities
- Equivalence: Frictionless backtest execution matches `calculate_carry_trade` from `models.carry_trade`
"""

from __future__ import annotations

from datetime import date
import pytest

from backtesting.execution import (
    ExecutionEngine,
    compute_entry_execution_rate,
    compute_exit_execution_rate,
)
from backtesting.financing import (
    DayCountConvention,
    RatePeriod,
    calculate_accrued_liability,
    calculate_fixed_financing,
    calculate_variable_financing,
)
from core.interest import loan_repayment
from models.carry_trade import CarryTradeInput, calculate_carry_trade
from schemas.backtest import ExecutionConfig, TradeStatus
from schemas.strategy import CurrencyPair, InterestConvention


def test_bid_ask_spread_and_slippage():
    """Ask rate at entry is higher than mid; Bid rate at exit is lower than mid."""
    mid = 1.2500
    spread_bps = 10.0  # 10 bps spread
    slippage_bps = 5.0  # 5 bps slippage

    entry_prices = compute_entry_execution_rate(mid, spread_bps=spread_bps, slippage_bps=slippage_bps)
    # Half spread = 5 bps = 0.0005. ask = 1.25 * 1.0005 = 1.250625.
    # Slippage = 5 bps = 0.0005. exec = 1.250625 * 1.0005 = 1.2512503...
    assert entry_prices.effective_rate > mid

    exit_prices = compute_exit_execution_rate(mid, spread_bps=spread_bps, slippage_bps=slippage_bps)
    # Bid is below mid; slippage lowers it further
    assert exit_prices.effective_rate < mid


def test_fixed_financing_bullet_repayment():
    """Fixed financing matches `core.interest.loan_repayment`."""
    principal = 100_000.0
    borrowing_rate = 0.06
    days = 180

    fin = calculate_fixed_financing(
        principal=principal,
        annual_rate=borrowing_rate,
        days=days,
        interest_convention=InterestConvention.COMPOUND,
        day_count=DayCountConvention.ACT_365,
    )

    expected_repayment = loan_repayment(
        principal=principal,
        annual_rate=borrowing_rate,
        years=days / 365.0,
        convention=InterestConvention.COMPOUND,
    )

    assert pytest.approx(fin.total_repayment, rel=1e-9) == expected_repayment
    assert pytest.approx(fin.interest_paid, rel=1e-9) == expected_repayment - principal


def test_variable_financing_rate_changes():
    """Variable financing properly steps across sub-intervals."""
    principal = 100_000.0
    # Period 1: 90 days at 5%
    # Period 2: 90 days at 7%
    periods = [
        RatePeriod(date(2024, 1, 1), date(2024, 3, 31), 0.05),
        RatePeriod(date(2024, 3, 31), date(2024, 6, 29), 0.07),
    ]

    var_fin = calculate_variable_financing(
        principal=principal,
        rate_periods=periods,
        interest_convention=InterestConvention.COMPOUND,
    )

    assert var_fin.days == 180
    assert var_fin.total_repayment > principal
    # Effective rate should be between 5% and 7%
    assert 0.05 < var_fin.effective_annual_rate < 0.07


def test_accrued_liability_intermediate():
    """Accrued intermediate liability grows monotonically from day 0 to maturity."""
    principal = 50_000.0
    rate = 0.08
    t0 = date(2024, 1, 1)

    l0 = calculate_accrued_liability(principal, rate, t0, date(2024, 1, 1))
    l30 = calculate_accrued_liability(principal, rate, t0, date(2024, 1, 31))
    l90 = calculate_accrued_liability(principal, rate, t0, date(2024, 3, 31))

    assert l0 == principal
    assert l0 < l30 < l90


def test_frictionless_round_trip_matches_core_carry_trade_module():
    """When spreads, fees, and slippage are zero, execution matches `calculate_carry_trade` exactly."""
    config = ExecutionConfig(
        bid_ask_spread_bps=0.0,
        slippage_bps=0.0,
        fixed_fee=0.0,
        variable_fee_bps=0.0,
        interest_convention=InterestConvention.COMPOUND,
    )
    engine = ExecutionEngine(config)

    pair = CurrencyPair(borrowing_currency="USD", investment_currency="EUR")
    principal = 100_000.0
    r_a = 0.03
    r_b = 0.08
    x_0 = 1.10
    x_1 = 1.12
    days = 365
    entry_date = date(2024, 1, 1)
    exit_date = date(2024, 12, 31)

    # 1. Backtesting engine execution
    open_trade = engine.open_trade(
        trade_id="TRD_001",
        strategy_name="Unhedged Carry",
        currency_pair=pair,
        entry_date=entry_date,
        tenor_days=days,
        principal_borrowed_a=principal,
        borrowing_rate=r_a,
        investment_rate=r_b,
        spot_mid_entry=x_0,
    )
    assert open_trade.status == TradeStatus.OPEN

    closed_trade = engine.close_trade(
        trade=open_trade,
        exit_date=exit_date,
        spot_mid_exit=x_1,
    )

    # 2. Mathematical engine execution (Phase 1 calculate_carry_trade)
    carry_input = CarryTradeInput(
        principal=principal,
        borrowing_rate=r_a,
        investment_return=r_b,
        initial_exchange_rate=x_0,
        final_exchange_rate=x_1,
        transaction_costs=0.0,
        years=1.0,
        interest_convention=InterestConvention.COMPOUND,
    )
    expected_result = calculate_carry_trade(carry_input)

    assert pytest.approx(closed_trade.invested_amount_b, rel=1e-7) == expected_result.invested_amount
    assert pytest.approx(closed_trade.investment_gross_value_b, rel=1e-7) == expected_result.investment_value
    assert pytest.approx(closed_trade.converted_back_a, rel=1e-7) == expected_result.converted_back_amount
    assert pytest.approx(closed_trade.loan_repayment_a, rel=1e-7) == expected_result.loan_repayment
    assert pytest.approx(closed_trade.net_profit_a, rel=1e-7) == expected_result.net_profit
    assert pytest.approx(closed_trade.return_on_capital, rel=1e-7) == expected_result.return_on_borrowed_capital


def test_execution_constraints_reject_invalid_sizes():
    """Trades smaller than min size or larger than max size are rejected."""
    config = ExecutionConfig(min_trade_size_a=5_000.0, max_trade_size_a=500_000.0)
    engine = ExecutionEngine(config)
    pair = CurrencyPair(borrowing_currency="USD", investment_currency="JPY")

    # Too small
    too_small = engine.open_trade(
        trade_id="T_SMALL",
        strategy_name="Unhedged Carry",
        currency_pair=pair,
        entry_date=date(2024, 1, 1),
        tenor_days=30,
        principal_borrowed_a=1_000.0,
        borrowing_rate=0.02,
        investment_rate=0.05,
        spot_mid_entry=0.0067,
    )
    assert too_small.status == TradeStatus.REJECTED
    assert "below min_trade_size_a" in (too_small.rejection_reason or "")

    # Too large
    too_large = engine.open_trade(
        trade_id="T_LARGE",
        strategy_name="Unhedged Carry",
        currency_pair=pair,
        entry_date=date(2024, 1, 1),
        tenor_days=30,
        principal_borrowed_a=1_000_000.0,
        borrowing_rate=0.02,
        investment_rate=0.05,
        spot_mid_entry=0.0067,
    )
    assert too_large.status == TradeStatus.REJECTED
    assert "exceeds max_trade_size_a" in (too_large.rejection_reason or "")
