"""Phase 1 demo entry point for the Infinite Money Glitch Detector.

Runs the first mathematical milestone scenario and a small
exchange-rate sensitivity grid. This script calls the deterministic
calculation engine directly - exactly the same function a backtester,
an API endpoint or the future AI assistant must use. No dashboard, no
LLM, no network access.

Run with:  python src/main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):  # allow `python src/main.py` without installation
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from models.carry_trade import CarryTradeInput, calculate_carry_trade
from simulation.sensitivity import exchange_rate_sensitivity

MILESTONE = CarryTradeInput(
    principal=100_000.0,
    borrowing_rate=0.12,
    investment_return=0.05,
    initial_exchange_rate=1.0,
    final_exchange_rate=1.15,
    transaction_costs=2_000.0,
    years=1.0,
)


def main() -> None:
    """Reproduce the milestone scenario and a sensitivity grid, then print them."""
    result = calculate_carry_trade(MILESTONE)

    print("Infinite Money Glitch Detector - mathematical milestone scenario")
    print("-" * 66)
    print(f"Investment value (B):        {result.investment_value:>15,.2f}")
    print(f"Converted back (A):          {result.converted_back_amount:>15,.2f}")
    print(f"Loan repayment (A):          {result.loan_repayment:>15,.2f}")
    print(f"Transaction costs (A):       {result.transaction_costs:>15,.2f}")
    print("-" * 66)
    print(f"Net profit (A):              {result.net_profit:>15,.2f}")
    print(f"Return on borrowed capital:  {result.return_on_borrowed_capital:>15.4%}")
    print(f"Break-even exchange rate:    {result.break_even_exchange_rate:>15,.6f}")
    print()

    print("Exchange-rate sensitivity (rates, principal and costs held constant)")
    for row in exchange_rate_sensitivity(MILESTONE):
        print(
            f"  shock {row.exchange_rate_shock:>7.1%} -> X1 {row.final_exchange_rate:>8.4f}"
            f" -> profit {row.net_profit:>13,.2f} A"
        )


if __name__ == "__main__":
    main()
