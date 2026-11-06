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


from enum import Enum


class QuoteConvention(str, Enum):
    """Quotation convention for exchange rate market observations.

    - QUOTE_PER_BASE: Units of quote currency per 1 unit of base currency (standard market convention, e.g. EUR/USD = 1.10 USD per 1 EUR).
    - BASE_PER_QUOTE: Units of base currency per 1 unit of quote currency (e.g. EUR/USD = 0.909 EUR per 1 USD).
    """

    QUOTE_PER_BASE = "quote_per_base"
    BASE_PER_QUOTE = "base_per_quote"


def invert_two_way_quote(bid: float, ask: float) -> tuple[float, float]:
    """Invert a two-way exchange rate quote (bid, ask) from BASE/QUOTE to QUOTE/BASE.

    Mathematical rule:
    - Inverse Bid = 1.0 / Ask
    - Inverse Ask = 1.0 / Bid

    Ensures that Inverse Bid <= Inverse Ask, and both are positive.
    """
    _check_rate(bid)
    _check_rate(ask)
    if bid > ask:
        raise ValueError(f"Crossed quote: bid ({bid}) cannot be strictly greater than ask ({ask}).")
    return 1.0 / ask, 1.0 / bid


def get_rate_a_per_b(
    value: float,
    obs_base: str,
    obs_quote: str,
    borrowing_currency: str,
    investment_currency: str,
    convention: QuoteConvention | str = QuoteConvention.QUOTE_PER_BASE,
) -> float:
    """Normalize a market exchange rate observation to strategy convention (units of A per unit of B).

    Args:
        value: The numerical observation rate (must be > 0).
        obs_base: Base currency of the observed quote (e.g. 'EUR' in 'EUR/USD').
        obs_quote: Quote currency of the observed quote (e.g. 'USD' in 'EUR/USD').
        borrowing_currency: Strategy borrowing currency A (e.g. 'EUR').
        investment_currency: Strategy investment currency B (e.g. 'USD').
        convention: Quotation convention of ``value`` (default: QUOTE_PER_BASE).

    Returns:
        Exchange rate expressed as units of borrowing currency A per unit of investment currency B (rate_a_per_b).

    Raises:
        ValueError: if rate is non-positive or currencies do not match the observation.
    """
    _check_rate(value)
    if isinstance(convention, str):
        convention = QuoteConvention(convention)

    # 1. Normalize value to QUOTE_PER_BASE (units of obs_quote per 1 obs_base)
    s_quote_per_base = (1.0 / value) if convention == QuoteConvention.BASE_PER_QUOTE else value

    b_obs = validate_currency_code(obs_base)
    q_obs = validate_currency_code(obs_quote)
    curr_a = validate_currency_code(borrowing_currency)
    curr_b = validate_currency_code(investment_currency)

    if curr_a == curr_b:
        raise ValueError(f"Borrowing and investment currencies must differ, got {curr_a!r} twice.")

    # 2. Map to units of A per unit of B
    if curr_a == b_obs and curr_b == q_obs:
        # Observation is B per A (e.g. EUR/USD with A=EUR, B=USD).
        # We need A per B (EUR per USD) -> 1 / (USD per EUR).
        return 1.0 / s_quote_per_base
    elif curr_a == q_obs and curr_b == b_obs:
        # Observation is A per B (e.g. EUR/USD with A=USD, B=EUR).
        # We need A per B (USD per EUR) -> directly s_quote_per_base.
        return s_quote_per_base
    else:
        raise ValueError(
            f"Observation currencies {b_obs}/{q_obs} do not match strategy pair {curr_a}/{curr_b}."
        )


def get_two_way_quote_a_per_b(
    bid: float,
    ask: float,
    obs_base: str,
    obs_quote: str,
    borrowing_currency: str,
    investment_currency: str,
    convention: QuoteConvention | str = QuoteConvention.QUOTE_PER_BASE,
) -> tuple[float, float]:
    """Normalize a market two-way quote (bid, ask) to strategy convention (units of A per unit of B).

    Returns:
        (bid_a_per_b, ask_a_per_b): Two-way quote in units of A per unit of B,
        where:
        - Buying B with A uses ask_a_per_b (entry leg)
        - Selling B for A uses bid_a_per_b (exit leg)
    """
    _check_rate(bid)
    _check_rate(ask)
    if bid > ask:
        raise ValueError(f"Crossed quote: bid ({bid}) cannot exceed ask ({ask}).")

    if isinstance(convention, str):
        convention = QuoteConvention(convention)

    # If quote was BASE_PER_QUOTE, invert first to QUOTE_PER_BASE
    if convention == QuoteConvention.BASE_PER_QUOTE:
        bid, ask = invert_two_way_quote(bid, ask)

    b_obs = validate_currency_code(obs_base)
    q_obs = validate_currency_code(obs_quote)
    curr_a = validate_currency_code(borrowing_currency)
    curr_b = validate_currency_code(investment_currency)

    if curr_a == curr_b:
        raise ValueError(f"Borrowing and investment currencies must differ, got {curr_a!r} twice.")

    if curr_a == b_obs and curr_b == q_obs:
        # Observation is B per A (e.g. EUR/USD with A=EUR, B=USD).
        # Inverting produces A per B (EUR per USD):
        return invert_two_way_quote(bid, ask)
    elif curr_a == q_obs and curr_b == b_obs:
        # Observation is A per B (e.g. EUR/USD with A=USD, B=EUR).
        # Already A per B:
        return bid, ask
    else:
        raise ValueError(
            f"Observation currencies {b_obs}/{q_obs} do not match strategy pair {curr_a}/{curr_b}."
        )
