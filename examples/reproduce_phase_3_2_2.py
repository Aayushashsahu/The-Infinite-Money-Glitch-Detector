"""Phase 3.2.2 Historical Reproduction & Comparative Analysis Runner.

Executes the full 2020-2024 USD/EUR experiment across 5 required configurations:
1. Configuration 1: Verified Strict Mode (Strict firewall enforcing EXACT_TIMESTAMP_VERIFIED)
2. Configuration 2: Estimated-Schedule Research Mode (Permits ESTIMATED_SCHEDULE timestamps)
3. Configuration 3: Research-Proxy Financial Input Configuration (ECB DFR & Treasury 3M yields)
4. Configuration 4: Explicit Benchmark Proxy (Zero Cash Benchmark vs Fixed Deposit Proxy)
5. Configuration 5: Covered Carry Trade (Rejection due to absence of genuine forward quotes)

Exports machine-generated JSON result objects to data/results/phase_3_2_2/ and outputs
the exact double-entry accounting reconciliation table.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

# Ensure src is on path
ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from backtesting.engine import BacktestEngine
from backtesting.reporting import export_backtest_result_json
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

    out_dir = Path("data/results/phase_3_2_2")
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {}

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
        fixed_amount=50_000.0,
        max_active_positions=1,
    )

    # -------------------------------------------------------------------------
    # 1. Configuration 1: Verified Strict Mode
    # -------------------------------------------------------------------------
    print("Running Configuration 1: Verified Strict Mode...")
    cfg_1 = BacktestConfig(
        strategy_name="Config 1: Verified Strict Mode",
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
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=False),
        benchmark_spec=BenchmarkSpecification(benchmark_type=BenchmarkType.ZERO_CASH, name="Zero Cash (0.0%)"),
    )
    res_1 = BacktestEngine(cfg_1, all_obs).run()
    results["config_1"] = export_backtest_result_json(res_1, out_dir / "config_1_verified_strict.json")

    # -------------------------------------------------------------------------
    # 2. Configuration 2: Estimated-Schedule Research Mode
    # -------------------------------------------------------------------------
    print("Running Configuration 2: Estimated-Schedule Research Mode...")
    cfg_2 = BacktestConfig(
        strategy_name="Config 2: Estimated-Schedule Research Mode",
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
        execution_config=exec_config,
        position_sizing=sizing_config,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.ESTIMATED_LAG, allow_synthetic=False),
        benchmark_spec=BenchmarkSpecification(
            benchmark_type=BenchmarkType.FIXED_HYPOTHETICAL_PROXY,
            fixed_rate_annual=0.015,
            name="Fixed Deposit Proxy (1.5% annual)",
        ),
    )
    res_2 = BacktestEngine(cfg_2, all_obs).run()
    results["config_2"] = export_backtest_result_json(res_2, out_dir / "config_2_estimated_schedule.json")

    # -------------------------------------------------------------------------
    # 3. Configuration 3: Research-Proxy Financial Input Configuration
    # -------------------------------------------------------------------------
    print("Running Configuration 3: Research-Proxy Financial Input Configuration...")
    cfg_3 = BacktestConfig(
        strategy_name="Config 3: Research-Proxy Inputs (DFR / DGS3MO)",
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
        require_commercial_rates=False,
        execution_config=exec_config,
        position_sizing=sizing_config,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.ESTIMATED_LAG, allow_synthetic=False),
        benchmark_spec=BenchmarkSpecification(
            benchmark_type=BenchmarkType.HISTORICAL_RISK_FREE,
            series_id="DGS3MO",
            name="Empirical Risk-Free Rate Benchmark (3M Treasury)",
        ),
    )
    res_3 = BacktestEngine(cfg_3, all_obs).run()
    results["config_3"] = export_backtest_result_json(res_3, out_dir / "config_3_research_proxy.json")

    # -------------------------------------------------------------------------
    # 4. Configuration 4: Explicit Zero-Cash Benchmark vs Commercial Proxy
    # -------------------------------------------------------------------------
    print("Running Configuration 4: Explicit Zero-Cash Benchmark...")
    cfg_4 = BacktestConfig(
        strategy_name="Config 4: Explicit Zero-Cash Benchmark",
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
        execution_config=exec_config,
        position_sizing=sizing_config,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.ESTIMATED_LAG, allow_synthetic=False),
        benchmark_spec=BenchmarkSpecification(benchmark_type=BenchmarkType.ZERO_CASH, name="Zero Cash Benchmark (0.0%)"),
    )
    res_4 = BacktestEngine(cfg_4, all_obs).run()
    results["config_4"] = export_backtest_result_json(res_4, out_dir / "config_4_zero_cash_benchmark.json")

    # -------------------------------------------------------------------------
    # 5. Configuration 5: Covered Carry Rejection (No Forward Quotes)
    # -------------------------------------------------------------------------
    print("Running Configuration 5: Covered Carry Rejection...")
    cfg_5 = BacktestConfig(
        strategy_name="Config 5: Covered Carry Rejection",
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
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=False),
    )
    res_5 = BacktestEngine(cfg_5, all_obs).run()
    results["config_5"] = export_backtest_result_json(res_5, out_dir / "config_5_covered_rejection.json")

    print("\n" + "=" * 90)
    print(" PHASE 3.2.2 HISTORICAL REPRODUCTION EXPERIMENT SUMMARY")
    print("=" * 90)
    print(f"{'Config':<10} | {'Status':<16} | {'Trades':<6} | {'Total Ret':<10} | {'Benchmark':<24} | {'Bm Ret':<8} | {'Excess Ret':<10} | {'Residual':<14}")
    print("-" * 115)

    configs = [
        ("Config 1", res_1),
        ("Config 2", res_2),
        ("Config 3", res_3),
        ("Config 4", res_4),
        ("Config 5", res_5),
    ]

    for name, r in configs:
        m = r.metrics
        bm_name = m.benchmark_name or "None"
        bm_ret = f"{m.benchmark_total_return:+.2%}" if m.benchmark_total_return is not None else "N/A"
        excess = f"{m.cumulative_excess_return:+.2%}" if m.cumulative_excess_return is not None else "N/A"
        res_str = f"{m.reconciliation_residual_a:+.10f}"
        print(f"{name:<10} | {r.strategy_status.value:<16} | {m.total_trades:<6} | {m.total_return:+.2%}    | {bm_name[:24]:<24} | {bm_ret:<8} | {excess:<10} | {res_str:<14}")

    print("=" * 115)
    return results


if __name__ == "__main__":
    run_experiments()
