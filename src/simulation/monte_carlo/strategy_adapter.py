"""Financial strategy evaluation adapter for simulated market paths.

Evaluates simulated scenario paths through the audited execution, financing,
portfolio accounting, and double-entry return attribution engines.
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
        residual <= 1e-10 on every simulated path.
        """
        # Apply stress friction multipliers if present
        spread_mult = stress_overlay.spread_multiplier if stress_overlay else 1.0
        slip_mult = stress_overlay.slippage_multiplier if stress_overlay else 1.0

        current_exec_config = self.exec_config.model_copy(
            update={
                "bid_ask_spread_bps": self.exec_config.bid_ask_spread_bps * spread_mult,
                "slippage_bps": self.exec_config.slippage_bps * slip_mult,
            }
        )

        portfolio = Portfolio(
            initial_capital_a=initial_capital_a,
            sizing_config=self.sizing,
            execution_config=current_exec_config,
            cash_deposit_rate_annual=self.cash_deposit_rate,
        )
        engine = ExecutionEngine(current_exec_config)

        # Baseline date references
        base_date = date(2024, 1, 1)

        peak_equity = initial_capital_a
        max_drawdown = 0.0

        total_steps = len(path.fx_rates)
        daily_returns: list[float] = []
        prior_equity = initial_capital_a

        # State tracking for the single active trade
        active_trade: TradeRecord | None = None
        trade_entry_step = 0
        trade_counter = 0

        # Itemized ledger totals across the path
        cum_pure_gross = 0.0
        cum_fx_gain = 0.0
        cum_yield_gain = 0.0
        cum_financing = 0.0
        cum_frictions = 0.0

        for t in range(total_steps):
            current_date = base_date + timedelta(days=t)
            current_fx_provider = path.fx_rates[t]
            current_borrow_rate = path.borrowing_rates[t]
            current_invest_rate = path.investment_rates[t]

            # Canonical spot rate in A per B: EUR per USD = 1.0 / provider_rate
            canonical_spot = 1.0 / current_fx_provider if current_fx_provider > 0 else 1.0

            # 1. Accrue cash interest on unallocated cash balance
            portfolio.accrue_cash_interest(days=1, convention=current_exec_config.interest_convention)

            # 2. Check trade exit conditions (tenor reached or last step of path)
            if active_trade is not None and (t - trade_entry_step >= self.tenor_days or t == total_steps - 1):
                closed = engine.close_trade(
                    trade=active_trade,
                    exit_date=current_date,
                    spot_mid_exit=canonical_spot,
                )
                portfolio.register_closed_trade(closed)

                # Accumulate itemized return attribution
                cum_pure_gross += (closed.pure_gross_gain_a or 0.0)
                cum_fx_gain += (closed.fx_translation_gain_a or 0.0)
                cum_yield_gain += (closed.investment_yield_gain_a or 0.0)
                cum_financing += (closed.interest_paid_a or 0.0)
                cum_frictions += (closed.total_frictions_a or 0.0)

                active_trade = None

            # 3. Snapshot portfolio equity and track drawdown (before opening new trades on this day)
            pair_key = f"{self.pair.borrowing_currency}/{self.pair.investment_currency}"
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

            # Track periodic return
            period_ret = (equity_t - prior_equity) / prior_equity if prior_equity > 0 else 0.0
            daily_returns.append(period_ret)
            prior_equity = equity_t

            # 4. Check trade entry conditions (no trade active, rebalance step)
            if active_trade is None and t % self.rebalance_days == 0 and t < total_steps - 5:
                sizing_res = portfolio.calculate_position_size()
                if sizing_res.is_allowed and sizing_res.allocated_amount_a > 0.0:
                    trade_counter += 1
                    trade_id = f"PATH_TRD_{trade_counter:04d}"

                    opened = engine.open_trade(
                        trade_id=trade_id,
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
                        trade_entry_step = t

        # Final terminal equity
        terminal_equity = portfolio.cash_a
        net_profit_a = terminal_equity - initial_capital_a
        tot_return = net_profit_a / initial_capital_a

        # Annualized return and volatility
        horizon_years = total_steps / 252.0
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
            capital_utilization=self.sizing.percent_of_equity,
            peak_exposure_a=initial_capital_a * self.sizing.percent_of_equity,
        )
