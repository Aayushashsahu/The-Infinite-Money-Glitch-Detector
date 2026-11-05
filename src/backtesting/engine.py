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

import hashlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from schemas.backtest import (
    AvailabilityPolicy,
    BacktestConfig,
    BacktestResult,
    BenchmarkSpecification,
    BenchmarkType,
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
from data.schemas import DataObservation, Frequency, ObservationKind, RateRole, StrategyExecutabilityStatus


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
        can_simulate = True
        unsupported_reason: str | None = None

        # Determine initial executability classification
        strategy_status = StrategyExecutabilityStatus.EXECUTABLE_VALIDATED
        PROXY_SERIES = {
            "DGS3MO", "DGS1MO", "DGS6MO", "DGS1YR",
            "KR.DFR.LEV", "KR.MRR_FR.LEV", "DFEDTARU", "FEDFUNDS",
        }
        if self.config.availability_config.policy == AvailabilityPolicy.RESEARCH_ONLY:
            is_executable = False
            strategy_status = StrategyExecutabilityStatus.RESEARCH_ONLY
            self._audit_trail.append(
                "WARNING: Backtest executed in RESEARCH_ONLY mode. "
                "Historical publication dates were ignored; results are retrospective and strictly unexecutable."
            )
        elif self.config.borrowing_rate_series_id in PROXY_SERIES or \
             self.config.investment_rate_series_id in PROXY_SERIES:
            strategy_status = StrategyExecutabilityStatus.RESEARCH_PROXY
            self._audit_trail.append(
                "RESEARCH PROXY: Strategy uses sovereign Treasury yields or central bank policy rates "
                "rather than commercial bank borrowing/deposit rates. Classified as RESEARCH_PROXY."
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
                can_simulate = False
                is_executable = False
                strategy_status = StrategyExecutabilityStatus.UNEXECUTABLE
                unsupported_reason = (
                    "Covered carry trade strategy cannot be executed: "
                    "actual historical forward exchange rate quotes are unavailable. "
                    "Theoretical CIP calculations cannot be substituted as executable market quotes."
                )
                self._audit_trail.append(f"EXECUTION REJECTED: {unsupported_reason}")

        # Check dataset feasibility: dataset must contain observations and spot exchange rates for the pair
        if len(self.observations) == 0:
            can_simulate = False
            is_executable = False
            strategy_status = StrategyExecutabilityStatus.UNEXECUTABLE
            unsupported_reason = f"No historical market observations provided for backtest {pair_code}."
            self._audit_trail.append(f"EXECUTION REJECTED: {unsupported_reason}")
        else:
            inv_code = None
            if "/" in pair_code:
                b, q = pair_code.split("/", 1)
                inv_code = f"{q}/{b}"
            has_pair_data = any(
                obs.kind == ObservationKind.EXCHANGE_RATE and (obs.entity_code == pair_code or obs.entity_code == inv_code)
                for obs in self.observations
            )
            if not has_pair_data:
                can_simulate = False
                is_executable = False
                strategy_status = StrategyExecutabilityStatus.UNEXECUTABLE
                unsupported_reason = f"Unsupported currency pair {pair_code}: no spot exchange rate observations available in dataset."
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

        while can_simulate and current_date <= self.config.end_date:
            # Check FX calendar for active trading day
            from backtesting.calendar import DEFAULT_FX_CALENDAR
            is_active_trading_day = DEFAULT_FX_CALENDAR.is_trading_day(current_date)
            if not is_active_trading_day:
                # Markets closed: no trade entry, no trade exit. Defer maturities to next active trading day.
                self.portfolio.accrue_cash_interest(1, self.config.execution_config.interest_convention)
                if not self.config.simulate_trading_days_only:
                    self.portfolio.snapshot(as_of=current_date, current_spot_rates={})
                current_date += timedelta(days=1)
                continue

            # Accrue interest on unencumbered portfolio cash balance
            self.portfolio.accrue_cash_interest(1, self.config.execution_config.interest_convention)

            # 1. Timestamp-aware simulation clock for signal evaluation
            sig_hour, sig_minute = self.config.signal_time_utc
            signal_timestamp = datetime(
                current_date.year, current_date.month, current_date.day,
                sig_hour, sig_minute, tzinfo=timezone.utc,
            )

            # Point-in-time market quote retrieval using timestamp
            spot_mid = self.data_store.get_rate(pair_code, as_of=signal_timestamp)
            record_borrow = self.data_store.get_record(
                ObservationKind.INTEREST_RATE,
                pair.borrowing_currency,
                as_of=signal_timestamp,
                indicator_id=self.config.borrowing_rate_series_id,
            )
            r_borrow = self.data_store.get_interest_rate(
                pair.borrowing_currency,
                as_of=signal_timestamp,
                indicator_id=self.config.borrowing_rate_series_id,
            )
            record_invest = self.data_store.get_record(
                ObservationKind.INTEREST_RATE,
                pair.investment_currency,
                as_of=signal_timestamp,
                indicator_id=self.config.investment_rate_series_id,
            )
            r_invest = self.data_store.get_interest_rate(
                pair.investment_currency,
                as_of=signal_timestamp,
                indicator_id=self.config.investment_rate_series_id,
            )
            fwd_mid = (
                self.data_store.get_forward_rate(pair_code, self.config.tenor_days, as_of=signal_timestamp)
                if is_covered_strategy
                else None
            )

            # Dynamic rate-role enforcement
            if record_borrow is not None and record_borrow.observation.rate_role is not None:
                if record_borrow.observation.rate_role in (RateRole.POLICY_RATE, RateRole.RISK_FREE_RATE):
                    if self.config.require_commercial_rates:
                        can_simulate = False
                        is_executable = False
                        strategy_status = StrategyExecutabilityStatus.UNEXECUTABLE
                        unsupported_reason = (
                            f"Commercial borrowing rate required, but {record_borrow.observation.indicator_id} "
                            f"has economic role {record_borrow.observation.rate_role.value}."
                        )
                    elif strategy_status == StrategyExecutabilityStatus.EXECUTABLE_VALIDATED:
                        strategy_status = StrategyExecutabilityStatus.RESEARCH_PROXY

            if record_invest is not None and record_invest.observation.rate_role is not None:
                if record_invest.observation.rate_role in (RateRole.POLICY_RATE, RateRole.RISK_FREE_RATE):
                    if strategy_status == StrategyExecutabilityStatus.EXECUTABLE_VALIDATED:
                        strategy_status = StrategyExecutabilityStatus.RESEARCH_PROXY

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
            if current_date >= next_rebalance_date and can_simulate:
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
                        
                        order_sub_ts = signal_timestamp + timedelta(seconds=1)
                        if self.config.execution_session == "next_session_open":
                            next_td = DEFAULT_FX_CALENDAR.next_trading_day(current_date)
                            exec_ts = datetime(next_td.year, next_td.month, next_td.day, 9, 0, tzinfo=timezone.utc)
                            trade_entry_date = next_td
                        else:
                            exec_ts = signal_timestamp + timedelta(minutes=self.config.execution_delay_minutes)
                            trade_entry_date = current_date

                        # Obtain eligible price associated with execution time or next session open
                        exec_spot = self.data_store.get_rate(pair_code, as_of=exec_ts)
                        if exec_spot is not None:
                            spot_entry = exec_spot
                            price_source = "execution_timestamp_market"
                        else:
                            spot_entry = signal.spot_rate
                            price_source = "signal_time_research_proxy"

                        # T+2 FX settlement strictly on business/trading days
                        settle_date = DEFAULT_FX_CALENDAR.add_trading_days(trade_entry_date, 2)
                        settle_ts = datetime(settle_date.year, settle_date.month, settle_date.day, exec_ts.hour, exec_ts.minute, tzinfo=timezone.utc)

                        trade_rec = self.execution_engine.open_trade(
                            trade_id=trade_id,
                            strategy_name=self.config.strategy_name,
                            currency_pair=pair,
                            entry_date=trade_entry_date,
                            tenor_days=self.config.tenor_days,
                            principal_borrowed_a=sizing.allocated_amount_a,
                            borrowing_rate=signal.borrowing_rate,
                            investment_rate=signal.investment_rate,
                            spot_mid_entry=spot_entry,
                            forward_mid=signal.forward_rate,
                            is_covered=is_covered_strategy,
                            is_verified_availability=(
                                self.config.availability_config.policy == AvailabilityPolicy.STRICT
                            ),
                            signal_timestamp=signal_timestamp,
                            order_submission_timestamp=order_sub_ts,
                            execution_timestamp=exec_ts,
                            settlement_timestamp=settle_ts,
                        )
                        if trade_rec.metadata is None:
                            trade_rec.metadata = {}
                        trade_rec.metadata["price_source"] = price_source
                        trade_rec.metadata["settlement_convention"] = "T+2_business_days"
                        if self.portfolio.register_open_trade(trade_rec):
                            self._audit_trail.append(
                                f"Trade {trade_id} OPENED on {trade_entry_date} (exec {exec_ts.isoformat()}): "
                                f"Borrowed {sizing.allocated_amount_a:,.2f} {pair.borrowing_currency} "
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
        final_sig_ts = datetime(
            self.config.end_date.year, self.config.end_date.month, self.config.end_date.day,
            self.config.signal_time_utc[0], self.config.signal_time_utc[1], tzinfo=timezone.utc,
        )
        final_spot = self.data_store.get_rate(pair_code, as_of=final_sig_ts, allow_stale=True)
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

        # 6. Generate comparative benchmark
        benchmark_series = None
        bm_spec = self.config.benchmark_spec
        if len(bm_dates) >= 2 and bm_spec is not None:
            try:
                if bm_spec.benchmark_type == BenchmarkType.ZERO_CASH:
                    cash_bm_rates = [0.0] * len(bm_dates)
                    benchmark_series = compute_borrowing_currency_benchmark(
                        dates=bm_dates,
                        borrowing_rates=cash_bm_rates,
                        interest_convention=self.config.execution_config.interest_convention,
                    )
                elif bm_spec.benchmark_type == BenchmarkType.FIXED_HYPOTHETICAL_PROXY:
                    rate = bm_spec.fixed_rate_annual or self.config.cash_deposit_rate_annual
                    cash_bm_rates = [rate] * len(bm_dates)
                    benchmark_series = compute_borrowing_currency_benchmark(
                        dates=bm_dates,
                        borrowing_rates=cash_bm_rates,
                        interest_convention=self.config.execution_config.interest_convention,
                    )
                elif bm_spec.benchmark_type == BenchmarkType.HISTORICAL_RISK_FREE:
                    rf_rates: list[float] = []
                    for d in bm_dates:
                        ts = datetime(d.year, d.month, d.day, self.config.signal_time_utc[0], self.config.signal_time_utc[1], tzinfo=timezone.utc)
                        r = self.data_store.get_interest_rate(
                            pair.borrowing_currency,
                            as_of=ts,
                            indicator_id=bm_spec.series_id,
                            rate_role=RateRole.RISK_FREE_RATE,
                        )
                        if r is not None:
                            rf_rates.append(r)
                        elif rf_rates:
                            rf_rates.append(rf_rates[-1])
                        else:
                            rf_rates.append(0.0)
                    benchmark_series = compute_borrowing_currency_benchmark(
                        dates=bm_dates,
                        borrowing_rates=rf_rates,
                        interest_convention=self.config.execution_config.interest_convention,
                    )
                elif bm_spec.benchmark_type == BenchmarkType.HISTORICAL_DEPOSIT:
                    dep_rates: list[float] = []
                    is_missing = False
                    for d in bm_dates:
                        ts = datetime(d.year, d.month, d.day, self.config.signal_time_utc[0], self.config.signal_time_utc[1], tzinfo=timezone.utc)
                        r = self.data_store.get_interest_rate(
                            pair.borrowing_currency,
                            as_of=ts,
                            rate_role=RateRole.DEPOSIT_RATE,
                        )
                        if r is not None:
                            dep_rates.append(r)
                        elif dep_rates:
                            dep_rates.append(dep_rates[-1])
                        else:
                            is_missing = True
                            break
                    if is_missing or not dep_rates:
                        benchmark_series = None
                        self._audit_trail.append("BENCHMARK UNAVAILABLE: Historical deposit rate series missing from dataset.")
                    else:
                        benchmark_series = compute_borrowing_currency_benchmark(
                            dates=bm_dates,
                            borrowing_rates=dep_rates,
                            interest_convention=self.config.execution_config.interest_convention,
                        )
                elif bm_spec.benchmark_type == BenchmarkType.UNAVAILABLE:
                    benchmark_series = None
            except Exception as e:
                self._audit_trail.append(f"Benchmark calculation error: {e}")

        # 7. Compute final performance metrics with return attribution
        all_trades = self.portfolio.closed_trades + self.portfolio.rejected_trades
        risk_free_ref = 0.0
        if bm_spec and bm_spec.benchmark_type == BenchmarkType.FIXED_HYPOTHETICAL_PROXY:
            risk_free_ref = bm_spec.fixed_rate_annual or self.config.cash_deposit_rate_annual
        elif bm_spec and bm_spec.benchmark_type == BenchmarkType.ZERO_CASH:
            risk_free_ref = 0.0
        elif bm_borrowing_rates:
            risk_free_ref = bm_borrowing_rates[-1]

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
        if bm_spec:
            metrics.benchmark_name = bm_spec.name

        # Check if 0 trades executed or unexecutable
        if len(self.portfolio.closed_trades) == 0:
            if is_covered_strategy and forward_sample is None:
                strategy_status = StrategyExecutabilityStatus.UNEXECUTABLE
            elif not can_simulate:
                strategy_status = StrategyExecutabilityStatus.UNEXECUTABLE
            elif strategy_status == StrategyExecutabilityStatus.EXECUTABLE_VALIDATED:
                strategy_status = StrategyExecutabilityStatus.NO_TRADES
        elif is_covered_strategy and forward_sample is None:
            strategy_status = StrategyExecutabilityStatus.UNEXECUTABLE

        # If any trade used signal_time_research_proxy, downgrade EXECUTABLE_VALIDATED to RESEARCH_PROXY
        if any(t.metadata.get("price_source") == "signal_time_research_proxy" for t in self.portfolio.closed_trades):
            if strategy_status == StrategyExecutabilityStatus.EXECUTABLE_VALIDATED:
                strategy_status = StrategyExecutabilityStatus.RESEARCH_PROXY
                self._audit_trail.append(
                    "RESEARCH PROXY: Daily fixing rate proxy used for execution timing. Classified as RESEARCH_PROXY."
                )

        # Enforce executability boolean:
        # If strategy_status is not EXECUTABLE_VALIDATED, is_executable MUST be False!
        if strategy_status in (
            StrategyExecutabilityStatus.RESEARCH_PROXY,
            StrategyExecutabilityStatus.RESEARCH_ONLY,
            StrategyExecutabilityStatus.UNEXECUTABLE,
            StrategyExecutabilityStatus.NO_TRADES,
        ):
            is_executable = False

        can_sim = can_simulate and (strategy_status != StrategyExecutabilityStatus.UNEXECUTABLE) and len(self.observations) > 0
        is_pit = (self.config.availability_config.policy != AvailabilityPolicy.RESEARCH_ONLY)
        is_econ = (strategy_status == StrategyExecutabilityStatus.EXECUTABLE_VALIDATED)

        # Manifest digest
        manifest_digest: str | None = None
        manifest_file = Path("data/manifest.json")
        if manifest_file.exists():
            manifest_digest = hashlib.sha256(manifest_file.read_bytes()).hexdigest()

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
            strategy_status=strategy_status,
            manifest_digest=manifest_digest,
            can_simulate=can_sim,
            is_point_in_time_credible=is_pit,
            is_economically_representative=is_econ,
            is_executable_strategy=is_executable,
            unsupported_reason=unsupported_reason,
        )
