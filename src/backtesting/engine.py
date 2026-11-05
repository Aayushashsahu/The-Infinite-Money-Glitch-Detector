"""Master Backtesting Engine for Cross-Currency Strategies.

Coordinates:
- Historical Information Firewall (Point-in-Time Data Access)
- Strategy Signal Generation (Unhedged & Covered Carry)
- Capital & Position Accounting (Portfolio)
- Market Microstructure & Frictions (ExecutionEngine)
- Mark-to-Market Valuation & Snapshots
- Performance & Risk Analytics (PerformanceMetrics)
- Benchmarks & Auditing
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Sequence

from schemas.backtest import (
    AvailabilityPolicy,
    BacktestConfig,
    BacktestResult,
    TradeRecord,
    TradeStatus,
)
from schemas.strategy import CurrencyPair
from backtesting.benchmarks import (
    compute_borrowing_currency_benchmark,
    compute_investment_currency_benchmark,
)
from backtesting.execution import ExecutionEngine
from backtesting.metrics import calculate_performance_metrics
from backtesting.point_in_time import PointInTimeDataStore, PointInTimeFirewall
from backtesting.portfolio import Portfolio
from backtesting.signals import (
    CoveredCarrySignalGenerator,
    TradingSignal,
    UnhedgedCarrySignalGenerator,
)
from data.schemas import DataObservation, Frequency, ObservationKind


class BacktestEngine:
    """Master orchestrator for point-in-time cross-currency strategy backtests."""

    def __init__(
        self,
        config: BacktestConfig,
        observations: Sequence[DataObservation],
    ):
        self.config = config
        self.observations = list(observations)
        
        # Point-in-time firewall
        self.firewall = PointInTimeFirewall(config.availability_config)
        self.data_store = PointInTimeDataStore(self.observations, self.firewall)

        # Execution and Portfolio
        self.execution_engine = ExecutionEngine(config.execution_config)
        self.portfolio = Portfolio(
            initial_capital_a=config.initial_capital_a,
            sizing_config=config.position_sizing,
            execution_config=config.execution_config,
            cash_deposit_rate_annual=config.cash_deposit_rate_annual,
        )

        # Signal generators
        self.unhedged_generator = UnhedgedCarrySignalGenerator(
            hurdle_rate_annual=config.hurdle_rate_annual,
            max_fx_volatility=config.volatility_filter_max,
        )
        self.covered_generator = CoveredCarrySignalGenerator(
            hurdle_rate_annual=config.hurdle_rate_annual,
        )

        self._rejections: list[dict[str, Any]] = []
        self._data_quality_flags: list[dict[str, Any]] = []
        self._audit_trail: list[str] = []

    def run(self) -> BacktestResult:
        """Execute the historical backtest deterministically across the simulation window."""
        pair = self.config.currency_pair
        pair_code = f"{pair.borrowing_currency}/{pair.investment_currency}"
        is_covered_strategy = "covered" in self.config.strategy_name.lower()
        is_executable = True
        unsupported_reason: str | None = None

        # Check research-only mode status
        if self.config.availability_config.policy == AvailabilityPolicy.RESEARCH_ONLY:
            is_executable = False
            self._audit_trail.append(
                "WARNING: Backtest executed in RESEARCH_ONLY mode. "
                "Historical publication dates were ignored; results are retrospective and strictly unexecutable."
            )

        # Check covered strategy feasibility: check if actual forward rates exist in dataset
        if is_covered_strategy:
            forward_sample = self.data_store.get_forward_rate(
                pair_code=pair_code,
                tenor_days=self.config.tenor_days,
                as_of=self.config.end_date,
                allow_stale=True,
            )
            if forward_sample is None:
                is_executable = False
                unsupported_reason = (
                    "Covered carry trade strategy cannot be executed: "
                    "actual historical forward exchange rate quotes are unavailable. "
                    "Theoretical CIP calculations cannot be substituted as executable market quotes."
                )
                self._audit_trail.append(f"EXECUTION REJECTED: {unsupported_reason}")

        # Chronological daily simulation loop
        current_date = self.config.start_date
        next_rebalance_date = current_date
        trade_counter = 0

        # Benchmark tracking arrays
        bm_dates: list[date] = []
        bm_borrowing_rates: list[float] = []
        bm_investment_rates: list[float] = []
        bm_spot_rates: list[float] = []

        while current_date <= self.config.end_date:
            # Check FX calendar for active trading day
            from backtesting.calendar import DEFAULT_FX_CALENDAR
            is_active_trading_day = DEFAULT_FX_CALENDAR.is_trading_day(current_date)
            if self.config.simulate_trading_days_only and not is_active_trading_day:
                # On non-trading days, accrue unallocated cash interest if configured, but skip market steps
                self.portfolio.accrue_cash_interest(1, self.config.execution_config.interest_convention)
                current_date += timedelta(days=1)
                continue

            # Accrue interest on unencumbered portfolio cash balance
            self.portfolio.accrue_cash_interest(1, self.config.execution_config.interest_convention)

            # 1. Point-in-time market quote retrieval
            spot_mid = self.data_store.get_rate(pair_code, current_date)
            r_borrow = self.data_store.get_interest_rate(
                pair.borrowing_currency,
                current_date,
                indicator_id=self.config.borrowing_rate_series_id,
            )
            r_invest = self.data_store.get_interest_rate(
                pair.investment_currency,
                current_date,
                indicator_id=self.config.investment_rate_series_id,
            )
            fwd_mid = (
                self.data_store.get_forward_rate(pair_code, self.config.tenor_days, current_date)
                if is_covered_strategy
                else None
            )

            # Record benchmark tracking points when quotes are available
            if spot_mid is not None and r_borrow is not None and r_invest is not None:
                bm_dates.append(current_date)
                bm_spot_rates.append(spot_mid)
                bm_borrowing_rates.append(r_borrow)
                bm_investment_rates.append(r_invest)

            # 2. Check and close maturing positions
            for trade in self.portfolio.open_trades:
                trade_age_days = (current_date - trade.entry_date).days
                if trade_age_days >= trade.target_tenor_days:
                    # Time to close
                    if spot_mid is None:
                        # Stale / missing price on close: record rejection and defer until next quote
                        self._rejections.append({
                            "date": current_date.isoformat(),
                            "trade_id": trade.trade_id,
                            "action": "close",
                            "reason": f"Missing exit spot rate quote for {pair_code} at maturity date {current_date}",
                        })
                        continue

                    closed_trade = self.execution_engine.close_trade(
                        trade=trade,
                        exit_date=current_date,
                        spot_mid_exit=spot_mid,
                    )
                    self.portfolio.register_closed_trade(closed_trade)
                    self._audit_trail.append(
                        f"Trade {trade.trade_id} CLOSED on {current_date}: PnL = {closed_trade.net_profit_a:.2f} {pair.borrowing_currency} "
                        f"(RoC: {closed_trade.return_on_capital:.2%})"
                    )

            # 3. Mark to market snapshot
            current_rates = {pair_code: spot_mid} if spot_mid else {}
            self.portfolio.snapshot(as_of=current_date, current_spot_rates=current_rates)

            # 4. Signal generation & entry on rebalance schedule
            if current_date >= next_rebalance_date and is_executable:
                # Evaluate signal
                if is_covered_strategy:
                    tenor_years = self.config.tenor_days / 365.0
                    signal = self.covered_generator.generate_signal(
                        as_of=current_date,
                        pair=pair,
                        borrowing_rate=r_borrow,
                        investment_rate=r_invest,
                        spot_rate=spot_mid,
                        forward_rate=fwd_mid,
                        tenor_years=tenor_years,
                    )
                else:
                    signal = self.unhedged_generator.generate_signal(
                        as_of=current_date,
                        pair=pair,
                        borrowing_rate=r_borrow,
                        investment_rate=r_invest,
                        spot_rate=spot_mid,
                    )

                if signal.should_enter:
                    # Check position sizing and portfolio limits
                    sizing = self.portfolio.calculate_position_size()
                    if sizing.is_allowed:
                        trade_counter += 1
                        trade_id = f"TRD_{pair.borrowing_currency}_{pair.investment_currency}_{trade_counter:04d}"
                        
                        trade_rec = self.execution_engine.open_trade(
                            trade_id=trade_id,
                            strategy_name=self.config.strategy_name,
                            currency_pair=pair,
                            entry_date=current_date,
                            tenor_days=self.config.tenor_days,
                            principal_borrowed_a=sizing.allocated_amount_a,
                            borrowing_rate=signal.borrowing_rate,
                            investment_rate=signal.investment_rate,
                            spot_mid_entry=signal.spot_rate,
                            forward_mid=signal.forward_rate,
                            is_covered=is_covered_strategy,
                            is_verified_availability=(
                                self.config.availability_config.policy == AvailabilityPolicy.STRICT
                            ),
                        )
                        if self.portfolio.register_open_trade(trade_rec):
                            self._audit_trail.append(
                                f"Trade {trade_id} OPENED on {current_date}: Borrowed {sizing.allocated_amount_a:,.2f} {pair.borrowing_currency} "
                                f"at {signal.borrowing_rate:.2%}, Invested in {pair.investment_currency} at {signal.investment_rate:.2%}, "
                                f"Spot = {trade_rec.spot_exec_entry:.4f}"
                            )
                        else:
                            self._rejections.append({
                                "date": current_date.isoformat(),
                                "action": "open",
                                "reason": trade_rec.rejection_reason or "Portfolio registration rejected",
                            })
                    else:
                        self._rejections.append({
                            "date": current_date.isoformat(),
                            "action": "open",
                            "reason": sizing.rejection_reason,
                        })
                elif signal.rejection_reason:
                    self._rejections.append({
                        "date": current_date.isoformat(),
                        "action": "signal",
                        "reason": signal.rejection_reason,
                    })

                next_rebalance_date = current_date + timedelta(days=self.config.rebalance_frequency_days)

            current_date += timedelta(days=1)

        # 5. At simulation end: close any remaining open positions at latest spot rate
        final_spot = self.data_store.get_rate(pair_code, self.config.end_date, allow_stale=True)
        for trade in list(self.portfolio.open_trades):
            if final_spot:
                closed = self.execution_engine.close_trade(
                    trade=trade,
                    exit_date=self.config.end_date,
                    spot_mid_exit=final_spot,
                )
                self.portfolio.register_closed_trade(closed)
                self._audit_trail.append(
                    f"Simulation End: Trade {trade.trade_id} liquidated on {self.config.end_date} at {final_spot:.4f}"
                )

        # 6. Generate comparative benchmark (distinguishing cash deposit/risk-free rate from borrowing rate)
        benchmark_series = None
        if len(bm_dates) >= 2:
            try:
                if self.config.cash_deposit_rate_annual > 0:
                    cash_bm_rates = [self.config.cash_deposit_rate_annual] * len(bm_dates)
                    benchmark_series = compute_borrowing_currency_benchmark(
                        dates=bm_dates,
                        borrowing_rates=cash_bm_rates,
                        interest_convention=self.config.execution_config.interest_convention,
                    )
                else:
                    benchmark_series = compute_borrowing_currency_benchmark(
                        dates=bm_dates,
                        borrowing_rates=bm_borrowing_rates,
                        interest_convention=self.config.execution_config.interest_convention,
                    )
            except Exception as e:
                self._audit_trail.append(f"Benchmark calculation error: {e}")

        # 7. Compute final performance metrics with return attribution
        all_trades = self.portfolio.closed_trades + self.portfolio.rejected_trades
        risk_free_ref = (
            self.config.cash_deposit_rate_annual
            if self.config.cash_deposit_rate_annual > 0
            else (bm_borrowing_rates[-1] if bm_borrowing_rates else 0.0)
        )
        periods_factor = 252.0 if self.config.simulate_trading_days_only else 365.0

        metrics = calculate_performance_metrics(
            trades=all_trades,
            snapshots=self.portfolio.snapshots,
            initial_capital_a=self.config.initial_capital_a,
            risk_free_rate_annual=risk_free_ref,
            benchmark=benchmark_series,
            interest_convention=self.config.execution_config.interest_convention,
            periods_per_year=periods_factor,
            cash_interest_earned=self.portfolio.total_cash_interest_earned,
        )

        # 8. Data Provenance & Traceability Report
        from backtesting.provenance import build_data_provenance_report
        provenance = build_data_provenance_report(
            observations=self.observations,
            start_date=self.config.start_date,
            end_date=self.config.end_date,
            currency_pair_code=pair_code,
            policy=self.config.availability_config.policy,
        )

        return BacktestResult(
            config=self.config,
            trades=all_trades,
            snapshots=self.portfolio.snapshots,
            metrics=metrics,
            provenance=provenance,
            rejections=self._rejections,
            data_quality_flags=self._data_quality_flags,
            audit_trail=self._audit_trail,
            is_executable_strategy=is_executable,
            unsupported_reason=unsupported_reason,
        )
