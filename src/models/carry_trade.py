"""Cross-currency carry trade: deterministic calculation engine.

Strategy
--------
Borrow ``L`` in currency A, convert to currency B at ``X_0``, invest at
``r_B``, convert the proceeds back at ``X_1``, repay the loan at ``r_A``
and subtract transaction costs ``C`` stated in A.

    Profit_A = L * [(1 + r_B) * (X_1 / X_0) - (1 + r_A)] - C

Exchange-rate convention: ``X`` is units of A per unit of B.

Architecture note
-----------------
This module is pure math on validated Pydantic inputs. It must stay free
of dashboard, database, network and LLM code so the exact same
calculation can be invoked from a script, a backtester, an API endpoint
or the future AI assistant.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from core.currency import convert_to_a, convert_to_b
from core.conversions import annualized_return
from core.interest import growth_factor, loan_repayment
from schemas.strategy import CurrencyPair, InterestConvention


class TransactionCosts(BaseModel):
    """Transaction-cost model for one carry-trade round trip.

    Costs are always stated in borrowing currency A.

    Attributes:
        fixed_cost: Flat fee in A, charged once for the round trip.
        spread_bps: Proportional fee in basis points of notional, charged on
            *each* conversion leg (A -> B and B -> A). 10 bps = 0.10 %.
    """

    fixed_cost: float = Field(default=0.0, ge=0, description="Flat fee in A.")
    spread_bps: float = Field(
        default=0.0,
        ge=0,
        le=10_000,
        description="Proportional fee in basis points of converted notional, per conversion leg.",
    )

    def total(self, notional_a_initial: float, notional_a_final: float) -> float:
        """Total costs in A: fixed fee plus spread on both conversion legs.

        Args:
            notional_a_initial: Value in A of the amount converted A -> B.
            notional_a_final: Value in A of the amount converted B -> A.
        """
        return self.fixed_cost + (self.spread_bps / 10_000) * (notional_a_initial + notional_a_final)


class CarryTradeInput(BaseModel):
    """Validated carry-trade inputs.

    All rates are annual fractions (``0.12`` = 12 %). Rates are NOT
    guaranteed outcomes: ``investment_return`` is an *assumed expected*
    return and must be supplied by the caller.
    """

    principal: float = Field(gt=0, description="L, amount borrowed in currency A.")
    borrowing_rate: float = Field(description="r_A, annual borrowing rate in A, as a fraction.")
    investment_return: float = Field(
        description="r_B, annual *expected* investment return in B, as a fraction (an assumption, not a forecast)."
    )
    initial_exchange_rate: float = Field(gt=0, description="X_0, units of A per unit of B.")
    final_exchange_rate: float = Field(gt=0, description="X_1, units of A per unit of B.")
    transaction_costs: float = Field(default=0.0, ge=0, description="C, total transaction costs in A.")
    years: float = Field(default=1.0, gt=0, description="Holding period in years.")
    interest_convention: InterestConvention = InterestConvention.COMPOUND
    currency_pair: CurrencyPair | None = Field(default=None, description="Optional metadata for reporting.")


class CarryTradeOutput(BaseModel):
    """Full deterministic breakdown of the carry trade.

    Amounts are in borrowing currency A unless marked otherwise. Field
    names mirror the milestone checklist so results are trivially
    auditable.
    """

    principal: float = Field(description="L in A.")
    invested_amount: float = Field(description="Amount converted into B (L / X_0).")
    investment_value: float = Field(description="Grown investment value in B.")
    converted_back_amount: float = Field(description="Grown value converted back to A at X_1.")
    loan_repayment: float = Field(description="Principal plus interest owed in A.")
    transaction_costs: float = Field(description="C in A.")
    net_profit: float = Field(description="Profit in A; may be negative.")
    return_on_borrowed_capital: float = Field(description="net_profit / principal, over the full horizon.")
    annualized_return_on_capital: float = Field(description="Constant annual rate equivalent to the horizon return.")
    break_even_exchange_rate: float = Field(description="X_1 level at which net profit is exactly zero.")
    break_even_exchange_rate_move: float = Field(
        description=(
            "Fractional move of X from X_0 to the break-even rate. "
            "Positive: currency B must APPRECIATE this much to break even; "
            "then no depreciation of B against A is tolerable before losses."
        )
    )


def calculate_carry_trade(inputs: CarryTradeInput) -> CarryTradeOutput:
    """Evaluate one carry trade deterministically.

    Derivation (with growth factors for the chosen convention,
    ``f_b = 1 + r_B`` effective over the holding period, ditto ``f_a``):

        invested_B      = L / X_0
        investment_value= invested_B * f_b
        converted_A     = investment_value * X_1
        repayment_A     = L * f_a
        net_profit      = converted_A - repayment_A - C
        break-even:     X_1* = X_0 * (f_a + C / L) / f_b

    Args:
        inputs: Validated :class:`CarryTradeInput`.

    Returns:
        :class:`CarryTradeOutput` with the full breakdown.

    Raises:
        ValueError: if the horizon return is a beyond-total loss and therefore
            cannot be annualized (reported as a raw loss instead).
    """
    invested = convert_to_b(inputs.principal, inputs.initial_exchange_rate)
    f_b = growth_factor(inputs.investment_return, inputs.years, inputs.interest_convention)
    f_a = growth_factor(inputs.borrowing_rate, inputs.years, inputs.interest_convention)

    investment_value = invested * f_b
    converted_back = convert_to_a(investment_value, inputs.final_exchange_rate)
    repayment = loan_repayment(
        inputs.principal, inputs.borrowing_rate, inputs.years, inputs.interest_convention
    )
    net_profit = converted_back - repayment - inputs.transaction_costs
    roi = net_profit / inputs.principal

    break_even_rate = (
        inputs.initial_exchange_rate
        * (f_a + inputs.transaction_costs / inputs.principal)
        / f_b
    )

    return CarryTradeOutput(
        principal=inputs.principal,
        invested_amount=invested,
        investment_value=investment_value,
        converted_back_amount=converted_back,
        loan_repayment=repayment,
        transaction_costs=inputs.transaction_costs,
        net_profit=net_profit,
        return_on_borrowed_capital=roi,
        annualized_return_on_capital=annualized_return(roi, inputs.years, inputs.interest_convention),
        break_even_exchange_rate=break_even_rate,
        break_even_exchange_rate_move=break_even_rate / inputs.initial_exchange_rate - 1.0,
    )
