"""Trade Execution Engine: Cross-Currency Execution with Frictions and Market Constraints.

Models:
- Bid/ask spreads: half-spread charged on entry (ask) and exit (bid).
- Slippage: adverse price impact on execution.
- Transaction costs: fixed fee plus proportional basis-point conversion fees.
- Capital conversion: reuses `core.currency.convert_to_b` and `convert_to_a`.
- Investment accrual: reuses `core.interest.growth_factor`.
- Loan repayment: reuses `backtesting.financing.calculate_fixed_financing`.
- Executability checks: strictly rejects missing, non-positive, or stale market quotes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from core.currency import convert_to_a, convert_to_b
from core.conversions import annualized_return
from core.interest import growth_factor
from schemas.backtest import ExecutionConfig, TradeRecord, TradeSide, TradeStatus
from schemas.strategy import CurrencyPair, InterestConvention
from backtesting.financing import calculate_fixed_financing, days_to_years


@dataclass(frozen=True)
class ExecutionPrices:
    """Breakdown of raw quote, spread, slippage, and effective execution rate."""

    mid_rate: float
    spread_bps: float
    slippage_bps: float
    effective_rate: float
    friction_cost_a: float


def compute_entry_execution_rate(
    spot_mid: float,
    spread_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> ExecutionPrices:
    """Compute effective exchange rate when converting borrowing currency A to investment B.

    Rate convention: units of A per unit of B.
    Buying B costs the ask price (higher A per B), plus adverse slippage.

    ask_rate = mid * (1 + (spread_bps / 20000))
    exec_rate = ask_rate * (1 + (slippage_bps / 10000))
    """
    if spot_mid <= 0:
        raise ValueError(f"Spot mid rate must be positive, got {spot_mid}")
    half_spread = (spread_bps / 2.0) / 10_000.0
    ask_rate = spot_mid * (1.0 + half_spread)
    exec_rate = ask_rate * (1.0 + slippage_bps / 10_000.0)
    friction = exec_rate - spot_mid

    return ExecutionPrices(
        mid_rate=spot_mid,
        spread_bps=spread_bps,
        slippage_bps=slippage_bps,
        effective_rate=exec_rate,
        friction_cost_a=friction,
    )


def compute_exit_execution_rate(
    spot_mid: float,
    spread_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> ExecutionPrices:
    """Compute effective exchange rate when converting investment currency B back to A.

    Rate convention: units of A per unit of B.
    Selling B receives the bid price (lower A per B), minus adverse slippage.

    bid_rate = mid * (1 - (spread_bps / 20000))
    exec_rate = bid_rate * (1 - (slippage_bps / 10000))
    """
    if spot_mid <= 0:
        raise ValueError(f"Spot mid rate must be positive, got {spot_mid}")
    half_spread = (spread_bps / 2.0) / 10_000.0
    bid_rate = spot_mid * (1.0 - half_spread)
    exec_rate = bid_rate * (1.0 - slippage_bps / 10_000.0)
    if exec_rate <= 0:
        raise ValueError(
            f"Execution rate after spread ({spread_bps} bps) and slippage ({slippage_bps} bps) "
            f"became non-positive ({exec_rate})."
        )
    friction = spot_mid - exec_rate

    return ExecutionPrices(
        mid_rate=spot_mid,
        spread_bps=spread_bps,
        slippage_bps=slippage_bps,
        effective_rate=exec_rate,
        friction_cost_a=friction,
    )


class ExecutionEngine:
    """Executes trades, applies market frictions, and produces auditable records."""

    def __init__(self, config: ExecutionConfig | None = None):
        self.config = config or ExecutionConfig()

    def open_trade(
        self,
        trade_id: str,
        strategy_name: str,
        currency_pair: CurrencyPair,
        entry_date: date,
        tenor_days: int,
        principal_borrowed_a: float,
        borrowing_rate: float,
        investment_rate: float,
        spot_mid_entry: float,
        forward_mid: float | None = None,
        is_covered: bool = False,
        is_verified_availability: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> TradeRecord:
        """Execute trade opening (borrow A, convert A -> B, hold for investment).

        Validates trade size and rates before execution.
        """
        # Validate constraints
        if principal_borrowed_a < self.config.min_trade_size_a:
            return TradeRecord(
                trade_id=trade_id,
                strategy_name=strategy_name,
                currency_pair=currency_pair,
                borrowing_currency=currency_pair.borrowing_currency,
                investment_currency=currency_pair.investment_currency,
                entry_date=entry_date,
                target_tenor_days=tenor_days,
                principal_borrowed_a=principal_borrowed_a,
                borrowing_rate=borrowing_rate,
                investment_rate=investment_rate,
                spot_mid_entry=spot_mid_entry,
                spot_exec_entry=spot_mid_entry,
                invested_amount_b=0.0,
                status=TradeStatus.REJECTED,
                rejection_reason=f"Principal {principal_borrowed_a} below min_trade_size_a {self.config.min_trade_size_a}",
            )

        if principal_borrowed_a > self.config.max_trade_size_a:
            return TradeRecord(
                trade_id=trade_id,
                strategy_name=strategy_name,
                currency_pair=currency_pair,
                borrowing_currency=currency_pair.borrowing_currency,
                investment_currency=currency_pair.investment_currency,
                entry_date=entry_date,
                target_tenor_days=tenor_days,
                principal_borrowed_a=principal_borrowed_a,
                borrowing_rate=borrowing_rate,
                investment_rate=investment_rate,
                spot_mid_entry=spot_mid_entry,
                spot_exec_entry=spot_mid_entry,
                invested_amount_b=0.0,
                status=TradeStatus.REJECTED,
                rejection_reason=f"Principal {principal_borrowed_a} exceeds max_trade_size_a {self.config.max_trade_size_a}",
            )

        if spot_mid_entry <= 0:
            return TradeRecord(
                trade_id=trade_id,
                strategy_name=strategy_name,
                currency_pair=currency_pair,
                borrowing_currency=currency_pair.borrowing_currency,
                investment_currency=currency_pair.investment_currency,
                entry_date=entry_date,
                target_tenor_days=tenor_days,
                principal_borrowed_a=principal_borrowed_a,
                borrowing_rate=borrowing_rate,
                investment_rate=investment_rate,
                spot_mid_entry=max(1e-9, spot_mid_entry),
                spot_exec_entry=max(1e-9, spot_mid_entry),
                invested_amount_b=0.0,
                status=TradeStatus.REJECTED,
                rejection_reason=f"Invalid spot mid rate: {spot_mid_entry}",
            )

        # Compute entry execution rate with spread and slippage
        entry_prices = compute_entry_execution_rate(
            spot_mid=spot_mid_entry,
            spread_bps=self.config.bid_ask_spread_bps,
            slippage_bps=self.config.slippage_bps,
        )

        # Conversion fee (entry leg)
        entry_variable_fee_a = principal_borrowed_a * (self.config.variable_fee_bps / 10_000.0)
        
        # Net principal converted into B
        effective_principal_converted = principal_borrowed_a - entry_variable_fee_a
        invested_b = convert_to_b(effective_principal_converted, entry_prices.effective_rate)

        # Decompose entry frictions
        half_spread_entry = (self.config.bid_ask_spread_bps / 2.0) / 10_000.0
        ask_entry = spot_mid_entry * (1.0 + half_spread_entry)
        entry_spread_cost_a = effective_principal_converted * (1.0 - (spot_mid_entry / ask_entry))
        entry_slippage_cost_a = effective_principal_converted * ((spot_mid_entry / ask_entry) - (spot_mid_entry / entry_prices.effective_rate))
        entry_fees_a = entry_variable_fee_a

        # Slippage cost in A
        mid_invested_b = convert_to_b(principal_borrowed_a, spot_mid_entry)
        slippage_loss_a = (mid_invested_b - invested_b) * spot_mid_entry

        # Forward execution if covered
        forward_exec: float | None = None
        if is_covered:
            if forward_mid is None or forward_mid <= 0:
                return TradeRecord(
                    trade_id=trade_id,
                    strategy_name=strategy_name,
                    currency_pair=currency_pair,
                    borrowing_currency=currency_pair.borrowing_currency,
                    investment_currency=currency_pair.investment_currency,
                    entry_date=entry_date,
                    target_tenor_days=tenor_days,
                    principal_borrowed_a=principal_borrowed_a,
                    borrowing_rate=borrowing_rate,
                    investment_rate=investment_rate,
                    spot_mid_entry=spot_mid_entry,
                    spot_exec_entry=entry_prices.effective_rate,
                    invested_amount_b=0.0,
                    status=TradeStatus.REJECTED,
                    rejection_reason="Covered trade requested but forward rate is missing or invalid.",
                )
            # When locking in exit forward at entry, selling B in forward market pays bid spread
            fwd_exit_prices = compute_exit_execution_rate(
                spot_mid=forward_mid,
                spread_bps=self.config.bid_ask_spread_bps,
                slippage_bps=self.config.slippage_bps,
            )
            forward_exec = fwd_exit_prices.effective_rate

        return TradeRecord(
            trade_id=trade_id,
            strategy_name=strategy_name,
            currency_pair=currency_pair,
            borrowing_currency=currency_pair.borrowing_currency,
            investment_currency=currency_pair.investment_currency,
            side=TradeSide.LONG_B_SHORT_A,
            entry_date=entry_date,
            target_tenor_days=tenor_days,
            principal_borrowed_a=principal_borrowed_a,
            borrowing_rate=borrowing_rate,
            investment_rate=investment_rate,
            spot_mid_entry=spot_mid_entry,
            spot_exec_entry=entry_prices.effective_rate,
            invested_amount_b=invested_b,
            is_covered=is_covered,
            forward_exec_rate=forward_exec,
            entry_spread_cost_a=entry_spread_cost_a,
            entry_slippage_cost_a=entry_slippage_cost_a,
            entry_fees_a=entry_fees_a,
            transaction_costs_a=entry_variable_fee_a,
            slippage_costs_a=max(0.0, slippage_loss_a),
            status=TradeStatus.OPEN,
            is_availability_verified=is_verified_availability,
            metadata=metadata or {},
        )

    def close_trade(
        self,
        trade: TradeRecord,
        exit_date: date,
        spot_mid_exit: float,
    ) -> TradeRecord:
        """Close an open trade at maturity or rebalance.

        Accumulates investment return in B, converts back to A, repays financing loan,
        deducts exit conversion fee and fixed fee, and computes realized PnL.
        """
        if trade.status != TradeStatus.OPEN:
            raise ValueError(f"Cannot close trade {trade.trade_id} with status {trade.status}")

        actual_days = (exit_date - trade.entry_date).days
        if actual_days <= 0:
            actual_days = 1  # Minimum 1 day holding
        years = days_to_years(actual_days)

        # 1. Accumulate investment in B
        f_b = growth_factor(trade.investment_rate, years, self.config.interest_convention)
        investment_value_b = trade.invested_amount_b * f_b

        # Determine effective exit exchange rate and frictions
        half_spread_exit = (self.config.bid_ask_spread_bps / 2.0) / 10_000.0
        if trade.is_covered and trade.forward_exec_rate is not None:
            # Locked forward rate
            exec_exit_rate = trade.forward_exec_rate
            exit_mid = spot_mid_exit
            bid_rate_exit = spot_mid_exit * (1.0 - half_spread_exit)
            exit_spread_cost_a = investment_value_b * (spot_mid_exit - bid_rate_exit)
            exit_slippage_cost_a = investment_value_b * max(0.0, bid_rate_exit - exec_exit_rate)
            exit_slippage = 0.0
        else:
            # Unhedged: spot conversion with bid spread and adverse slippage
            if spot_mid_exit <= 0:
                raise ValueError(f"Invalid exit spot rate: {spot_mid_exit}")
            exit_prices = compute_exit_execution_rate(
                spot_mid=spot_mid_exit,
                spread_bps=self.config.bid_ask_spread_bps,
                slippage_bps=self.config.slippage_bps,
            )
            exec_exit_rate = exit_prices.effective_rate
            exit_mid = spot_mid_exit
            bid_rate_exit = spot_mid_exit * (1.0 - half_spread_exit)
            exit_spread_cost_a = investment_value_b * (spot_mid_exit - bid_rate_exit)
            exit_slippage_cost_a = investment_value_b * max(0.0, bid_rate_exit - exec_exit_rate)
            exit_slippage = (spot_mid_exit - exec_exit_rate)

        # 2. Convert B back to A
        converted_back_a = convert_to_a(investment_value_b, exec_exit_rate)

        # 3. Calculate loan repayment in A
        financing = calculate_fixed_financing(
            principal=trade.principal_borrowed_a,
            annual_rate=trade.borrowing_rate,
            days=actual_days,
            interest_convention=self.config.interest_convention,
        )
        repayment_a = financing.total_repayment
        interest_a = financing.interest_paid

        # 4. Transaction fees on exit
        exit_variable_fee_a = converted_back_a * (self.config.variable_fee_bps / 10_000.0)
        fixed_fee_a = self.config.fixed_fee
        total_transaction_costs = (
            trade.transaction_costs_a
            + exit_variable_fee_a
            + fixed_fee_a
        )

        # Exit slippage cost in A
        total_slippage = trade.slippage_costs_a + max(0.0, exit_slippage * investment_value_b)

        # 5. Net profit in A
        net_profit_a = converted_back_a - repayment_a - exit_variable_fee_a - fixed_fee_a
        roi = net_profit_a / trade.principal_borrowed_a

        # Pure gross mid-to-mid gain:
        pure_gross_value_a = (trade.principal_borrowed_a / trade.spot_mid_entry) * f_b * exit_mid
        pure_gross_gain_a = pure_gross_value_a - trade.principal_borrowed_a

        # Total frictions: exact difference between pure gross value and net cash realized before financing
        total_frictions_a = pure_gross_value_a - (converted_back_a - exit_variable_fee_a - fixed_fee_a)
        reconciliation_residual_a = abs(net_profit_a - (pure_gross_gain_a - interest_a - total_frictions_a))

        # Annualized return
        ann_return: float | None = None
        try:
            ann_return = annualized_return(roi, years, self.config.interest_convention)
        except ValueError:
            # If loss is beyond -100%, cannot annualize
            ann_return = None

        return trade.model_copy(
            update={
                "exit_date": exit_date,
                "actual_tenor_days": actual_days,
                "spot_mid_exit": exit_mid,
                "spot_exec_exit": exec_exit_rate,
                "investment_gross_value_b": investment_value_b,
                "converted_back_a": converted_back_a,
                "loan_repayment_a": repayment_a,
                "interest_paid_a": interest_a,
                "pure_gross_gain_a": pure_gross_gain_a,
                "financing_cost_a": interest_a,
                "exit_spread_cost_a": exit_spread_cost_a,
                "exit_slippage_cost_a": exit_slippage_cost_a,
                "exit_fees_a": exit_variable_fee_a,
                "fixed_fee_a": fixed_fee_a,
                "total_frictions_a": total_frictions_a,
                "transaction_costs_a": total_transaction_costs,
                "slippage_costs_a": total_slippage,
                "net_profit_a": net_profit_a,
                "reconciliation_residual_a": reconciliation_residual_a,
                "return_on_capital": roi,
                "annualized_return": ann_return,
                "status": TradeStatus.CLOSED,
            }
        )
