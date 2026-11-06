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
from datetime import date, datetime
from typing import Any

from core.currency import convert_to_a, convert_to_b
from core.conversions import annualized_return
from core.interest import growth_factor
from schemas.backtest import (
    ExecutableQuoteResult,
    ExecutionConfig,
    PriceType,
    TradeRecord,
    TradeSide,
    TradeStatus,
)
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
    observed_ask: float | None = None,
) -> ExecutionPrices:
    """Compute effective exchange rate when converting borrowing currency A to investment B.

    Rate convention: units of A per unit of B.
    Buying B costs the ask price (higher A per B), plus adverse slippage.

    If observed_ask is provided, it is used directly without adding synthetic spread.
    Otherwise, ask_rate = mid * (1 + (spread_bps / 20000)).
    exec_rate = ask_rate * (1 + (slippage_bps / 10000)).
    """
    if spot_mid <= 0:
        raise ValueError(f"Spot mid rate must be positive, got {spot_mid}")
    if observed_ask is not None:
        if observed_ask <= 0:
            raise ValueError(f"Observed ask rate must be positive, got {observed_ask}")
        ask_rate = observed_ask
        spread_bps_eff = ((ask_rate / spot_mid) - 1.0) * 20_000.0
    else:
        half_spread = (spread_bps / 2.0) / 10_000.0
        ask_rate = spot_mid * (1.0 + half_spread)
        spread_bps_eff = spread_bps

    exec_rate = ask_rate * (1.0 + slippage_bps / 10_000.0)
    friction = exec_rate - spot_mid

    return ExecutionPrices(
        mid_rate=spot_mid,
        spread_bps=spread_bps_eff,
        slippage_bps=slippage_bps,
        effective_rate=exec_rate,
        friction_cost_a=friction,
    )


def compute_exit_execution_rate(
    spot_mid: float,
    spread_bps: float = 0.0,
    slippage_bps: float = 0.0,
    observed_bid: float | None = None,
) -> ExecutionPrices:
    """Compute effective exchange rate when converting investment currency B back to A.

    Rate convention: units of A per unit of B.
    Selling B receives the bid price (lower A per B), minus adverse slippage.

    If observed_bid is provided, it is used directly without subtracting synthetic spread.
    Otherwise, bid_rate = mid * (1 - (spread_bps / 20000)).
    exec_rate = bid_rate * (1 - (slippage_bps / 10000)).
    """
    if spot_mid <= 0:
        raise ValueError(f"Spot mid rate must be positive, got {spot_mid}")
    if observed_bid is not None:
        if observed_bid <= 0:
            raise ValueError(f"Observed bid rate must be positive, got {observed_bid}")
        bid_rate = observed_bid
        spread_bps_eff = (1.0 - (bid_rate / spot_mid)) * 20_000.0
    else:
        half_spread = (spread_bps / 2.0) / 10_000.0
        bid_rate = spot_mid * (1.0 - half_spread)
        spread_bps_eff = spread_bps

    exec_rate = bid_rate * (1.0 - slippage_bps / 10_000.0)
    if exec_rate <= 0:
        raise ValueError(
            f"Execution rate after spread and slippage became non-positive ({exec_rate})."
        )
    friction = spot_mid - exec_rate

    return ExecutionPrices(
        mid_rate=spot_mid,
        spread_bps=spread_bps_eff,
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
        exec_quote: ExecutableQuoteResult | None = None,
        forward_mid: float | None = None,
        is_covered: bool = False,
        is_verified_availability: bool = True,
        signal_timestamp: datetime | None = None,
        order_submission_timestamp: datetime | None = None,
        execution_timestamp: datetime | None = None,
        settlement_timestamp: datetime | None = None,
        entry_price_type: PriceType | None = None,
        entry_price_source: str | None = None,
        entry_quote_timestamp: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TradeRecord:
        """Execute trade opening (borrow A, convert A -> B, hold for investment).

        Validates trade size and rates before execution.
        Supports Mode A (observed market spread) and Mode B (modelled spread).
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

        if exec_quote is not None:
            if exec_quote.canonical_side == "bid" or (
                exec_quote.quote_assembly_method.startswith("standalone_one_sided")
                and exec_quote.ask_a_per_b is None
            ) or (
                exec_quote.price_type == PriceType.BID_QUOTE and exec_quote.ask_a_per_b is None
            ):
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
                    rejection_reason="Cannot execute long-entry with a standalone BID quote (missing ask quote).",
                )

        spot_mid = exec_quote.rate_a_per_b if (exec_quote and exec_quote.rate_a_per_b > 0) else spot_mid_entry
        if spot_mid <= 0:
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
                spot_mid_entry=max(1e-9, spot_mid),
                spot_exec_entry=max(1e-9, spot_mid),
                invested_amount_b=0.0,
                status=TradeStatus.REJECTED,
                rejection_reason=f"Invalid spot mid rate: {spot_mid}",
            )

        # Conversion fee (entry leg)
        entry_variable_fee_a = principal_borrowed_a * (self.config.variable_fee_bps / 10_000.0)
        effective_principal_converted = principal_borrowed_a - entry_variable_fee_a

        # Check Mode A (Observed Spread) vs Mode B (Modelled Spread)
        is_mode_a = (
            exec_quote is not None
            and exec_quote.is_observed_spread
            and self.config.use_observed_spread
            and exec_quote.ask_a_per_b is not None
            and exec_quote.ask_a_per_b > 0
        )

        if is_mode_a:
            observed_ask = exec_quote.ask_a_per_b
            entry_prices = compute_entry_execution_rate(
                spot_mid=spot_mid,
                slippage_bps=self.config.slippage_bps,
                observed_ask=observed_ask,
            )
            entry_observed_spread_cost_a = effective_principal_converted * (1.0 - (spot_mid / observed_ask))
            entry_modelled_spread_cost_a = 0.0
            entry_slippage_cost_a = effective_principal_converted * ((spot_mid / observed_ask) - (spot_mid / entry_prices.effective_rate))
            is_proxy = False
        else:
            entry_prices = compute_entry_execution_rate(
                spot_mid=spot_mid,
                spread_bps=self.config.bid_ask_spread_bps,
                slippage_bps=self.config.slippage_bps,
            )
            half_spread_entry = (self.config.bid_ask_spread_bps / 2.0) / 10_000.0
            ask_entry = spot_mid * (1.0 + half_spread_entry)
            entry_observed_spread_cost_a = 0.0
            entry_modelled_spread_cost_a = effective_principal_converted * (1.0 - (spot_mid / ask_entry))
            entry_slippage_cost_a = effective_principal_converted * ((spot_mid / ask_entry) - (spot_mid / entry_prices.effective_rate))
            is_proxy = (exec_quote is None or not exec_quote.is_executable)

        # Net principal converted into B
        invested_b = convert_to_b(effective_principal_converted, entry_prices.effective_rate)
        entry_fees_a = entry_variable_fee_a
        entry_spread_cost_a = entry_observed_spread_cost_a + entry_modelled_spread_cost_a

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
                    spot_mid_entry=spot_mid,
                    spot_exec_entry=entry_prices.effective_rate,
                    invested_amount_b=0.0,
                    status=TradeStatus.REJECTED,
                    rejection_reason="Covered trade requested but forward rate is missing or invalid.",
                )
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
            spot_mid_entry=spot_mid,
            spot_exec_entry=entry_prices.effective_rate,
            invested_amount_b=invested_b,
            is_covered=is_covered,
            forward_exec_rate=forward_exec,
            entry_spread_cost_a=entry_spread_cost_a,
            entry_slippage_cost_a=entry_slippage_cost_a,
            entry_fees_a=entry_fees_a,
            transaction_costs_a=entry_variable_fee_a,
            slippage_costs_a=entry_slippage_cost_a,
            observed_spread_cost_a=entry_observed_spread_cost_a,
            modelled_spread_cost_a=entry_modelled_spread_cost_a,
            slippage_cost_a=entry_slippage_cost_a,
            is_proxy_execution=is_proxy,
            status=TradeStatus.OPEN,
            is_availability_verified=is_verified_availability,
            entry_price_type=entry_price_type or (exec_quote.price_type if exec_quote else None),
            entry_price_source=entry_price_source or (exec_quote.data_source if exec_quote else None),
            entry_quote_timestamp=entry_quote_timestamp or (exec_quote.observation_timestamp if exec_quote else None),
            entry_provider_price_type=exec_quote.provider_price_type if exec_quote else None,
            entry_provider_side=exec_quote.provider_side if exec_quote else None,
            entry_provider_base=exec_quote.provider_base_currency if exec_quote else "",
            entry_provider_quote=exec_quote.provider_quote_currency if exec_quote else "",
            entry_provider_convention=exec_quote.provider_convention if exec_quote else None,
            entry_canonical_side=exec_quote.canonical_side if exec_quote else None,
            signal_timestamp=signal_timestamp,
            order_submission_timestamp=order_submission_timestamp,
            execution_timestamp=execution_timestamp,
            settlement_timestamp=settlement_timestamp,
            metadata=metadata or {},
        )

    def close_trade(
        self,
        trade: TradeRecord,
        exit_date: date,
        spot_mid_exit: float,
        exec_quote: ExecutableQuoteResult | None = None,
        exit_signal_timestamp: datetime | None = None,
        exit_order_submission_timestamp: datetime | None = None,
        exit_execution_timestamp: datetime | None = None,
        exit_price_source: str | None = None,
        exit_quote_timestamp: datetime | None = None,
        exit_price_type: PriceType | None = None,
    ) -> TradeRecord:
        """Close an open trade at maturity or rebalance.

        Supports Mode A (observed market spread) and Mode B (modelled spread).
        Reconciles pure FX translation vs investment yield gain and itemized frictions.
        """
        if trade.status != TradeStatus.OPEN:
            raise ValueError(f"Cannot close trade {trade.trade_id} with status {trade.status}")

        if exec_quote is not None:
            if exec_quote.canonical_side == "ask" or (
                exec_quote.quote_assembly_method.startswith("standalone_one_sided")
                and exec_quote.bid_a_per_b is None
            ) or (
                exec_quote.price_type == PriceType.ASK_QUOTE and exec_quote.bid_a_per_b is None
            ):
                raise ValueError("Cannot execute exit with a standalone ASK quote (missing bid quote).")

        actual_days = (exit_date - trade.entry_date).days
        if actual_days <= 0:
            actual_days = 1  # Minimum 1 day holding
        years = days_to_years(actual_days)

        # 1. Accumulate investment in B
        f_b = growth_factor(trade.investment_rate, years, self.config.interest_convention)
        investment_value_b = trade.invested_amount_b * f_b

        exit_mid = exec_quote.rate_a_per_b if (exec_quote and exec_quote.rate_a_per_b > 0) else spot_mid_exit
        if exit_mid <= 0:
            raise ValueError(f"Invalid exit spot rate: {exit_mid}")

        # Determine effective exit exchange rate and frictions
        if trade.is_covered and trade.forward_exec_rate is not None:
            exec_exit_rate = trade.forward_exec_rate
            exit_observed_spread_cost_a = 0.0
            exit_modelled_spread_cost_a = 0.0
            exit_slippage_cost_a = 0.0
            is_proxy_exit = False
        else:
            is_mode_a = (
                exec_quote is not None
                and exec_quote.is_observed_spread
                and self.config.use_observed_spread
                and exec_quote.bid_a_per_b is not None
                and exec_quote.bid_a_per_b > 0
            )

            if is_mode_a:
                observed_bid = exec_quote.bid_a_per_b
                exit_prices = compute_exit_execution_rate(
                    spot_mid=exit_mid,
                    slippage_bps=self.config.slippage_bps,
                    observed_bid=observed_bid,
                )
                exec_exit_rate = exit_prices.effective_rate
                exit_observed_spread_cost_a = investment_value_b * (exit_mid - observed_bid)
                exit_modelled_spread_cost_a = 0.0
                exit_slippage_cost_a = investment_value_b * (observed_bid - exec_exit_rate)
                is_proxy_exit = False
            else:
                exit_prices = compute_exit_execution_rate(
                    spot_mid=exit_mid,
                    spread_bps=self.config.bid_ask_spread_bps,
                    slippage_bps=self.config.slippage_bps,
                )
                exec_exit_rate = exit_prices.effective_rate
                half_spread_exit = (self.config.bid_ask_spread_bps / 2.0) / 10_000.0
                bid_rate_exit = exit_mid * (1.0 - half_spread_exit)
                exit_observed_spread_cost_a = 0.0
                exit_modelled_spread_cost_a = investment_value_b * (exit_mid - bid_rate_exit)
                exit_slippage_cost_a = investment_value_b * (bid_rate_exit - exec_exit_rate)
                is_proxy_exit = (exec_quote is None or not exec_quote.is_executable)

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

        exit_spread_cost_a = exit_observed_spread_cost_a + exit_modelled_spread_cost_a
        total_observed_spread_cost_a = (trade.observed_spread_cost_a or 0.0) + exit_observed_spread_cost_a
        total_modelled_spread_cost_a = (trade.modelled_spread_cost_a or 0.0) + exit_modelled_spread_cost_a
        total_slippage = (trade.slippage_cost_a or trade.entry_slippage_cost_a or 0.0) + exit_slippage_cost_a

        # 5. Net profit in A
        net_profit_a = converted_back_a - repayment_a - exit_variable_fee_a - fixed_fee_a
        roi = net_profit_a / trade.principal_borrowed_a

        # Decomposition of gross gains:
        # investment_yield_gain_a = foreign yield converted to A at entry spot mid
        # fx_translation_gain_a = foreign principal+interest multiplied by (exit spot mid - entry spot mid)
        investment_yield_gain_a = trade.invested_amount_b * (f_b - 1.0) * trade.spot_mid_entry
        fx_translation_gain_a = (trade.invested_amount_b * f_b) * (exit_mid - trade.spot_mid_entry)
        pure_gross_gain_a = investment_yield_gain_a + fx_translation_gain_a

        # Pure gross mid-to-mid value:
        pure_gross_value_a = (trade.principal_borrowed_a / trade.spot_mid_entry) * f_b * exit_mid

        # Total frictions: exact difference between pure gross value and net cash realized before financing
        total_frictions_a = total_observed_spread_cost_a + total_modelled_spread_cost_a + total_slippage + trade.entry_fees_a + exit_variable_fee_a + fixed_fee_a
        reconciliation_residual_a = abs(net_profit_a - (pure_gross_gain_a - interest_a - total_frictions_a))

        # Annualized return
        ann_return: float | None = None
        try:
            ann_return = annualized_return(roi, years, self.config.interest_convention)
        except ValueError:
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
                "investment_yield_gain_a": investment_yield_gain_a,
                "fx_translation_gain_a": fx_translation_gain_a,
                "financing_cost_a": interest_a,
                "exit_spread_cost_a": exit_spread_cost_a,
                "exit_slippage_cost_a": exit_slippage_cost_a,
                "exit_fees_a": exit_variable_fee_a,
                "fixed_fee_a": fixed_fee_a,
                "observed_spread_cost_a": total_observed_spread_cost_a,
                "modelled_spread_cost_a": total_modelled_spread_cost_a,
                "slippage_cost_a": total_slippage,
                "is_proxy_exit": is_proxy_exit,
                "total_frictions_a": total_frictions_a,
                "transaction_costs_a": total_transaction_costs,
                "slippage_costs_a": total_slippage,
                "net_profit_a": net_profit_a,
                "reconciliation_residual_a": reconciliation_residual_a,
                "return_on_capital": roi,
                "annualized_return": ann_return,
                "status": TradeStatus.CLOSED,
                "exit_signal_timestamp": exit_signal_timestamp,
                "exit_order_submission_timestamp": exit_order_submission_timestamp,
                "exit_execution_timestamp": exit_execution_timestamp,
                "exit_price_source": exit_price_source or (exec_quote.data_source if exec_quote else None),
                "exit_quote_timestamp": exit_quote_timestamp or (exec_quote.observation_timestamp if exec_quote else None),
                "exit_price_type": exit_price_type or (exec_quote.price_type if exec_quote else None),
                "exit_provider_price_type": exec_quote.provider_price_type if exec_quote else None,
                "exit_provider_side": exec_quote.provider_side if exec_quote else None,
                "exit_provider_base": exec_quote.provider_base_currency if exec_quote else "",
                "exit_provider_quote": exec_quote.provider_quote_currency if exec_quote else "",
                "exit_provider_convention": exec_quote.provider_convention if exec_quote else None,
                "exit_canonical_side": exec_quote.canonical_side if exec_quote else None,
            }
        )
