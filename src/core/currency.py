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
import math
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
        raise ValueError(f"Invalid currency code: {code!r}. Expected a 3-letter ISO 4217 style code, e.g. 'USD'.")
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


@dataclass(frozen=True)
class NormalizedFXMetadata:
    """Validated and normalized FX quotation metadata."""

    base_currency: str
    quote_currency: str
    quote_convention: QuoteConvention
    unit: str
    pair: str
    canonical_usd_per_eur: float | None = None


def _extract_pair_codes(text: str | None, *, strict: bool = False) -> tuple[str, str] | None:
    """Extract (base, quote) currency codes from a pair representation string.

    Supported formats:
    - 'BASE/QUOTE' (e.g. 'EUR/USD')
    - 'BASE_QUOTE' where both are 3 alphabetic chars (e.g. 'EUR_USD')
    """
    if not text:
        return None
    s = text.strip()
    if "/" in s:
        parts = s.split("/")
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            b, q = parts[0].strip().upper(), parts[1].strip().upper()
            if len(b) == 3 and b.isalpha() and len(q) == 3 and q.isalpha():
                return b, q
            if strict:
                raise ValueError(
                    f"Invalid currency codes in pair '{text}': '{b}/{q}'. Must be 3-letter ISO-4217 alphabetic codes."
                )
    elif "_" in s:
        parts = s.split("_")
        if (
            len(parts) == 2
            and len(parts[0].strip()) == 3
            and parts[0].strip().isalpha()
            and len(parts[1].strip()) == 3
            and parts[1].strip().isalpha()
        ):
            return parts[0].strip().upper(), parts[1].strip().upper()
        if strict and len(parts) == 2:
            raise ValueError(f"Invalid currency codes in pair '{text}'. Must be 3-letter ISO-4217 alphabetic codes.")
    elif strict:
        raise ValueError(f"Malformed FX pair metadata: '{text}'. Must be a currency pair like 'EUR/USD' or 'EUR_USD'.")
    return None


def validate_and_normalize_fx_metadata(
    *,
    base_currency: str | None = None,
    quote_currency: str | None = None,
    quote_convention: QuoteConvention | str | None = None,
    unit: str | None = None,
    pair: str | None = None,
    entity_code: str | None = None,
    value: float | None = None,
    require_eur_usd_pair: bool = False,
    require_currencies: bool = True,
) -> NormalizedFXMetadata:
    """Validate mutual consistency across FX base, quote, quote_convention, and unit metadata.

    Universal Quotation Rules:
    - QUOTE_PER_BASE: units of quote currency per 1 base currency.
      (e.g., EUR/USD = 1.09 USD per EUR; USD/EUR = 0.91 EUR per USD)
    - BASE_PER_QUOTE: units of base currency per 1 quote currency.
      (e.g., EUR/USD = 0.91 EUR per USD; USD/EUR = 1.09 USD per EUR)

    Requirements:
    1. Validate pair and entity_code independently whenever either contains a recognizable currency pair.
    2. Explicit base/quote currencies must agree with both pair representations.
    3. Never ignore a contradictory entity code merely because base and quote currencies were already supplied.
    4. Explicit units must agree with both the currency pair and declared quote convention.
    5. Generic units ('quote_per_base', 'base_per_quote') must agree with declared quote_convention.
    6. Missing, contradictory, ambiguous, or unsupported metadata fails closed (ValueError).
    7. Partial metadata policy: Never silently overwrite an explicitly declared quote_convention.
    8. In lenient schema-validation mode, missing metadata is tolerated only where intended; invalid supplied
       currency codes fail closed.
    9. If value is positive and finite, computes canonical USD per EUR for EUR/USD factor pipeline.
    """
    unit_raw = (unit or "").strip()
    unit_str = unit_raw.lower()

    # 3. Explicitly supplied currency codes must be valid 3-letter codes even in lenient mode
    base_explicit = base_currency.strip().upper() if base_currency else None
    quote_explicit = quote_currency.strip().upper() if quote_currency else None
    base = base_explicit
    quote = quote_explicit
    if base is not None:
        base = validate_currency_code(base)
    if quote is not None:
        quote = validate_currency_code(quote)

    # 4. Extract pair representations from pair and entity_code independently
    pair_explicit = (pair or "").strip()
    pair_tuple: tuple[str, str] | None = None
    if pair_explicit:
        pair_tuple = _extract_pair_codes(pair_explicit, strict=True)

    entity_explicit = (entity_code or "").strip()
    entity_tuple: tuple[str, str] | None = None
    if entity_explicit:
        entity_tuple = _extract_pair_codes(entity_explicit, strict=False)

    # 1. Resolve quote_convention if explicitly provided (never silently overwrite)
    conv: QuoteConvention
    if quote_convention is not None:
        if isinstance(quote_convention, str):
            qc_str = quote_convention.strip().lower()
            if qc_str in ("quote_per_base", "quotation_per_base", "quote/base"):
                conv = QuoteConvention.QUOTE_PER_BASE
            elif qc_str in ("base_per_quote", "base/quote"):
                conv = QuoteConvention.BASE_PER_QUOTE
            else:
                raise ValueError(
                    f"Unsupported quote convention: '{quote_convention}'. Must be QUOTE_PER_BASE or BASE_PER_QUOTE."
                )
        elif isinstance(quote_convention, QuoteConvention):
            conv = quote_convention
        else:
            raise ValueError(f"Invalid quote_convention type: {type(quote_convention)}")
    else:
        # Default convention when not explicitly declared:
        if unit_str in ("base_per_quote", "base/quote"):
            conv = QuoteConvention.BASE_PER_QUOTE
        elif unit_str in ("quote_per_base", "quotation_per_base", "quote/base"):
            conv = QuoteConvention.QUOTE_PER_BASE
        elif (
            base_explicit is None
            and quote_explicit is None
            and entity_tuple is not None
            and unit_str in ("usd_per_eur", "usd/eur", "usd per eur")
        ):
            e_b, e_q = entity_tuple
            if e_b == "USD" and e_q == "EUR":
                conv = QuoteConvention.BASE_PER_QUOTE
            else:
                conv = QuoteConvention.QUOTE_PER_BASE
        elif (
            base_explicit is None
            and quote_explicit is None
            and entity_tuple is not None
            and unit_str in ("eur_per_usd", "eur/usd", "eur per usd")
        ):
            e_b, e_q = entity_tuple
            if e_b == "EUR" and e_q == "USD":
                conv = QuoteConvention.BASE_PER_QUOTE
            else:
                conv = QuoteConvention.QUOTE_PER_BASE
        else:
            conv = QuoteConvention.QUOTE_PER_BASE

    # 2. Generic quote units must agree with declared/inferred convention immediately
    if unit_str in ("quote_per_base", "quotation_per_base", "quote/base"):
        if conv != QuoteConvention.QUOTE_PER_BASE:
            raise ValueError(
                f"Contradictory FX metadata: generic unit '{unit}' contradicts "
                f"declared quote_convention='{conv.value}'."
            )
    elif unit_str in ("base_per_quote", "base/quote"):
        if conv != QuoteConvention.BASE_PER_QUOTE:
            raise ValueError(
                f"Contradictory FX metadata: generic unit '{unit}' contradicts "
                f"declared quote_convention='{conv.value}'."
            )

    # 5. Independent validation and cross-check
    if pair_tuple is not None and entity_tuple is not None:
        p_b, p_q = pair_tuple
        e_b, e_q = entity_tuple
        if p_b != e_b or p_q != e_q:
            raise ValueError(
                f"Contradictory FX pair and entity_code metadata: pair '{pair_explicit}' ({p_b}/{p_q}) "
                f"contradicts entity_code '{entity_explicit}' ({e_b}/{e_q})."
            )

    if pair_tuple is not None:
        p_b, p_q = pair_tuple
        if base is not None and base != p_b:
            raise ValueError(
                f"Contradictory FX pair metadata: pair '{pair_explicit}' implies {p_b}/{p_q} "
                f"which contradicts base_currency='{base}' and quote_currency='{quote}'."
            )
        if quote is not None and quote != p_q:
            raise ValueError(
                f"Contradictory FX pair metadata: pair '{pair_explicit}' implies {p_b}/{p_q} "
                f"which contradicts base_currency='{base}' and quote_currency='{quote}'."
            )
        if base is None and quote is None:
            base = p_b
            quote = p_q

    if entity_tuple is not None:
        e_b, e_q = entity_tuple
        if base_explicit is not None and base_explicit != e_b:
            raise ValueError(
                f"Contradictory FX entity_code metadata: entity_code '{entity_explicit}' implies {e_b}/{e_q} "
                f"which contradicts base_currency='{base_explicit}' and quote_currency='{quote_explicit}'."
            )
        if quote_explicit is not None and quote_explicit != e_q:
            raise ValueError(
                f"Contradictory FX entity_code metadata: entity_code '{entity_explicit}' implies {e_b}/{e_q} "
                f"which contradicts base_currency='{base_explicit}' and quote_currency='{quote_explicit}'."
            )
        if base is None and quote is None:
            base = e_b
            quote = e_q

    # 6. Infer currencies from explicit unit if currencies absent
    if base is None and quote is None:
        if unit_str in ("usd_per_eur", "usd/eur", "usd per eur"):
            if conv == QuoteConvention.BASE_PER_QUOTE:
                base, quote = "USD", "EUR"
            else:
                base, quote = "EUR", "USD"
        elif unit_str in ("eur_per_usd", "eur/usd", "eur per usd"):
            if conv == QuoteConvention.BASE_PER_QUOTE:
                base, quote = "EUR", "USD"
            else:
                base, quote = "USD", "EUR"

    # 7. Generic quote units require currencies to be identifiable
    if unit_str in ("quote_per_base", "quotation_per_base", "quote/base", "base_per_quote", "base/quote"):
        if base is None or quote is None:
            if require_currencies or require_eur_usd_pair:
                raise ValueError(
                    f"Cannot determine quote convention: missing base or quote currency metadata for FX observation: "
                    f"base='{base}', quote='{quote}', unit='{unit}', pair='{pair_explicit or entity_explicit}'. Fail closed."
                )

    # 8. Missing currency policy
    if base is None or quote is None:
        if not require_currencies and not require_eur_usd_pair:
            return NormalizedFXMetadata(
                base_currency=base or "",
                quote_currency=quote or "",
                quote_convention=conv,
                unit=unit_raw,
                pair=pair_explicit
                or (f"{base}/{quote}" if base and quote else (entity_explicit if "/" in entity_explicit else "")),
                canonical_usd_per_eur=None,
            )
        raise ValueError(
            f"Cannot determine quote convention: missing base or quote currency metadata for FX observation: "
            f"base='{base}', quote='{quote}', unit='{unit}', pair='{pair_explicit or entity_explicit}'. Fail closed."
        )

    base = validate_currency_code(base)
    quote = validate_currency_code(quote)

    if base == quote:
        raise ValueError(
            f"Contradictory FX currency metadata: base_currency and quote_currency are identical ({base})."
        )

    if require_eur_usd_pair:
        currencies = {c for c in (base, quote) if c}
        if currencies != {"EUR", "USD"}:
            raise ValueError(
                f"Cannot determine quote convention: Contradictory FX currency metadata: currencies {currencies} "
                f"do not match required EUR/USD factor pair."
            )

    # Validate unit against declared/inferred convention and currencies
    if unit_str in ("quote_per_base", "quotation_per_base", "quote/base"):
        if conv != QuoteConvention.QUOTE_PER_BASE:
            raise ValueError(
                f"Contradictory FX metadata: generic unit '{unit}' contradicts "
                f"declared quote_convention='{conv.value}'."
            )
        resolved_unit = "quote_per_base"
    elif unit_str in ("base_per_quote", "base/quote"):
        if conv != QuoteConvention.BASE_PER_QUOTE:
            raise ValueError(
                f"Contradictory FX metadata: generic unit '{unit}' contradicts "
                f"declared quote_convention='{conv.value}'."
            )
        resolved_unit = "base_per_quote"
    elif unit_str in ("rate", "exchange_rate", "fx_rate", "ratio"):
        resolved_unit = conv.value
    elif not unit_str:
        resolved_unit = conv.value
    elif quote and unit_str == quote.lower():
        if conv != QuoteConvention.QUOTE_PER_BASE:
            raise ValueError(
                f"Contradictory FX metadata: unit '{unit}' (quote currency) contradicts "
                f"declared quote_convention='{conv.value}'."
            )
        resolved_unit = f"{quote}_per_{base}" if base else unit_raw
    elif base and unit_str == base.lower():
        if conv != QuoteConvention.BASE_PER_QUOTE:
            raise ValueError(
                f"Contradictory FX metadata: unit '{unit}' (base currency) contradicts "
                f"declared quote_convention='{conv.value}'."
            )
        resolved_unit = f"{base}_per_{quote}" if quote else unit_raw
    elif unit_str in ("usd_per_eur", "usd/eur", "usd per eur"):
        if conv == QuoteConvention.QUOTE_PER_BASE:
            if base != "EUR" or quote != "USD":
                raise ValueError(
                    f"Contradictory FX metadata: explicit unit '{unit}' contradicts base_currency='{base}' and quote_currency='{quote}'."
                )
        elif conv == QuoteConvention.BASE_PER_QUOTE:
            if base != "USD" or quote != "EUR":
                raise ValueError(
                    f"Contradictory FX metadata: explicit unit '{unit}' contradicts base_currency='{base}' and quote_currency='{quote}'."
                )
        resolved_unit = "USD_per_EUR"
    elif unit_str in ("eur_per_usd", "eur/usd", "eur per usd"):
        if conv == QuoteConvention.QUOTE_PER_BASE:
            if base != "USD" or quote != "EUR":
                raise ValueError(
                    f"Contradictory FX metadata: explicit unit '{unit}' contradicts base_currency='{base}' and quote_currency='{quote}'."
                )
        elif conv == QuoteConvention.BASE_PER_QUOTE:
            if base != "EUR" or quote != "USD":
                raise ValueError(
                    f"Contradictory FX metadata: explicit unit '{unit}' contradicts base_currency='{base}' and quote_currency='{quote}'."
                )
        resolved_unit = "EUR_per_USD"
    else:
        m = re.match(r"^([a-z]{3})[_\s/:]+per[_\s/:]+([a-z]{3})$", unit_str)
        if m:
            u_q, u_b = m.group(1).upper(), m.group(2).upper()
            if conv == QuoteConvention.QUOTE_PER_BASE:
                if (quote and u_q != quote) or (base and u_b != base):
                    raise ValueError(
                        f"Contradictory FX metadata: explicit unit '{unit}' ({u_q} per {u_b}) contradicts base_currency='{base}', "
                        f"quote_currency='{quote}', and quote_convention='{conv.value}'."
                    )
            elif conv == QuoteConvention.BASE_PER_QUOTE:
                if (base and u_q != base) or (quote and u_b != quote):
                    raise ValueError(
                        f"Contradictory FX metadata: explicit unit '{unit}' ({u_q} per {u_b}) contradicts base_currency='{base}', "
                        f"quote_currency='{quote}', and quote_convention='{conv.value}'."
                    )
            resolved_unit = f"{u_q}_per_{u_b}"
        else:
            raise ValueError(
                f"Unsupported or ambiguous FX unit metadata: '{unit}'. "
                "Explicit supported quote units are 'quote_per_base', 'base_per_quote', 'USD_per_EUR', or 'EUR_per_USD'."
            )

    canonical = None
    if value is not None and math.isfinite(value) and value > 0:
        if {base, quote} == {"EUR", "USD"}:
            if conv == QuoteConvention.QUOTE_PER_BASE:
                if base == "EUR" and quote == "USD":
                    canonical = float(value)
                else:  # USD/EUR
                    canonical = float(1.0 / value)
            else:  # BASE_PER_QUOTE
                if base == "EUR" and quote == "USD":
                    canonical = float(1.0 / value)
                else:  # USD/EUR
                    canonical = float(value)

    return NormalizedFXMetadata(
        base_currency=base,
        quote_currency=quote,
        quote_convention=conv,
        unit=resolved_unit,
        pair=f"{base}/{quote}",
        canonical_usd_per_eur=canonical,
    )


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
        raise ValueError(f"Observation currencies {b_obs}/{q_obs} do not match strategy pair {curr_a}/{curr_b}.")


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
        raise ValueError(f"Observation currencies {b_obs}/{q_obs} do not match strategy pair {curr_a}/{curr_b}.")


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
