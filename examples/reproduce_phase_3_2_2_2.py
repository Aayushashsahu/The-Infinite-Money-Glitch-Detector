"""Phase 3.2.2.2 Historical Reproduction & Quantitative Validation Runner.

Executes the full 2020-2024 USD/EUR experiment across 6 required configurations:
1. Configuration 1: Strict Verified Point-in-Time (Strict firewall enforcing EXACT_TIMESTAMP_VERIFIED)
2. Configuration 2: Estimated-Availability Reference-Rate Research (Daily reference rate proxy allowed)
3. Configuration 3: Strict Executable Quotes Enforcement (Rejection of daily reference rates as executable quotes)
4. Configuration 4: Currency-Matched Benchmark (EUR Fixed Deposit Proxy, matching EUR borrowing)
5. Configuration 5: Currency-Mismatched Benchmark (USD Treasury DGS3MO vs EUR borrowing currency)
6. Configuration 6: Covered Carry Trade Rejection (Rejection due to absence of genuine forward quotes)

Exports machine-generated JSON result objects to data/results/phase_3_2_2_2/ and outputs
the exact double-entry accounting reconciliation table.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
import sys

# Ensure src is on path
ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from backtesting.engine import BacktestEngine
from backtesting.reporting import export_backtest_result_json, format_backtest_report
from data.db.engine import make_engine, make_session_factory
from data.repository import Repository
from schemas.backtest import (
    AvailabilityPolicy,
    BacktestConfig,
    BenchmarkSpecification,
    BenchmarkType,
    DataAvailabilityConfig,
    ExecutionConfig,
    PositionSizingConfig,
    PositionSizingMethod,
)
from schemas.strategy import CurrencyPair


def run_experiments():
    db_path = "sqlite:///data/processed/gmdb.db"
    engine = make_engine(db_path)
    session_factory = make_session_factory(engine)
    repo = Repository(session_factory)
    all_obs = repo.load_observation_objects(include_synthetic=False)

    out_dir = Path("data/results/phase_3_2_2_2")
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {}

    default_exec_config = ExecutionConfig(
        bid_ask_spread_bps=2.0,
        slippage_bps=0.5,
        variable_fee_bps=1.0,
        fixed_fee=0.0,
        min_trade_size_a=1_000.0,
        max_trade_size_a=200_000.0,
        max_quote_age_minutes=1440.0,
        allow_reference_rate_proxy=True,
    )

    sizing_config = PositionSizingConfig(
        method=PositionSizingMethod.FIXED_AMOUNT,
        fixed_amount=50_000.0,
        max_active_positions=1,
    )

    # -------------------------------------------------------------------------
    # 1. Configuration 1: Strict Verified Point-in-Time
    # -------------------------------------------------------------------------
    print("Running Configuration 1: Strict Verified Point-in-Time...")
    cfg_1 = BacktestConfig(
        strategy_name="Config 1: Strict Verified Point-in-Time",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        initial_capital_a=100_000.0,
        tenor_days=30,
        rebalance_frequency_days=30,
        hurdle_rate_annual=0.005,
        borrowing_rate_series_id="KR.DFR.LEV",
        investment_rate_series_id="DGS3MO",
        execution_config=default_exec_config,
        position_sizing=sizing_config,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=False),
        benchmark_spec=BenchmarkSpecification(benchmark_type=BenchmarkType.ZERO_CASH, name="Zero Cash (0.0%)"),
    )
    res_1 = BacktestEngine(cfg_1, all_obs).run()
    results["config_1"] = export_backtest_result_json(res_1, out_dir / "config_1_strict_pit.json")

    # -------------------------------------------------------------------------
    # 2. Configuration 2: Estimated-Availability Reference-Rate Research
    # -------------------------------------------------------------------------
    print("Running Configuration 2: Estimated-Availability Reference-Rate Research...")
    cfg_2 = BacktestConfig(
        strategy_name="Config 2: Estimated-Availability Reference-Rate Research",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        initial_capital_a=100_000.0,
        tenor_days=30,
        rebalance_frequency_days=30,
        hurdle_rate_annual=0.005,
        cash_deposit_rate_annual=0.015,
        borrowing_rate_series_id="KR.DFR.LEV",
        investment_rate_series_id="DGS3MO",
        execution_config=default_exec_config,
        position_sizing=sizing_config,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.ESTIMATED_LAG, allow_synthetic=False),
        benchmark_spec=BenchmarkSpecification(
            benchmark_type=BenchmarkType.FIXED_HYPOTHETICAL_PROXY,
            fixed_rate_annual=0.015,
            name="EUR Fixed Deposit Proxy (1.5% annual)",
            currency="EUR",
            reporting_currency="EUR",
        ),
    )
    res_2 = BacktestEngine(cfg_2, all_obs).run()
    results["config_2"] = export_backtest_result_json(res_2, out_dir / "config_2_estimated_schedule.json")

    # -------------------------------------------------------------------------
    # 3. Configuration 3: Strict Executable Quotes Enforcement
    # -------------------------------------------------------------------------
    print("Running Configuration 3: Strict Executable Quotes Enforcement...")
    exec_config_strict_quotes = default_exec_config.model_copy(update={"allow_reference_rate_proxy": False})
    cfg_3 = BacktestConfig(
        strategy_name="Config 3: Strict Executable Quotes Enforcement",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        initial_capital_a=100_000.0,
        tenor_days=30,
        rebalance_frequency_days=30,
        hurdle_rate_annual=0.005,
        cash_deposit_rate_annual=0.0,
        borrowing_rate_series_id="KR.DFR.LEV",
        investment_rate_series_id="DGS3MO",
        execution_config=exec_config_strict_quotes,
        position_sizing=sizing_config,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.ESTIMATED_LAG, allow_synthetic=False),
        benchmark_spec=BenchmarkSpecification(benchmark_type=BenchmarkType.ZERO_CASH, name="Zero Cash (0.0%)"),
    )
    res_3 = BacktestEngine(cfg_3, all_obs).run()
    results["config_3"] = export_backtest_result_json(res_3, out_dir / "config_3_strict_quotes.json")

    # -------------------------------------------------------------------------
    # 4. Configuration 4: Currency-Matched Benchmark (EUR Fixed Deposit Proxy)
    # -------------------------------------------------------------------------
    print("Running Configuration 4: Currency-Matched Benchmark...")
    cfg_4 = BacktestConfig(
        strategy_name="Config 4: Currency-Matched Benchmark (EUR)",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        initial_capital_a=100_000.0,
        tenor_days=30,
        rebalance_frequency_days=30,
        hurdle_rate_annual=0.005,
        cash_deposit_rate_annual=0.015,
        borrowing_rate_series_id="KR.DFR.LEV",
        investment_rate_series_id="DGS3MO",
        execution_config=default_exec_config,
        position_sizing=sizing_config,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.ESTIMATED_LAG, allow_synthetic=False),
        benchmark_spec=BenchmarkSpecification(
            benchmark_type=BenchmarkType.FIXED_HYPOTHETICAL_PROXY,
            fixed_rate_annual=0.015,
            currency="EUR",
            reporting_currency="EUR",
            name="EUR Matched Deposit Benchmark (1.5%)",
        ),
    )
    res_4 = BacktestEngine(cfg_4, all_obs).run()
    results["config_4"] = export_backtest_result_json(res_4, out_dir / "config_4_matched_benchmark.json")

    # -------------------------------------------------------------------------
    # 5. Configuration 5: Currency-Mismatched Benchmark Validation
    # -------------------------------------------------------------------------
    print("Running Configuration 5: Currency-Mismatched Benchmark Validation...")
    cfg_5 = BacktestConfig(
        strategy_name="Config 5: Currency-Mismatched Benchmark (USD vs EUR)",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        initial_capital_a=100_000.0,
        tenor_days=30,
        rebalance_frequency_days=30,
        hurdle_rate_annual=0.005,
        cash_deposit_rate_annual=0.015,
        borrowing_rate_series_id="KR.DFR.LEV",
        investment_rate_series_id="DGS3MO",
        execution_config=default_exec_config,
        position_sizing=sizing_config,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.ESTIMATED_LAG, allow_synthetic=False),
        benchmark_spec=BenchmarkSpecification(
            benchmark_type=BenchmarkType.HISTORICAL_RISK_FREE,
            series_id="DGS3MO",
            currency="USD",
            reporting_currency="USD",
            name="US Treasury 3M Yield (Mismatched Currency)",
        ),
    )
    res_5 = BacktestEngine(cfg_5, all_obs).run()
    results["config_5"] = export_backtest_result_json(res_5, out_dir / "config_5_mismatched_benchmark.json")

    # -------------------------------------------------------------------------
    # 6. Configuration 6: Covered Carry Rejection (No Forward Quotes)
    # -------------------------------------------------------------------------
    print("Running Configuration 6: Covered Carry Rejection...")
    cfg_6 = BacktestConfig(
        strategy_name="Covered Carry Trade",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        initial_capital_a=100_000.0,
        tenor_days=30,
        rebalance_frequency_days=30,
        hurdle_rate_annual=0.005,
        borrowing_rate_series_id="KR.DFR.LEV",
        investment_rate_series_id="DGS3MO",
        execution_config=default_exec_config,
        position_sizing=sizing_config,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=False),
    )
    res_6 = BacktestEngine(cfg_6, all_obs).run()
    results["config_6"] = export_backtest_result_json(res_6, out_dir / "config_6_covered_rejection.json")

    print("\n" + "=" * 125)
    print(" PHASE 3.2.2.2 HISTORICAL REPRODUCTION EXPERIMENT SUMMARY")
    print("=" * 125)
    print(f"{'Config':<10} | {'Status':<16} | {'Trades':<6} | {'Total Ret':<10} | {'Benchmark':<28} | {'Bm Ret':<8} | {'Excess Ret':<10} | {'Residual':<14}")
    print("-" * 125)

    configs = [
        ("Config 1", res_1),
        ("Config 2", res_2),
        ("Config 3", res_3),
        ("Config 4", res_4),
        ("Config 5", res_5),
        ("Config 6", res_6),
    ]

    for name, r in configs:
        m = r.metrics
        bm_name = m.benchmark_name or "None"
        bm_ret = f"{m.benchmark_total_return:+.2%}" if m.benchmark_total_return is not None else "N/A"
        excess = f"{m.cumulative_excess_return:+.2%}" if m.cumulative_excess_return is not None else "N/A"
        res_str = f"{m.reconciliation_residual_a:+.10f}"
        print(f"{name:<10} | {r.strategy_status.value:<16} | {m.total_trades:<6} | {m.total_return:+.2%}    | {bm_name[:28]:<28} | {bm_ret:<8} | {excess:<10} | {res_str:<14}")

    print("=" * 125)
    return results


if __name__ == "__main__":
    run_experiments()
