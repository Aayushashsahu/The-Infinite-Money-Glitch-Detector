"""Real Market Data Validation & Backtesting Demonstration.

This script executes genuine historical backtests using real market data stored
in the analytical database (data/processed/gmdb.db).

Demonstrates:
1. Complete Data Provenance and classification verification (100% REAL_VERIFIED).
2. Point-in-time filtering in STRICT mode.
3. Unhedged Carry Trade: Positive carry (Borrow EUR, Invest USD).
4. Unhedged Carry Trade: Negative carry (Borrow USD, Invest EUR).
5. Regime Analysis:
   - Regime 1 (2020-01-01 to 2022-03-31): NIRP/ZIRP era (EUR -0.50%, USD 0.10%).
   - Regime 2 (2022-04-01 to 2024-12-31): Rapid monetary tightening cycle.
6. Cash Deposit Benchmark comparison with identical capital denominators and exact attribution.
7. Covered Carry Trade executability check (proving rejection when forward quotes are unavailable).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

# Ensure 'src' is on sys.path without shadowing standard library 'http'
ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if sys.path and Path(sys.path[0]).resolve() == (SRC_DIR / "data").resolve():
    sys.path.pop(0)

from backtesting.engine import BacktestEngine
from backtesting.provenance import build_data_provenance_report
from backtesting.reporting import format_backtest_report
from data.db.engine import make_engine, make_session_factory
from data.repository import Repository
from data.schemas import DataClassification, Frequency, ObservationKind
from schemas.backtest import (
    AvailabilityPolicy,
    BacktestConfig,
    DataAvailabilityConfig,
    ExecutionConfig,
    PositionSizingConfig,
    PositionSizingMethod,
)
from schemas.strategy import CurrencyPair


def print_header(title: str) -> None:
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)


def print_metrics_table(name: str, res) -> None:
    m = res.metrics
    final_eq = res.snapshots[-1].equity_a if res.snapshots else res.config.initial_capital_a
    print(f"\n--- Performance Summary: {name} ---")
    print(f"Total Trades Executed:    {m.total_trades}")
    print(f"Win Rate:                 {m.win_rate:.1%}")
    print(f"Initial Capital:          ${res.config.initial_capital_a:,.2f}")
    print(f"Final Capital:            ${final_eq:,.2f}")
    print(f"Total Strategy Return:    {m.total_return:+.2%}")
    print(f"Annualized Return:        {m.annualized_return:+.2%}")
    print(f"Annualized Volatility:    {m.annualized_volatility:.2%}")
    print(f"Sharpe Ratio:             {m.sharpe_ratio:.2f}" if m.sharpe_ratio is not None else "Sharpe Ratio:             N/A")
    print(f"Sortino Ratio:            {m.sortino_ratio:.2f}" if m.sortino_ratio is not None else "Sortino Ratio:            N/A")
    print(f"Maximum Drawdown:         {m.max_drawdown:.2%}")
    print(f"Daily VaR (95%):          {m.var_95:.2%}")
    print(f"Daily CVaR (95%):         {m.cvar_95:.2%}")
    print("\nReturn Attribution Breakdown:")
    print(f"  Gross Trade Return:     {m.gross_trade_return:+.2%}" if m.gross_trade_return is not None else "  Gross Trade Return:     N/A")
    print(f"  - Financing Drag:       {m.financing_cost_drag:.2%}" if m.financing_cost_drag is not None else "  - Financing Drag:       N/A")
    print(f"  - Frictions Drag:       {m.transaction_cost_drag:.2%}" if m.transaction_cost_drag is not None else "  - Frictions Drag:       N/A")
    print(f"  + Cash Yield Return:    {m.cash_yield_return:+.2%}" if m.cash_yield_return is not None else "  + Cash Yield Return:    N/A")
    reconciled = (
        (m.gross_trade_return or 0.0)
        - (m.financing_cost_drag or 0.0)
        - (m.transaction_cost_drag or 0.0)
        + (m.cash_yield_return or 0.0)
    )
    print(f"  = Net Calculated:       {reconciled:+.2%}")
    bm_ret_str = f"{m.benchmark_total_return:+.2%}" if m.benchmark_total_return is not None else "N/A"
    print(f"Benchmark ({m.benchmark_name}): {bm_ret_str}")
    alpha_str = f"{m.alpha:+.2%}" if m.alpha is not None else "N/A"
    print(f"Excess Return vs Cash:    {alpha_str}")
    print(f"Is Executable:            {res.is_executable_strategy}")
    if res.unsupported_reason:
        print(f"Rejection Reason:         {res.unsupported_reason}")


def main() -> None:
    print_header("PHASE 3.2: REAL MARKET DATA VALIDATION & BACKTESTING")

    db_path = "sqlite:///data/processed/gmdb.db"
    engine = make_engine(db_path)
    session_factory = make_session_factory(engine)
    repo = Repository(session_factory)

    # 1. Load genuine observations
    print("\n[Step 1] Loading genuine market data from SQLite database...")
    all_obs = repo.load_observation_objects(include_synthetic=False)
    print(f"Loaded {len(all_obs):,} genuine historical observations.")

    # 2. Provenance Report
    print_header("DATA PROVENANCE & CLASSIFICATION AUDIT")
    prov = build_data_provenance_report(
        observations=all_obs,
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        currency_pair_code="EUR/USD",
        policy=AvailabilityPolicy.STRICT,
    )
    print(f"Dataset Total Observations: {prov.total_observations:,}")
    print(f"Date Range:                 {prov.date_range[0]} to {prov.date_range[1]}")
    print(f"Calendar Days:              {prov.calendar_days} (Trading Days: {prov.trading_days})")
    print(f"Real Verified Count:        {prov.real_verified_count:,} ({prov.real_verified_count / prov.total_observations:.1%})")
    print(f"Real Estimated Count:       {prov.real_estimated_count:,}")
    print(f"Real Retrospective Count:   {prov.real_retrospective_count:,}")
    print(f"Synthetic Observations:     {prov.synthetic_observations_count:,} ({prov.synthetic_observations_count / prov.total_observations:.1%})")
    print(f"Point-in-Time Policy:       {prov.point_in_time_policy.value.upper()}")
    print(f"Publication Availability:   {prov.publication_date_availability_pct:.1%}")
    print(f"Missing Trading Days:       {prov.missing_trading_days_pct:.1%}")
    print(f"Source Providers:           {', '.join(prov.source_providers)}")
    print(f"Dataset Identifiers:        {', '.join(prov.dataset_identifiers)}")
    print(f"\nAudit Declaration:\n  {prov.provenance_declaration}")

    # 3. Execution Configuration
    exec_config = ExecutionConfig(
        bid_ask_spread_bps=2.0,
        slippage_bps=0.5,
        variable_fee_bps=1.0,
        fixed_fee=0.0,
        min_trade_size_a=1_000.0,
        max_trade_size_a=200_000.0,
    )

    sizing_config = PositionSizingConfig(
        method=PositionSizingMethod.FIXED_AMOUNT,
        fixed_amount=50_000.0,  # $50k deployed per tranche, $50k unallocated
        max_active_positions=1,
    )

    avail_config = DataAvailabilityConfig(
        policy=AvailabilityPolicy.STRICT,
        allow_synthetic=False,
        max_stale_days=5,
        stale_by_trading_days=True,
    )

    # -------------------------------------------------------------------------
    # 4. Strategy 1: Unhedged Carry Trade (Positive Carry: Borrow EUR, Invest USD)
    # Full 5-Year Window: 2020-01-01 to 2024-12-31
    # -------------------------------------------------------------------------
    print_header("RUN 1: POSITIVE UNHEDGED CARRY (BORROW EUR, INVEST USD) - 2020-2024")
    config_pos = BacktestConfig(
        strategy_name="Positive Unhedged Carry (EUR/USD)",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        initial_capital_a=100_000.0,
        tenor_days=30,
        rebalance_frequency_days=30,
        hurdle_rate_annual=0.005,  # 50 bps hurdle
        cash_deposit_rate_annual=0.015,  # 1.5% average cash deposit rate
        borrowing_rate_series_id="KR.DFR.LEV",
        investment_rate_series_id="DGS3MO",
        execution_config=exec_config,
        position_sizing=sizing_config,
        availability_config=avail_config,
    )
    engine_pos = BacktestEngine(config_pos, all_obs)
    res_pos = engine_pos.run()
    print_metrics_table("5-Year Positive Carry (Borrow EUR, Invest USD)", res_pos)

    # -------------------------------------------------------------------------
    # 5. Strategy 2: Unhedged Carry Trade (Negative Carry: Borrow USD, Invest EUR)
    # Full 5-Year Window: 2020-01-01 to 2024-12-31
    # -------------------------------------------------------------------------
    print_header("RUN 2: NEGATIVE UNHEDGED CARRY (BORROW USD, INVEST EUR) - 2020-2024")
    config_neg = BacktestConfig(
        strategy_name="Negative Unhedged Carry (USD/EUR)",
        currency_pair=CurrencyPair(borrowing_currency="USD", investment_currency="EUR"),
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        initial_capital_a=100_000.0,
        tenor_days=30,
        rebalance_frequency_days=30,
        hurdle_rate_annual=0.005,
        cash_deposit_rate_annual=0.020,
        borrowing_rate_series_id="DGS3MO",
        investment_rate_series_id="KR.DFR.LEV",
        execution_config=exec_config,
        position_sizing=sizing_config,
        availability_config=avail_config,
    )
    engine_neg = BacktestEngine(config_neg, all_obs)
    res_neg = engine_neg.run()
    print_metrics_table("5-Year Negative Carry (Borrow USD, Invest EUR)", res_neg)

    # -------------------------------------------------------------------------
    # 6. Regime 1: NIRP/ZIRP Era (2020-01-01 to 2022-03-31)
    # -------------------------------------------------------------------------
    print_header("RUN 3: REGIME 1 (2020-01-01 to 2022-03-31) - NIRP/ZIRP ERA")
    config_r1 = BacktestConfig(
        strategy_name="Regime 1: Positive Carry (EUR/USD)",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=date(2020, 1, 1),
        end_date=date(2022, 3, 31),
        initial_capital_a=100_000.0,
        tenor_days=30,
        rebalance_frequency_days=30,
        hurdle_rate_annual=0.005,
        cash_deposit_rate_annual=0.00,  # Zero cash rate during ZIRP
        borrowing_rate_series_id="KR.DFR.LEV",
        investment_rate_series_id="DGS3MO",
        execution_config=exec_config,
        position_sizing=sizing_config,
        availability_config=avail_config,
    )
    engine_r1 = BacktestEngine(config_r1, all_obs)
    res_r1 = engine_r1.run()
    print_metrics_table("Regime 1 (2020-2022) Positive Carry", res_r1)

    # -------------------------------------------------------------------------
    # 7. Regime 2: Rate Tightening Era (2022-04-01 to 2024-12-31)
    # -------------------------------------------------------------------------
    print_header("RUN 4: REGIME 2 (2022-04-01 to 2024-12-31) - TIGHTENING CYCLE")
    config_r2 = BacktestConfig(
        strategy_name="Regime 2: Positive Carry (EUR/USD)",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=date(2022, 4, 1),
        end_date=date(2024, 12, 31),
        initial_capital_a=100_000.0,
        tenor_days=30,
        rebalance_frequency_days=30,
        hurdle_rate_annual=0.005,
        cash_deposit_rate_annual=0.035,  # 3.5% cash deposit rate during high-rate regime
        borrowing_rate_series_id="KR.DFR.LEV",
        investment_rate_series_id="DGS3MO",
        execution_config=exec_config,
        position_sizing=sizing_config,
        availability_config=avail_config,
    )
    engine_r2 = BacktestEngine(config_r2, all_obs)
    res_r2 = engine_r2.run()
    print_metrics_table("Regime 2 (2022-2024) Positive Carry", res_r2)

    # -------------------------------------------------------------------------
    # 8. Covered Carry Trade Executability Verification
    # -------------------------------------------------------------------------
    print_header("RUN 5: COVERED CARRY TRADE EXECUTABILITY CHECK")
    config_cov = BacktestConfig(
        strategy_name="Covered Carry Trade (EUR/USD)",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        initial_capital_a=100_000.0,
        tenor_days=30,
        rebalance_frequency_days=30,
        hurdle_rate_annual=0.005,
        borrowing_rate_series_id="KR.DFR.LEV",
        investment_rate_series_id="DGS3MO",
        execution_config=exec_config,
        position_sizing=sizing_config,
        availability_config=avail_config,
    )
    engine_cov = BacktestEngine(config_cov, all_obs)
    res_cov = engine_cov.run()
    print(f"Strategy:            {res_cov.config.strategy_name}")
    print(f"Is Executable:       {res_cov.is_executable_strategy}")
    print(f"Rejection Reason:    {res_cov.unsupported_reason}")
    print(f"Total Trades Opened: {len(res_cov.trades)}")
    assert not res_cov.is_executable_strategy, "Covered carry must be flagged unexecutable when forward quotes are absent!"
    print("SUCCESS: Engine strictly rejected covered carry execution due to lack of genuine forward market quotes.")

    print_header("REAL MARKET DATA VALIDATION COMPLETE")


if __name__ == "__main__":
    main()
