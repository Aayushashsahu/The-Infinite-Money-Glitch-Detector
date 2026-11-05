"""Deterministic sensitivity analysis for the carry trade.

One driver is varied at a time while all others stay fixed, producing an
auditable scenario grid. Every row is a *hypothetical scenario*, not a
forecast.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field

from models.carry_trade import CarryTradeInput, calculate_carry_trade

DEFAULT_EXCHANGE_RATE_SHOCKS: tuple[float, ...] = (-0.2, -0.1, -0.05, -0.02, 0.0, 0.02, 0.05, 0.1, 0.2)


class SensitivityRow(BaseModel):
    """One deterministic scenario: X_1 shifted relative to X_0, other drivers constant."""

    exchange_rate_shock: float = Field(description="Fractional move of the A-per-B rate relative to X_0.")
    final_exchange_rate: float = Field(description="Scenario X_1 in units of A per unit of B.")
    net_profit: float = Field(description="Scenario net profit in A; may be negative.")
    return_on_borrowed_capital: float = Field(description="Scenario net_profit / principal.")


def exchange_rate_sensitivity(
    base: CarryTradeInput,
    shocks: Sequence[float] = DEFAULT_EXCHANGE_RATE_SHOCKS,
) -> list[SensitivityRow]:
    """Recompute the carry trade over a grid of final exchange rates.

    For each shock ``s`` the scenario rate is ``X_1 = X_0 * (1 + s)``.
    A negative shock means currency B weakens against A; a positive
    shock means B strengthens. Borrowing rate, investment return,
    principal, costs, horizon and interest convention are held constant.

    Args:
        base: The base-case :class:`CarryTradeInput`.
        shocks: Fractional exchange-rate shocks. Must be finite.

    Returns:
        One :class:`SensitivityRow` per shock, in input order.
    """
    rows: list[SensitivityRow] = []
    for shock in shocks:
        if shock == float("inf") or shock != shock:  # reject inf and NaN
            raise ValueError(f"Exchange-rate shock must be finite, got {shock!r}.")
        scenario = base.model_copy(
            update={"final_exchange_rate": base.initial_exchange_rate * (1.0 + shock)}
        )
        result = calculate_carry_trade(scenario)
        rows.append(
            SensitivityRow(
                exchange_rate_shock=shock,
                final_exchange_rate=scenario.final_exchange_rate,
                net_profit=result.net_profit,
                return_on_borrowed_capital=result.return_on_borrowed_capital,
            )
        )
    return rows
