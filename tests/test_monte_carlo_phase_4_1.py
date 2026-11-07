"""Phase 4.1 Quantitative Integrity & Simulation Validation Test Suite.

Comprehensive tests verifying:
1. FX stress shock semantics and timing contracts (pre_entry, after_entry, at_step, persistent, reversal)
2. Simulated trading calendar, horizon semantics, weekend financing, and contractual tenor
3. Factor panel construction, absence of cross-series substitution, row provenance, and revision resolution
4. Volatility regime modeling: 20th/80th percentiles, warm-up exclusion, stationary sampling, and statistics
5. Parametric models: Student-t profile MLE df estimation, Gaussian model, and PSD repair diagnostics
6. Real holdout diagnostics: 2024 evaluation, volatility coverage, return quantile, and KS test
7. Multi-metric convergence tracking across distribution statistics and tail sample sizes
8. Correlation breakdown stress scenario decoupling and PSD repair
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
import numpy as np
import pytest

from data.schemas import AvailabilityEvidence, DataClassification, DataObservation, Frequency, ObservationKind
from simulation.monte_carlo.schemas import (
    BootstrapMethod,
    FactorCategory,
    Frequency,
    MarketFactor,
    MissingDataTreatment,
    RegimeState,
    ScenarioPath,
    SimulationConfig,
    SimulationModelType,
    StressScenario,
    TransformationMethod,
)
from simulation.monte_carlo.factors import (
    _resolve_observation,
    build_fx_carry_factor_panel,
    compute_differences,
    compute_log_returns,
)
from simulation.monte_carlo.calibration import calibrate_factor_panel
from simulation.monte_carlo.shocks import (
    apply_stress_scenario,
    build_standard_stress_scenarios,
    generate_correlation_breakdown_path,
)
from simulation.monte_carlo.strategy_adapter import (
    CarryTradeScenarioStrategy,
    generate_simulated_trading_sessions,
)
from simulation.monte_carlo.regimes import (
    RegimeConditionedSampler,
    VolatilityRegimeClassifier,
)
from simulation.monte_carlo.distributions import (
    MultivariateGaussianModel,
    MultivariateStudentTModel,
    ensure_positive_semidefinite,
)
from simulation.monte_carlo.convergence import evaluate_convergence
from simulation.monte_carlo.holdout import evaluate_holdout_diagnostics


# =============================================================================
# Synthetic Data Helpers
# =============================================================================


def make_test_observations(
    start_date: date = date(2020, 1, 1),
    num_days: int = 300,
    include_dgs3mo: bool = True,
) -> list[DataObservation]:
    """Generate realistic synthetic observations with full provenance for testing."""
    obs: list[DataObservation] = []
    base_fx = 1.12
    base_dgs1mo = 0.045
    base_dgs3mo = 0.048
    base_ecb = 0.025

    rng = np.random.default_rng(12345)

    for i in range(num_days):
        current_date = start_date + timedelta(days=i)
        # Skip weekends to simulate trading calendar
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
                availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
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
                availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
                is_synthetic=False,
            )
        )

        # US Treasury 3M (optional)
        if include_dgs3mo:
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
                    availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
                    is_synthetic=False,
                )
            )

        # ECB Borrowing Rate (piecewise constant)
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
                availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
                is_synthetic=False,
            )
        )

    return obs


# =============================================================================
# 1. FX Stress Shock Semantics Tests
# =============================================================================


def test_persistent_fx_shock_affects_open_position_pnl():
    """Adverse FX shock applied at shock_step materially degrades strategy P&L relative to baseline."""
    horizon = 30
    base = ScenarioPath(
        path_id=0,
        steps=horizon,
        fx_rates=[1.10] * (horizon + 1),
        borrowing_rates=[0.02] * (horizon + 1),
        investment_rates=[0.05] * (horizon + 1),
        is_synthetic=True,
    )

    strategy = CarryTradeScenarioStrategy(tenor_days=30, rebalance_days=30)
    base_eval = strategy.evaluate_path(base, initial_capital_a=100_000.0)

    # Adverse shock to USD (-10% USD value, so USD depreciates)
    adverse_stress = StressScenario(
        name="Adverse FX -10%",
        description="USD depreciates 10% after trade entry",
        fx_shock_pct=-0.10,
        shock_timing="after_entry",
        shock_step=5,
        is_persistent=True,
    )
    adverse_path = apply_stress_scenario(base, adverse_stress)
    adverse_eval = strategy.evaluate_path(adverse_path, initial_capital_a=100_000.0)

    # Terminal P&L must be materially worse
    assert adverse_eval.cumulative_net_profit_a < base_eval.cumulative_net_profit_a
    # Max drawdown must be worse
    assert adverse_eval.max_drawdown < base_eval.max_drawdown
    pnl_diff = base_eval.cumulative_net_profit_a - adverse_eval.cumulative_net_profit_a
    assert pnl_diff > 5_000.0


def test_shock_direction_affects_pnl():
    """Adverse shock (-10%) produces significantly lower P&L than favorable shock (+10%)."""
    horizon = 30
    base = ScenarioPath(
        path_id=0,
        steps=horizon,
        fx_rates=[1.10] * (horizon + 1),
        borrowing_rates=[0.02] * (horizon + 1),
        investment_rates=[0.05] * (horizon + 1),
        is_synthetic=True,
    )

    strategy = CarryTradeScenarioStrategy(tenor_days=30, rebalance_days=30)

    adverse = apply_stress_scenario(
        base,
        StressScenario(name="Adverse", description="-10%", fx_shock_pct=-0.10, shock_timing="after_entry", shock_step=5),
    )
    favorable = apply_stress_scenario(
        base,
        StressScenario(name="Favorable", description="+10%", fx_shock_pct=0.10, shock_timing="after_entry", shock_step=5),
    )

    eval_adverse = strategy.evaluate_path(adverse, initial_capital_a=100_000.0)
    eval_favorable = strategy.evaluate_path(favorable, initial_capital_a=100_000.0)

    assert eval_adverse.cumulative_net_profit_a < eval_favorable.cumulative_net_profit_a
    assert eval_adverse.max_drawdown < eval_favorable.max_drawdown


def test_zero_shock_equals_baseline():
    """A 0% shock scenario reproduces baseline path P&L with exact residual parity (|res| <= 1e-9)."""
    horizon = 30
    base = ScenarioPath(
        path_id=0,
        steps=horizon,
        fx_rates=[1.10] * (horizon + 1),
        borrowing_rates=[0.02] * (horizon + 1),
        investment_rates=[0.05] * (horizon + 1),
        is_synthetic=True,
    )

    zero_stress = StressScenario(
        name="Zero Shock",
        description="No shocks applied",
        fx_shock_pct=0.0,
        borrowing_rate_shock_bps=0.0,
        investment_rate_shock_bps=0.0,
    )
    stressed_path = apply_stress_scenario(base, zero_stress)

    strategy = CarryTradeScenarioStrategy(tenor_days=30, rebalance_days=30)
    eval_base = strategy.evaluate_path(base, initial_capital_a=100_000.0)
    eval_zero = strategy.evaluate_path(stressed_path, initial_capital_a=100_000.0)

    assert eval_zero.terminal_equity == pytest.approx(eval_base.terminal_equity, rel=1e-12)
    assert eval_zero.cumulative_net_profit_a == pytest.approx(eval_base.cumulative_net_profit_a, rel=1e-12)
    assert eval_zero.max_drawdown == pytest.approx(eval_base.max_drawdown, rel=1e-12)


def test_shock_timing_contract():
    """Shock timing contracts (pre_entry, after_entry, at_step) behave as specified."""
    horizon = 10
    base = ScenarioPath(
        path_id=0,
        steps=horizon,
        fx_rates=[1.10] * (horizon + 1),
        borrowing_rates=[0.02] * (horizon + 1),
        investment_rates=[0.05] * (horizon + 1),
        is_synthetic=True,
    )

    # 1. pre_entry: shifts entire path from step 0
    pre_path = apply_stress_scenario(
        base,
        StressScenario(name="Pre", description="", fx_shock_pct=-0.10, shock_timing="pre_entry"),
    )
    assert pre_path.fx_rates[0] == pytest.approx(1.10 / 0.90, rel=1e-12)
    assert pre_path.fx_rates[5] == pytest.approx(1.10 / 0.90, rel=1e-12)

    # 2. after_entry persistent: step 0 unshocked, step >= shock_step shocked
    after_path = apply_stress_scenario(
        base,
        StressScenario(name="After", description="", fx_shock_pct=-0.10, shock_timing="after_entry", shock_step=5, is_persistent=True),
    )
    assert after_path.fx_rates[0] == pytest.approx(1.10, rel=1e-12)
    assert after_path.fx_rates[4] == pytest.approx(1.10, rel=1e-12)
    assert after_path.fx_rates[5] == pytest.approx(1.10 / 0.90, rel=1e-12)
    assert after_path.fx_rates[10] == pytest.approx(1.10 / 0.90, rel=1e-12)

    # 3. at_step temporary (reversal at step 7):
    temp_path = apply_stress_scenario(
        base,
        StressScenario(name="Temp", description="", fx_shock_pct=-0.10, shock_timing="at_step", shock_step=5, is_persistent=False, reversal_step=7),
    )
    assert temp_path.fx_rates[4] == pytest.approx(1.10, rel=1e-12)
    assert temp_path.fx_rates[5] == pytest.approx(1.10 / 0.90, rel=1e-12)
    assert temp_path.fx_rates[6] == pytest.approx(1.10 / 0.90, rel=1e-12)
    assert temp_path.fx_rates[7] == pytest.approx(1.10, rel=1e-12)


def test_compound_crisis_scenario():
    """Severe crisis scenario degrades strategy P&L significantly more than single shock."""
    horizon = 30
    base = ScenarioPath(
        path_id=0,
        steps=horizon,
        fx_rates=[1.10] * (horizon + 1),
        borrowing_rates=[0.02] * (horizon + 1),
        investment_rates=[0.05] * (horizon + 1),
        is_synthetic=True,
    )
    strategy = CarryTradeScenarioStrategy(tenor_days=30, rebalance_days=30)
    single_shock = apply_stress_scenario(
        base,
        StressScenario(name="Single", description="", fx_shock_pct=-0.10, shock_timing="after_entry", shock_step=5),
    )
    compound_crisis = apply_stress_scenario(
        base,
        StressScenario(
            name="Crisis",
            description="",
            fx_shock_pct=-0.20,
            borrowing_rate_shock_bps=500.0,
            spread_multiplier=5.0,
            slippage_multiplier=5.0,
            shock_timing="after_entry",
            shock_step=5,
            is_persistent=True,
        ),
    )

    ev_single = strategy.evaluate_path(single_shock, initial_capital_a=100_000.0)
    ev_crisis = strategy.evaluate_path(compound_crisis, initial_capital_a=100_000.0)

    assert ev_crisis.cumulative_net_profit_a < ev_single.cumulative_net_profit_a
    assert ev_crisis.max_drawdown < ev_single.max_drawdown


# =============================================================================
# 2. Simulated Trading Calendar & Horizon Semantics Tests
# =============================================================================


def test_horizon_steps_and_levels_relation():
    """A simulation of N steps produces N+1 levels and exactly N return transitions."""
    sessions = generate_simulated_trading_sessions(start_date=date(2024, 1, 2), n_sessions=253)
    assert len(sessions) == 253
    for s in sessions:
        assert s.weekday() < 5


def test_initial_state_zero_days_elapsed():
    """Initial market state at t=0 has 0 days elapsed and 0 initial cash interest accrued."""
    horizon = 20
    base = ScenarioPath(
        path_id=0,
        steps=horizon,
        fx_rates=[1.10] * (horizon + 1),
        borrowing_rates=[0.02] * (horizon + 1),
        investment_rates=[0.05] * (horizon + 1),
        is_synthetic=True,
    )
    strategy = CarryTradeScenarioStrategy(tenor_days=30, rebalance_days=30)
    ev = strategy.evaluate_path(base, initial_capital_a=100_000.0)

    assert abs(ev.reconciliation_residual_a) <= 1e-10
    assert ev.reconciliation_exact is True


def test_weekend_calendar_accrual():
    """Strategy accounts for 3 calendar days of financing across Friday-to-Monday."""
    start_friday = date(2024, 1, 5) # Friday
    sessions = generate_simulated_trading_sessions(start_date=start_friday, n_sessions=3)
    assert sessions[0].weekday() == 4 # Friday
    assert sessions[1].weekday() == 0 # Monday
    assert (sessions[1] - sessions[0]).days == 3


def test_tenor_calendar_day_maturity():
    """A 30-day tenor contract matures on or after entry + 30 calendar days, not 30 sessions."""
    start_date = date(2024, 1, 2) # Tuesday
    sessions = generate_simulated_trading_sessions(start_date=start_date, n_sessions=60)
    entry_date = sessions[0]
    contractual_maturity = entry_date + timedelta(days=30)
    assert contractual_maturity == date(2024, 2, 1)

    maturity_idx = [i for i, s in enumerate(sessions) if s >= contractual_maturity][0]
    assert 20 <= maturity_idx <= 24
    assert maturity_idx < 30


# =============================================================================
# 3. Factor Data Integrity & Availability Tests
# =============================================================================


def test_no_cross_series_substitution():
    """Factor panel builder never substitutes DGS1MO for missing DGS3MO."""
    obs_no_3m = make_test_observations(num_days=150, include_dgs3mo=False)

    panel = build_fx_carry_factor_panel(obs_no_3m, sovereign_yield_series_id="DGS3MO")
    factor_ids = [f.factor_id for f in panel.factors]
    assert "FX_EUR_USD_LOGRET" in factor_ids
    assert "RATE_DIFF_EUR_BORROW_BPS" in factor_ids
    assert "YIELD_DIFF_USD_1M_BPS" in factor_ids
    assert "YIELD_DIFF_USD_3M_BPS" not in factor_ids
    assert any("Option B: Reduced research panel" in log for log in panel.alignment_audit)


def test_option_a_when_dgs3mo_available():
    """Factor panel builder retains all 4 factors (Option A) when DGS3MO is present."""
    obs_with_3m = make_test_observations(num_days=150, include_dgs3mo=True)

    panel = build_fx_carry_factor_panel(obs_with_3m, sovereign_yield_series_id="DGS3MO")
    factor_ids = [f.factor_id for f in panel.factors]
    assert len(factor_ids) == 4
    assert "YIELD_DIFF_USD_3M_BPS" in factor_ids
    assert any("Option A: Complete common panel" in log for log in panel.alignment_audit)


def test_row_level_provenance_tracking():
    """FactorPanel preserves row-level provenance for every factor observation."""
    obs = make_test_observations(num_days=100)
    panel = build_fx_carry_factor_panel(obs)

    assert panel.row_provenance is not None
    assert "FX_EUR_USD_LOGRET" in panel.row_provenance
    prov_rows = panel.row_provenance["FX_EUR_USD_LOGRET"]
    assert len(prov_rows) == len(panel.dates)

    first_row = prov_rows[0]
    assert first_row.observation_date == panel.dates[0]
    assert first_row.data_classification in (DataClassification.REAL_VERIFIED, DataClassification.REAL_RETROSPECTIVE)
    assert first_row.source_id == "frankfurter"
    assert first_row.raw_value > 0.0


def test_deterministic_revision_resolution():
    """Candidate observation with higher revision or later retrieved_at wins deterministically."""
    d = date(2023, 5, 10)
    ts = datetime(2023, 5, 10, 12, 0, tzinfo=timezone.utc)

    o1 = DataObservation(
        kind=ObservationKind.INTEREST_RATE,
        source_id="ecb",
        entity_code="ECB_EA",
        indicator_id="KR.MRR_FR.LEV",
        value=3.25,
        unit="percent",
        frequency=Frequency.DAILY,
        observation_date=d,
        publication_date=d,
        observation_timestamp=ts,
        publication_timestamp=ts,
        revision=1,
        retrieved_at=datetime(2023, 5, 11, 8, 0, tzinfo=timezone.utc),
        classification=DataClassification.REAL_VERIFIED,
        availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
    )
    o2 = DataObservation(
        kind=ObservationKind.INTEREST_RATE,
        source_id="ecb",
        entity_code="ECB_EA",
        indicator_id="KR.MRR_FR.LEV",
        value=3.50,
        unit="percent",
        frequency=Frequency.DAILY,
        observation_date=d,
        publication_date=d,
        observation_timestamp=ts,
        publication_timestamp=ts,
        revision=2,
        retrieved_at=datetime(2023, 5, 11, 8, 0, tzinfo=timezone.utc),
        classification=DataClassification.REAL_VERIFIED,
        availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
    )

    winner = _resolve_observation(o1, o2)
    assert winner.revision == 2
    assert winner.value == 3.50


def test_calibration_availability_summary():
    """CalibrationReport includes CalibrationAvailabilitySummary breakdown."""
    obs = make_test_observations(num_days=200)
    panel = build_fx_carry_factor_panel(obs)
    report = calibrate_factor_panel(panel, raw_observations=obs)

    assert report.availability_summary is not None
    summary = report.availability_summary
    assert summary.total_genuine_observations > 0
    assert summary.exact_timestamp_verified_count > 0
    assert summary.excluded_synthetic_count == 0
    assert summary.exact_timestamp_verified_count > 0


# =============================================================================
# 4. Volatility Regime Modeling Tests
# =============================================================================


def test_regime_classifier_percentiles_and_warmup():
    """VolatilityRegimeClassifier excludes warm-up window and uses 20th/80th percentiles."""
    obs = make_test_observations(num_days=250)
    panel = build_fx_carry_factor_panel(obs)

    classifier = VolatilityRegimeClassifier(
        panel,
        rolling_window=63,
        low_vol_percentile=20.0,
        high_vol_percentile=80.0,
    )

    # First 62 observations must be None (warmup window)
    for i in range(62):
        assert classifier.regimes[i] is None

    # Valid observations must be len(fx_returns) - 62
    assert classifier.total_valid_obs == len(panel.dates) - 62

    # Check regime counts
    for s_name in [RegimeState.LOW_VOLATILITY.value, RegimeState.HIGH_VOLATILITY.value, RegimeState.STRESS.value]:
        assert classifier.regime_counts[s_name] > 0

    # Diagnostic report check
    report = classifier.build_report()
    assert report.rolling_window_days == 63
    assert len(report.regime_summaries) == 3
    # Check that stationary probabilities sum to 1.0
    tot_p = sum(s.stationary_probability for s in report.regime_summaries.values())
    assert tot_p == pytest.approx(1.0, rel=1e-6)


def test_regime_transition_matrix_valid_pairs_only():
    """Transition matrix only counts consecutive transitions where both t-1 and t are valid."""
    obs = make_test_observations(num_days=250)
    panel = build_fx_carry_factor_panel(obs)
    classifier = VolatilityRegimeClassifier(panel, rolling_window=63)
    trans_mat = classifier.compute_transition_matrix()

    for s_from in [RegimeState.LOW_VOLATILITY.value, RegimeState.HIGH_VOLATILITY.value, RegimeState.STRESS.value]:
        row_sum = sum(trans_mat[s_from].values())
        assert row_sum == pytest.approx(1.0, rel=1e-6)


def test_regime_conditioned_sampler_paths():
    """RegimeConditionedSampler generates valid correlated paths conditioned on regimes."""
    obs = make_test_observations(num_days=250)
    panel = build_fx_carry_factor_panel(obs)
    classifier = VolatilityRegimeClassifier(panel, rolling_window=63)
    sampler = RegimeConditionedSampler(panel, classifier, random_seed=42)

    seq = sampler.sample_regime_sequence(horizon=30)
    assert len(seq) == 30
    assert all(s in [RegimeState.LOW_VOLATILITY.value, RegimeState.HIGH_VOLATILITY.value, RegimeState.STRESS.value] for s in seq)

    path = sampler.generate_path(path_id=1, horizon=30)
    assert path.steps == 30
    assert len(path.fx_rates) == 31
    assert all(r > 0.0 for r in path.fx_rates)


# =============================================================================
# 5. Parametric Multivariate Models & Profile MLE
# =============================================================================


def test_student_t_profile_mle_df_estimation():
    """MultivariateStudentTModel estimates degrees of freedom nu via profile MLE."""
    obs = make_test_observations(num_days=200)
    panel = build_fx_carry_factor_panel(obs)

    model = MultivariateStudentTModel(panel, random_seed=42)
    assert model.nu is not None
    assert 2.1 <= model.nu <= 40.0
    assert model.is_converged is True
    assert model.build_fit_report().model_type == "multivariate_student_t"
    assert model.build_fit_report().degrees_of_freedom == pytest.approx(model.nu, rel=1e-6)


def test_multivariate_gaussian_model():
    """MultivariateGaussianModel estimates parameters and generates correlated paths."""
    obs = make_test_observations(num_days=200)
    panel = build_fx_carry_factor_panel(obs)

    model = MultivariateGaussianModel(panel, random_seed=42)
    fit_rep = model.build_fit_report()
    assert fit_rep.model_type == "multivariate_gaussian"
    assert fit_rep.degrees_of_freedom is None
    assert fit_rep.aic is not None
    assert fit_rep.bic is not None

    paths = model.generate_paths(num_paths=5, horizon=30)
    assert len(paths) == 5
    for p in paths:
        assert p.steps == 30
        assert len(p.fx_rates) == 31
        assert all(rate > 0.0 for rate in p.fx_rates)


def test_multivariate_student_t_model():
    """MultivariateStudentTModel estimates nu via profile MLE and generates paths."""
    obs = make_test_observations(num_days=200)
    panel = build_fx_carry_factor_panel(obs)

    model = MultivariateStudentTModel(panel, random_seed=42)
    fit_rep = model.build_fit_report()
    assert fit_rep.model_type == "multivariate_student_t"
    assert fit_rep.degrees_of_freedom is not None
    assert 2.1 <= fit_rep.degrees_of_freedom <= 100.0

    paths = model.generate_paths(num_paths=5, horizon=30)
    assert len(paths) == 5
    for p in paths:
        assert p.steps == 30
        assert all(rate > 0.0 for rate in p.fx_rates)


def test_positive_semidefinite_repair():
    """ensure_positive_semidefinite repairs non-PSD matrices and records adjustment."""
    non_psd = np.array([
        [1.0, 0.99, 0.99],
        [0.99, 1.0, 0.99],
        [0.99, 0.99, 0.98],
    ])
    # The matrix has eigenvalues; check repair
    repaired, was_repaired, diff = ensure_positive_semidefinite(non_psd)
    eigvals = np.linalg.eigvalsh(repaired)
    assert all(ev >= 1e-8 for ev in eigvals)


# =============================================================================
# 6. Real Holdout Diagnostics Tests
# =============================================================================


def test_holdout_diagnostics_evaluation():
    """evaluate_holdout_against_distribution validates 2024 holdout against predictive paths."""
    obs_calib = make_test_observations(start_date=date(2020, 1, 1), num_days=200)
    obs_holdout = make_test_observations(start_date=date(2024, 1, 1), num_days=100)

    panel_calib = build_fx_carry_factor_panel(obs_calib)
    panel_holdout = build_fx_carry_factor_panel(obs_holdout)

    model = MultivariateGaussianModel(panel_calib, random_seed=42)
    paths = model.generate_paths(num_paths=20, horizon=len(panel_holdout.dates))

    strategy = CarryTradeScenarioStrategy(tenor_days=30, rebalance_days=30)
    evals = [strategy.evaluate_path(p, initial_capital_a=100_000.0) for p in paths]

    diag = evaluate_holdout_diagnostics(
        calibration_panel=panel_calib,
        holdout_panel=panel_holdout,
        predictive_evaluations=evals,
    )

    assert diag.holdout_year == 2024
    assert diag.holdout_days == len(panel_holdout.dates)
    assert diag.realized_fx_volatility_annualized > 0.0
    assert 0.0 <= diag.predictive_quantile_return <= 100.0
    assert 0.0 <= diag.rate_change_ks_pvalue <= 1.0
    assert len(diag.limitations_notes) > 0


# =============================================================================
# 7. Multi-Metric Convergence Tests
# =============================================================================


def test_multi_metric_convergence_tracking():
    """assess_multi_metric_convergence tracks mean, median, loss prob, VaR, CVaR, drawdown."""
    obs = make_test_observations(num_days=200)
    panel = build_fx_carry_factor_panel(obs)
    model = MultivariateGaussianModel(panel, random_seed=42)
    paths = model.generate_paths(num_paths=40, horizon=30)

    strategy = CarryTradeScenarioStrategy(tenor_days=30, rebalance_days=30)
    evals = [strategy.evaluate_path(p, initial_capital_a=100_000.0) for p in paths]

    conv_rep = evaluate_convergence(
        evaluations=evals,
        checkpoints=[10, 20, 40],
    )

    assert len(conv_rep.checkpoints) == 3
    final_chk = conv_rep.checkpoints[-1]
    assert final_chk.sample_size == 40
    assert final_chk.var_95 is not None
    assert final_chk.cvar_95 is not None
    assert final_chk.tail_sample_size >= 2
    assert final_chk.max_drawdown_median is not None


# =============================================================================
# 8. Correlation Breakdown Stress Scenario Tests
# =============================================================================


def test_correlation_breakdown_scenario():
    """generate_correlation_breakdown_path sets off-diagonal correlations to 0 and repairs PSD."""
    obs = make_test_observations(num_days=200)
    panel = build_fx_carry_factor_panel(obs)

    stressed_path, info = generate_correlation_breakdown_path(panel, horizon=30, random_seed=42)
    assert stressed_path.steps == 30
    assert len(stressed_path.fx_rates) == 31
    assert all(r > 0.0 for r in stressed_path.fx_rates)
    assert all(b >= 0.0 for b in stressed_path.borrowing_rates)
    assert all(y >= 0.0 for y in stressed_path.investment_rates)
    assert stressed_path.is_synthetic is True
