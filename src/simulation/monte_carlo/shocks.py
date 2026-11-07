"""Deterministic macro-financial stress scenarios.

Defines single-factor shocks, compound stress events, liquidity deterioration,
and correlation breakdown overlays.
"""

from __future__ import annotations

import math
from typing import Any

from simulation.monte_carlo.schemas import ScenarioPath, StressScenario


def build_standard_stress_scenarios() -> list[StressScenario]:
    """Construct the comprehensive suite of required deterministic stress scenarios."""
    scenarios: list[StressScenario] = []

    # 1. Single-Factor FX Shocks
    fx_shocks = [0.05, -0.05, 0.10, -0.10, 0.20, -0.20]
    for s in fx_shocks:
        sign_str = f"+{int(s*100)}%" if s > 0 else f"{int(s*100)}%"
        scenarios.append(
            StressScenario(
                name=f"FX Shock {sign_str}",
                description=f"Instantaneous {sign_str} move in exchange rate (investment currency relative to borrowing currency)",
                category="single_factor",
                fx_shock_pct=s,
            )
        )

    # 2. Funding-Rate Shocks
    rate_shocks = [100.0, 300.0, 500.0]
    for r in rate_shocks:
        scenarios.append(
            StressScenario(
                name=f"Borrowing Spike +{int(r)} bps",
                description=f"Instantaneous +{int(r)} basis points increase in commercial borrowing cost",
                category="single_factor",
                borrowing_rate_shock_bps=r,
            )
        )

    # 3. Investment-Rate Shocks
    invest_shocks = [-100.0, -200.0, 100.0]
    for inv in invest_shocks:
        sign_str = f"+{int(inv)} bps" if inv > 0 else f"{int(inv)} bps"
        scenarios.append(
            StressScenario(
                name=f"Investment Yield Shift {sign_str}",
                description=f"Instantaneous {sign_str} shift in foreign asset investment yield",
                category="single_factor",
                investment_rate_shock_bps=inv,
            )
        )

    # 4. Execution / Liquidity Shocks
    scenarios.extend([
        StressScenario(
            name="Liquidity Widening (2x Spread, 2x Slippage)",
            description="Dealer bid/ask spreads and market execution slippage double",
            category="liquidity",
            spread_multiplier=2.0,
            slippage_multiplier=2.0,
        ),
        StressScenario(
            name="Liquidity Freeze (5x Spread, 5x Slippage)",
            description="Severe market fragmentation with 5x spread expansion and 5x execution slippage",
            category="liquidity",
            spread_multiplier=5.0,
            slippage_multiplier=5.0,
        ),
    ])

    # 5. Compound Stress Scenarios
    scenarios.extend([
        StressScenario(
            name="Currency Plunge (-10%) & Funding Spike (+300 bps)",
            description="Foreign investment currency depreciates 10% alongside a 300 bps domestic funding rate spike",
            category="compound",
            fx_shock_pct=-0.10,
            borrowing_rate_shock_bps=300.0,
        ),
        StressScenario(
            name="Severe Crisis (-20% FX, +500 bps Borrowing, 5x Frictions)",
            description="Compound crisis: 20% currency devaluation, 500 bps funding surge, and 5x execution friction blowout",
            category="compound",
            fx_shock_pct=-0.20,
            borrowing_rate_shock_bps=500.0,
            spread_multiplier=5.0,
            slippage_multiplier=5.0,
        ),
        StressScenario(
            name="Carry Compression (-200 bps Yield, +100 bps Borrowing)",
            description="Interest-rate differential collapses: US yields fall 200 bps while Euro funding rises 100 bps",
            category="compound",
            investment_rate_shock_bps=-200.0,
            borrowing_rate_shock_bps=100.0,
        ),
    ])

    return scenarios


def apply_stress_scenario(
    base_path: ScenarioPath,
    stress: StressScenario,
) -> ScenarioPath:
    """Apply deterministic stress shocks to an existing baseline scenario path."""
    # 1. Apply FX shock: S_t = S_t * (1 + shock)
    if stress.fx_shock_pct < -0.999:
        raise ValueError(f"FX shock cannot be <= -100%: {stress.fx_shock_pct}")
    fx_multiplier = 1.0 + stress.fx_shock_pct
    stressed_fx = [max(1e-6, p * fx_multiplier) for p in base_path.fx_rates]

    # 2. Apply Borrowing Rate shock in bps -> annual decimal
    borrow_shift = stress.borrowing_rate_shock_bps / 10000.0
    stressed_borrowing = [max(0.0, r + borrow_shift) for r in base_path.borrowing_rates]

    # 3. Apply Investment Rate shock in bps -> annual decimal
    invest_shift = stress.investment_rate_shock_bps / 10000.0
    stressed_invest = [max(0.0, r + invest_shift) for r in base_path.investment_rates]

    return ScenarioPath(
        path_id=base_path.path_id,
        steps=base_path.steps,
        dates=base_path.dates,
        fx_rates=stressed_fx,
        borrowing_rates=stressed_borrowing,
        investment_rates=stressed_invest,
        regimes=base_path.regimes,
        is_synthetic=True,
    )
