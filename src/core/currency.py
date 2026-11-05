"""Currency primitives and exchange-rate conversion utilities.

Exchange-rate convention used across this package
-------------------------------------------------
Every exchange rate ``X`` is expressed as **units of the borrowing
currency (A) per unit of the investment currency (B)**.

* an amount in A converts to B with ``convert_to_b(amount_a, X) = amount_a / X``
* an amount in B converts back to A with ``convert_to_a(amount_b, X) = amount_b * X``

Keeping exactly one convention across the codebase avoids the most
common arithmetic error in cross-currency work: silently inverting a rate.
"""

from __future__ import annotations

import re

_CURRENCY_CODE = re.compile(r"^[A-Za-z]{3}$")


def _check_rate(rate: float) -> None:
    if rate is None or rate <= 0:
        raise ValueError(
            f"Exchange rate must be a positive number, got {rate!r}. "
            "Convention: rate is units of currency A per unit of currency B."
        )


def validate_currency_code(code: str) -> str:
    """Validate that ``code`` looks like an ISO 4217 style code (3 letters).

    Raises:
        ValueError: if the code is not a 3-letter alphabetic code.
    """
    if not isinstance(code, str) or not _CURRENCY_CODE.match(code):
        raise ValueError(
            f"Invalid currency code: {code!r}. Expected a 3-letter ISO 4217 style code, e.g. 'USD'."
        )
    return code.upper()


def convert_to_b(amount_a: float, rate_a_per_b: float) -> float:
    """Convert an amount from borrowing currency A to investment currency B.

    Convention: ``rate_a_per_b`` is units of A per unit of B.

    Args:
        amount_a: Amount held in currency A.
        rate_a_per_b: Exchange rate, units of A per unit of B (must be > 0).

    Returns:
        The equivalent amount in currency B.

    Raises:
        ValueError: if the rate is not strictly positive.
    """
    _check_rate(rate_a_per_b)
    return amount_a / rate_a_per_b


def convert_to_a(amount_b: float, rate_a_per_b: float) -> float:
    """Convert an amount from investment currency B back to borrowing currency A.

    Convention: ``rate_a_per_b`` is units of A per unit of B.

    Args:
        amount_b: Amount held in currency B.
        rate_a_per_b: Exchange rate, units of A per unit of B (must be > 0).

    Returns:
        The equivalent amount in currency A.

    Raises:
        ValueError: if the rate is not strictly positive.
    """
    _check_rate(rate_a_per_b)
    return amount_b * rate_a_per_b


def inverse_rate(rate_a_per_b: float) -> float:
    """Express the same rate in the opposite direction (units of B per unit of A).

    Useful only when talking to external data sources that quote rates the
    other way. Never invert a rate by hand inside strategy code; use this.

    Raises:
        ValueError: if the rate is not strictly positive.
    """
    _check_rate(rate_a_per_b)
    return 1.0 / rate_a_per_b
