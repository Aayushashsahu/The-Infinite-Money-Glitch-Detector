"""Phase 3.2.2.3.3 Historical Reproduction & FX Symmetry and Integrity Runner.

Executes the full 2020-2024 EUR/USD experiment across 6 required configurations:
1. Configuration 1: Strict Verified Point-in-Time (Strict firewall enforcing EXACT_TIMESTAMP_VERIFIED)
2. Configuration 2: Estimated-Availability Reference-Rate Research (Daily reference rate proxy allowed with canonical FX conversion)
3. Configuration 3: Strict Executable Quotes Enforcement (Rejection of daily reference rates as executable quotes)
4. Configuration 4: Currency-Matched Benchmark (EUR Fixed Deposit Proxy, matching EUR borrowing)
5. Configuration 5: Currency-Mismatched Benchmark (USD Treasury DGS3MO vs EUR borrowing currency - Sharpe/Alpha = N/A)
6. Configuration 6: Covered Carry Trade Rejection (Rejection due to absence of genuine forward quotes)

Exports machine-generated JSON result objects to data/results/phase_3_2_2_3_3/ and outputs
the exact double-entry accounting reconciliation and attribution table.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sys
import time

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

    out_dir = Path("data/results/phase_3_2_2_3_3")
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {}

    default_exec_config = ExecutionConfig(
        bid_ask_spread_bps=2.0,
        slippage_bps=0.5,
        variable_fee_bps=1.0,
        fixed_fee=5.0,
        min_trade_size_a=1_000.0,
        max_trade_size_a=10_000_000.0,
        allow_reference_rate_proxy=True,
        use_observed_spread=True,
    )

    default_sizing = PositionSizingConfig(
        method=PositionSizingMethod.PERCENT_OF_EQUITY,
        percent_of_equity=0.5,
        max_leverage=1.0,
        max_active_positions=1,
    )

    pair = CurrencyPair(
        base_currency="EUR",
        quote_currency="USD",
        borrowing_currency="EUR",
        investment_currency="USD",
    )

    # -------------------------------------------------------------
    # Configuration 1: Strict Verified Point-in-Time
    # -------------------------------------------------------------
    print("Running Configuration 1: Strict Verified Point-in-Time...")
    cfg_1 = BacktestConfig(
        strategy_name="Config 1: Strict Verified Point-in-Time",
        currency_pair=pair,
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        initial_capital_a=100_000.0,
        cash_deposit_rate_annual=0.0,
        tenor_days=30,
        rebalance_frequency_days=30,
        borrowing_rate_series_id="KR.MRR_FR.LEV",
        investment_rate_series_id="DGS1MO",
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT),
        execution_config=default_exec_config,
        position_sizing=default_sizing,
        benchmark_spec=BenchmarkSpecification(benchmark_type=BenchmarkType.ZERO_CASH, name="Zero Cash (0.0%)"),
    )
    b_engine_1 = BacktestEngine(cfg_1, all_obs)
    res_1 = b_engine_1.run()
    results["Config 1"] = res_1
    export_backtest_result_json(res_1, out_dir / "config_1_strict_pit.json")

    # -------------------------------------------------------------
    # Configuration 2: Estimated-Availability Reference-Rate Research
    # -------------------------------------------------------------
    print("Running Configuration 2: Estimated-Availability Reference-Rate Research...")
    cfg_2 = BacktestConfig(
        strategy_name="Config 2: Estimated-Availability Reference-Rate Research",
        currency_pair=pair,
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        initial_capital_a=100_000.0,
        cash_deposit_rate_annual=0.015,
        tenor_days=30,
        rebalance_frequency_days=30,
        borrowing_rate_series_id="KR.MRR_FR.LEV",
        investment_rate_series_id="DGS1MO",
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.ESTIMATED_LAG),
        execution_config=default_exec_config,
        position_sizing=default_sizing,
        benchmark_spec=BenchmarkSpecification(
            benchmark_type=BenchmarkType.FIXED_HYPOTHETICAL_PROXY,
            fixed_rate_annual=0.015,
            name="EUR Fixed Deposit Proxy (1.5% annual)",
            currency="EUR",
        ),
    )
    b_engine_2 = BacktestEngine(cfg_2, all_obs)
    res_2 = b_engine_2.run()
    results["Config 2"] = res_2
    export_backtest_result_json(res_2, out_dir / "config_2_estimated_schedule.json")

    # -------------------------------------------------------------
    # Configuration 3: Strict Executable Quotes Enforcement
    # -------------------------------------------------------------
    print("Running Configuration 3: Strict Executable Quotes Enforcement...")
    cfg_3 = BacktestConfig(
        strategy_name="Config 3: Strict Executable Quotes Enforcement",
        currency_pair=pair,
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        initial_capital_a=100_000.0,
        cash_deposit_rate_annual=0.0,
        tenor_days=30,
        rebalance_frequency_days=30,
        borrowing_rate_series_id="KR.MRR_FR.LEV",
        investment_rate_series_id="DGS1MO",
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.ESTIMATED_LAG),
        execution_config=ExecutionConfig(
            bid_ask_spread_bps=2.0,
            slippage_bps=0.5,
            variable_fee_bps=1.0,
            fixed_fee=5.0,
            allow_reference_rate_proxy=False,  # Strict: reference rates cannot execute!
            use_observed_spread=True,
        ),
        position_sizing=default_sizing,
        benchmark_spec=BenchmarkSpecification(benchmark_type=BenchmarkType.ZERO_CASH, name="Zero Cash (0.0%)"),
    )
    b_engine_3 = BacktestEngine(cfg_3, all_obs)
    res_3 = b_engine_3.run()
    results["Config 3"] = res_3
    export_backtest_result_json(res_3, out_dir / "config_3_strict_quotes.json")

    # -------------------------------------------------------------
    # Configuration 4: Currency-Matched Benchmark
    # -------------------------------------------------------------
    print("Running Configuration 4: Currency-Matched Benchmark...")
    cfg_4 = BacktestConfig(
        strategy_name="Config 4: Currency-Matched Benchmark (EUR Deposit Proxy)",
        currency_pair=pair,
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        initial_capital_a=100_000.0,
        cash_deposit_rate_annual=0.015,
        tenor_days=30,
        rebalance_frequency_days=30,
        borrowing_rate_series_id="KR.MRR_FR.LEV",
        investment_rate_series_id="DGS1MO",
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.ESTIMATED_LAG),
        execution_config=default_exec_config,
        position_sizing=default_sizing,
        benchmark_spec=BenchmarkSpecification(
            benchmark_type=BenchmarkType.FIXED_HYPOTHETICAL_PROXY,
            fixed_rate_annual=0.015,
            name="EUR Fixed Deposit (1.5%)",
            currency="EUR",
        ),
    )
    b_engine_4 = BacktestEngine(cfg_4, all_obs)
    res_4 = b_engine_4.run()
    results["Config 4"] = res_4
    export_backtest_result_json(res_4, out_dir / "config_4_matched_benchmark.json")

    # -------------------------------------------------------------
    # Configuration 5: Currency-Mismatched Benchmark Validation
    # -------------------------------------------------------------
    print("Running Configuration 5: Currency-Mismatched Benchmark Validation...")
    cfg_5 = BacktestConfig(
        strategy_name="Config 5: Currency-Mismatched Benchmark (USD vs EUR)",
        currency_pair=pair,
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        initial_capital_a=100_000.0,
        cash_deposit_rate_annual=0.015,
        tenor_days=30,
        rebalance_frequency_days=30,
        borrowing_rate_series_id="KR.MRR_FR.LEV",
        investment_rate_series_id="DGS1MO",
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.ESTIMATED_LAG),
        execution_config=default_exec_config,
        position_sizing=default_sizing,
        benchmark_spec=BenchmarkSpecification(
            benchmark_type=BenchmarkType.HISTORICAL_RISK_FREE,
            series_id="DGS3MO",
            name="US Treasury 3M Yield (Mismatched Currency)",
            currency="USD",  # Mismatch: USD vs borrowing EUR
        ),
    )
    b_engine_5 = BacktestEngine(cfg_5, all_obs)
    res_5 = b_engine_5.run()
    results["Config 5"] = res_5
    export_backtest_result_json(res_5, out_dir / "config_5_mismatched_benchmark.json")

    # -------------------------------------------------------------
    # Configuration 6: Covered Carry Rejection
    # -------------------------------------------------------------
    print("Running Configuration 6: Covered Carry Rejection...")
    cfg_6 = BacktestConfig(
        strategy_name="Config 6: Covered Carry Rejection",
        currency_pair=pair,
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        initial_capital_a=100_000.0,
        cash_deposit_rate_annual=0.0,
        tenor_days=30,
        rebalance_frequency_days=30,
        borrowing_rate_series_id="KR.MRR_FR.LEV",
        investment_rate_series_id="DGS1MO",
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT),
        execution_config=default_exec_config,
        position_sizing=default_sizing,
        benchmark_spec=BenchmarkSpecification(benchmark_type=BenchmarkType.UNAVAILABLE, name="Unavailable"),
    )
    b_engine_6 = BacktestEngine(cfg_6, all_obs)
    res_6 = b_engine_6.run()
    results["Config 6"] = res_6
    export_backtest_result_json(res_6, out_dir / "config_6_covered_rejection.json")

    # Print summary table
    print("\n" + "=" * 165)
    print(" PHASE 3.2.2.3.3 FX SYMMETRY, EXECUTION & ARTIFACT INTEGRITY REPRODUCTION SUMMARY")
    print("=" * 165)
    print(f"{'Config':<10} | {'Status':<16} | {'PIT Status':<23} | {'PIT Cred':<8} | {'Trades':<6} | {'Total Ret':<10} | {'Pure FX':<10} | {'Asset Yield':<12} | {'Fin Cost':<10} | {'Sharpe':<8} | {'Alpha':<8}")
    print("-" * 165)
    for name, r in results.items():
        pit_cred = "YES" if r.is_point_in_time_credible else "NO"
        m = r.metrics
        trades_cnt = m.total_trades if m else 0
        tot_ret = f"{m.total_return:+.2%}" if m and m.total_return is not None else "N/A"
        pure_fx = f"{m.pure_fx_return:+.2%}" if m and m.pure_fx_return is not None else "N/A"
        yield_ret = f"{m.investment_yield_return:+.2%}" if m and m.investment_yield_return is not None else "N/A"
        fin_drag = f"{-m.financing_cost_drag:+.2%}" if m and m.financing_cost_drag is not None else "N/A"
        sharpe = f"{m.sharpe_ratio:.2f}" if m and m.sharpe_ratio is not None else "N/A"
        alpha = f"{m.alpha:+.2%}" if m and m.alpha is not None else "N/A"
        pit_st = r.pit_availability_status.value if hasattr(r, "pit_availability_status") and r.pit_availability_status else "unknown"

        print(f"{name:<10} | {r.strategy_status.value:<16} | {pit_st:<23} | {pit_cred:<8} | {trades_cnt:<6} | {tot_ret:<10} | {pure_fx:<10} | {yield_ret:<12} | {fin_drag:<10} | {sharpe:<8} | {alpha:<8}")
    print("=" * 165 + "\n")

    # Format markdown report for Configuration 2
    md_report = format_backtest_report(res_2)
    report_file = (out_dir / "config_2_audit_report.md").resolve()
    for attempt in range(10):
        try:
            report_file.write_text(md_report, encoding="utf-8")
            break
        except OSError:
            if attempt == 9:
                raise
            time.sleep(0.5)
    print(f"Configuration 2 audit report written to: {report_file}")


if __name__ == "__main__":
    run_experiments()
