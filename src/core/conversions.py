"""Unit conversions used by the calculation engine.

Percent <-> fraction helpers, total-return <-> annualized-rate
conversion, and rate-change helpers. Conversions are pure functions:
they never mutate state and never touch I/O.
"""

from __future__ import annotations

from schemas.strategy import InterestConvention


def to_fraction(percent: float) -> float:
    """Convert a percentage to a fraction: ``12 -> 0.12``."""
    return percent / 100.0


def to_percent(fraction: float) -> float:
    """Convert a fraction to a percentage: ``0.12 -> 12``."""
    return fraction * 100.0


def rate_change(new_value: float, old_value: float) -> float:
    """Fractional change between two values (e.g. exchange rates): ``(new - old) / old``.

    Raises:
        ValueError: if ``old_value`` is zero.
    """
    if old_value == 0:
        raise ValueError("rate_change is undefined for an old value of zero.")
    return (new_value - old_value) / old_value


def annualized_return(
    total_return: float,
    years: float,
    convention: InterestConvention = InterestConvention.COMPOUND,
) -> float:
    """Constant annual rate equivalent to ``total_return`` earned over ``years``.

    * compound:  ``(1 + total_return) ** (1 / years) - 1``
    * simple:    ``total_return / years``

    Args:
        total_return: Total return over the whole horizon as a fraction (0.0675 = 6.75 %).
        years: Horizon in years, must be > 0.
        convention: Convention used to annualize.

    Returns:
        Annualized return as a fraction.

    Raises:
        ValueError: if ``years`` is not positive, or the implied growth factor is
            non-positive (a beyond-total-loss ratio cannot be annualized).
    """
    if years is None or years <= 0:
        raise ValueError(f"years must be positive, got {years!r}.")
    if convention is InterestConvention.SIMPLE:
        return total_return / years
    if convention is InterestConvention.COMPOUND:
        growth = 1.0 + total_return
        if growth <= 0:
            raise ValueError(
                "Cannot annualize a return whose growth factor is non-positive "
                f"(total return {total_return!r}). Report the raw loss instead."
            )
        return growth ** (1.0 / years) - 1.0
    raise ValueError(f"Unknown interest convention: {convention!r}")
