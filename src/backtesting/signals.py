"""Signal Generation Models for Cross-Currency Strategies.

Strategy A: Unhedged Carry Trade
- Evaluates interest rate differential: r_B - r_A
- Compares against configurable hurdle rate
- Optional realized FX volatility filter

Strategy B: Covered Carry Trade
- Uses actual historical spot and forward exchange rates
- Evaluates Covered Interest Parity (CIP) implied return
- Strictly rejects execution if forward quote data is missing or fabricated
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from schemas.strategy import CurrencyPair


@dataclass(frozen=True)
class TradingSignal:
    """Trading decision output for simulation timestamp T."""

    signal_date: date
    currency_pair: CurrencyPair
    should_enter: bool
    is_covered: bool
    borrowing_rate: float
    investment_rate: float
    spot_rate: float
    forward_rate: float | None
    interest_differential: float
    expected_edge: float
    confidence: float
    is_executable: bool
    rejection_reason: str | None = None
    metadata: dict[str, Any] | None = None


class UnhedgedCarrySignalGenerator:
    """Generates unhedged carry trade entry signals based on interest rate differentials."""

    def __init__(
        self,
        hurdle_rate_annual: float = 0.01,
        max_fx_volatility: float | None = None,
    ):
        self.hurdle_rate = hurdle_rate_annual
        self.max_fx_volatility = max_fx_volatility

    def generate_signal(
        self,
        as_of: date,
        pair: CurrencyPair,
        borrowing_rate: float | None,
        investment_rate: float | None,
        spot_rate: float | None,
        trailing_fx_volatility: float | None = None,
    ) -> TradingSignal:
        """Evaluate unhedged carry trade opportunity."""
        # Check data completeness
        if spot_rate is None or spot_rate <= 0:
            return TradingSignal(
                signal_date=as_of,
                currency_pair=pair,
                should_enter=False,
                is_covered=False,
                borrowing_rate=0.0,
                investment_rate=0.0,
                spot_rate=0.0,
                forward_rate=None,
                interest_differential=0.0,
                expected_edge=0.0,
                confidence=0.0,
                is_executable=False,
                rejection_reason=f"Missing or invalid spot exchange rate quote for {pair.borrowing_currency}/{pair.investment_currency}",
            )

        if borrowing_rate is None:
            return TradingSignal(
                signal_date=as_of,
                currency_pair=pair,
                should_enter=False,
                is_covered=False,
                borrowing_rate=0.0,
                investment_rate=0.0,
                spot_rate=spot_rate,
                forward_rate=None,
                interest_differential=0.0,
                expected_edge=0.0,
                confidence=0.0,
                is_executable=False,
                rejection_reason=f"Missing borrowing rate for {pair.borrowing_currency}",
            )

        if investment_rate is None:
            return TradingSignal(
                signal_date=as_of,
                currency_pair=pair,
                should_enter=False,
                is_covered=False,
                borrowing_rate=borrowing_rate,
                investment_rate=0.0,
                spot_rate=spot_rate,
                forward_rate=None,
                interest_differential=0.0,
                expected_edge=0.0,
                confidence=0.0,
                is_executable=False,
                rejection_reason=f"Missing investment rate for {pair.investment_currency}",
            )

        diff = investment_rate - borrowing_rate

        # Volatility filter check
        if self.max_fx_volatility is not None and trailing_fx_volatility is not None:
            if trailing_fx_volatility > self.max_fx_volatility:
                return TradingSignal(
                    signal_date=as_of,
                    currency_pair=pair,
                    should_enter=False,
                    is_covered=False,
                    borrowing_rate=borrowing_rate,
                    investment_rate=investment_rate,
                    spot_rate=spot_rate,
                    forward_rate=None,
                    interest_differential=diff,
                    expected_edge=diff,
                    confidence=0.0,
                    is_executable=True,
                    rejection_reason=(
                        f"Trailing FX volatility ({trailing_fx_volatility:.2%}) exceeds "
                        f"maximum threshold ({self.max_fx_volatility:.2%})"
                    ),
                )

        # Hurdle check
        if diff >= self.hurdle_rate:
            return TradingSignal(
                signal_date=as_of,
                currency_pair=pair,
                should_enter=True,
                is_covered=False,
                borrowing_rate=borrowing_rate,
                investment_rate=investment_rate,
                spot_rate=spot_rate,
                forward_rate=None,
                interest_differential=diff,
                expected_edge=diff,
                confidence=min(1.0, diff / 0.10),
                is_executable=True,
                rejection_reason=None,
            )

        return TradingSignal(
            signal_date=as_of,
            currency_pair=pair,
            should_enter=False,
            is_covered=False,
            borrowing_rate=borrowing_rate,
            investment_rate=investment_rate,
            spot_rate=spot_rate,
            forward_rate=None,
            interest_differential=diff,
            expected_edge=diff,
            confidence=0.0,
            is_executable=True,
            rejection_reason=f"Interest differential ({diff:.2%}) below hurdle rate ({self.hurdle_rate:.2%})",
        )


class CoveredCarrySignalGenerator:
    """Generates covered carry trade signals using actual market forward rates.

    Never fabricates forward rates from theoretical CIP.
    """

    def __init__(self, hurdle_rate_annual: float = 0.005):
        self.hurdle_rate = hurdle_rate_annual

    def generate_signal(
        self,
        as_of: date,
        pair: CurrencyPair,
        borrowing_rate: float | None,
        investment_rate: float | None,
        spot_rate: float | None,
        forward_rate: float | None,
        tenor_years: float = 1.0,
        interest_convention: Any = "compound",
    ) -> TradingSignal:
        """Evaluate covered interest parity opportunity."""
        from schemas.strategy import InterestConvention
        convention = (
            interest_convention
            if isinstance(interest_convention, InterestConvention)
            else (InterestConvention.SIMPLE if str(interest_convention).lower() == "simple" else InterestConvention.COMPOUND)
        )
        if spot_rate is None or spot_rate <= 0:
            return TradingSignal(
                signal_date=as_of,
                currency_pair=pair,
                should_enter=False,
                is_covered=True,
                borrowing_rate=0.0,
                investment_rate=0.0,
                spot_rate=0.0,
                forward_rate=forward_rate,
                interest_differential=0.0,
                expected_edge=0.0,
                confidence=0.0,
                is_executable=False,
                rejection_reason=f"Missing or invalid spot rate for {pair.borrowing_currency}/{pair.investment_currency}",
            )

        # STRICT requirement: actual forward rate MUST be available
        if forward_rate is None or forward_rate <= 0:
            return TradingSignal(
                signal_date=as_of,
                currency_pair=pair,
                should_enter=False,
                is_covered=True,
                borrowing_rate=borrowing_rate or 0.0,
                investment_rate=investment_rate or 0.0,
                spot_rate=spot_rate,
                forward_rate=None,
                interest_differential=0.0,
                expected_edge=0.0,
                confidence=0.0,
                is_executable=False,
                rejection_reason=(
                    "Historical forward exchange rate data is unavailable for executable backtesting. "
                    "Theoretical CIP cannot be substituted as executable market quotes."
                ),
            )

        if borrowing_rate is None or investment_rate is None:
            return TradingSignal(
                signal_date=as_of,
                currency_pair=pair,
                should_enter=False,
                is_covered=True,
                borrowing_rate=borrowing_rate or 0.0,
                investment_rate=investment_rate or 0.0,
                spot_rate=spot_rate,
                forward_rate=forward_rate,
                interest_differential=0.0,
                expected_edge=0.0,
                confidence=0.0,
                is_executable=False,
                rejection_reason="Missing borrowing or investment rate for covered trade",
            )

        # Covered return in currency A:
        # Invested amount in B = L / spot_rate
        # Investment grows to (L / spot_rate) * (1 + r_B * tenor)
        # Converted back at locked forward F = (L / spot_rate) * (1 + r_B * tenor) * forward_rate
        # Loan repayment = L * (1 + r_A * tenor)
        # Covered gross return = (forward_rate / spot_rate) * (1 + r_B * tenor) - (1 + r_A * tenor)
        from core.interest import growth_factor
        from schemas.strategy import InterestConvention
        f_b = growth_factor(investment_rate, tenor_years, convention)
        f_a = growth_factor(borrowing_rate, tenor_years, convention)
        covered_gain = (forward_rate / spot_rate) * f_b - f_a
        diff = investment_rate - borrowing_rate

        if covered_gain >= self.hurdle_rate:
            return TradingSignal(
                signal_date=as_of,
                currency_pair=pair,
                should_enter=True,
                is_covered=True,
                borrowing_rate=borrowing_rate,
                investment_rate=investment_rate,
                spot_rate=spot_rate,
                forward_rate=forward_rate,
                interest_differential=diff,
                expected_edge=covered_gain,
                confidence=1.0,
                is_executable=True,
                rejection_reason=None,
            )

        return TradingSignal(
            signal_date=as_of,
            currency_pair=pair,
            should_enter=False,
            is_covered=True,
            borrowing_rate=borrowing_rate,
            investment_rate=investment_rate,
            spot_rate=spot_rate,
            forward_rate=forward_rate,
            interest_differential=diff,
            expected_edge=covered_gain,
            confidence=0.0,
            is_executable=True,
            rejection_reason=f"Covered return edge ({covered_gain:.2%}) below hurdle ({self.hurdle_rate:.2%})",
        )
