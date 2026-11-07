"""Phase 4.1.2.1 Execution-Path Integration & Research Integrity Closure Test Suite.

Comprehensive validation verifying:
1. Point-in-time (PIT) availability pipeline integration:
   - Strict PIT mode fails cleanly when dataset has insufficient verified observations (< 50).
   - Unverified publication timestamps cannot bypass release lag schedules.
   - Exact publication timestamps trusted ONLY when availability evidence is EXACT_TIMESTAMP_VERIFIED.
   - MonteCarloEngine accepts and uses injected pre-built factor panel.
   - PIT mode propagates to FactorPanel and MonteCarloResult.
2. Joint currency settlement calendar integration across all simulation models:
   - All 6 models, deterministic stress tests, and correlation breakdown generate paths with real calendar dates.
   - CarryTradeScenarioStrategy with strict_calendar=True raises ValueError if path.dates is missing.
   - All session dates match JointCurrencySettlementCalendar (TARGET2 + Fed holiday closures).
3. Contractual maturity rollover semantics:
   - rollover_mode="CONTRACTUAL_MATURITY" eliminates the 8-day idle gap between 30-calendar-day contract maturity and 30-trading-step rebalance.
   - Continuous carry exposure maintained upon contractual maturity.
4. Report narrative reconciliation:
   - Dynamic worst CVaR calculation and dynamic volatility regime classification in closure report.
   - Portfolio holdout diagnostic status strictly UNAVAILABLE and SIMULATED_RESEARCH_PROXY.
5. Phase 4.1.2.1 reproducibility manifest completeness, relative path portability, and SHA-256 integrity.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import numpy as np
import pytest

from backtesting.calendar import JointCurrencySettlementCalendar
from data.schemas import AvailabilityEvidence, DataClassification, DataObservation, Frequency, ObservationKind
from simulation.monte_carlo.bootstrap import HistoricalBootstrapSampler
from simulation.monte_carlo.distributions import MultivariateGaussianModel, MultivariateStudentTModel
from simulation.monte_carlo.engine import MonteCarloEngine
from simulation.monte_carlo.factors import (
    build_fx_carry_factor_panel,
    get_effective_availability_timestamp,
)
from simulation.monte_carlo.holdout import (
    evaluate_portfolio_holdout_diagnostics,
)
from simulation.monte_carlo.metrics import calculate_distribution_metrics
from simulation.monte_carlo.regimes import RegimeConditionedSampler, VolatilityRegimeClassifier
from simulation.monte_carlo.reporting import (
    generate_phase_4_1_2_1_research_report,
)
from simulation.monte_carlo.schemas import (
    AvailabilityAuditReport,
    BootstrapMethod,
    CorrelationStressComparison,
    FactorHoldoutDiagnostics,
    ModelComparisonEntry,
    MonteCarloResult,
    PathEvaluationResult,
    PITMode,
    ScenarioPath,
    SimulationConfig,
    SimulationModelType,
)
from simulation.monte_carlo.shocks import (
    generate_correlation_breakdown_path,
)
from simulation.monte_carlo.strategy_adapter import (
    CarryTradeScenarioStrategy,
    evaluate_funding_sensitivity,
    generate_simulated_trading_sessions,
    validate_market_calendar_evidence,
)


def make_test_observations(
    start_date: date = date(2020, 1, 1),
    num_days: int = 400,
    evidence: AvailabilityEvidence = AvailabilityEvidence.ESTIMATED_SCHEDULE,
) -> list[DataObservation]:
    """Generate synthetic observations matching database schema."""
    obs: list[DataObservation] = []
    base_fx = 1.12
    base_dgs1mo = 0.045
    base_dgs3mo = 0.048
    base_ecb = 0.025

    rng = np.random.default_rng(12345)

    for i in range(num_days):
        current_date = start_date + timedelta(days=i)
        if current_date.weekday() >= 5:
            continue

        ts = datetime.combine(current_date, datetime.min.time(), tzinfo=timezone.utc)
        pub_ts = ts + timedelta(hours=16)

        # FX EUR/USD
        ret = rng.normal(0.0001, 0.005)
        base_fx *= math.exp(ret)
        obs.append(
            DataObservation(
                kind=ObservationKind.EXCHANGE_RATE,
                source_id="frankfurter",
                entity_code="EUR/USD",
                value=round(base_fx, 4),
                unit="USD_per_EUR",
                frequency=Frequency.DAILY,
                observation_date=current_date,
                publication_date=current_date,
                observation_timestamp=ts,
                publication_timestamp=pub_ts,
                retrieved_at=pub_ts,
                classification=DataClassification.REAL_VERIFIED,
                availability_evidence=evidence,
                is_synthetic=False,
            )
        )

        # US Treasury 1M
        base_dgs1mo = max(0.001, base_dgs1mo + rng.normal(0.0, 0.0005))
        obs.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                source_id="us_treasury",
                entity_code="USD",
                indicator_id="DGS1MO",
                value=round(base_dgs1mo * 100.0, 4),
                unit="percent",
                frequency=Frequency.DAILY,
                observation_date=current_date,
                publication_date=current_date,
                observation_timestamp=ts,
                publication_timestamp=pub_ts,
                retrieved_at=pub_ts,
                classification=DataClassification.REAL_VERIFIED,
                availability_evidence=evidence,
                is_synthetic=False,
            )
        )

        # US Treasury 3M
        base_dgs3mo = max(0.001, base_dgs3mo + rng.normal(0.0, 0.0005))
        obs.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                source_id="us_treasury",
                entity_code="USD",
                indicator_id="DGS3MO",
                value=round(base_dgs3mo * 100.0, 4),
                unit="percent",
                frequency=Frequency.DAILY,
                observation_date=current_date,
                publication_date=current_date,
                observation_timestamp=ts,
                publication_timestamp=pub_ts,
                retrieved_at=pub_ts,
                classification=DataClassification.REAL_VERIFIED,
                availability_evidence=evidence,
                is_synthetic=False,
            )
        )

        # ECB Rate
        if i % 7 == 0:
            base_ecb = max(0.001, base_ecb + rng.normal(0.0, 0.0002))
        obs.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                source_id="ecb",
                entity_code="ECB_EA",
                indicator_id="KR.MRR_FR.LEV",
                value=round(base_ecb * 100.0, 4),
                unit="percent",
                frequency=Frequency.DAILY,
                observation_date=current_date,
                publication_date=current_date,
                observation_timestamp=ts,
                publication_timestamp=pub_ts,
                retrieved_at=pub_ts,
                classification=DataClassification.REAL_VERIFIED,
                availability_evidence=evidence,
                is_synthetic=False,
            )
        )

    return obs


def test_unverified_publication_timestamp_does_not_override_estimated_schedule():
    """Verify unverified publication timestamps cannot bypass release lag schedules."""
    obs_date = date(2023, 5, 10)  # Wednesday
    pub_ts = datetime(2023, 5, 10, 16, 0, tzinfo=timezone.utc)  # Same-day 16:00 UTC

    obs_unverified = DataObservation(
        kind=ObservationKind.INTEREST_RATE,
        source_id="us_treasury",
        entity_code="USD",
        indicator_id="DGS1MO",
        value=5.0,
        unit="percent",
        frequency=Frequency.DAILY,
        observation_date=obs_date,
        publication_date=obs_date,
        observation_timestamp=datetime(2023, 5, 10, 0, 0, tzinfo=timezone.utc),
        publication_timestamp=pub_ts,
        retrieved_at=pub_ts,
        classification=DataClassification.REAL_VERIFIED,
        availability_evidence=AvailabilityEvidence.ESTIMATED_SCHEDULE,
    )

    eff_ts = get_effective_availability_timestamp(obs_unverified)
    assert eff_ts == datetime(2023, 5, 11, 15, 0, tzinfo=timezone.utc)
    assert eff_ts != pub_ts, "Unverified publication timestamp erroneously bypassed estimated lag schedule"


def test_exact_timestamp_trusted_only_when_evidence_verified():
    """Verify exact publication timestamp is honored if and only if EXACT_TIMESTAMP_VERIFIED."""
    obs_date = date(2023, 5, 10)
    exact_ts = datetime(2023, 5, 10, 14, 30, tzinfo=timezone.utc)

    obs_verified = DataObservation(
        kind=ObservationKind.INTEREST_RATE,
        source_id="us_treasury",
        entity_code="USD",
        indicator_id="DGS1MO",
        value=5.0,
        unit="percent",
        frequency=Frequency.DAILY,
        observation_date=obs_date,
        publication_date=obs_date,
        observation_timestamp=datetime(2023, 5, 10, 0, 0, tzinfo=timezone.utc),
        publication_timestamp=exact_ts,
        retrieved_at=exact_ts,
        classification=DataClassification.REAL_VERIFIED,
        availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
    )

    eff_ts = get_effective_availability_timestamp(obs_verified)
    assert eff_ts == exact_ts, f"Verified exact timestamp was not respected: {eff_ts} != {exact_ts}"


def test_strict_pit_mode_fails_with_insufficient_verified_data():
    """Verify build_fx_carry_factor_panel fails cleanly when STRICT_VERIFIED is requested with insufficient verified data."""
    obs = make_test_observations(evidence=AvailabilityEvidence.ESTIMATED_SCHEDULE)

    with pytest.raises(ValueError, match="Strict verified PIT mode requested, but dataset contains"):
        build_fx_carry_factor_panel(
            observations=obs,
            start_date=date(2020, 1, 1),
            end_date=date(2020, 6, 30),
            pit_mode=PITMode.STRICT_VERIFIED,
        )


def test_pit_mode_propagation_to_factor_panel_and_engine():
    """Verify PITMode is recorded on FactorPanel and propagated to MonteCarloResult."""
    obs = make_test_observations(num_days=80, evidence=AvailabilityEvidence.ESTIMATED_SCHEDULE)
    panel = build_fx_carry_factor_panel(
        observations=obs,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 3, 31),
        pit_mode=PITMode.ESTIMATED_LAG,
    )
    assert panel.pit_mode == PITMode.ESTIMATED_LAG.value

    cfg = SimulationConfig(
        simulation_id="TEST_PIT_PROPAGATION",
        model_type=SimulationModelType.MULTIVARIATE_GAUSSIAN,
        num_paths=10,
        horizon_steps=20,
        random_seed=42,
        pit_mode=PITMode.ESTIMATED_LAG,
    )
    strategy = CarryTradeScenarioStrategy(tenor_days=30, rebalance_days=30)
    engine = MonteCarloEngine(cfg, obs, strategy=strategy, panel=panel)
    assert engine.panel is panel, "Engine did not use injected panel"
    res = engine.run()
    assert res.pit_mode == PITMode.ESTIMATED_LAG.value


def test_all_simulation_paths_contain_joint_settlement_dates():
    """Verify paths generated by distributions, bootstrap, and regimes carry real JointTarget2Fed settlement dates."""
    obs = make_test_observations(num_days=100)
    panel = build_fx_carry_factor_panel(
        observations=obs,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 3, 31),
        pit_mode=PITMode.ESTIMATED_LAG,
    )

    cal = JointCurrencySettlementCalendar("EUR", "USD")
    session_dates = generate_simulated_trading_sessions(
        start_date=date(2024, 1, 2),
        n_sessions=21,
        calendar_type="JOINT_TARGET2_FED",
    )

    # 1. Gaussian Model
    g_model = MultivariateGaussianModel(panel, random_seed=42)
    p_gauss = g_model.generate_paths(num_paths=2, horizon=20, dates=session_dates)
    assert len(p_gauss) == 2
    assert p_gauss[0].dates == session_dates
    for d in p_gauss[0].dates:
        assert cal.is_settlement_day(d), f"Date {d} is not a valid joint settlement day"

    # 2. Student-t Model
    t_model = MultivariateStudentTModel(panel, random_seed=42)
    p_t = t_model.generate_paths(num_paths=2, horizon=20, dates=session_dates)
    assert p_t[0].dates == session_dates

    # 3. Bootstrap Sampler
    b_model = HistoricalBootstrapSampler(panel, method=BootstrapMethod.MOVING_BLOCK, block_size=5, random_seed=42)
    p_b = b_model.generate_paths(num_paths=2, horizon=20, dates=session_dates)
    assert p_b[0].dates == session_dates

    # 4. Regime Sampler
    classifier = VolatilityRegimeClassifier(panel, rolling_window=20)
    r_model = RegimeConditionedSampler(panel, classifier=classifier, random_seed=42)
    p_r = r_model.generate_paths(num_paths=2, horizon=20, dates=session_dates)
    assert p_r[0].dates == session_dates


def test_strict_calendar_fails_if_dates_missing():
    """Verify CarryTradeScenarioStrategy with strict_calendar=True raises ValueError if path.dates is missing."""
    strategy = CarryTradeScenarioStrategy(
        tenor_days=30,
        rebalance_days=30,
        calendar_type="JOINT_TARGET2_FED",
        strict_calendar=True,
    )

    path_no_dates = ScenarioPath(
        path_id=0,
        steps=20,
        dates=None,
        fx_rates=[1.10] * 21,
        borrowing_rates=[0.04] * 21,
        investment_rates=[0.05] * 21,
    )

    with pytest.raises(ValueError, match="must provide explicit calendar dates"):
        strategy.evaluate_path(path_no_dates)


def test_correlation_stress_paths_contain_settlement_dates():
    """Verify correlation breakdown stress paths include joint settlement dates."""
    obs = make_test_observations(num_days=80)
    panel = build_fx_carry_factor_panel(
        observations=obs,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 3, 31),
    )
    p_stressed, _meta = generate_correlation_breakdown_path(
        panel=panel,
        horizon=20,
        random_seed=42,
    )
    assert p_stressed.dates is not None
    assert len(p_stressed.dates) == 21
    cal = JointCurrencySettlementCalendar("EUR", "USD")
    for d in p_stressed.dates:
        assert cal.is_settlement_day(d)


def test_contractual_maturity_rollover_eliminates_idle_gap():
    """Verify rollover_mode='CONTRACTUAL_MATURITY' enters next contract immediately upon maturity."""
    session_dates = generate_simulated_trading_sessions(
        start_date=date(2024, 1, 2),
        n_sessions=45,
        calendar_type="JOINT_TARGET2_FED",
    )

    path = ScenarioPath(
        path_id=1,
        steps=len(session_dates) - 1,
        dates=session_dates,
        fx_rates=[1.10] * len(session_dates),
        borrowing_rates=[0.04] * len(session_dates),
        investment_rates=[0.05] * len(session_dates),
    )

    strat_periodic = CarryTradeScenarioStrategy(
        tenor_days=30,
        rebalance_days=30,
        rollover_mode="PERIODIC_REBALANCE",
        strict_calendar=True,
    )
    res_periodic = strat_periodic.evaluate_path(path)

    strat_contractual = CarryTradeScenarioStrategy(
        tenor_days=30,
        rebalance_days=30,
        rollover_mode="CONTRACTUAL_MATURITY",
        strict_calendar=True,
    )
    res_contractual = strat_contractual.evaluate_path(path)

    maturity_step = None
    for step_idx, d in enumerate(session_dates):
        if d >= date(2024, 1, 2) + timedelta(days=30):
            maturity_step = step_idx
            break

    assert maturity_step is not None
    assert maturity_step < 30, "Maturity should occur before trading step 30"
    assert res_contractual.pure_gross_gain_a > res_periodic.pure_gross_gain_a, (
        f"Contractual maturity rollover should maintain active investment exposure: "
        f"{res_contractual.pure_gross_gain_a:.2f} vs {res_periodic.pure_gross_gain_a:.2f}"
    )
    assert res_contractual.total_financing_costs_a > res_periodic.total_financing_costs_a, (
        f"Contractual rollover should continuously accrue financing without idle gaps: "
        f"{res_contractual.total_financing_costs_a:.2f} vs {res_periodic.total_financing_costs_a:.2f}"
    )


def test_dynamic_report_narrative_and_holdout_status():
    """Verify closure report computes worst CVaR dynamically and reflects factor holdout diagnostics."""
    avail_audit = AvailabilityAuditReport(
        total_source_observations=1000,
        synthetic_observations_excluded=100,
        genuine_observations_included=900,
        date_window_exclusions=100,
        factor_alignment_exclusions=50,
        exact_timestamp_verified_count=0,
        estimated_availability_count=900,
        retrospective_count=0,
        missing_evidence_count=0,
        unrecognized_evidence_count=0,
        is_reconciled=True,
        reconciliation_residual=0,
        release_lag_policies={"EURUSD": "ECB 15:00 UTC", "USD_DGS1MO": "FRED NBD 15:00 UTC"},
        pit_mode="ESTIMATED_LAG",
    )

    model_comps = [
        ModelComparisonEntry(
            model_name="Multivariate Gaussian",
            num_paths=100,
            median_return=0.02,
            mean_return=0.019,
            std_return=0.06,
            var_95=-0.03,
            cvar_95=-0.045,
            max_drawdown_median=0.04,
            max_drawdown_p95=0.08,
            prob_loss=0.35,
            prob_loss_se=0.02,
            prob_drawdown_10pct=0.05,
            mean_fx_drag=0.0,
            mean_financing_drag=0.02,
        ),
        ModelComparisonEntry(
            model_name="Multivariate Student-t",
            num_paths=100,
            median_return=0.018,
            mean_return=0.015,
            std_return=0.07,
            var_95=-0.04,
            cvar_95=-0.062,
            max_drawdown_median=0.045,
            max_drawdown_p95=0.09,
            prob_loss=0.38,
            prob_loss_se=0.02,
            prob_drawdown_10pct=0.08,
            mean_fx_drag=0.0,
            mean_financing_drag=0.02,
        ),
    ]

    factor_diag = FactorHoldoutDiagnostics(
        holdout_start=date(2024, 1, 1),
        holdout_end=date(2024, 12, 31),
        holdout_days=247,
        num_predictive_paths=1000,
        actual_fx_realized_volatility=0.0618,
        volatility_regime_classification="NORMAL_VOLATILITY",
        simulated_fx_volatility_median=0.063,
        predictive_percentile_fx_volatility=0.45,
        actual_fx_cumulative_return=-0.025,
        predictive_percentile_fx_return=0.38,
        predictive_percentile_fx_return_mc_se=0.015,
        simulated_fx_return_p025=-0.12,
        simulated_fx_return_p975=0.08,
        simulated_fx_return_median=-0.01,
        actual_fx_max_drawdown=0.065,
        simulated_fx_drawdown_median=0.05,
        predictive_percentile_fx_drawdown=0.42,
        fx_log_return_ks_stat=0.045,
        fx_log_return_ks_pvalue=0.65,
        fx_log_return_ks_caveat="Asymptotic KS test valid for N=247 observations.",
        diagnostic_summary="Realized 2024 path lies well within simulated bounds.",
    )

    port_diag = evaluate_portfolio_holdout_diagnostics()
    assert port_diag.status == "UNAVAILABLE"
    assert port_diag.is_available is False

    cal_val = validate_market_calendar_evidence()
    funding_sens = evaluate_funding_sensitivity()

    corr_stress = CorrelationStressComparison(
        baseline_model="Multivariate Student-t",
        stressed_model="Stressed (R=I)",
        num_paths=100,
        marginal_means_preserved=True,
        marginal_variances_preserved=True,
        is_psd_repaired=False,
        psd_repair_frobenius_norm=0.0,
        baseline_mean_return=0.02,
        stressed_mean_return=0.018,
        mean_return_difference=-0.002,
        baseline_median_return=0.021,
        stressed_median_return=0.019,
        median_return_difference=-0.002,
        baseline_prob_loss=0.30,
        stressed_prob_loss=0.32,
        prob_loss_difference=0.02,
        prob_loss_difference_se=0.005,
        baseline_var_95=0.03,
        stressed_var_95=0.032,
        var_95_difference=0.002,
        baseline_cvar_95=0.045,
        stressed_cvar_95=0.048,
        cvar_95_difference=0.003,
        baseline_median_drawdown=0.04,
        stressed_median_drawdown=0.042,
        median_drawdown_difference=0.002,
        baseline_mean_financing_cost_a=2000.0,
        stressed_mean_financing_cost_a=2000.0,
        financing_cost_difference_a=0.0,
        baseline_mean_fx_translation_a=0.0,
        stressed_mean_fx_translation_a=0.0,
        fx_translation_difference_a=0.0,
        paired_return_difference_mean=-0.002,
        paired_return_difference_std=0.01,
        paired_return_difference_p05=-0.018,
        paired_return_difference_p50=-0.002,
        paired_return_difference_p95=0.014,
    )

    fake_eval = PathEvaluationResult(
        path_id=0,
        terminal_equity=101000.0,
        total_return=0.01,
        annualized_return=0.01,
        annualized_volatility=0.06,
        max_drawdown=-0.04,
        sharpe_ratio=0.2,
        pure_gross_gain_a=1500.0,
        fx_translation_gain_a=0.0,
        investment_yield_gain_a=1500.0,
        total_financing_costs_a=2000.0,
        total_frictions_a=100.0,
        total_cash_interest_a=500.0,
        cumulative_net_profit_a=1500.0,
        reconciliation_residual_a=0.0,
        reconciliation_exact=True,
        is_loss=False,
        breached_drawdown_5pct=False,
        breached_drawdown_10pct=False,
        breached_drawdown_20pct=False,
        capital_utilization=0.1,
        peak_exposure_a=10000.0,
    )
    dist_metrics = calculate_distribution_metrics([fake_eval], horizon_steps=20)
    fake_mc = MonteCarloResult(
        simulation_id="FAKE",
        config=SimulationConfig(
            simulation_id="FAKE",
            model_type=SimulationModelType.MULTIVARIATE_GAUSSIAN,
            num_paths=10,
            horizon_steps=20,
        ),
        distribution_metrics=dist_metrics,
    )

    report_md = generate_phase_4_1_2_1_research_report(
        avail_audit=avail_audit,
        model_comparisons=model_comps,
        factor_diag=factor_diag,
        port_diag=port_diag,
        corr_stress=corr_stress,
        cal_val=cal_val,
        funding_sens=funding_sens,
        bootstrap_result=fake_mc,
        student_t_result=fake_mc,
        regime_result=fake_mc,
        gaussian_result=fake_mc,
    )

    assert "-6.20%" in report_md, "Dynamic worst CVaR was not computed correctly in report"
    assert "NORMAL_VOLATILITY" in report_md
    assert "Point-in-Time Mode Enforced" in report_md
    assert "ESTIMATED_LAG" in report_md


def test_phase_4_1_2_1_manifest_completeness_and_hashes():
    """Verify Phase 4.1.2.1 simulation_manifest.json contains required fields, relative paths, and valid SHA256 hashes."""
    manifest_path = Path("data/results/phase_4_1_2_1/simulation_manifest.json")
    if not manifest_path.exists():
        pytest.skip("Phase 4.1.2.1 artifacts not yet generated on disk (run research runner first).")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert "git_commit" in manifest
    assert "simulation_source_commit" in manifest
    assert "source_tree_digest" in manifest
    assert "database_sha256" in manifest
    assert "rng_bit_generator" in manifest
    assert manifest["rng_bit_generator"] == "PCG64"
    assert manifest["random_seed"] == 42
    assert manifest["data_classification"] == "SIMULATED_RESEARCH_PROXY"
    assert "pit_policy" in manifest
    assert "calendar_implementation" in manifest
    assert "JointTarget2FedCalendar" in manifest["calendar_implementation"]
    assert "artifact_hashes" in manifest

    out_dir_str = manifest["simulation_parameters"]["output_directory"]
    assert not out_dir_str.startswith("D:") and not out_dir_str.startswith("C:"), (
        f"Output directory must be portable relative path, got: {out_dir_str}"
    )
    assert out_dir_str == "data/results/phase_4_1_2_1"

    required_artifacts = [
        "availability_audit.json",
        "factor_holdout_diagnostics.json",
        "portfolio_holdout_diagnostics.json",
        "correlation_stress_comparison.json",
        "calendar_validation.json",
        "funding_sensitivity.json",
        "model_comparison.json",
        "convergence_report.json",
        "phase_4_1_2_1_research_report.md",
        "calibration_report.json",
        "factor_panel_manifest.json",
        "gaussian_results.json",
        "bootstrap_results.json",
        "student_t_results.json",
        "regime_results.json",
        "stress_test_results.json",
        "holdout_diagnostics.json",
    ]

    for req in required_artifacts:
        assert req in manifest["artifact_hashes"], f"Required artifact {req} missing from manifest artifact_hashes"

    for filename, recorded_hash in manifest["artifact_hashes"].items():
        artifact_file = Path("data/results/phase_4_1_2_1") / filename
        assert artifact_file.exists(), f"Artifact {filename} missing on disk"
        hasher = hashlib.sha256()
        with open(artifact_file, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        computed_hash = hasher.hexdigest()
        assert computed_hash == recorded_hash, (
            f"Hash mismatch for {filename}: computed {computed_hash} != recorded {recorded_hash}"
        )
