"""Financial strategy evaluation adapter for simulated market paths.

Evaluates simulated scenario paths through the audited execution, financing,
portfolio accounting, and double-entry return attribution engines.
Enforces realistic trading session calendars, weekend financing accrual,
and calendar-day tenor maturity semantics.
"""

from __future__ import annotations

from datetime import date, timedelta
import math
from typing import Protocol

import numpy as np

from backtesting.execution import ExecutionEngine
from backtesting.portfolio import Portfolio
from core.currency import QuoteConvention
from schemas.backtest import (
    ExecutionConfig,
    PositionSizingConfig,
    PositionSizingMethod,
    TradeRecord,
    TradeStatus,
)
from schemas.strategy import CurrencyPair
from simulation.monte_carlo.schemas import (
    PathEvaluationResult,
    ScenarioPath,
    StressScenario,
)


def generate_simulated_trading_sessions(
    start_date: date,
    n_sessions: int,
) -> list[date]:
    """Generate n_sessions consecutive business day trading dates starting on or after start_date.

    Skips Saturdays and Sundays so that session intervals across weekends reflect
    actual elapsed calendar time (Friday to Monday = 3 days).
    """
    sessions: list[date] = []
    curr = start_date
    while len(sessions) < n_sessions:
        if curr.weekday() < 5:  # Monday=0, ..., Friday=4
            sessions.append(curr)
        curr += timedelta(days=1)
    return sessions


class ScenarioStrategy(Protocol):
    """Protocol for financial strategies evaluated along simulated scenario paths."""

    def evaluate_path(
        self,
        path: ScenarioPath,
        initial_capital_a: float,
        stress_overlay: StressScenario | None = None,
    ) -> PathEvaluationResult:
        """Evaluate strategy performance, risk, and cash ledger along path."""
        ...


class CarryTradeScenarioStrategy:
    """Evaluates an unhedged FX carry trade across simulated market paths.

    Reuses the audited core modules:
    - core.currency: Canonical rate normalization and quote conventions.
    - core.interest: Day-count conventions and compounding.
    - backtesting.execution: Entry/exit cost accounting, spreads, and loan repayment.
    - backtesting.portfolio: Portfolio cash ledger, capital sizing, and snapshots.

    Trading Calendar & Horizon Semantics:
    - For horizon N, there are N market-return transitions and N+1 price levels (t=0, ..., N).
    - t=0 represents the initial market state: 0 elapsed days, no interest or financing accrued.
    - For t=1..N, financing and idle-cash interest accrue over actual elapsed calendar days
      between trading sessions (e.g., Friday to Monday = 3 days).
    - Contractual trade tenor is 30 calendar days: a trade matures on the first eligible
      market session on or after entry_date + 30 calendar days.
    """

    def __init__(
        self,
        currency_pair: CurrencyPair | None = None,
        tenor_days: int = 30,
        rebalance_days: int = 30,
        execution_config: ExecutionConfig | None = None,
        position_sizing: PositionSizingConfig | None = None,
        cash_deposit_rate_annual: float = 0.015,
    ) -> None:
        self.pair = currency_pair or CurrencyPair(
            base_currency="EUR",
            quote_currency="USD",
            borrowing_currency="EUR",
            investment_currency="USD",
        )
        self.tenor_days = tenor_days
        self.rebalance_days = rebalance_days
        self.exec_config = execution_config or ExecutionConfig(
            bid_ask_spread_bps=2.0,
            slippage_bps=0.5,
            variable_fee_bps=1.0,
            fixed_fee=5.0,
            min_trade_size_a=1_000.0,
            max_trade_size_a=10_000_000.0,
        )
        self.sizing = position_sizing or PositionSizingConfig(
            method=PositionSizingMethod.PERCENT_OF_EQUITY,
            percent_of_equity=0.5,
            max_leverage=1.0,
            max_active_positions=1,
        )
        self.cash_deposit_rate = cash_deposit_rate_annual

    def evaluate_path(
        self,
        path: ScenarioPath,
        initial_capital_a: float = 100_000.0,
        stress_overlay: StressScenario | None = None,
    ) -> PathEvaluationResult:
        """Evaluate the carry trade sequentially step-by-step along a single path.

        Performs full double-entry accounting reconciliation guaranteeing
        residual <= 1e-9 on every simulated path.
        """
        # Apply stress friction multipliers if present
        current_exec_config = self.exec_config
        if stress_overlay is not None:
            current_exec_config = ExecutionConfig(
                bid_ask_spread_bps=self.exec_config.bid_ask_spread_bps * stress_overlay.spread_multiplier,
                slippage_bps=self.exec_config.slippage_bps * stress_overlay.slippage_multiplier,
                variable_fee_bps=self.exec_config.variable_fee_bps,
                fixed_fee=self.exec_config.fixed_fee,
                min_trade_size_a=self.exec_config.min_trade_size_a,
                max_trade_size_a=self.exec_config.max_trade_size_a,
                interest_convention=self.exec_config.interest_convention,
            )

        portfolio = Portfolio(
            initial_capital_a=initial_capital_a,
            sizing_config=self.sizing,
            execution_config=current_exec_config,
            cash_deposit_rate_annual=self.cash_deposit_rate,
        )
        engine = ExecutionEngine(current_exec_config)

        total_levels = len(path.fx_rates)
        n_transitions = path.steps if path.steps > 0 else (total_levels - 1)

        # Build explicit trading-session calendar
        if path.dates is not None and len(path.dates) >= total_levels:
            session_dates = path.dates[:total_levels]
        else:
            session_dates = generate_simulated_trading_sessions(date(2024, 1, 2), total_levels)

        peak_equity = initial_capital_a
        max_drawdown = 0.0

        daily_returns: list[float] = []
        prior_equity = initial_capital_a

        # State tracking for the active position
        active_trade: TradeRecord | None = None
        trade_counter = 0

        # Itemized ledger totals across the path
        cum_pure_gross = 0.0
        cum_fx_gain = 0.0
        cum_yield_gain = 0.0
        cum_financing = 0.0
        cum_frictions = 0.0

        pair_key = f"{self.pair.borrowing_currency}/{self.pair.investment_currency}"

        # Step t=0: Initial market state
        # Zero days elapsed, no financing or cash interest accrued before interval
        s0_provider = path.fx_rates[0]
        s0_canonical = 1.0 / s0_provider if s0_provider > 0 else 1.0

        # Initial trade entry at t=0
        sizing_res = portfolio.calculate_position_size()
        if sizing_res.is_allowed and sizing_res.allocated_amount_a > 0.0 and total_levels > 1:
            trade_counter += 1
            opened = engine.open_trade(
                trade_id=f"PATH_TRD_{trade_counter:04d}",
                strategy_name="CarryTradeScenario",
                currency_pair=self.pair,
                entry_date=session_dates[0],
                tenor_days=self.tenor_days,
                principal_borrowed_a=sizing_res.allocated_amount_a,
                borrowing_rate=path.borrowing_rates[0],
                investment_rate=path.investment_rates[0],
                spot_mid_entry=s0_canonical,
            )
            if portfolio.register_open_trade(opened):
                active_trade = opened

        # Snapshot at t=0
        snap_0 = portfolio.snapshot(
            as_of=session_dates[0],
            current_spot_rates={pair_key: s0_canonical},
        )
        prior_equity = snap_0.equity_a
        peak_equity = max(peak_equity, prior_equity)

        # Step t=1..total_levels-1: Market-return transitions
        for t in range(1, total_levels):
            current_date = session_dates[t]
            prev_date = session_dates[t - 1]

            # Actual elapsed calendar days (1 on standard weekday, 3 over weekend)
            delta_days = (current_date - prev_date).days

            current_fx_provider = path.fx_rates[t]
            current_borrow_rate = path.borrowing_rates[t]
            current_invest_rate = path.investment_rates[t]
            canonical_spot = 1.0 / current_fx_provider if current_fx_provider > 0 else 1.0

            # 1. Accrue unallocated cash interest over actual elapsed calendar days
            if delta_days > 0:
                portfolio.accrue_cash_interest(days=delta_days, convention=current_exec_config.interest_convention)

            # 2. Check trade exit conditions (30 calendar days elapsed or terminal step)
            if active_trade is not None:
                contractual_maturity = active_trade.entry_date + timedelta(days=self.tenor_days)
                is_matured = current_date >= contractual_maturity
                is_terminal = (t == total_levels - 1)

                if is_matured or is_terminal:
                    closed = engine.close_trade(
                        trade=active_trade,
                        exit_date=current_date,
                        spot_mid_exit=canonical_spot,
                    )
                    portfolio.register_closed_trade(closed)

                    cum_pure_gross += (closed.pure_gross_gain_a or 0.0)
                    cum_fx_gain += (closed.fx_translation_gain_a or 0.0)
                    cum_yield_gain += (closed.investment_yield_gain_a or 0.0)
                    cum_financing += (closed.interest_paid_a or 0.0)
                    cum_frictions += (closed.total_frictions_a or 0.0)

                    active_trade = None

            # 3. Snapshot portfolio equity and track drawdown
            snap = portfolio.snapshot(
                as_of=current_date,
                current_spot_rates={pair_key: canonical_spot},
            )
            equity_t = snap.equity_a

            if equity_t > peak_equity:
                peak_equity = equity_t

            dd_t = (equity_t - peak_equity) / peak_equity if peak_equity > 0 else 0.0
            if dd_t < max_drawdown:
                max_drawdown = dd_t

            # Periodic return for this transition
            period_ret = (equity_t - prior_equity) / prior_equity if prior_equity > 0 else 0.0
            daily_returns.append(period_ret)
            prior_equity = equity_t

            # 4. Check trade entry conditions (no active trade, rebalance step, not terminal)
            if active_trade is None and t % self.rebalance_days == 0 and t < total_levels - 1:
                sizing_res = portfolio.calculate_position_size()
                if sizing_res.is_allowed and sizing_res.allocated_amount_a > 0.0:
                    trade_counter += 1
                    opened = engine.open_trade(
                        trade_id=f"PATH_TRD_{trade_counter:04d}",
                        strategy_name="CarryTradeScenario",
                        currency_pair=self.pair,
                        entry_date=current_date,
                        tenor_days=self.tenor_days,
                        principal_borrowed_a=sizing_res.allocated_amount_a,
                        borrowing_rate=current_borrow_rate,
                        investment_rate=current_invest_rate,
                        spot_mid_entry=canonical_spot,
                    )
                    if portfolio.register_open_trade(opened):
                        active_trade = opened

        # Final terminal equity calculation
        terminal_equity = portfolio.cash_a
        net_profit_a = terminal_equity - initial_capital_a
        tot_return = net_profit_a / initial_capital_a

        # Annualized return and volatility based on market transitions
        horizon_years = n_transitions / 252.0
        ann_return = ((1.0 + tot_return) ** (1.0 / horizon_years) - 1.0) if horizon_years > 0 else tot_return
        ann_vol = float(np.std(daily_returns, ddof=1) * math.sqrt(252)) if len(daily_returns) > 1 else 0.0

        # Exact double-entry cash ledger reconciliation
        total_cash_int = portfolio.total_cash_interest_earned
        reconciliation_residual = abs(
            net_profit_a - (cum_pure_gross - cum_financing - cum_frictions + total_cash_int)
        )
        is_exact = reconciliation_residual <= 1e-9

        # Sharpe ratio relative to cash deposit rate
        sharpe = (ann_return - self.cash_deposit_rate) / ann_vol if ann_vol > 1e-6 else None

        return PathEvaluationResult(
            path_id=path.path_id,
            terminal_equity=terminal_equity,
            total_return=tot_return,
            annualized_return=ann_return,
            annualized_volatility=ann_vol,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe,
            pure_gross_gain_a=cum_pure_gross,
            fx_translation_gain_a=cum_fx_gain,
            investment_yield_gain_a=cum_yield_gain,
            total_financing_costs_a=cum_financing,
            total_frictions_a=cum_frictions,
            total_cash_interest_a=total_cash_int,
            cumulative_net_profit_a=net_profit_a,
            reconciliation_residual_a=reconciliation_residual,
            reconciliation_exact=is_exact,
            is_loss=net_profit_a < 0.0,
            breached_drawdown_5pct=max_drawdown <= -0.05,
            breached_drawdown_10pct=max_drawdown <= -0.10,
            breached_drawdown_20pct=max_drawdown <= -0.20,
        )
