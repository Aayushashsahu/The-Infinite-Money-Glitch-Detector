"""Interest mathematics: compounding conventions, periodic rates, loan repayment.

All rates in this package are **annual**, stated as fractions
(``0.12`` means 12 % per annum). Producing a period-specific rate is an
explicit step with an explicit convention (simple or compound), never an
implicit assumption.
"""

from __future__ import annotations

from schemas.strategy import InterestConvention


def _check_years(years: float) -> None:
    if years is None or years <= 0:
        raise ValueError(f"Holding period must be positive, got {years!r} years.")


def growth_factor(
    annual_rate: float,
    years: float = 1.0,
    convention: InterestConvention = InterestConvention.COMPOUND,
) -> float:
    """Multiplicative growth factor of an annual rate held for ``years``.

    * simple:    ``1 + r * years``
    * compound:  ``(1 + r) ** years``

    Args:
        annual_rate: Annual rate as a fraction (0.12 = 12 %).
        years: Holding period in years (must be > 0; fractional values allowed).
        convention: Simple or compound interest.

    Returns:
        The factor by which a principal grows over the period.

    Raises:
        ValueError: if ``years`` is not positive.
    """
    _check_years(years)
    if convention is InterestConvention.SIMPLE:
        return 1.0 + annual_rate * years
    if convention is InterestConvention.COMPOUND:
        return (1.0 + annual_rate) ** years
    raise ValueError(f"Unknown interest convention: {convention!r}")


def period_rate_from_annual(
    annual_rate: float,
    periods_per_year: float,
    convention: InterestConvention = InterestConvention.COMPOUND,
) -> float:
    """Convert an annual rate into the rate for one period.

    * simple:    ``annual_rate / periods_per_year``
    * compound:  ``(1 + annual_rate) ** (1 / periods_per_year) - 1``

    Args:
        annual_rate: Annual rate as a fraction.
        periods_per_year: Number of periods per year (e.g. 12 = monthly), must be > 0.
        convention: Simple or compound interest.

    Raises:
        ValueError: if ``periods_per_year`` is not positive.
    """
    if periods_per_year is None or periods_per_year <= 0:
        raise ValueError(f"periods_per_year must be positive, got {periods_per_year!r}.")
    if convention is InterestConvention.SIMPLE:
        return annual_rate / periods_per_year
    if convention is InterestConvention.COMPOUND:
        return (1.0 + annual_rate) ** (1.0 / periods_per_year) - 1.0
    raise ValueError(f"Unknown interest convention: {convention!r}")


def loan_repayment(
    principal: float,
    annual_rate: float,
    years: float = 1.0,
    convention: InterestConvention = InterestConvention.COMPOUND,
) -> float:
    """Total amount owed on a bullet loan (repay principal + interest once at the end).

    Args:
        principal: Amount borrowed (must be > 0 for break-even math to apply).
        annual_rate: Annual borrowing rate as a fraction.
        years: Holding period in years.
        convention: Simple or compound interest.

    Returns:
        Repayment amount in the loan currency.
    """
    _check_years(years)
    return principal * growth_factor(annual_rate, years, convention)


def interest_paid(
    principal: float,
    repayment: float,
) -> float:
    """Interest component of a repayment: ``repayment - principal``.

    Useful for reporting the split between principal and financing cost.
    """
    return repayment - principal
