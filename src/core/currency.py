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

from dataclasses import dataclass
from enum import Enum
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


@dataclass(frozen=True)
class DirectionalQuoteResult:
    """Canonicalized result of a directional one-sided or two-way quote translation."""

    canonical_price: float
    canonical_side: str  # "ask" or "bid"
    provider_price: float
    provider_side: str  # "ask" or "bid"
    provider_base: str
    provider_quote: str
    provider_convention: QuoteConvention
    borrowing_currency: str
    investment_currency: str


def map_canonical_side_to_provider_side(
    requested_canonical_side: str,
    obs_base: str,
    obs_quote: str,
    borrowing_currency: str,
    investment_currency: str,
    convention: QuoteConvention | str = QuoteConvention.QUOTE_PER_BASE,
) -> str:
    """Determine which provider quote side ('bid' or 'ask') is required to obtain requested_canonical_side.

    Rules:
    - requested_canonical_side="ask": Strategy buying investment currency B using borrowing currency A.
      - If provider quote is already in units of A per B: requires provider ASK.
      - If provider quote is in units of B per A: requires provider BID (which inverts to canonical ask 1.0 / bid).
    - requested_canonical_side="bid": Strategy selling investment currency B to receive borrowing currency A.
      - If provider quote is already in units of A per B: requires provider BID.
      - If provider quote is in units of B per A: requires provider ASK (which inverts to canonical bid 1.0 / ask).
    """
    req = requested_canonical_side.lower()
    if req not in ("bid", "ask"):
        raise ValueError(f"requested_canonical_side must be 'bid' or 'ask', got {requested_canonical_side!r}")

    if isinstance(convention, str):
        convention = QuoteConvention(convention)

    b_obs = validate_currency_code(obs_base)
    q_obs = validate_currency_code(obs_quote)
    curr_a = validate_currency_code(borrowing_currency)
    curr_b = validate_currency_code(investment_currency)

    if curr_a == curr_b:
        raise ValueError(f"Borrowing and investment currencies must differ, got {curr_a!r} twice.")

    # Determine whether provider's quote is inherently units of A per B
    if convention == QuoteConvention.QUOTE_PER_BASE:
        if curr_a == q_obs and curr_b == b_obs:
            is_a_per_b = True
        elif curr_a == b_obs and curr_b == q_obs:
            is_a_per_b = False
        else:
            raise ValueError(f"Observation currencies {b_obs}/{q_obs} do not match strategy pair {curr_a}/{curr_b}.")
    elif convention == QuoteConvention.BASE_PER_QUOTE:
        if curr_a == b_obs and curr_b == q_obs:
            is_a_per_b = True
        elif curr_a == q_obs and curr_b == b_obs:
            is_a_per_b = False
        else:
            raise ValueError(f"Observation currencies {b_obs}/{q_obs} do not match strategy pair {curr_a}/{curr_b}.")
    else:
        raise ValueError(f"Unsupported quote convention: {convention}")

    if is_a_per_b:
        return req
    else:
        return "bid" if req == "ask" else "ask"


def normalize_directional_quote(
    provider_price: float,
    provider_side: str,
    obs_base: str,
    obs_quote: str,
    borrowing_currency: str,
    investment_currency: str,
    convention: QuoteConvention | str = QuoteConvention.QUOTE_PER_BASE,
    transaction_direction: str | None = None,
    requested_canonical_side: str | None = None,
) -> DirectionalQuoteResult:
    """Normalize a provider quote side into a strategy canonical rate_a_per_b.

    Args:
        provider_price: Raw price from the provider observation (> 0).
        provider_side: Provider price side ('bid' or 'ask').
        obs_base: Base currency of provider pair.
        obs_quote: Quote currency of provider pair.
        borrowing_currency: Strategy currency A.
        investment_currency: Strategy currency B.
        convention: QUOTE_PER_BASE or BASE_PER_QUOTE.
        transaction_direction: Optional 'entry' (buy B) or 'exit' (sell B).
        requested_canonical_side: Optional 'ask' (entry) or 'bid' (exit).

    Returns:
        DirectionalQuoteResult containing canonical_price and canonical_side.
    """
    _check_rate(provider_price)
    prov_side = provider_side.lower()
    if prov_side not in ("bid", "ask"):
        raise ValueError(f"provider_side must be 'bid' or 'ask', got {provider_side!r}")

    if isinstance(convention, str):
        convention = QuoteConvention(convention)

    b_obs = validate_currency_code(obs_base)
    q_obs = validate_currency_code(obs_quote)
    curr_a = validate_currency_code(borrowing_currency)
    curr_b = validate_currency_code(investment_currency)

    if curr_a == curr_b:
        raise ValueError(f"Borrowing and investment currencies must differ, got {curr_a!r} twice.")

    if convention == QuoteConvention.QUOTE_PER_BASE:
        if curr_a == q_obs and curr_b == b_obs:
            is_a_per_b = True
        elif curr_a == b_obs and curr_b == q_obs:
            is_a_per_b = False
        else:
            raise ValueError(f"Observation currencies {b_obs}/{q_obs} do not match strategy pair {curr_a}/{curr_b}.")
    elif convention == QuoteConvention.BASE_PER_QUOTE:
        if curr_a == b_obs and curr_b == q_obs:
            is_a_per_b = True
        elif curr_a == q_obs and curr_b == b_obs:
            is_a_per_b = False
        else:
            raise ValueError(f"Observation currencies {b_obs}/{q_obs} do not match strategy pair {curr_a}/{curr_b}.")
    else:
        raise ValueError(f"Unsupported quote convention: {convention}")

    if is_a_per_b:
        canonical_price = provider_price
        canonical_side = prov_side
    else:
        canonical_price = 1.0 / provider_price
        canonical_side = "ask" if prov_side == "bid" else "bid"

    expected_side = requested_canonical_side
    if expected_side is None and transaction_direction is not None:
        direction_lower = transaction_direction.lower()
        if direction_lower in ("entry", "open", "buy_b"):
            expected_side = "ask"
        elif direction_lower in ("exit", "close", "sell_b"):
            expected_side = "bid"

    if expected_side is not None:
        if canonical_side != expected_side.lower():
            raise ValueError(
                f"Directional mismatch: Provider {prov_side.upper()} normalizes to canonical {canonical_side.upper()} "
                f"({canonical_price:.6f} {curr_a}/{curr_b}), which does not satisfy requested canonical {expected_side.upper()}."
            )

    return DirectionalQuoteResult(
        canonical_price=canonical_price,
        canonical_side=canonical_side,
        provider_price=provider_price,
        provider_side=prov_side,
        provider_base=b_obs,
        provider_quote=q_obs,
        provider_convention=convention,
        borrowing_currency=curr_a,
        investment_currency=curr_b,
    )

