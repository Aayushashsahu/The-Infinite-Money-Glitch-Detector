"""Purchasing Power Parity (PPP) baseline model.

IMPORTANT - what this model is and is not
-----------------------------------------
Relative PPP is a *theoretical long-run relationship*:

    Expected depreciation of A against B  ≈  π_A − π_B  (annual inflation differential)

Empirically PPP holds only loosely even over multi-year horizons:
deviations from PPP can persist for years, and short-term exchange rates
are dominated by interest differentials, capital flows, risk premia and
policy events. Outputs of this module are a long-run *baseline*, never a
short-term forecast and never a trading signal by themselves.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PPPInput(BaseModel):
    """Validated PPP inputs. Inflation rates are annual fractions."""

    inflation_a: float = Field(description="π_A, annual inflation in currency A, as a fraction.")
    inflation_b: float = Field(description="π_B, annual inflation in currency B, as a fraction.")
    horizon_years: float = Field(default=1.0, gt=0, description="Horizon in years.")
    initial_exchange_rate: float = Field(
        default=1.0, gt=0, description="X_0, units of A per unit of B (same convention as the carry trade)."
    )


class PPPOutput(BaseModel):
    """Baseline PPP-implied currency move (label: long-run theoretical baseline)."""

    annual_depreciation_of_a: float = Field(
        description="≈ π_A − π_B per year. Positive means currency A is expected to LOSE value against B "
        "(the A-per-B rate rises)."
    )
    horizon_depreciation_of_a: float = Field(description="(1 + annual depreciation) ** horizon−1, compounded.")
    expected_exchange_rate: float = Field(description="PPP-baseline expected X at the horizon; A per B.")


def calculate_ppp(inputs: PPPInput) -> PPPOutput:
    """Compute the PPP-baseline expected currency move over the horizon.

    Args:
        inputs: Validated :class:`PPPInput`.

    Returns:
        :class:`PPPOutput`.

    Raises:
        ValueError: if the inflation differential is so extreme (below −100 %)
            that the baseline growth factor becomes non-positive.
    """
    differential = inputs.inflation_a - inputs.inflation_b
    growth = 1.0 + differential
    if growth <= 0:
        raise ValueError(
            "PPP baseline is undefined for an inflation differential below -100% "
            f"({differential!r}). Check the inflation inputs."
        )
    horizon_factor = growth ** inputs.horizon_years
    return PPPOutput(
        annual_depreciation_of_a=differential,
        horizon_depreciation_of_a=horizon_factor - 1.0,
        expected_exchange_rate=inputs.initial_exchange_rate * horizon_factor,
    )
