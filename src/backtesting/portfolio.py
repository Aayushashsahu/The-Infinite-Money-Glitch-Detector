"""Portfolio and Capital Management: Position Accounting, Sizing, and Risk Limits.

Enforces:
- Single-allocation rule: prevents double-allocating capital to multiple simultaneous trades.
- Leverage constraint: prevents gross borrowing exposure from exceeding equity * max_leverage.
- Active position limits: caps simultaneous concurrent trades.
- Dynamic position sizing: Fixed Amount, Percent of Equity, or All Available Cash.
- Cash balance and realized PnL accounting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from schemas.backtest import (
    ExecutionConfig,
    PortfolioSnapshot,
    PositionSizingConfig,
    PositionSizingMethod,
    TradeRecord,
    TradeStatus,
)
from schemas.strategy import InterestConvention
from backtesting.valuation import compute_portfolio_snapshot


@dataclass(frozen=True)
class SizingResult:
    """Outcome of position-sizing evaluation."""

    allocated_amount_a: float
    is_allowed: bool
    rejection_reason: str | None = None


class Portfolio:
    """Manages cash, capital allocation, active positions, and leverage constraints."""

    def __init__(
        self,
        initial_capital_a: float = 100_000.0,
        sizing_config: PositionSizingConfig | None = None,
        execution_config: ExecutionConfig | None = None,
        cash_deposit_rate_annual: float = 0.0,
    ):
        if initial_capital_a <= 0:
            raise ValueError(f"Initial capital must be positive, got {initial_capital_a}")
        self.initial_capital_a = initial_capital_a
        self.cash_a = initial_capital_a
        self.cash_deposit_rate_annual = cash_deposit_rate_annual
        self.total_cash_interest_earned = 0.0
        self.realized_pnl_a = 0.0
        self.sizing_config = sizing_config or PositionSizingConfig()
        self.execution_config = execution_config or ExecutionConfig()

        self._open_trades: dict[str, TradeRecord] = {}
        self._closed_trades: list[TradeRecord] = []
        self._rejected_trades: list[TradeRecord] = []
        self._snapshots: list[PortfolioSnapshot] = []

    @property
    def open_trades(self) -> list[TradeRecord]:
        return list(self._open_trades.values())

    @property
    def closed_trades(self) -> list[TradeRecord]:
        return list(self._closed_trades)

    @property
    def rejected_trades(self) -> list[TradeRecord]:
        return list(self._rejected_trades)

    @property
    def snapshots(self) -> list[PortfolioSnapshot]:
        return list(self._snapshots)

    @property
    def total_borrowed_exposure_a(self) -> float:
        return sum(t.principal_borrowed_a for t in self._open_trades.values())

    def calculate_position_size(self, current_equity_a: float | None = None) -> SizingResult:
        """Calculate eligible borrowing size for a new trade adhering to capital constraints.

        Prevents double-allocation of capital and respects leverage limits.
        """
        equity = current_equity_a if current_equity_a is not None else self.cash_a
        if equity <= 0:
            return SizingResult(
                allocated_amount_a=0.0,
                is_allowed=False,
                rejection_reason=f"Portfolio equity is non-positive ({equity:.2f}). Trading halted.",
            )

        # Check maximum active positions limit
        if len(self._open_trades) >= self.sizing_config.max_active_positions:
            return SizingResult(
                allocated_amount_a=0.0,
                is_allowed=False,
                rejection_reason=(
                    f"Max active positions reached ({len(self._open_trades)} / "
                    f"{self.sizing_config.max_active_positions}). Capital cannot be double-allocated."
                ),
            )

        # Available borrowing capacity under leverage limit
        max_allowed_borrowing = equity * self.sizing_config.max_leverage
        remaining_capacity = max_allowed_borrowing - self.total_borrowed_exposure_a
        if remaining_capacity <= 0:
            return SizingResult(
                allocated_amount_a=0.0,
                is_allowed=False,
                rejection_reason=(
                    f"Borrowing capacity exhausted (current borrowed: {self.total_borrowed_exposure_a:.2f}, "
                    f"max allowed: {max_allowed_borrowing:.2f})."
                ),
            )

        # Target sizing by method
        method = self.sizing_config.method
        if method == PositionSizingMethod.FIXED_AMOUNT:
            target = self.sizing_config.fixed_amount
        elif method == PositionSizingMethod.PERCENT_OF_EQUITY:
            target = equity * self.sizing_config.percent_of_equity
        elif method == PositionSizingMethod.ALL_AVAILABLE_CASH:
            target = remaining_capacity
        else:
            raise ValueError(f"Unknown sizing method: {method}")

        # Sizing cannot exceed remaining capacity
        allocated = min(target, remaining_capacity)

        # Check execution min size
        if allocated < self.execution_config.min_trade_size_a:
            return SizingResult(
                allocated_amount_a=0.0,
                is_allowed=False,
                rejection_reason=(
                    f"Allocated size {allocated:.2f} is below min_trade_size_a "
                    f"{self.execution_config.min_trade_size_a}."
                ),
            )

        return SizingResult(
            allocated_amount_a=allocated,
            is_allowed=True,
            rejection_reason=None,
        )

    def register_open_trade(self, trade: TradeRecord) -> bool:
        """Register a newly opened trade and reserve its borrowed capital."""
        if trade.status != TradeStatus.OPEN:
            self._rejected_trades.append(trade)
            return False

        if trade.trade_id in self._open_trades:
            raise ValueError(f"Trade with id {trade.trade_id} already open.")

        # Double check allocation
        sizing = self.calculate_position_size()
        if not sizing.is_allowed and trade.principal_borrowed_a > 0:
            trade_rejected = trade.model_copy(
                update={
                    "status": TradeStatus.REJECTED,
                    "rejection_reason": sizing.rejection_reason,
                }
            )
            self._rejected_trades.append(trade_rejected)
            return False

        self._open_trades[trade.trade_id] = trade
        # Deduct initial transaction costs from cash
        self.cash_a -= trade.transaction_costs_a
        return True

    def register_closed_trade(self, closed_trade: TradeRecord) -> None:
        """Register a closed trade, release capital, and update cash with net profit."""
        if closed_trade.status != TradeStatus.CLOSED:
            raise ValueError(f"Trade {closed_trade.trade_id} is not CLOSED.")

        if closed_trade.trade_id not in self._open_trades:
            raise ValueError(f"Trade {closed_trade.trade_id} is not an open trade in this portfolio.")

        # Remove from active
        del self._open_trades[closed_trade.trade_id]
        self._closed_trades.append(closed_trade)

        # Update realized PnL and cash
        # Note: net_profit_a already accounts for all financing costs, conversions, and transaction fees
        profit = closed_trade.net_profit_a or 0.0
        # Since entry transaction cost was already deducted when trade was opened,
        # we adjust cash by: profit + entry_transaction_cost (to avoid double deduction of entry fee)
        # Net effect on cash = cash + profit
        # Specifically:
        # Cash_before_entry = C0
        # Cash_after_entry = C0 - entry_cost
        # Cash_after_close = C0 + net_profit = (C0 - entry_cost) + (net_profit + entry_cost)
        entry_cost = closed_trade.transaction_costs_a - (
            (closed_trade.converted_back_a or 0.0) * (self.execution_config.variable_fee_bps / 10_000.0)
            + self.execution_config.fixed_fee
        )
        self.cash_a += (profit + max(0.0, entry_cost))
        self.realized_pnl_a += profit

    def accrue_cash_interest(
        self,
        days: int,
        convention: InterestConvention = InterestConvention.COMPOUND,
    ) -> float:
        """Accrue interest on unencumbered cash balance in borrowing currency A."""
        if days <= 0 or self.cash_deposit_rate_annual <= 0.0 or self.cash_a <= 0.0:
            return 0.0
        from core.interest import growth_factor
        from backtesting.financing import days_to_years
        years = days_to_years(days)
        factor = growth_factor(self.cash_deposit_rate_annual, years, convention)
        interest = self.cash_a * (factor - 1.0)
        self.cash_a += interest
        self.total_cash_interest_earned += interest
        return interest

    def snapshot(
        self,
        as_of: date,
        current_spot_rates: dict[str, float],
    ) -> PortfolioSnapshot:
        """Record a mark-to-market snapshot of the portfolio at timestamp T."""
        snap = compute_portfolio_snapshot(
            as_of=as_of,
            cash_a=self.cash_a,
            open_trades=self.open_trades,
            current_spot_rates=current_spot_rates,
            realized_pnl_a=self.realized_pnl_a,
            execution_config=self.execution_config,
        )
        self._snapshots.append(snap)
        return snap
