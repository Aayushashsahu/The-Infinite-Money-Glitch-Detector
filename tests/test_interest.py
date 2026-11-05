"""Unit tests for interest mathematics and return conversion, each with
independently hand-computed expected values.
"""

from math import isclose

import pytest

from core.conversions import annualized_return, rate_change, to_fraction, to_percent
from core.interest import (
    growth_factor,
    interest_paid,
    loan_repayment,
    period_rate_from_annual,
)
from schemas.strategy import InterestConvention as Conv


def test_growth_factor_one_year_matches_milestone() -> None:
    assert isclose(growth_factor(0.12, 1.0, Conv.COMPOUND), 1.12)
    assert isclose(growth_factor(0.12, 1.0, Conv.SIMPLE), 1.12)


def test_simple_vs_compound_diverge_over_five_years() -> None:
    assert isclose(growth_factor(0.12, 5.0, Conv.SIMPLE), 1.6)
    assert isclose(growth_factor(0.12, 5.0, Conv.COMPOUND), 1.12**5)


def test_fractional_year_compound() -> None:
    # 1.12 ** 0.5 ≈ 1.0583005244...
    assert isclose(growth_factor(0.12, 0.5, Conv.COMPOUND), 1.12**0.5)


def test_period_rates() -> None:
    assert isclose(period_rate_from_annual(0.12, 12, Conv.SIMPLE), 0.01)
    assert isclose(period_rate_from_annual(0.12, 12, Conv.COMPOUND), 1.12 ** (1 / 12) - 1)
    assert isclose(period_rate_from_annual(0.0, 12, Conv.COMPOUND), 0.0)


def test_loan_repayment_milestone() -> None:
    assert isclose(loan_repayment(100_000.0, 0.12, 1.0, Conv.COMPOUND), 112_000.0)


def test_loan_repayment_zero_rate_returns_principal() -> None:
    assert isclose(loan_repayment(100_000.0, 0.0, 3.0, Conv.COMPOUND), 100_000.0)


def test_loan_repayment_two_year_conventions() -> None:
    assert isclose(loan_repayment(100_000.0, 0.12, 2.0, Conv.SIMPLE), 124_000.0)
    assert isclose(loan_repayment(100_000.0, 0.12, 2.0, Conv.COMPOUND), 125_440.0)


def test_interest_paid() -> None:
    assert isclose(interest_paid(100_000.0, 112_000.0), 12_000.0)


def test_annualized_return_matches_horizon() -> None:
    # Milestone ROI: 6.75 % over 1 year annualizes to itself.
    assert isclose(annualized_return(0.0675, 1.0), 0.0675)
    # Simple convention: linear division.
    assert isclose(annualized_return(0.60, 5.0, Conv.SIMPLE), 0.12)
    # Compound: (1.6)^(1/5) - 1.
    assert isclose(annualized_return(0.60, 5.0, Conv.COMPOUND), 1.6**0.2 - 1)


def test_annualized_return_rejects_beyond_total_loss() -> None:
    with pytest.raises(ValueError):
        annualized_return(-1.5, 1.0)


def test_percent_helpers_and_rate_change() -> None:
    assert isclose(to_fraction(12.0), 0.12)
    assert isclose(to_percent(0.12), 12.0)
    assert isclose(rate_change(1.15, 1.0), 0.15)
    with pytest.raises(ValueError):
        rate_change(1.15, 0.0)


def test_nonpositive_horizon_is_rejected() -> None:
    with pytest.raises(ValueError):
        growth_factor(0.12, 0.0)
    with pytest.raises(ValueError):
        loan_repayment(100.0, 0.12, -1.0)
    with pytest.raises(ValueError):
        annualized_return(0.1, 0.0)
    with pytest.raises(ValueError):
        period_rate_from_annual(0.12, 0)
