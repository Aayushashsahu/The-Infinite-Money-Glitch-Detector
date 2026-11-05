"""The FIRST mathematical milestone: every expected number below was
computed by hand independently of the implementation.

Scenario
--------
- Borrow: 100,000 A. Borrowing rate 12 %.
- Investment return: 5 %.
- Initial exchange rate: 1 A per B. Final: 1.15 A per B.
- Transaction costs: 2,000 A. Holding period: 1 year.

Expected
--------
    Investment value: 105,000 B
    Converted back:   120,750 A
    Loan repayment:   112,000 A
    Costs:              2,000 A
    Net profit:        +6,750 A
"""

from math import isclose

import pytest
from pydantic import ValidationError

from models.carry_trade import (
    CarryTradeInput,
    TransactionCosts,
    calculate_carry_trade,
)
from schemas.strategy import CurrencyPair, InterestConvention


def _milestone(**overrides) -> CarryTradeInput:
    defaults = dict(
        principal=100_000.0,
        borrowing_rate=0.12,
        investment_return=0.05,
        initial_exchange_rate=1.0,
        final_exchange_rate=1.15,
        transaction_costs=2_000.0,
        years=1.0,
        interest_convention=InterestConvention.COMPOUND,
    )
    defaults.update(overrides)
    return CarryTradeInput(**defaults)


def test_milestone_scenario_end_to_end() -> None:
    """The gate test: reproduce exactly +6,750 A or nothing moves forward."""
    result = calculate_carry_trade(_milestone())
    assert isclose(result.investment_value, 105_000.0)
    assert isclose(result.converted_back_amount, 120_750.0)
    assert isclose(result.loan_repayment, 112_000.0)
    assert isclose(result.transaction_costs, 2_000.0)
    assert isclose(result.net_profit, 6_750.0)
    assert isclose(result.return_on_borrowed_capital, 0.0675)


def test_milestone_with_simple_convention_is_identical_for_one_year() -> None:
    """After exactly one year, simple and compound must agree."""
    result = calculate_carry_trade(_milestone(interest_convention=InterestConvention.SIMPLE))
    assert isclose(result.net_profit, 6_750.0)


def test_milestone_break_even_exchange_rate() -> None:
    """X* solves L*f_b*(X*/X0) - L*f_a - C = 0, so X* = X0*(f_a + C/L)/f_b = 1.14/1.05."""
    result = calculate_carry_trade(_milestone())
    assert isclose(result.break_even_exchange_rate, 1.14 / 1.05)
    assert isclose(result.break_even_exchange_rate_move, 1.14 / 1.05 - 1.0)
    # Sanity: exactly at the break-even rate the profit must be zero.
    at_be = calculate_carry_trade(
        _milestone(final_exchange_rate=result.break_even_exchange_rate)
    )
    assert abs(at_be.net_profit) < 1e-6


def test_inversion_of_rate_direction_produces_a_loss() -> None:
    """If B weakens to X1 = 0.9 A per B: 100000*(1.05*0.9 - 1.12) - 2000 = -19,500."""
    result = calculate_carry_trade(_milestone(final_exchange_rate=0.9))
    assert isclose(result.net_profit, -19_500.0)


def test_zero_transaction_costs_and_flat_fx() -> None:
    """No move, no costs: profit is exactly the pure rate differential."""
    result = calculate_carry_trade(_milestone(initial_exchange_rate=1.0, final_exchange_rate=1.0, transaction_costs=0.0))
    assert isclose(result.net_profit, 100_000.0 * (1.05 - 1.12))


def test_holding_period_and_simple_vs_compound_diverge_over_two_years() -> None:
    """2 years, flat FX, no costs:
    simple:    L*(1 + 0.05*2) - L*(1 + 0.12*2) = 110,000 - 124,000 = -14,000
    compound:  L*(1.05^2)     - L*(1.12^2)     = 110,250 - 125,440 = -15,190
    """
    two_years = dict(years=2.0, initial_exchange_rate=1.0, final_exchange_rate=1.0, transaction_costs=0.0)
    simple = calculate_carry_trade(_milestone(interest_convention=InterestConvention.SIMPLE, **two_years))
    compound = calculate_carry_trade(_milestone(interest_convention=InterestConvention.COMPOUND, **two_years))
    assert isclose(simple.net_profit, -14_000.0)
    assert isclose(compound.net_profit, -15_190.0)


def test_transaction_cost_model_total() -> None:
    costs = TransactionCosts(fixed_cost=500.0, spread_bps=10)
    # fixed 500 + 0.0010 * (100,000 + 120,750) = 500 + 220.75
    assert isclose(costs.total(100_000.0, 120_750.0), 720.75)
    assert isclose(TransactionCosts().total(1.0, 1.0), 0.0)


def test_input_validation() -> None:
    with pytest.raises(ValidationError):
        _milestone(principal=-5.0)
    with pytest.raises(ValidationError):
        _milestone(final_exchange_rate=0.0)
    with pytest.raises(ValidationError):
        _milestone(years=0.0)
    with pytest.raises(ValidationError):
        _milestone(transaction_costs=-1.0)


def test_currency_pair_metadata_is_validated() -> None:
    pair = CurrencyPair(borrowing_currency="usd", investment_currency="JPY")
    assert pair.borrowing_currency == "USD"
    with pytest.raises(ValidationError):
        CurrencyPair(borrowing_currency="USDX", investment_currency="JPY")
    with pytest.raises(ValidationError):
        CurrencyPair(borrowing_currency="USD", investment_currency="USD")
