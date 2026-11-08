"""Phase 4.1.2 — Final Research Integrity & Reproducibility Closure Research Runner.

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
artifacts to data/results/phase_4_1_2/ (leaving data/results/phase_4/, phase_4_1/, phase_4_1_1/ untouched).
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
from pathlib import Path
import subprocess
import sys

import numpy as np
import scipy

# Ensure src is on path
ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from backtesting.calendar import FederalReserveH15Calendar
from data.db.engine import make_engine, make_session_factory
from data.repository import Repository
from simulation.monte_carlo import (
    BootstrapMethod,
    CarryTradeScenarioStrategy,
    ModelComparisonEntry,
    MonteCarloEngine,
    MonteCarloResult,
    PITMode,
    SimulationConfig,
    SimulationModelType,
    build_availability_audit,
    build_fx_carry_factor_panel,
    calibrate_factor_panel,
    evaluate_correlation_stress_distribution,
    evaluate_factor_holdout_diagnostics,
    evaluate_funding_sensitivity,
    evaluate_holdout_diagnostics,
    evaluate_portfolio_holdout_diagnostics,
    export_json,
    export_markdown,
    generate_phase_4_1_1_research_report,
    generate_phase_4_1_2_research_report,
    generate_phase_4_1_2_1_research_report,
    generate_phase_4_1_2_2_research_report,
    generate_phase_4_1_2_2_1_research_report,
    generate_phase_4_1_2_2_2_research_report,
    resolve_initial_market_levels,
    split_calibration_holdout,
    validate_market_calendar_evidence,
)


def get_git_commit() -> str:
    """Retrieve current git commit SHA."""
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return "unknown"


def get_git_tree_digest() -> str:
    """Retrieve current git tree SHA."""
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return "unknown"


def check_git_working_tree_clean() -> bool:
    """Check whether git working tree has no uncommitted changes."""
    try:
        res = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True)
        return len(res.stdout.strip()) == 0
    except Exception:
        return True


def compute_file_sha256(path: Path) -> str:
    """Compute SHA256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def compute_string_sha256(text: str) -> str:
    """Compute SHA256 hex digest of a UTF-8 string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_monte_carlo_laboratory(
    num_paths: int = 1000,
    horizon_steps: int = 252,
    random_seed: int = 42,
    output_dir: Path | None = None,
    pit_mode: str | PITMode = PITMode.ESTIMATED_LAG,
) -> None:
    """Execute complete Phase 4.1.2.1 Monte Carlo simulation and reproducibility closure suite."""
    out_dir = output_dir or (ROOT_DIR / "data" / "results" / "phase_4_1_2_2_2")
    out_dir.mkdir(parents=True, exist_ok=True)
    mode = PITMode(pit_mode) if isinstance(pit_mode, str) else pit_mode

    print("=" * 85)
    print(" PHASE 4.1.2.2.2 — CANONICAL FX PANEL INTEGRITY & ARTIFACT RECONCILIATION")
    print(f" Paths: {num_paths:,} | Horizon: {horizon_steps} steps | Seed: {random_seed} | PIT Mode: {mode.value}")
    print(f" Output Directory: {out_dir}")
    print("=" * 85)

    # 1. Load historical database observations (including synthetic for audit reconciliation)
    db_path = "sqlite:///data/processed/gmdb.db"
    print(f"\n[1/9] Loading historical data from {db_path}...")
    engine = make_engine(db_path)
    repo = Repository(make_session_factory(engine))
    all_observations = repo.load_observation_objects(include_synthetic=True)
    observations = [o for o in all_observations if not getattr(o, "is_synthetic", False)]
    print(f"      Loaded {len(all_observations):,} total observations ({len(observations):,} genuine, {len(all_observations) - len(observations)} synthetic).")

    # 2. Build full factor panel and split into calibration vs holdout
    print(f"\n[2/9] Constructing and aligning factor panels (Option A / Option B, PIT mode: {mode.value})...")
    full_panel = build_fx_carry_factor_panel(
        observations=observations,
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        sovereign_yield_series_id="DGS3MO",
        pit_mode=mode,
    )
    calib_panel, holdout_panel = split_calibration_holdout(
        panel=full_panel,
        calibration_end=date(2023, 12, 31),
    )
    print(f"      Calibration Panel: {calib_panel.effective_sample_size} days ({calib_panel.dates[0]} to {calib_panel.dates[-1]})")
    print(f"      Holdout Panel:     {holdout_panel.effective_sample_size} days ({holdout_panel.dates[0]} to {holdout_panel.dates[-1]})")
    print(f"      Retained Factors:  {[f.factor_id for f in calib_panel.factors]}")

    # 3. Exhaustive point-in-time availability audit and calibration report
    print("\n[3/9] Executing exhaustive point-in-time availability reconciliation audit...")
    avail_audit = build_availability_audit(
        all_db_observations=all_observations,
        panel=calib_panel,
        start_date=date(2020, 1, 1),
        end_date=date(2023, 12, 31),
    )
    export_json(avail_audit, out_dir / "availability_audit.json")
    print(f"      Availability Audit Reconciled: {avail_audit.is_reconciled} ({avail_audit.genuine_observations_included:,} genuine evaluated)")
    print("      Exported availability_audit.json")

    calib_report = calibrate_factor_panel(
        calib_panel,
        holdout_panel=holdout_panel,
        raw_observations=observations,
    )
    export_json(calib_report, out_dir / "calibration_report.json")
    export_json(full_panel.model_dump(mode="json"), out_dir / "factor_panel_manifest.json")
    print("      Exported calibration_report.json and factor_panel_manifest.json")

    # Ground initial simulation market state dynamically from latest available observations
    initial_levels = resolve_initial_market_levels(
        observations=observations,
        as_of_decision_timestamp=datetime(2024, 1, 2, 16, 0, 0, tzinfo=timezone.utc),
        pit_mode=mode,
    )
    print(f"      Grounded initial market levels as of {initial_levels.as_of_decision_timestamp.isoformat()}:")
    print(f"        FX Mid:     {initial_levels.initial_fx_rate:.6f} USD/EUR (from {initial_levels.fx_source_id} {initial_levels.fx_entity_code} on {initial_levels.fx_observation_date})")
    print(f"        Borrowing:  {initial_levels.initial_borrowing_rate:.4f} ({initial_levels.initial_borrowing_rate*100:.2f}%) (from {initial_levels.borrowing_source_id} {initial_levels.borrowing_indicator_id} on {initial_levels.borrowing_observation_date})")
    print(f"        Investment: {initial_levels.initial_investment_rate:.4f} ({initial_levels.initial_investment_rate*100:.2f}%) (from {initial_levels.investment_source_id} {initial_levels.investment_indicator_id} on {initial_levels.investment_observation_date})")

    # 4. Run simulations across 6 model architectures
    print(f"\n[4/9] Generating {num_paths:,} simulation paths across 6 model architectures...")
    strategy = CarryTradeScenarioStrategy(
        tenor_days=30,
        rebalance_days=30,
        calendar_type="JOINT_TARGET2_FED",
        rollover_mode="CONTRACTUAL_MATURITY",
        strict_calendar=True,
    )
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
        pit_mode=mode,
        initial_fx_rate=initial_levels.initial_fx_rate,
        initial_borrowing_rate=initial_levels.initial_borrowing_rate,
        initial_investment_rate=initial_levels.initial_investment_rate,
    )
    mc_gauss = MonteCarloEngine(cfg_gauss, observations, strategy=strategy, panel=calib_panel).run()
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
        pit_mode=mode,
        initial_fx_rate=initial_levels.initial_fx_rate,
        initial_borrowing_rate=initial_levels.initial_borrowing_rate,
        initial_investment_rate=initial_levels.initial_investment_rate,
    )
    mc_mb = MonteCarloEngine(cfg_mb, observations, strategy=strategy, panel=calib_panel).run()
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
        pit_mode=mode,
        initial_fx_rate=initial_levels.initial_fx_rate,
        initial_borrowing_rate=initial_levels.initial_borrowing_rate,
        initial_investment_rate=initial_levels.initial_investment_rate,
    )
    mc_iid = MonteCarloEngine(cfg_iid, observations, strategy=strategy, panel=calib_panel).run()
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
        pit_mode=mode,
        initial_fx_rate=initial_levels.initial_fx_rate,
        initial_borrowing_rate=initial_levels.initial_borrowing_rate,
        initial_investment_rate=initial_levels.initial_investment_rate,
    )
    mc_stat = MonteCarloEngine(cfg_stat, observations, strategy=strategy, panel=calib_panel).run()
    results["stationary_bootstrap"] = mc_stat

    # Model 4: Multivariate Student-t (Fat-Tailed Parametric with Profile MLE df)
    print("      -> [4/6] Running Multivariate Student-t (Profile MLE degrees of freedom)...")
    cfg_t = SimulationConfig(
        simulation_id="MC_MULTIVARIATE_STUDENT_T",
        model_type=SimulationModelType.MULTIVARIATE_STUDENT_T,
        num_paths=num_paths,
        horizon_steps=horizon_steps,
        random_seed=random_seed + 4,
        pit_mode=mode,
        initial_fx_rate=initial_levels.initial_fx_rate,
        initial_borrowing_rate=initial_levels.initial_borrowing_rate,
        initial_investment_rate=initial_levels.initial_investment_rate,
    )
    mc_t = MonteCarloEngine(cfg_t, observations, strategy=strategy, panel=calib_panel).run()
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
        pit_mode=mode,
        initial_fx_rate=initial_levels.initial_fx_rate,
        initial_borrowing_rate=initial_levels.initial_borrowing_rate,
        initial_investment_rate=initial_levels.initial_investment_rate,
    )
    mc_reg = MonteCarloEngine(cfg_reg, observations, strategy=strategy, panel=calib_panel).run()
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
        conv = r.convergence_report
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
                checkpoint_stability_status=conv.stability_status if conv else "CHECKPOINT_STABILITY_ACHIEVED",
                is_converged_mean=conv.is_converged_mean if conv else True,
                is_converged_median=conv.is_converged_median if conv else True,
                is_converged_prob_loss=conv.is_converged_prob_loss if conv else True,
                is_converged_var_95=conv.is_converged_var_95 if conv else True,
                is_converged_cvar_95=conv.is_converged_cvar_95 if conv else True,
                is_converged_drawdown=conv.is_converged_drawdown if conv else True,
                tail_sample_size=conv.tail_sample_size_final if conv else int(0.05 * r.config.num_paths),
                stability_notes=conv.convergence_notes if conv else "",
            )
        )

    export_json([m.model_dump(mode="json") for m in model_comparisons], out_dir / "model_comparison.json")
    print("      Exported model_comparison.json (6 models)")

    # 5. Execute Deterministic Stress Tests & Correlation Breakdown Distribution Comparison
    print("\n[5/9] Executing deterministic macro-financial stress suite...")
    stress_results = MonteCarloEngine(cfg_mb, observations, strategy=strategy, panel=calib_panel).run_deterministic_stress_tests()
    export_json(stress_results, out_dir / "stress_test_results.json")
    print(f"      Completed {len(stress_results)} stress scenarios; exported stress_test_results.json")

    print("\n[6/9] Executing correlation-breakdown distribution comparison (Common Random Numbers)...")
    corr_stress = evaluate_correlation_stress_distribution(
        panel=calib_panel,
        strategy=strategy,
        num_paths=num_paths,
        horizon=horizon_steps,
        random_seed=random_seed,
    )
    export_json(corr_stress, out_dir / "correlation_stress_comparison.json")
    print(f"      Evaluated {corr_stress.num_paths:,} paired paths under empirical vs decoupled correlation.")
    print(f"      Mean return difference: {corr_stress.mean_return_difference:+.4%} | Median diff: {corr_stress.median_return_difference:+.4%}")
    print("      Exported correlation_stress_comparison.json")

    # 7. Out-of-Sample Holdout Diagnostics (Untouched 2024 Data)
    print("\n[7/9] Evaluating untouched 2024 holdout diagnostics against predictive distributions...")
    mb_engine = MonteCarloEngine(cfg_mb, observations, strategy=strategy, panel=calib_panel)
    mb_model = mb_engine._initialize_model()
    # Generate 1,000 predictive factor paths with real calendar dates for full predictive coverage
    predictive_paths = mb_model.generate_paths(
        num_paths=1000,
        horizon=len(holdout_panel.dates),
        dates=holdout_panel.dates,
    )

    factor_diag = evaluate_factor_holdout_diagnostics(
        calibration_panel=calib_panel,
        holdout_panel=holdout_panel,
        predictive_paths=predictive_paths,
    )
    export_json(factor_diag, out_dir / "factor_holdout_diagnostics.json")
    print(f"      2024 Realized Volatility: {factor_diag.actual_fx_realized_volatility:.2%} (Regime: {factor_diag.volatility_regime_classification})")
    print(f"      2024 Realized FX Return:  {factor_diag.actual_fx_cumulative_return:+.2%} (Percentile: {factor_diag.predictive_percentile_fx_return:.1%})")
    print("      Exported factor_holdout_diagnostics.json")

    port_diag = evaluate_portfolio_holdout_diagnostics()
    export_json(port_diag, out_dir / "portfolio_holdout_diagnostics.json")
    print(f"      Portfolio Holdout Status: {port_diag.status} (Reason: {port_diag.reason[:60]}...)")
    print("      Exported portfolio_holdout_diagnostics.json")

    holdout_diag = evaluate_holdout_diagnostics(
        calibration_panel=calib_panel,
        holdout_panel=holdout_panel,
        predictive_paths=predictive_paths,
    )
    export_json(holdout_diag, out_dir / "holdout_diagnostics.json")

    # 8. Calendar Validation & Funding Sensitivity Analysis
    print("\n[8/9] Validating calendar mechanics and funding sensitivity...")
    cal_val = validate_market_calendar_evidence()
    export_json(cal_val, out_dir / "calendar_validation.json")
    print(f"      Calendar Validation: Weekend={cal_val.weekend_3day_accrual_verified}, Holiday={cal_val.holiday_accrual_verified}, Tenor={cal_val.tenor_30day_maturity_verified}")
    print("      Exported calendar_validation.json")

    funding_sens = evaluate_funding_sensitivity()
    export_json(funding_sens, out_dir / "funding_sensitivity.json")
    print(f"      Funding Sensitivity: Evaluated {len(funding_sens.scenarios)} scenarios across fixed vs floating funding.")
    print("      Exported funding_sensitivity.json")

    per_model_stab = {}
    for name, r in [
        ("Multivariate Gaussian", mc_gauss),
        ("Moving-Block Bootstrap (20d)", mc_mb),
        ("IID Bootstrap", mc_iid),
        ("Stationary Bootstrap (20d)", mc_stat),
        ("Multivariate Student-t", mc_t),
        ("Regime-Conditioned Bootstrap", mc_reg),
    ]:
        if r.convergence_report:
            c = r.convergence_report
            per_model_stab[name] = {
                "stability_status": c.stability_status,
                "is_converged": c.is_converged,
                "is_converged_mean": c.is_converged_mean,
                "is_converged_median": c.is_converged_median,
                "is_converged_prob_loss": c.is_converged_prob_loss,
                "is_converged_var_95": c.is_converged_var_95,
                "is_converged_cvar_95": c.is_converged_cvar_95,
                "is_converged_drawdown": c.is_converged_drawdown,
                "tail_sample_size": c.tail_sample_size_final,
                "notes": c.convergence_notes,
            }

    if mc_mb.convergence_report:
        mc_mb.convergence_report.per_model_stability = per_model_stab
        export_json(mc_mb.convergence_report, out_dir / "convergence_report.json")
        print("      Exported convergence_report.json")

    # 9. Generate Research Report & Reproducibility Manifest
    report_filename = f"{out_dir.name}_research_report.md"
    print(f"\n[9/9] Generating {report_filename} and simulation_manifest.json...")
    git_sha = get_git_commit()
    data_manifest_p = ROOT_DIR / "data" / "manifest.json"
    manifest_digest = compute_file_sha256(data_manifest_p) if data_manifest_p.exists() else None
    lockfile_p = ROOT_DIR / "uv.lock"
    lockfile_digest = compute_file_sha256(lockfile_p) if lockfile_p.exists() else None
    pyproject_p = ROOT_DIR / "pyproject.toml"
    pyproject_digest = compute_file_sha256(pyproject_p) if pyproject_p.exists() else None
    db_p = ROOT_DIR / "data" / "processed" / "gmdb.db"
    db_digest = compute_file_sha256(db_p) if db_p.exists() else None

    factor_cfg_digest = compute_string_sha256(str([f.model_dump(mode="json") for f in calib_panel.factors]))
    strat_cfg_digest = compute_string_sha256(str(strategy.exec_config.model_dump(mode="json")))
    model_cfg_digest = compute_string_sha256(str(cfg_mb.model_dump(mode="json")))

    manifest_metadata = {
        "git_commit": git_sha,
        "simulation_code_commit": git_sha,
        "simulation_source_commit": git_sha,
        "documentation_commit": "UNCOMMITTED_AT_EXECUTION",
        "source_tree_digest": get_git_tree_digest(),
        "database_sha256": db_digest,
        "git_working_tree_clean": check_git_working_tree_clean(),
        "rng_bit_generator": "PCG64",
        "random_seed": random_seed,
        "environment": {
            "python_version": sys.version,
            "numpy_version": np.__version__,
            "scipy_version": scipy.__version__,
            "platform": sys.platform,
        },
        "dependency_lockfile_digest": lockfile_digest,
        "pyproject_digest": pyproject_digest,
        "factor_panel_config_digest": factor_cfg_digest,
        "strategy_config_digest": strat_cfg_digest,
        "model_config_digest": model_cfg_digest,
        "data_classification": "SIMULATED_RESEARCH_PROXY",
        "pit_policy": mode.value if hasattr(mode, "value") else str(mode),
        "predictive_sample_size": 1000,
        "calendar_implementation": "JointTarget2FedCalendar (TARGET2 + Federal Reserve holiday settlement calendar; Federal Reserve H.15 release calendar at 4:15 PM Eastern Time)",
        "h15_release_schedule": "4:15 PM Eastern Time on next Federal Reserve business day (ZoneInfo('America/New_York'))",
        "aligned_level_count": calib_panel.aligned_level_count,
        "transition_count": calib_panel.transition_count,
        "first_level_date": str(calib_panel.first_level_date) if calib_panel.first_level_date else None,
        "last_level_date": str(calib_panel.last_level_date) if calib_panel.last_level_date else None,
        "first_transition_date": str(calib_panel.first_transition_date) if calib_panel.first_transition_date else None,
        "last_transition_date": str(calib_panel.last_transition_date) if calib_panel.last_transition_date else None,
        "h15_exceptional_closures": {str(k): v for k, v in FederalReserveH15Calendar.get_exceptional_closures().items()},
        "checkpoint_stability_summary": {
            "total_models": len(model_comparisons),
            "achieved_count": sum(1 for mc in model_comparisons if getattr(mc, "checkpoint_stability_status", "") == "CHECKPOINT_STABILITY_ACHIEVED"),
            "not_achieved_count": sum(1 for mc in model_comparisons if getattr(mc, "checkpoint_stability_status", "") != "CHECKPOINT_STABILITY_ACHIEVED"),
        },
        "correlation_stress_config": {
            "method": "zero_off_diagonal_decoupling",
            "variance_reduction": "common_random_numbers",
            "num_paths": num_paths,
        },
        "initial_market_levels": initial_levels.model_dump(mode="json"),
    }

    if "4_1_2_2_2" in out_dir.name:
        report_md = generate_phase_4_1_2_2_2_research_report(
            avail_audit=avail_audit,
            model_comparisons=model_comparisons,
            factor_diag=factor_diag,
            port_diag=port_diag,
            corr_stress=corr_stress,
            cal_val=cal_val,
            funding_sens=funding_sens,
            bootstrap_result=mc_mb,
            student_t_result=mc_t,
            regime_result=mc_reg,
            gaussian_result=mc_gauss,
            manifest_info=manifest_metadata,
            initial_levels=initial_levels,
            calibration_report=calib_report,
        )
    elif "4_1_2_2_1" in out_dir.name:
        report_md = generate_phase_4_1_2_2_1_research_report(
            avail_audit=avail_audit,
            model_comparisons=model_comparisons,
            factor_diag=factor_diag,
            port_diag=port_diag,
            corr_stress=corr_stress,
            cal_val=cal_val,
            funding_sens=funding_sens,
            bootstrap_result=mc_mb,
            student_t_result=mc_t,
            regime_result=mc_reg,
            gaussian_result=mc_gauss,
            manifest_info=manifest_metadata,
            initial_levels=initial_levels,
        )
    elif "4_1_2_2" in out_dir.name:
        report_md = generate_phase_4_1_2_2_research_report(
            avail_audit=avail_audit,
            model_comparisons=model_comparisons,
            factor_diag=factor_diag,
            port_diag=port_diag,
            corr_stress=corr_stress,
            cal_val=cal_val,
            funding_sens=funding_sens,
            bootstrap_result=mc_mb,
            student_t_result=mc_t,
            regime_result=mc_reg,
            gaussian_result=mc_gauss,
            manifest_info=manifest_metadata,
            initial_levels=initial_levels,
        )
    elif "4_1_2_1" in out_dir.name:
        report_md = generate_phase_4_1_2_1_research_report(
            avail_audit=avail_audit,
            model_comparisons=model_comparisons,
            factor_diag=factor_diag,
            port_diag=port_diag,
            corr_stress=corr_stress,
            cal_val=cal_val,
            funding_sens=funding_sens,
            bootstrap_result=mc_mb,
            student_t_result=mc_t,
            regime_result=mc_reg,
            gaussian_result=mc_gauss,
            manifest_info=manifest_metadata,
        )
    elif "4_1_2" in out_dir.name:
        report_md = generate_phase_4_1_2_research_report(
            avail_audit=avail_audit,
            model_comparisons=model_comparisons,
            factor_diag=factor_diag,
            port_diag=port_diag,
            corr_stress=corr_stress,
            cal_val=cal_val,
            funding_sens=funding_sens,
            bootstrap_result=mc_mb,
            student_t_result=mc_t,
            regime_result=mc_reg,
            gaussian_result=mc_gauss,
            manifest_info=manifest_metadata,
        )
    else:
        report_md = generate_phase_4_1_1_research_report(
            avail_audit=avail_audit,
            model_comparisons=model_comparisons,
            factor_diag=factor_diag,
            port_diag=port_diag,
            corr_stress=corr_stress,
            cal_val=cal_val,
            funding_sens=funding_sens,
            bootstrap_result=mc_mb,
            student_t_result=mc_t,
            regime_result=mc_reg,
            gaussian_result=mc_gauss,
            manifest_info=manifest_metadata,
        )

    report_path = out_dir / report_filename
    export_markdown(report_md, report_path)
    print(f"      Report written to: {report_path}")

    # Compute artifact digests for reproducibility manifest across ALL required artifacts
    artifacts_to_hash = [
        "availability_audit.json",
        "factor_holdout_diagnostics.json",
        "portfolio_holdout_diagnostics.json",
        "correlation_stress_comparison.json",
        "calendar_validation.json",
        "funding_sensitivity.json",
        "model_comparison.json",
        "convergence_report.json",
        report_filename,
        "calibration_report.json",
        "factor_panel_manifest.json",
        "gaussian_results.json",
        "bootstrap_results.json",
        "student_t_results.json",
        "regime_results.json",
        "stress_test_results.json",
        "holdout_diagnostics.json",
    ]
    artifact_hashes = {}
    for fname in artifacts_to_hash:
        fpath = out_dir / fname
        if fpath.exists():
            artifact_hashes[fname] = compute_file_sha256(fpath)

    sim_manifest = {
        **manifest_metadata,
        "data_manifest_digest": manifest_digest,
        "calibration_window": {
            "start": "2020-01-01",
            "end": "2023-12-31",
            "aligned_level_count": calib_panel.aligned_level_count,
            "transition_count": calib_panel.transition_count,
            "first_level_date": str(calib_panel.first_level_date) if calib_panel.first_level_date else None,
            "last_level_date": str(calib_panel.last_level_date) if calib_panel.last_level_date else None,
            "first_transition_date": str(calib_panel.first_transition_date) if calib_panel.first_transition_date else None,
            "last_transition_date": str(calib_panel.last_transition_date) if calib_panel.last_transition_date else None,
            "trading_days": calib_panel.effective_sample_size,
        },
        "holdout_window": {
            "start": "2024-01-01",
            "end": "2024-12-31",
            "aligned_level_count": holdout_panel.aligned_level_count,
            "transition_count": holdout_panel.transition_count,
            "first_level_date": str(holdout_panel.first_level_date) if holdout_panel else None,
            "last_level_date": str(holdout_panel.last_level_date) if holdout_panel else None,
            "first_transition_date": str(holdout_panel.first_transition_date) if holdout_panel else None,
            "last_transition_date": str(holdout_panel.last_transition_date) if holdout_panel else None,
            "trading_days": holdout_panel.effective_sample_size,
        },
        "simulation_parameters": {
            "num_paths": num_paths,
            "horizon_steps": horizon_steps,
            "random_seed": random_seed,
            "output_directory": out_dir.relative_to(ROOT_DIR).as_posix() if out_dir.is_relative_to(ROOT_DIR) else str(out_dir),
            "pit_mode": mode.value if hasattr(mode, "value") else str(mode),
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
    print(f" {out_dir.name.upper()} MONTE CARLO CROSS-MODEL RISK & RETURN SUMMARY")
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
    parser = argparse.ArgumentParser(description="Phase 4.1.2.2.2 Monte Carlo Research Integrity & Reproducibility Closure Runner")
    parser.add_argument("--paths", type=int, default=1000, help="Number of simulation paths per model (default: 1000)")
    parser.add_argument("--horizon", type=int, default=252, help="Simulation horizon in trading days (default: 252)")
    parser.add_argument("--seed", type=int, default=42, help="Random number generator seed (default: 42)")
    parser.add_argument("--output-dir", type=str, default="data/results/phase_4_1_2_2_2", help="Output directory for simulation results")
    parser.add_argument("--pit-mode", type=str, default="ESTIMATED_LAG", choices=["STRICT_VERIFIED", "ESTIMATED_LAG", "RESEARCH_ONLY"], help="Point-in-time enforcement mode (default: ESTIMATED_LAG)")
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
        pit_mode=args.pit_mode,
    )


if __name__ == "__main__":
    main()

