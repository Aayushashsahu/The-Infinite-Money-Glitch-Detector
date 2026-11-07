"""Phase 4 — Monte Carlo & Market Scenario Laboratory Research Runner.

Executes probabilistic market simulation across multiple models:
- IID Bootstrap
- Moving-Block Bootstrap
- Stationary Bootstrap (Politis & Romano 1994)
- Multivariate Student-t
- Observable Volatility Regime Switching
- Deterministic Macro-Financial Stress Tests

Evaluates the unhedged FX carry strategy through audited core financial modules,
computes distributional risk metrics with Monte Carlo standard errors, and exports
all machine-readable artifacts and research reports to data/results/phase_4/.
"""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
from pathlib import Path
import subprocess
import sys
import time

# Ensure src is on path
ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from data.db.engine import make_engine, make_session_factory
from data.repository import Repository
from simulation.monte_carlo import (
    BootstrapMethod,
    CarryTradeScenarioStrategy,
    ConvergenceReport,
    FactorPanel,
    ModelComparisonEntry,
    MonteCarloEngine,
    MonteCarloResult,
    RegimeState,
    ScenarioPath,
    SimulationConfig,
    SimulationModelType,
    build_fx_carry_factor_panel,
    build_standard_stress_scenarios,
    calibrate_factor_panel,
    export_json,
    generate_research_report,
    split_calibration_holdout,
)


def get_git_commit() -> str:
    """Retrieve current git commit SHA."""
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return "unknown"


def run_monte_carlo_laboratory(
    num_paths: int = 1000,
    horizon_steps: int = 252,
    random_seed: int = 42,
    output_dir: Path | None = None,
) -> None:
    """Execute complete Phase 4 Monte Carlo simulation research suite."""
    out_dir = output_dir or (ROOT_DIR / "data" / "results" / "phase_4")
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print(" PHASE 4 — MONTE CARLO & MARKET SCENARIO LABORATORY")
    print(f" Paths: {num_paths:,} | Horizon: {horizon_steps} steps | Seed: {random_seed}")
    print("=" * 80)

    # 1. Load historical database observations
    db_path = "sqlite:///data/processed/gmdb.db"
    print(f"\n[1/7] Loading historical data from {db_path}...")
    engine = make_engine(db_path)
    repo = Repository(make_session_factory(engine))
    observations = repo.load_observation_objects(include_synthetic=False)
    print(f"      Loaded {len(observations):,} genuine historical observations.")

    # 2. Build full factor panel and split into calibration vs holdout
    print("\n[2/7] Constructing and aligning factor panels...")
    full_panel = build_fx_carry_factor_panel(
        observations=observations,
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
    )
    calib_panel, holdout_panel = split_calibration_holdout(
        panel=full_panel,
        calibration_end=date(2023, 12, 31),
    )
    print(f"      Calibration Panel: {calib_panel.effective_sample_size} days ({calib_panel.dates[0]} to {calib_panel.dates[-1]})")
    print(f"      Holdout Panel:     {holdout_panel.effective_sample_size} days ({holdout_panel.dates[0]} to {holdout_panel.dates[-1]})")

    # 3. Calibrate historical distribution and sample sufficiency
    print("\n[3/7] Calibrating empirical distributions & covariance matrix...")
    calib_report = calibrate_factor_panel(calib_panel, holdout_panel)
    export_json(calib_report, out_dir / "calibration_report.json")
    export_json(full_panel.model_dump(mode="json"), out_dir / "factor_panel_manifest.json")
    print("      Exported calibration_report.json and factor_panel_manifest.json")

    # 4. Run simulations across all supported model architectures
    print(f"\n[4/7] Generating {num_paths:,} simulation paths across 5 model types...")
    strategy = CarryTradeScenarioStrategy(tenor_days=30, rebalance_days=30)
    results: dict[str, MonteCarloResult] = {}
    model_comparisons: list[ModelComparisonEntry] = []

    # Model 1: Moving-Block Bootstrap (Primary Non-Parametric)
    print("      -> Running Moving-Block Bootstrap (20-day blocks)...")
    cfg_mb = SimulationConfig(
        simulation_id="MC_MOVING_BLOCK_BOOTSTRAP",
        model_type=SimulationModelType.HISTORICAL_BOOTSTRAP,
        bootstrap_method=BootstrapMethod.MOVING_BLOCK,
        block_size=20,
        num_paths=num_paths,
        horizon_steps=horizon_steps,
        random_seed=random_seed,
    )
    mc_mb = MonteCarloEngine(cfg_mb, observations, strategy=strategy).run()
    results["moving_block_bootstrap"] = mc_mb
    export_json(mc_mb, out_dir / "bootstrap_results.json")

    # Model 2: IID Bootstrap (Diagnostic Baseline)
    print("      -> Running IID Bootstrap (Baseline)...")
    cfg_iid = SimulationConfig(
        simulation_id="MC_IID_BOOTSTRAP",
        model_type=SimulationModelType.HISTORICAL_BOOTSTRAP,
        bootstrap_method=BootstrapMethod.IID,
        num_paths=num_paths,
        horizon_steps=horizon_steps,
        random_seed=random_seed + 1,
    )
    mc_iid = MonteCarloEngine(cfg_iid, observations, strategy=strategy).run()
    results["iid_bootstrap"] = mc_iid

    # Model 3: Stationary Bootstrap (Politis & Romano 1994)
    print("      -> Running Stationary Bootstrap (Expected block length 20 days)...")
    cfg_stat = SimulationConfig(
        simulation_id="MC_STATIONARY_BOOTSTRAP",
        model_type=SimulationModelType.HISTORICAL_BOOTSTRAP,
        bootstrap_method=BootstrapMethod.STATIONARY,
        block_size=20,
        num_paths=num_paths,
        horizon_steps=horizon_steps,
        random_seed=random_seed + 2,
    )
    mc_stat = MonteCarloEngine(cfg_stat, observations, strategy=strategy).run()
    results["stationary_bootstrap"] = mc_stat

    # Model 4: Multivariate Student-t
    print("      -> Running Multivariate Student-t Parametric Generator...")
    cfg_t = SimulationConfig(
        simulation_id="MC_MULTIVARIATE_STUDENT_T",
        model_type=SimulationModelType.MULTIVARIATE_STUDENT_T,
        num_paths=num_paths,
        horizon_steps=horizon_steps,
        random_seed=random_seed + 3,
    )
    mc_t = MonteCarloEngine(cfg_t, observations, strategy=strategy).run()
    results["student_t"] = mc_t
    export_json(mc_t, out_dir / "student_t_results.json")

    # Model 5: Regime-Conditioned Volatility Switching
    print("      -> Running Regime-Conditioned Volatility Switching...")
    cfg_reg = SimulationConfig(
        simulation_id="MC_REGIME_CONDITIONED_BOOTSTRAP",
        model_type=SimulationModelType.REGIME_CONDITIONED_BOOTSTRAP,
        num_paths=num_paths,
        horizon_steps=horizon_steps,
        random_seed=random_seed + 4,
    )
    mc_reg = MonteCarloEngine(cfg_reg, observations, strategy=strategy).run()
    results["regimes"] = mc_reg
    export_json(mc_reg, out_dir / "regime_results.json")

    # Build model comparison list
    for name, r in [
        ("IID Bootstrap", mc_iid),
        ("Moving-Block Bootstrap (20d)", mc_mb),
        ("Stationary Bootstrap (20d)", mc_stat),
        ("Multivariate Student-t", mc_t),
        ("Regime-Conditioned Bootstrap", mc_reg),
    ]:
        dm = r.distribution_metrics
        model_comparisons.append(
            ModelComparisonEntry(
                model_name=name,
                num_paths=r.config.num_paths,
                median_return=dm.total_return.p50,
                mean_return=dm.total_return.mean,
                std_return=dm.annualized_volatility.mean,
                var_95=dm.var_95,
                cvar_95=dm.cvar_95,
                max_drawdown_median=dm.max_drawdown.p50,
                max_drawdown_p95=dm.max_drawdown.p05,
                prob_loss=dm.prob_loss,
                prob_loss_se=dm.prob_loss_se,
                prob_drawdown_10pct=dm.prob_drawdown_10pct,
                mean_fx_drag=dm.mean_fx_translation_gain_a / 100_000.0,
                mean_financing_drag=dm.mean_financing_costs_a / 100_000.0,
            )
        )

    export_json([m.model_dump(mode="json") for m in model_comparisons], out_dir / "model_comparison.json")

    # 5. Execute Deterministic Stress Tests
    print("\n[5/7] Executing deterministic macro-financial stress tests...")
    stress_results = MonteCarloEngine(cfg_mb, observations, strategy=strategy).run_deterministic_stress_tests()
    export_json(stress_results, out_dir / "stress_test_results.json")
    print(f"      Completed {len(stress_results)} stress scenarios; exported stress_test_results.json")

    # 6. Export Convergence Analysis
    print("\n[6/7] Exporting convergence diagnostics...")
    if mc_mb.convergence_report:
        export_json(mc_mb.convergence_report, out_dir / "convergence_report.json")
        print("      Exported convergence_report.json")

    # Manifest
    git_sha = get_git_commit()
    manifest_digest = hashlib.sha256(Path("data/manifest.json").read_bytes()).hexdigest() if Path("data/manifest.json").exists() else None
    sim_manifest = {
        "git_commit": git_sha,
        "data_manifest_digest": manifest_digest,
        "calibration_start": "2020-01-01",
        "calibration_end": "2023-12-31",
        "holdout_start": "2024-01-01",
        "holdout_end": "2024-12-31",
        "num_paths": num_paths,
        "horizon_steps": horizon_steps,
        "random_seed": random_seed,
        "models_evaluated": list(results.keys()),
        "output_files": [
            "calibration_report.json",
            "factor_panel_manifest.json",
            "bootstrap_results.json",
            "student_t_results.json",
            "regime_results.json",
            "stress_test_results.json",
            "model_comparison.json",
            "convergence_report.json",
            "simulation_manifest.json",
            "phase_4_research_report.md",
        ],
    }
    export_json(sim_manifest, out_dir / "simulation_manifest.json")

    # 7. Generate Comprehensive Research Report
    print("\n[7/7] Generating phase_4_research_report.md...")
    report_md = generate_research_report(
        calibration=calib_report,
        model_comparisons=model_comparisons,
        stress_results=stress_results,
        bootstrap_result=mc_mb,
        student_t_result=mc_t,
        regime_result=mc_reg,
    )
    report_path = out_dir / "phase_4_research_report.md"
    report_path.write_text(report_md, encoding="utf-8")
    print(f"      Report written to: {report_path}")

    # Terminal summary display
    print("\n" + "=" * 135)
    print(" PHASE 4 MONTE CARLO CROSS-MODEL RISK & RETURN SUMMARY")
    print("=" * 135)
    print(f"{'Model Name':<30} | {'Paths':<7} | {'Median Ret':<10} | {'Mean Ret':<10} | {'Vol':<8} | {'VaR (95%)':<10} | {'CVaR (95%)':<11} | {'Prob(Loss)':<15} | {'Prob(DD>=10%)':<13}")
    print("-" * 135)
    for mc in model_comparisons:
        se_str = f"±{mc.prob_loss_se:.2%}"
        print(
            f"{mc.model_name:<30} | {mc.num_paths:<7,} | {mc.median_return:<+10.2%} | {mc.mean_return:<+10.2%} | "
            f"{mc.std_return:<8.2%} | {mc.var_95:<+10.2%} | {mc.cvar_95:<+11.2%} | {mc.prob_loss:<6.1%} ({se_str:<7}) | {mc.prob_drawdown_10pct:<13.1%}"
        )
    print("=" * 135 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 4 Monte Carlo & Market Scenario Laboratory")
    parser.add_argument("--paths", type=int, default=1000, help="Number of simulation paths (default: 1000)")
    parser.add_argument("--horizon", type=int, default=252, help="Simulation horizon in trading days (default: 252)")
    parser.add_argument("--seed", type=int, default=42, help="Random number generator seed (default: 42)")
    parser.add_argument("--smoke", action="store_true", help="Run fast smoke test with 100 paths over 30 steps")
    args = parser.parse_args()

    paths = 100 if args.smoke else args.paths
    horizon = 30 if args.smoke else args.horizon

    run_monte_carlo_laboratory(
        num_paths=paths,
        horizon_steps=horizon,
        random_seed=args.seed,
    )


if __name__ == "__main__":
    main()
