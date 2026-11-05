"""Mark-to-Market Valuation Engine for Open Cross-Currency Positions.

Computes:
- Current investment value in foreign currency B
- Liquidation value in base currency A at prevailing bid exchange rates
- Current accrued financing liabilities in base currency A
- Unrealized profit and loss (PnL)
- Portfolio-level equity, leverage, and capital utilization
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from core.currency import convert_to_a
from core.interest import growth_factor
from schemas.backtest import ExecutionConfig, PortfolioSnapshot, TradeRecord, TradeStatus
from schemas.strategy import InterestConvention
from backtesting.financing import calculate_accrued_liability, days_to_years
from backtesting.execution import compute_exit_execution_rate


@dataclass(frozen=True)
class PositionValuation:
    """Mark-to-market status of one open position as of date T."""

    trade_id: str
    as_of: date
    days_held: int
    investment_value_b: float
    liquidation_rate_a_per_b: float
    liquidation_value_a: float
    accrued_liability_a: float
    unrealized_pnl_a: float


def mark_position_to_market(
    trade: TradeRecord,
    as_of: date,
    current_spot_mid: float,
    execution_config: ExecutionConfig | None = None,
) -> PositionValuation:
    """Mark a single open trade to market at date T."""
    if trade.status != TradeStatus.OPEN:
        raise ValueError(f"Trade {trade.trade_id} is not OPEN (status: {trade.status})")
    if as_of < trade.entry_date:
        raise ValueError(f"as_of ({as_of}) is before entry_date ({trade.entry_date})")

    config = execution_config or ExecutionConfig()
    days_held = (as_of - trade.entry_date).days
    years = days_to_years(days_held)

    # 1. Foreign currency value accrued to date
    f_b = growth_factor(trade.investment_rate, years, config.interest_convention)
    inv_val_b = trade.invested_amount_b * f_b

    # 2. Liquidation rate in A (bid spread + slippage)
    if trade.is_covered and trade.forward_exec_rate is not None:
        exec_rate = trade.forward_exec_rate
    else:
        prices = compute_exit_execution_rate(
            spot_mid=current_spot_mid,
            spread_bps=config.bid_ask_spread_bps,
            slippage_bps=config.slippage_bps,
        )
        exec_rate = prices.effective_rate

    # 3. Liquidation value in A
    liq_val_a = convert_to_a(inv_val_b, exec_rate)

    # 4. Accrued loan liability in A
    liability_a = calculate_accrued_liability(
        principal=trade.principal_borrowed_a,
        annual_rate=trade.borrowing_rate,
        entry_date=trade.entry_date,
        as_of=as_of,
        interest_convention=config.interest_convention,
    )

    # 5. Estimated exit fees
    exit_fee = liq_val_a * (config.variable_fee_bps / 10_000.0) + config.fixed_fee

    # 6. Unrealized PnL in A
    unrealized_pnl = liq_val_a - liability_a - exit_fee

    return PositionValuation(
        trade_id=trade.trade_id,
        as_of=as_of,
        days_held=days_held,
        investment_value_b=inv_val_b,
        liquidation_rate_a_per_b=exec_rate,
        liquidation_value_a=liq_val_a,
        accrued_liability_a=liability_a,
        unrealized_pnl_a=unrealized_pnl,
    )


def compute_portfolio_snapshot(
    as_of: date,
    cash_a: float,
    open_trades: Sequence[TradeRecord],
    current_spot_rates: dict[str, float],
    realized_pnl_a: float,
    execution_config: ExecutionConfig | None = None,
) -> PortfolioSnapshot:
    """Compute aggregate portfolio balance sheet and risk metrics as of timestamp T."""
    config = execution_config or ExecutionConfig()

    total_borrowed = 0.0
    total_obligations = 0.0
    total_positions_val = 0.0
    total_unrealized_pnl = 0.0

    for trade in open_trades:
        pair_code = f"{trade.currency_pair.borrowing_currency}/{trade.currency_pair.investment_currency}"
        spot_rate = current_spot_rates.get(pair_code, trade.spot_mid_entry)
        val = mark_position_to_market(trade, as_of, spot_rate, config)
        
        total_borrowed += trade.principal_borrowed_a
        total_obligations += val.accrued_liability_a
        total_positions_val += val.liquidation_value_a
        total_unrealized_pnl += val.unrealized_pnl_a

    # Equity = Cash + Positions Liquidation Value - Obligations
    # Equivalently = Initial Cash + Realized PnL + Unrealized PnL
    equity = cash_a + total_unrealized_pnl

    # Leverage = Total gross exposure / Equity
    leverage = (total_borrowed / equity) if equity > 0 else 0.0

    # Capital utilization = Borrowed / (Equity * Max Leverage)
    capital_utilization = (total_borrowed / equity) if equity > 0 else 0.0

    return PortfolioSnapshot(
        as_of=as_of,
        cash_a=cash_a,
        total_borrowed_a=total_borrowed,
        total_obligations_a=total_obligations,
        active_positions_count=len(open_trades),
        positions_value_a=total_positions_val,
        equity_a=equity,
        leverage=leverage,
        unrealized_pnl_a=total_unrealized_pnl,
        realized_pnl_a=realized_pnl_a,
        capital_utilization=capital_utilization,
    )
