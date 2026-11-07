"""Financing cost calculation and loan repayment accounting for historical backtesting.

Reuses core mathematical primitives from `core.interest`:
- `growth_factor`
- `loan_repayment`
- `interest_paid`
- `period_rate_from_annual`

Supports:
- Fixed borrowing rates over the loan tenor
- Variable borrowing rates with time-weighted sub-period accrual
- Bullet loan repayment at maturity
- Intermediate mark-to-market accrued loan liabilities
- Day count conventions (ACT/365, ACT/360)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Sequence

from core.interest import growth_factor, interest_paid, loan_repayment
from schemas.strategy import InterestConvention


class DayCountConvention(str, Enum):
    ACT_365 = "ACT/365"
    ACT_360 = "ACT/360"


@dataclass(frozen=True)
class RatePeriod:
    """An interval over which a specific borrowing rate was in effect."""

    start_date: date
    end_date: date
    annual_rate: float


@dataclass(frozen=True)
class FinancingSummary:
    """Complete breakdown of loan repayment obligations."""

    principal: float
    total_repayment: float
    interest_paid: float
    effective_annual_rate: float
    days: int
    years: float
    convention: InterestConvention


def days_to_years(days: int, convention: DayCountConvention = DayCountConvention.ACT_365) -> float:
    """Convert integer calendar days to fractional years."""
    if days < 0:
        raise ValueError(f"Days must be non-negative, got {days}")
    if convention == DayCountConvention.ACT_365:
        return days / 365.0
    if convention == DayCountConvention.ACT_360:
        return days / 360.0
    raise ValueError(f"Unknown day count convention: {convention}")


def calculate_fixed_financing(
    principal: float,
    annual_rate: float,
    days: int,
    interest_convention: InterestConvention = InterestConvention.COMPOUND,
    day_count: DayCountConvention = DayCountConvention.ACT_365,
) -> FinancingSummary:
    """Compute bullet loan repayment for a fixed borrowing rate over a given number of days.

    Args:
        principal: Principal borrowed in currency A (must be > 0).
        annual_rate: Annualized borrowing rate as a fraction (e.g. 0.05 for 5%).
        days: Holding period in calendar days (must be > 0).
        interest_convention: COMPOUND or SIMPLE.
        day_count: ACT/365 or ACT/360.

    Returns:
        FinancingSummary with principal, repayment, interest, and effective years.
    """
    if principal <= 0:
        raise ValueError(f"Principal must be positive, got {principal}")
    if days <= 0:
        raise ValueError(f"Days must be positive, got {days}")

    years = days_to_years(days, day_count)
    repayment = loan_repayment(
        principal=principal,
        annual_rate=annual_rate,
        years=years,
        convention=interest_convention,
    )
    interest = interest_paid(principal, repayment)

    return FinancingSummary(
        principal=principal,
        total_repayment=repayment,
        interest_paid=interest,
        effective_annual_rate=annual_rate,
        days=days,
        years=years,
        convention=interest_convention,
    )


def calculate_variable_financing(
    principal: float,
    rate_periods: Sequence[RatePeriod],
    interest_convention: InterestConvention = InterestConvention.COMPOUND,
    day_count: DayCountConvention = DayCountConvention.ACT_365,
) -> FinancingSummary:
    """Compute loan repayment where borrowing rate varies across the holding period.

    Accrues interest chronologically over each sub-interval.
    """
    if principal <= 0:
        raise ValueError(f"Principal must be positive, got {principal}")
    if not rate_periods:
        raise ValueError("rate_periods cannot be empty")

    current_balance = principal
    total_days = 0

    for period in rate_periods:
        period_days = (period.end_date - period.start_date).days
        if period_days <= 0:
            continue
        total_days += period_days
        sub_years = days_to_years(period_days, day_count)

        factor = growth_factor(period.annual_rate, sub_years, interest_convention)
        current_balance *= factor

    total_years = days_to_years(total_days, day_count)
    interest = current_balance - principal

    # Implied effective annual rate
    if total_years > 0 and interest_convention == InterestConvention.COMPOUND:
        effective_annual = (current_balance / principal) ** (1.0 / total_years) - 1.0
    elif total_years > 0 and interest_convention == InterestConvention.SIMPLE:
        effective_annual = interest / (principal * total_years)
    else:
        effective_annual = 0.0

    return FinancingSummary(
        principal=principal,
        total_repayment=current_balance,
        interest_paid=interest,
        effective_annual_rate=effective_annual,
        days=total_days,
        years=total_years,
        convention=interest_convention,
    )


def calculate_accrued_liability(
    principal: float,
    annual_rate: float,
    entry_date: date,
    as_of: date,
    interest_convention: InterestConvention = InterestConvention.COMPOUND,
    day_count: DayCountConvention = DayCountConvention.ACT_365,
) -> float:
    """Compute the current loan obligation (principal + accrued interest) at intermediate date T."""
    if as_of < entry_date:
        raise ValueError(f"as_of ({as_of}) cannot be before entry_date ({entry_date})")
    days = (as_of - entry_date).days
    if days == 0:
        return principal
    years = days_to_years(days, day_count)
    return loan_repayment(
        principal=principal,
        annual_rate=annual_rate,
        years=years,
        convention=interest_convention,
    )
