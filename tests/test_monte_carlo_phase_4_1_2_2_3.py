"""Unit and integration tests for Phase 4.1.2.2.3 Holdout Forecast Initialization & Scenario-Date Integrity.

Verifies:
- Workstream A: Holdout Predictive-Path Construction & Calendar Alignment:
  - Predictive paths contain exactly H+1 = 248 levels and 248 dates for H = 247 holdout transitions.
  - Dates start on calibration boundary date (2023-12-29) and end on 2024-12-31.
  - First step models transition from 2023-12-29 to 2024-01-02.
  - Initial levels match calibration boundary state (FX ~ 1.104997, Borrow ~ 0.045, Invest ~ 0.0555).
  - Sampler fallback defaults (1.09, 0.04, 0.05) are never used.
  - Generated paths pass validate_calendar_dates for JOINT_TARGET2_FED and WEEKDAY_TRADING_PROXY.
  - Contrast with old flawed behavior (length mismatch).
  - Post-condition assertions fail closed if dates or levels mismatch.
- Workstream B: Empirical Invariance & Factor Holdout Diagnostics:
  - Factor holdout metrics are mathematically consistent under canonical path generation.
  - Portfolio holdout status remains strictly UNAVAILABLE.
- Workstream C: Research closure report and simulation manifest completeness.
"""

from datetime import date
import pytest
import numpy as np

from simulation.monte_carlo.strategy_adapter import (
    validate_calendar_dates,
)
from data.db.engine import make_engine, make_session_factory
from data.repository import Repository
from simulation.monte_carlo.bootstrap import HistoricalBootstrapSampler
from simulation.monte_carlo.calibration import (
    CalibrationReport,
    split_calibration_holdout,
)
from simulation.monte_carlo.factors import (
    build_fx_carry_factor_panel,
)
from simulation.monte_carlo.holdout import (
    generate_holdout_predictive_paths,
    evaluate_factor_holdout_diagnostics,
    evaluate_portfolio_holdout_diagnostics,
)
from simulation.monte_carlo.reporting import (
    generate_phase_4_1_2_2_3_research_report,
)
from simulation.monte_carlo.metrics import (
    PathEvaluationResult,
    calculate_distribution_metrics,
)
from simulation.monte_carlo.schemas import (
    AvailabilityAuditReport,
    BootstrapMethod,
    CalendarValidationReport,
    CorrelationStressComparison,
    FactorHoldoutDiagnostics,
    FundingSensitivityReport,
    ModelComparisonEntry,
    MonteCarloResult,
    PITMode,
    PortfolioHoldoutDiagnostics,
    SimulationConfig,
    SimulationModelType,
)


@pytest.fixture(scope="module")
def real_data_panels():
    """Load genuine database observations and build calibration and holdout panels."""
    db_path = "sqlite:///data/processed/gmdb.db"
    engine = make_engine(db_path)
    repo = Repository(make_session_factory(engine))
    all_obs = repo.load_observation_objects(include_synthetic=True)
    observations = [o for o in all_obs if not getattr(o, "is_synthetic", False)]

    full_panel = build_fx_carry_factor_panel(
        observations=observations,
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        sovereign_yield_series_id="DGS3MO",
        pit_mode=PITMode.ESTIMATED_LAG,
    )
    calib_panel, holdout_panel = split_calibration_holdout(
        panel=full_panel,
        calibration_end=date(2023, 12, 31),
    )
    return calib_panel, holdout_panel


# ==============================================================================
# Workstream A: Holdout Predictive-Path Construction & Calendar Alignment
# ==============================================================================

class TestHoldoutPredictivePathsAlignment:
    """Tests verifying 248 levels, 248 dates, boundary anchoring, and calendar validation."""

    def test_holdout_predictive_paths_level_and_date_counts(self, real_data_panels):
        """Horizon H = 247 must produce exactly H + 1 = 248 levels and 248 dates."""
        calib_panel, holdout_panel = real_data_panels
        assert len(holdout_panel.dates) == 247
        assert len(holdout_panel.level_dates) == 248

        sampler = HistoricalBootstrapSampler(calib_panel, method=BootstrapMethod.MOVING_BLOCK, random_seed=42)
        paths = generate_holdout_predictive_paths(
            model=sampler,
            calibration_panel=calib_panel,
            holdout_panel=holdout_panel,
            num_paths=10,
        )

        assert len(paths) == 10
        for p in paths:
            assert p.steps == 247
            assert p.dates is not None
            assert len(p.dates) == 248
            assert len(p.fx_rates) == 248
            assert len(p.borrowing_rates) == 248
            assert len(p.investment_rates) == 248

    def test_holdout_predictive_paths_dates_strictly_chronological(self, real_data_panels):
        """Dates start on calibration boundary (2023-12-29) and end on 2024-12-31."""
        calib_panel, holdout_panel = real_data_panels
        sampler = HistoricalBootstrapSampler(calib_panel, method=BootstrapMethod.MOVING_BLOCK, random_seed=42)
        paths = generate_holdout_predictive_paths(
            model=sampler,
            calibration_panel=calib_panel,
            holdout_panel=holdout_panel,
            num_paths=5,
        )

        for p in paths:
            dates = p.dates
            assert dates[0] == date(2023, 12, 29)
            assert dates[1] == date(2024, 1, 2)
            assert dates[-1] == date(2024, 12, 31)

            # Strictly strictly increasing
            for i in range(len(dates) - 1):
                assert dates[i] < dates[i + 1], f"Date ordering violation at index {i}: {dates[i]} >= {dates[i+1]}"

    def test_holdout_predictive_paths_anchored_at_calibration_boundary(self, real_data_panels):
        """Initial state must match calibration boundary canonical levels, NOT default fallbacks."""
        calib_panel, holdout_panel = real_data_panels
        sampler = HistoricalBootstrapSampler(calib_panel, method=BootstrapMethod.MOVING_BLOCK, random_seed=42)
        paths = generate_holdout_predictive_paths(
            model=sampler,
            calibration_panel=calib_panel,
            holdout_panel=holdout_panel,
            num_paths=5,
        )

        expected_fx = calib_panel.canonical_levels["FX_EUR_USD_LOGRET"][-1]
        expected_borrow = calib_panel.canonical_levels["RATE_DIFF_EUR_BORROW_BPS"][-1] / 100.0
        expected_invest = calib_panel.canonical_levels["YIELD_DIFF_USD_1M_BPS"][-1] / 100.0

        assert expected_fx == pytest.approx(1.1049967955, rel=1e-6)
        assert expected_borrow == pytest.approx(0.045, rel=1e-6)
        assert expected_invest == pytest.approx(0.0555, rel=1e-6)

        for p in paths:
            assert p.fx_rates[0] == pytest.approx(expected_fx, abs=1e-9)
            assert p.borrowing_rates[0] == pytest.approx(expected_borrow, abs=1e-9)
            assert p.investment_rates[0] == pytest.approx(expected_invest, abs=1e-9)

            # Ensure default sampler fallbacks (1.09, 0.04, 0.05) were NOT used
            assert p.fx_rates[0] != 1.09
            assert p.borrowing_rates[0] != 0.04
            assert p.investment_rates[0] != 0.05

    def test_holdout_predictive_paths_pass_calendar_validation(self, real_data_panels):
        """Generated paths must pass strict calendar validation."""
        calib_panel, holdout_panel = real_data_panels
        sampler = HistoricalBootstrapSampler(calib_panel, method=BootstrapMethod.MOVING_BLOCK, random_seed=42)
        paths = generate_holdout_predictive_paths(
            model=sampler,
            calibration_panel=calib_panel,
            holdout_panel=holdout_panel,
            num_paths=3,
        )

        for p in paths:
            # 1. Joint TARGET2 + Fed calendar validation
            validate_calendar_dates(
                dates=p.dates,
                total_levels=len(p.fx_rates),
                calendar_type="JOINT_TARGET2_FED",
            )
            # 2. Weekday trading proxy validation
            validate_calendar_dates(
                dates=p.dates,
                total_levels=len(p.fx_rates),
                calendar_type="WEEKDAY_TRADING_PROXY",
            )

    def test_contrast_old_flawed_behavior_fails_calendar_validation(self, real_data_panels):
        """Passing transition dates (247 dates) to validate_calendar_dates with 248 levels fails."""
        _, holdout_panel = real_data_panels
        assert len(holdout_panel.dates) == 247

        with pytest.raises(ValueError, match="Scenario path calendar dates length mismatch: received 247 dates, expected exactly 248"):
            validate_calendar_dates(
                dates=holdout_panel.dates,
                total_levels=248,
                calendar_type="JOINT_TARGET2_FED",
            )

    def test_first_holdout_transition_modeling(self, real_data_panels):
        """The first step in the predictive path models the transition from 2023-12-29 to 2024-01-02."""
        calib_panel, holdout_panel = real_data_panels
        sampler = HistoricalBootstrapSampler(calib_panel, method=BootstrapMethod.MOVING_BLOCK, random_seed=42)
        paths = generate_holdout_predictive_paths(
            model=sampler,
            calibration_panel=calib_panel,
            holdout_panel=holdout_panel,
            num_paths=1,
        )

        p = paths[0]
        # Step 0 to step 1
        s0 = p.fx_rates[0]
        s1 = p.fx_rates[1]
        log_ret_step1 = np.log(s1 / s0)

        assert p.dates[0] == date(2023, 12, 29)
        assert p.dates[1] == date(2024, 1, 2)
        assert np.isfinite(log_ret_step1)

    def test_fallback_date_construction_when_level_dates_empty(self, real_data_panels):
        """When holdout_panel.level_dates is empty, boundary date is prepended correctly."""
        calib_panel, holdout_panel = real_data_panels
        synthetic_holdout = holdout_panel.model_copy(update={"level_dates": []})

        sampler = HistoricalBootstrapSampler(calib_panel, method=BootstrapMethod.MOVING_BLOCK, random_seed=42)
        paths = generate_holdout_predictive_paths(
            model=sampler,
            calibration_panel=calib_panel,
            holdout_panel=synthetic_holdout,
            num_paths=2,
        )

        assert len(paths[0].dates) == 248
        assert paths[0].dates[0] == date(2023, 12, 29)
        assert paths[0].dates[1] == date(2024, 1, 2)
        assert paths[0].dates[-1] == date(2024, 12, 31)

    def test_rejects_mismatched_boundary_dates(self, real_data_panels):
        """Fails closed if holdout initial date does not match calibration boundary."""
        calib_panel, holdout_panel = real_data_panels
        bad_holdout = holdout_panel.model_copy(
            update={"level_dates": [date(2023, 12, 28)] + holdout_panel.level_dates[1:]}
        )

        sampler = HistoricalBootstrapSampler(calib_panel, method=BootstrapMethod.MOVING_BLOCK, random_seed=42)
        with pytest.raises(ValueError, match="Holdout scenario initial date.*does not match calibration boundary date"):
            generate_holdout_predictive_paths(
                model=sampler,
                calibration_panel=calib_panel,
                holdout_panel=bad_holdout,
                num_paths=1,
            )

    def test_rejects_missing_factor_levels(self, real_data_panels):
        """Fails closed if calibration panel lacks required factors."""
        calib_panel, holdout_panel = real_data_panels
        bad_calib = calib_panel.model_copy(
            update={"factors": [], "canonical_levels": {}, "raw_levels": {}}
        )

        sampler = HistoricalBootstrapSampler(calib_panel, method=BootstrapMethod.MOVING_BLOCK, random_seed=42)
        with pytest.raises(ValueError, match="Cannot resolve initial FX level"):
            generate_holdout_predictive_paths(
                model=sampler,
                calibration_panel=bad_calib,
                holdout_panel=holdout_panel,
                num_paths=1,
            )


# ==============================================================================
# Workstream B: Empirical Invariance & Factor Holdout Diagnostics
# ==============================================================================

class TestHoldoutFactorDiagnostics:
    """Tests verifying factor holdout diagnostics behavior and empirical consistency."""

    def test_factor_holdout_diagnostics_empirical_consistency(self, real_data_panels):
        """Evaluate factor holdout diagnostics with anchored predictive paths."""
        calib_panel, holdout_panel = real_data_panels
        sampler = HistoricalBootstrapSampler(calib_panel, method=BootstrapMethod.MOVING_BLOCK, random_seed=42)
        paths = generate_holdout_predictive_paths(
            model=sampler,
            calibration_panel=calib_panel,
            holdout_panel=holdout_panel,
            num_paths=100,
        )

        diag = evaluate_factor_holdout_diagnostics(
            calibration_panel=calib_panel,
            holdout_panel=holdout_panel,
            predictive_paths=paths,
        )

        assert diag.holdout_days == 247
        assert diag.num_predictive_paths == 100
        # 2024 actual realized cumulative return is ~ -5.98% under canonical EUR/USD
        assert diag.actual_fx_cumulative_return == pytest.approx(-0.0598, abs=0.01)
        # 2024 realized annualized volatility is ~ 6.18%
        assert diag.actual_fx_realized_volatility == pytest.approx(0.0618, abs=0.01)
        # Max drawdown is ~ -7.21%
        assert diag.actual_fx_max_drawdown == pytest.approx(-0.0721, abs=0.01)

        # Percentiles are bounded in [0, 1]
        assert 0.0 <= diag.predictive_percentile_fx_return <= 1.0
        assert 0.0 <= diag.predictive_percentile_fx_volatility <= 1.0
        assert 0.0 <= diag.predictive_percentile_fx_drawdown <= 1.0

        # Regime classification is NORMAL_VOLATILITY (between ~5.74% and ~9.49%)
        assert diag.volatility_regime_classification == "NORMAL_VOLATILITY"

    def test_portfolio_holdout_diagnostics_strictly_unavailable(self):
        """Portfolio holdout must report UNAVAILABLE and not synthesize live fills."""
        port_diag = evaluate_portfolio_holdout_diagnostics()
        assert port_diag.status == "UNAVAILABLE"
        assert not port_diag.is_available
        assert "SIMULATED_RESEARCH_PROXY without live execution evidence" in port_diag.reason


# ==============================================================================
# Workstream C: Research Report & Manifest Verification
# ==============================================================================

class TestPhase41223ReportGenerator:
    """Tests verifying Phase 4.1.2.2.3 research closure report generation."""

    def test_generate_phase_4_1_2_2_3_report_structure(self):
        """Report generator dynamically formats title, level/transition counts, and sections."""
        avail_audit = AvailabilityAuditReport(
            total_source_observations=8900,
            genuine_observations_included=5613,
            synthetic_observations_excluded=140,
            date_window_exclusions=0,
            classification_exclusions=0,
            factor_alignment_exclusions=0,
            exact_timestamp_verified_count=0,
            estimated_availability_count=5613,
            retrospective_count=0,
            missing_evidence_count=0,
            unrecognized_evidence_count=0,
            is_reconciled=True,
            data_classification_label="SIMULATED_RESEARCH_PROXY",
            pit_mode="ESTIMATED_LAG",
            aligned_level_count=990,
            transition_count=989,
            first_level_date=date(2020, 1, 6),
            last_level_date=date(2023, 12, 29),
            first_transition_date=date(2020, 1, 7),
            last_transition_date=date(2023, 12, 29),
        )

        calib_report = CalibrationReport(
            calibration_start=date(2020, 1, 1),
            calibration_end=date(2023, 12, 31),
            calibration_sample_size=989,
            calibration_level_count=990,
            calibration_transition_count=989,
            first_calibration_level_date=date(2020, 1, 6),
            last_calibration_level_date=date(2023, 12, 29),
            first_calibration_transition_date=date(2020, 1, 7),
            last_calibration_transition_date=date(2023, 12, 29),
            holdout_start=date(2024, 1, 1),
            holdout_end=date(2024, 12, 31),
            holdout_sample_size=247,
            holdout_level_count=248,
            holdout_transition_count=247,
            first_holdout_level_date=date(2023, 12, 29),
            last_holdout_level_date=date(2024, 12, 31),
            first_holdout_transition_date=date(2024, 1, 2),
            last_holdout_transition_date=date(2024, 12, 31),
            factor_summaries={},
            factor_names=["FX_EUR_USD", "EUR_BORROW_RATE", "DGS3MO"],
            correlation_matrix=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            covariance_matrix=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        )

        diag = FactorHoldoutDiagnostics(
            holdout_start=date(2024, 1, 2),
            holdout_end=date(2024, 12, 31),
            holdout_days=247,
            num_predictive_paths=1000,
            actual_fx_cumulative_return=-0.0598,
            actual_fx_realized_volatility=0.0618,
            actual_fx_max_drawdown=-0.0721,
            simulated_fx_return_median=0.0128,
            simulated_fx_return_p025=-0.1292,
            simulated_fx_return_p975=0.1757,
            simulated_fx_volatility_median=0.0795,
            simulated_fx_drawdown_median=-0.0650,
            predictive_percentile_fx_return=0.229,
            predictive_percentile_fx_return_mc_se=0.0133,
            predictive_percentile_fx_volatility=0.006,
            predictive_percentile_fx_drawdown=0.649,
            volatility_regime_classification="NORMAL_VOLATILITY",
            low_vol_threshold=0.0574,
            high_vol_threshold=0.0949,
            fx_log_return_ks_stat=0.0940,
            fx_log_return_ks_pvalue=0.0559,
        )

        port_diag = PortfolioHoldoutDiagnostics(
            status="UNAVAILABLE",
            is_available=False,
            reason="No live execution evidence.",
        )

        corr_stress = CorrelationStressComparison(
            baseline_model="multivariate_gaussian",
            stressed_model="multivariate_gaussian_decorrelated",
            num_paths=1000,
            baseline_mean_return=0.0137,
            baseline_median_return=0.0128,
            baseline_prob_loss=0.384,
            baseline_var_95=-0.0481,
            baseline_cvar_95=-0.0655,
            baseline_median_drawdown=0.0500,
            stressed_mean_return=0.0137,
            stressed_median_return=0.0128,
            stressed_prob_loss=0.384,
            stressed_var_95=-0.0481,
            stressed_cvar_95=-0.0655,
            stressed_median_drawdown=0.0500,
            mean_return_difference=0.0,
            median_return_difference=0.0,
            prob_loss_difference=0.0,
            var_95_difference=0.0,
            cvar_95_difference=0.0,
            median_drawdown_difference=0.0,
            baseline_mean_financing_cost_a=2540.0,
            stressed_mean_financing_cost_a=2540.0,
            financing_cost_difference_a=0.0,
            baseline_mean_fx_translation_a=1370.0,
            stressed_mean_fx_translation_a=1370.0,
            fx_translation_difference_a=0.0,
            paired_return_difference_mean=0.0,
            paired_return_difference_std=0.0,
            paired_return_difference_p05=0.0,
            paired_return_difference_p50=0.0,
            paired_return_difference_p95=0.0,
        )

        cal_val = CalendarValidationReport(
            calendar_implementation="JointTarget2FedCalendar",
            session_count=252,
            initial_state_zero_interest=True,
            weekend_3day_accrual_verified=True,
            holiday_accrual_verified=True,
            tenor_30day_maturity_verified=True,
            independent_numerical_accrual_verified=True,
            transitions_n_levels_n_plus_1_verified=True,
            array_lengths_verified=True,
        )

        funding_sens = FundingSensitivityReport(
            baseline_borrowing_rate=0.025,
            funding_conventions=["fixed", "floating"],
            shocks_bps=[-100, 0, 100],
            scenarios=[],
        )

        evals = [
            PathEvaluationResult(
                path_id=i,
                terminal_equity=100_000.0 + (i % 20 - 10) * 500.0,
                total_return=(i % 20 - 10) * 0.005,
                annualized_return=(i % 20 - 10) * 0.005,
                annualized_volatility=0.03,
                max_drawdown=-0.02,
                is_loss=((i % 20 - 10) < 0),
            )
            for i in range(100)
        ]
        dummy_dist = calculate_distribution_metrics(evaluations=evals, horizon_steps=252)

        dummy_mc = MonteCarloResult(
            simulation_id="dummy_sim",
            config=SimulationConfig(num_paths=1000, horizon_steps=252, random_seed=42),
            model_type=SimulationModelType.HISTORICAL_BOOTSTRAP,
            path_results=[],
            distribution_metrics=dummy_dist,
        )

        models = [
            ModelComparisonEntry(
                model_name="Moving-Block Bootstrap (20d)",
                num_paths=1000,
                median_return=0.0128,
                mean_return=0.0137,
                std_return=0.0401,
                var_95=-0.0481,
                cvar_95=-0.0655,
                max_drawdown_median=0.0500,
                max_drawdown_p95=0.0800,
                prob_loss=0.384,
                prob_loss_se=0.0154,
                prob_drawdown_10pct=0.005,
                mean_fx_drag=-0.0027,
                mean_financing_drag=0.0254,
                checkpoint_stability_status="CHECKPOINT_STABILITY_ACHIEVED",
            ),
        ]

        manifest_info = {
            "holdout_predictive_initialization": {
                "calibration_boundary_date": "2023-12-29",
                "first_holdout_transition_date": "2024-01-02",
                "initial_fx_rate": 1.1049967955,
                "initial_borrowing_rate": 0.045,
                "initial_investment_rate": 0.0555,
                "scenario_level_count": 248,
                "scenario_transition_count": 247,
                "calendar_alignment_verified": True,
            }
        }

        report_md = generate_phase_4_1_2_2_3_research_report(
            avail_audit=avail_audit,
            model_comparisons=models,
            factor_diag=diag,
            port_diag=port_diag,
            corr_stress=corr_stress,
            cal_val=cal_val,
            funding_sens=funding_sens,
            bootstrap_result=dummy_mc,
            student_t_result=dummy_mc,
            regime_result=dummy_mc,
            gaussian_result=dummy_mc,
            calibration_report=calib_report,
            manifest_info=manifest_info,
        )

        assert "# Phase 4.1.2.2.3 — Holdout Forecast Initialization & Scenario-Date Integrity Closure Report" in report_md
        assert "990 aligned level dates [2020-01-06 to 2023-12-29]" in report_md
        assert "989 factor return transitions [2020-01-07 to 2023-12-29]" in report_md
        assert "248 aligned level dates [2023-12-29 to 2024-12-31]" in report_md
        assert "247 factor return transitions [2024-01-02 to 2024-12-31]" in report_md
        assert "CHECKPOINT_STABILITY_ACHIEVED" in report_md
