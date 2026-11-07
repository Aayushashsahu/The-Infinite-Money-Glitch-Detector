"""Phase 4.1 — Simulation Integrity & Quantitative Validation Research Runner.

Executes probabilistic market simulation across 6 models:
0. Multivariate Gaussian (Parametric Baseline)
1. Moving-Block Bootstrap (20-day blocks, Primary Nonparametric)
2. IID Bootstrap (Empirical Innovation Resampling)
3. Stationary Bootstrap (Politis & Romano 1994, mean 20-day blocks)
4. Multivariate Student-t (Estimated profile MLE nu, fat-tailed parametric)
5. Regime-Conditioned Volatility Switching (20th/80th percentiles, warm-up excluded)
6. Deterministic Macro-Financial Stress Tests (with shock timing contracts & correlation breakdown)

Evaluates the unhedged FX carry strategy through audited core financial modules,
computes distributional risk metrics with Monte Carlo standard errors, evaluates 2024 holdout
diagnostics, tracks multi-metric convergence stability, and exports all machine-readable
artifacts to data/results/phase_4_1/ (leaving data/results/phase_4/ untouched).
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import scipy

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
    evaluate_holdout_diagnostics,
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


def compute_file_sha256(path: Path) -> str:
    """Compute SHA256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def run_monte_carlo_laboratory(
    num_paths: int = 1000,
    horizon_steps: int = 252,
    random_seed: int = 42,
    output_dir: Path | None = None,
) -> None:
    """Execute complete Phase 4.1 Monte Carlo simulation research suite."""
    out_dir = output_dir or (ROOT_DIR / "data" / "results" / "phase_4_1")
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 85)
    print(" PHASE 4.1 — SIMULATION INTEGRITY & QUANTITATIVE VALIDATION CLOSURE")
    print(f" Paths: {num_paths:,} | Horizon: {horizon_steps} steps | Seed: {random_seed}")
    print(f" Output Directory: {out_dir}")
    print("=" * 85)

    # 1. Load historical database observations
    db_path = "sqlite:///data/processed/gmdb.db"
    print(f"\n[1/8] Loading historical data from {db_path}...")
    engine = make_engine(db_path)
    repo = Repository(make_session_factory(engine))
    observations = repo.load_observation_objects(include_synthetic=False)
    print(f"      Loaded {len(observations):,} genuine historical observations.")

    # 2. Build full factor panel and split into calibration vs holdout
    print("\n[2/8] Constructing and aligning factor panels (Option A / Option B)...")
    full_panel = build_fx_carry_factor_panel(
        observations=observations,
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        sovereign_yield_series_id="DGS3MO",
    )
    calib_panel, holdout_panel = split_calibration_holdout(
        panel=full_panel,
        calibration_end=date(2023, 12, 31),
    )
    print(f"      Calibration Panel: {calib_panel.effective_sample_size} days ({calib_panel.dates[0]} to {calib_panel.dates[-1]})")
    print(f"      Holdout Panel:     {holdout_panel.effective_sample_size} days ({holdout_panel.dates[0]} to {holdout_panel.dates[-1]})")
    print(f"      Retained Factors:  {[f.factor_id for f in calib_panel.factors]}")

    # 3. Calibrate historical distribution, covariance, and availability summary
    print("\n[3/8] Calibrating empirical distributions, covariance & availability breakdown...")
    calib_report = calibrate_factor_panel(
        calib_panel,
        holdout_panel=holdout_panel,
        raw_observations=observations,
    )
    export_json(calib_report, out_dir / "calibration_report.json")
    export_json(full_panel.model_dump(mode="json"), out_dir / "factor_panel_manifest.json")
    print("      Exported calibration_report.json and factor_panel_manifest.json")

    # 4. Run simulations across 6 model architectures
    print(f"\n[4/8] Generating {num_paths:,} simulation paths across 6 model architectures...")
    strategy = CarryTradeScenarioStrategy(tenor_days=30, rebalance_days=30)
    results: dict[str, MonteCarloResult] = {}
    model_comparisons: list[ModelComparisonEntry] = []

    # Model 0: Multivariate Gaussian (Parametric Baseline)
    print("      -> [0/6] Running Multivariate Gaussian Model...")
    cfg_gauss = SimulationConfig(
        simulation_id="MC_MULTIVARIATE_GAUSSIAN",
        model_type=SimulationModelType.MULTIVARIATE_GAUSSIAN,
        num_paths=num_paths,
        horizon_steps=horizon_steps,
        random_seed=random_seed,
    )
    mc_gauss = MonteCarloEngine(cfg_gauss, observations, strategy=strategy).run()
    results["multivariate_gaussian"] = mc_gauss
    export_json(mc_gauss, out_dir / "gaussian_results.json")

    # Model 1: Moving-Block Bootstrap (Primary Non-Parametric)
    print("      -> [1/6] Running Moving-Block Bootstrap (20-day blocks)...")
    cfg_mb = SimulationConfig(
        simulation_id="MC_MOVING_BLOCK_BOOTSTRAP",
        model_type=SimulationModelType.HISTORICAL_BOOTSTRAP,
        bootstrap_method=BootstrapMethod.MOVING_BLOCK,
        block_size=20,
        num_paths=num_paths,
        horizon_steps=horizon_steps,
        random_seed=random_seed + 1,
    )
    mc_mb = MonteCarloEngine(cfg_mb, observations, strategy=strategy).run()
    results["moving_block_bootstrap"] = mc_mb
    export_json(mc_mb, out_dir / "bootstrap_results.json")

    # Model 2: IID Bootstrap (Diagnostic Baseline)
    print("      -> [2/6] Running IID Bootstrap (Independent Innovation Resampling)...")
    cfg_iid = SimulationConfig(
        simulation_id="MC_IID_BOOTSTRAP",
        model_type=SimulationModelType.HISTORICAL_BOOTSTRAP,
        bootstrap_method=BootstrapMethod.IID,
        num_paths=num_paths,
        horizon_steps=horizon_steps,
        random_seed=random_seed + 2,
    )
    mc_iid = MonteCarloEngine(cfg_iid, observations, strategy=strategy).run()
    results["iid_bootstrap"] = mc_iid

    # Model 3: Stationary Bootstrap (Politis & Romano 1994)
    print("      -> [3/6] Running Stationary Bootstrap (Mean block length 20 days)...")
    cfg_stat = SimulationConfig(
        simulation_id="MC_STATIONARY_BOOTSTRAP",
        model_type=SimulationModelType.HISTORICAL_BOOTSTRAP,
        bootstrap_method=BootstrapMethod.STATIONARY,
        block_size=20,
        num_paths=num_paths,
        horizon_steps=horizon_steps,
        random_seed=random_seed + 3,
    )
    mc_stat = MonteCarloEngine(cfg_stat, observations, strategy=strategy).run()
    results["stationary_bootstrap"] = mc_stat

    # Model 4: Multivariate Student-t (Fat-Tailed Parametric with Profile MLE df)
    print("      -> [4/6] Running Multivariate Student-t (Profile MLE degrees of freedom)...")
    cfg_t = SimulationConfig(
        simulation_id="MC_MULTIVARIATE_STUDENT_T",
        model_type=SimulationModelType.MULTIVARIATE_STUDENT_T,
        num_paths=num_paths,
        horizon_steps=horizon_steps,
        random_seed=random_seed + 4,
    )
    mc_t = MonteCarloEngine(cfg_t, observations, strategy=strategy).run()
    results["student_t"] = mc_t
    export_json(mc_t, out_dir / "student_t_results.json")

    # Model 5: Regime-Conditioned Volatility Switching
    print("      -> [5/6] Running Regime-Conditioned Volatility Switching (20th/80th pct, warm-up excluded)...")
    cfg_reg = SimulationConfig(
        simulation_id="MC_REGIME_CONDITIONED_BOOTSTRAP",
        model_type=SimulationModelType.REGIME_CONDITIONED_BOOTSTRAP,
        num_paths=num_paths,
        horizon_steps=horizon_steps,
        random_seed=random_seed + 5,
    )
    mc_reg = MonteCarloEngine(cfg_reg, observations, strategy=strategy).run()
    results["regimes"] = mc_reg
    export_json(mc_reg, out_dir / "regime_results.json")

    # Build comparative table across ALL models
    for name, r in [
        ("Multivariate Gaussian", mc_gauss),
        ("Moving-Block Bootstrap (20d)", mc_mb),
        ("IID Bootstrap", mc_iid),
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
    print("      Exported model_comparison.json (6 models)")

    # 5. Execute Deterministic Stress Tests (with timing contracts & correlation breakdown)
    print("\n[5/8] Executing deterministic macro-financial stress suite (including correlation breakdown)...")
    stress_results = MonteCarloEngine(cfg_mb, observations, strategy=strategy).run_deterministic_stress_tests()
    export_json(stress_results, out_dir / "stress_test_results.json")
    print(f"      Completed {len(stress_results)} stress scenarios; exported stress_test_results.json")

    # 6. Out-of-Sample Holdout Diagnostics (Untouched 2024 Data)
    print("\n[6/8] Evaluating untouched 2024 holdout diagnostics against predictive distributions...")
    # Gather sample predictive paths from moving-block bootstrap
    holdout_evals = []
    mb_engine = MonteCarloEngine(cfg_mb, observations, strategy=strategy)
    for p in mc_mb.representative_paths.values():
        holdout_evals.append(strategy.evaluate_path(p, initial_capital_a=100_000.0))
    # Add a set of 50 sample evaluations for empirical coverage
    mb_model = mb_engine._initialize_model()
    sample_paths = mb_model.generate_paths(num_paths=50, horizon=len(holdout_panel.dates))
    for sp in sample_paths:
        holdout_evals.append(strategy.evaluate_path(sp, initial_capital_a=100_000.0))

    holdout_diag = evaluate_holdout_diagnostics(
        calibration_panel=calib_panel,
        holdout_panel=holdout_panel,
        predictive_evaluations=holdout_evals,
    )
    export_json(holdout_diag, out_dir / "holdout_diagnostics.json")
    print(f"      2024 Realized Volatility: {holdout_diag.realized_fx_volatility_annualized:.2%} (Regime: {holdout_diag.volatility_regime_classification})")
    print("      Exported holdout_diagnostics.json")

    # 7. Export Multi-Metric Convergence Analysis
    print("\n[7/8] Exporting multi-metric convergence diagnostics...")
    if mc_mb.convergence_report:
        export_json(mc_mb.convergence_report, out_dir / "convergence_report.json")
        print("      Exported convergence_report.json")

    # 8. Generate Research Report & Reproducibility Manifest
    print("\n[8/8] Generating phase_4_1_research_report.md and simulation_manifest.json...")
    report_md = generate_research_report(
        calibration=calib_report,
        model_comparisons=model_comparisons,
        stress_results=stress_results,
        bootstrap_result=mc_mb,
        student_t_result=mc_t,
        regime_result=mc_reg,
        gaussian_result=mc_gauss,
        holdout_diag=holdout_diag,
    )
    report_path = out_dir / "phase_4_1_research_report.md"
    report_path.write_text(report_md, encoding="utf-8")
    print(f"      Report written to: {report_path}")

    # Compute artifact digests for reproducibility manifest
    artifacts_to_hash = [
        "calibration_report.json",
        "factor_panel_manifest.json",
        "gaussian_results.json",
        "bootstrap_results.json",
        "student_t_results.json",
        "regime_results.json",
        "stress_test_results.json",
        "model_comparison.json",
        "convergence_report.json",
        "holdout_diagnostics.json",
        "phase_4_1_research_report.md",
    ]
    artifact_hashes = {}
    for fname in artifacts_to_hash:
        fpath = out_dir / fname
        if fpath.exists():
            artifact_hashes[fname] = compute_file_sha256(fpath)

    git_sha = get_git_commit()
    data_manifest_p = ROOT_DIR / "data" / "manifest.json"
    manifest_digest = compute_file_sha256(data_manifest_p) if data_manifest_p.exists() else None

    sim_manifest = {
        "git_commit": git_sha,
        "data_manifest_digest": manifest_digest,
        "environment": {
            "python_version": sys.version,
            "numpy_version": np.__version__,
            "scipy_version": scipy.__version__,
            "platform": sys.platform,
        },
        "calibration_window": {
            "start": "2020-01-01",
            "end": "2023-12-31",
            "trading_days": calib_panel.effective_sample_size,
        },
        "holdout_window": {
            "start": "2024-01-01",
            "end": "2024-12-31",
            "trading_days": holdout_panel.effective_sample_size,
        },
        "simulation_parameters": {
            "num_paths": num_paths,
            "horizon_steps": horizon_steps,
            "random_seed": random_seed,
            "output_directory": str(out_dir),
        },
        "models_evaluated": [
            "multivariate_gaussian",
            "moving_block_bootstrap",
            "iid_bootstrap",
            "stationary_bootstrap",
            "multivariate_student_t",
            "regime_conditioned_bootstrap",
        ],
        "artifact_hashes": artifact_hashes,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    export_json(sim_manifest, out_dir / "simulation_manifest.json")
    print("      Exported simulation_manifest.json with complete environment provenance")

    # Display cross-model summary table in console
    print("\n" + "=" * 140)
    print(" PHASE 4.1 MONTE CARLO CROSS-MODEL RISK & RETURN SUMMARY")
    print("=" * 140)
    print(f"{'Model Name':<32} | {'Paths':<7} | {'Median Ret':<10} | {'Mean Ret':<10} | {'Vol':<8} | {'VaR (95%)':<10} | {'CVaR (95%)':<11} | {'Prob(Loss)':<16} | {'Prob(DD>=10%)':<13}")
    print("-" * 140)
    for mc in model_comparisons:
        se_str = f"±{mc.prob_loss_se:.2%}"
        print(
            f"{mc.model_name:<32} | {mc.num_paths:<7,} | {mc.median_return:<+10.2%} | {mc.mean_return:<+10.2%} | "
            f"{mc.std_return:<8.2%} | {mc.var_95:<+10.2%} | {mc.cvar_95:<+11.2%} | {mc.prob_loss:<6.1%} ({se_str:<7}) | {mc.prob_drawdown_10pct:<13.1%}"
        )
    print("=" * 140 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 4.1 Monte Carlo Simulation Integrity Research Runner")
    parser.add_argument("--paths", type=int, default=1000, help="Number of simulation paths per model (default: 1000)")
    parser.add_argument("--horizon", type=int, default=252, help="Simulation horizon in trading days (default: 252)")
    parser.add_argument("--seed", type=int, default=42, help="Random number generator seed (default: 42)")
    parser.add_argument("--output-dir", type=str, default="data/results/phase_4_1", help="Output directory for Phase 4.1 results")
    parser.add_argument("--smoke", action="store_true", help="Run fast smoke test with 50 paths over 30 steps")
    args = parser.parse_args()

    paths = 50 if args.smoke else args.paths
    horizon = 30 if args.smoke else args.horizon
    out_path = ROOT_DIR / Path(args.output_dir)

    run_monte_carlo_laboratory(
        num_paths=paths,
        horizon_steps=horizon,
        random_seed=args.seed,
        output_dir=out_path,
    )


if __name__ == "__main__":
    main()
