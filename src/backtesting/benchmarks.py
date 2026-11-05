"""Benchmark Generators for Cross-Currency Historical Backtesting.

Includes:
1. Borrowing Currency Cash Benchmark (Risk-free cash in A)
2. Investment Currency Holding Benchmark (Unhedged spot FX + foreign deposit in B)
3. Theoretical Covered Interest Parity (CIP) Diagnostic Benchmark

Every benchmark makes its mathematical assumptions explicit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from core.currency import convert_to_a, convert_to_b
from core.interest import growth_factor
from schemas.strategy import InterestConvention
from backtesting.financing import days_to_years


@dataclass(frozen=True)
class BenchmarkSeries:
    """Benchmark performance tracking over a simulated backtest period."""

    name: str
    description: str
    dates: list[date]
    values: list[float]  # Index or equity curve starting at 1.0
    returns: list[float]
    total_return: float
    annualized_return: float
    annualized_volatility: float
    sharpe_ratio: float | None
    assumptions: str


@dataclass(frozen=True)
class CIPDiagnostic:
    """Theoretical Covered Interest Parity comparison for diagnostic evaluation.

    Never to be used as an executable quote.
    """

    as_of: date
    spot_rate: float
    actual_forward_rate: float | None
    theoretical_forward_rate: float
    absolute_deviation: float | None
    basis_bps: float | None
    interpretation: str


def compute_borrowing_currency_benchmark(
    dates: Sequence[date],
    borrowing_rates: Sequence[float],
    interest_convention: InterestConvention = InterestConvention.COMPOUND,
) -> BenchmarkSeries:
    """Benchmark 1: Holding risk-free cash in borrowing currency A earning r_A.

    Assumptions:
    - 100% of initial capital remains in currency A.
    - Accrues interest continuously or daily at the prevailing borrowing/policy rate in A.
    - Zero exchange rate risk, zero transaction costs.
    """
    if len(dates) < 2:
        raise ValueError("At least 2 dates required for benchmark series.")
    if len(dates) != len(borrowing_rates):
        raise ValueError("dates and borrowing_rates must have identical length.")

    values = [1.0]
    returns = [0.0]

    for i in range(1, len(dates)):
        days = (dates[i] - dates[i - 1]).days
        years = days_to_years(days)
        rate = borrowing_rates[i - 1]
        step_factor = growth_factor(rate, years, interest_convention)
        new_val = values[-1] * step_factor
        step_return = (new_val / values[-1]) - 1.0
        values.append(new_val)
        returns.append(step_return)

    total_days = (dates[-1] - dates[0]).days
    total_years = max(1e-6, days_to_years(total_days))
    total_ret = values[-1] - 1.0
    ann_ret = (values[-1]) ** (1.0 / total_years) - 1.0

    return BenchmarkSeries(
        name="Holding Borrowing Currency (A)",
        description="Passive cash held in currency A earning the local risk-free/policy rate.",
        dates=list(dates),
        values=values,
        returns=returns,
        total_return=total_ret,
        annualized_return=ann_ret,
        annualized_volatility=0.0,
        sharpe_ratio=None,
        assumptions=(
            "Accrues daily interest at r_A with compounding convention; zero FX risk; zero transaction fees."
        ),
    )


def compute_investment_currency_benchmark(
    dates: Sequence[date],
    spot_rates: Sequence[float],
    investment_rates: Sequence[float],
    interest_convention: InterestConvention = InterestConvention.COMPOUND,
) -> BenchmarkSeries:
    """Benchmark 2: Holding investment currency B unhedged.

    Assumptions:
    - 100% of capital is converted from A to B at t=0 at the initial spot rate.
    - Earns interest in B at r_B.
    - At each timestamp, converted back to A at prevailing spot rate X_t to evaluate value.
    - Reflects buy-and-hold exposure to foreign currency B plus foreign interest rate.
    """
    if len(dates) < 2:
        raise ValueError("At least 2 dates required for benchmark series.")
    if not (len(dates) == len(spot_rates) == len(investment_rates)):
        raise ValueError("dates, spot_rates, and investment_rates must have identical length.")

    # Starting with 1.0 unit of currency A
    initial_spot = spot_rates[0]
    initial_b = convert_to_b(1.0, initial_spot)
    
    current_b = initial_b
    values = [1.0]
    returns = [0.0]

    for i in range(1, len(dates)):
        days = (dates[i] - dates[i - 1]).days
        years = days_to_years(days)
        rate_b = investment_rates[i - 1]
        
        # Accumulate foreign interest
        f_b = growth_factor(rate_b, years, interest_convention)
        current_b *= f_b
        
        # Value in currency A
        val_a = convert_to_a(current_b, spot_rates[i])
        step_return = (val_a / values[-1]) - 1.0
        values.append(val_a)
        returns.append(step_return)

    total_days = (dates[-1] - dates[0]).days
    total_years = max(1e-6, days_to_years(total_days))
    total_ret = values[-1] - 1.0
    
    ann_ret = (val_a) ** (1.0 / total_years) - 1.0 if val_a > 0 else -1.0

    return BenchmarkSeries(
        name="Holding Investment Currency (B)",
        description="Passive buy-and-hold in currency B earning foreign deposit rate r_B, evaluated in A.",
        dates=list(dates),
        values=values,
        returns=returns,
        total_return=total_ret,
        annualized_return=ann_ret,
        annualized_volatility=0.0,  # can be updated with sample std
        sharpe_ratio=None,
        assumptions=(
            "Full conversion into currency B at t0; earns foreign interest r_B; marked to market in A at spot rates; frictionless."
        ),
    )


def compute_theoretical_cip_rate(
    spot_rate: float,
    borrowing_rate: float,
    investment_rate: float,
    tenor_years: float = 1.0,
    interest_convention: InterestConvention = InterestConvention.COMPOUND,
) -> float:
    """Compute the theoretical Covered Interest Parity (CIP) forward rate.

    Convention: Rate X is units of A per unit of B.
    By no-arbitrage:
        F* = X_0 * (1 + r_A)^years / (1 + r_B)^years
    """
    f_a = growth_factor(borrowing_rate, tenor_years, interest_convention)
    f_b = growth_factor(investment_rate, tenor_years, interest_convention)
    return spot_rate * (f_a / f_b)


def evaluate_cip_diagnostic(
    as_of: date,
    spot_rate: float,
    borrowing_rate: float,
    investment_rate: float,
    actual_forward_rate: float | None,
    tenor_years: float = 1.0,
    interest_convention: InterestConvention = InterestConvention.COMPOUND,
) -> CIPDiagnostic:
    """Diagnostic comparison between actual market forward quote and theoretical CIP forward.

    Used strictly for diagnostic analysis of cross-currency basis, never as an executable quote.
    """
    theoretical_fwd = compute_theoretical_cip_rate(
        spot_rate=spot_rate,
        borrowing_rate=borrowing_rate,
        investment_rate=investment_rate,
        tenor_years=tenor_years,
        interest_convention=interest_convention,
    )

    if actual_forward_rate is None or actual_forward_rate <= 0:
        return CIPDiagnostic(
            as_of=as_of,
            spot_rate=spot_rate,
            actual_forward_rate=None,
            theoretical_forward_rate=theoretical_fwd,
            absolute_deviation=None,
            basis_bps=None,
            interpretation="Actual market forward rate unavailable; theoretical CIP cannot be compared.",
        )

    abs_dev = actual_forward_rate - theoretical_fwd
    # Cross-currency basis in basis points: (actual / theoretical - 1) * 10000 / tenor
    basis_bps = ((actual_forward_rate / theoretical_fwd) - 1.0) * (10_000.0 / tenor_years)

    if abs(basis_bps) < 5.0:
        interp = "Forward market aligned with covered interest parity within standard transaction costs."
    elif basis_bps > 0:
        interp = f"Forward trades at premium of {basis_bps:.1f} bps above theoretical CIP (covered carry advantage in B)."
    else:
        interp = f"Forward trades at discount of {abs(basis_bps):.1f} bps below theoretical CIP (foreign currency funding strain)."

    return CIPDiagnostic(
        as_of=as_of,
        spot_rate=spot_rate,
        actual_forward_rate=actual_forward_rate,
        theoretical_forward_rate=theoretical_fwd,
        absolute_deviation=abs_dev,
        basis_bps=basis_bps,
        interpretation=interp,
    )
