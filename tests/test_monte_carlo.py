"""Test suite for Phase 4 Monte Carlo & Market Scenario Laboratory.

Validates factor models, transformations, bootstrap samplers, parametric distributions,
volatility regimes, deterministic stress scenarios, strategy evaluation,
double-entry accounting reconciliation, and provenance contracts.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import math

import numpy as np
import pytest

from data.schemas import (
    AvailabilityEvidence,
    DataClassification,
    DataObservation,
    Frequency,
    ObservationKind,
)
from simulation.monte_carlo import (
    BootstrapMethod,
    CarryTradeScenarioStrategy,
    ConvergenceReport,
    DistributionMetrics,
    FactorCategory,
    FactorPanel,
    HistoricalBootstrapSampler,
    MarketFactor,
    MonteCarloEngine,
    MonteCarloResult,
    MultivariateGaussianModel,
    MultivariateStudentTModel,
    PathEvaluationResult,
    RegimeConditionedSampler,
    RegimeState,
    ScenarioPath,
    SimulationConfig,
    SimulationModelType,
    StressScenario,
    TransformationMethod,
    VolatilityRegimeClassifier,
    apply_stress_scenario,
    build_fx_carry_factor_panel,
    build_standard_stress_scenarios,
    calibrate_factor_panel,
    calculate_distribution_metrics,
    compute_differences,
    compute_log_returns,
    ensure_positive_semidefinite,
    evaluate_convergence,
    reconstruct_price_levels,
    reconstruct_rate_levels,
    split_calibration_holdout,
)


# =============================================================================
# Helper Fixtures
# =============================================================================


def make_synthetic_obs_series(
    start_date: date = date(2020, 1, 1),
    num_days: int = 500,
    seed: int = 1234,
) -> list[DataObservation]:
    """Generate realistic deterministic observations for testing."""
    rng = np.random.default_rng(seed)
    obs: list[DataObservation] = []

    curr_fx = 1.10
    curr_ecb = 2.0
    curr_treasury = 3.5

    for i in range(num_days):
        d = start_date + timedelta(days=i)
        if d.weekday() >= 5:  # Skip weekends
            continue

        ts = datetime(d.year, d.month, d.day, 14, 15, tzinfo=timezone.utc)
        pub_ts = datetime(d.year, d.month, d.day, 15, 0, tzinfo=timezone.utc)

        # FX EUR/USD step
        curr_fx *= math.exp(float(rng.normal(0.0, 0.005)))
        obs.append(
            DataObservation(
                kind=ObservationKind.EXCHANGE_RATE,
                source_id="frankfurter",
                entity_code="EUR/USD",
                value=curr_fx,
                unit="USD_per_EUR",
                frequency=Frequency.DAILY,
                observation_date=d,
                publication_date=d,
                observation_timestamp=ts,
                publication_timestamp=pub_ts,
                retrieved_at=pub_ts,
                classification=DataClassification.REAL_VERIFIED,
                availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            )
        )

        # ECB policy rate (stepped changes every ~40 days)
        if i % 40 == 0 and i > 0:
            curr_ecb += float(rng.choice([-0.25, 0.25, 0.50]))
        obs.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                source_id="ecb",
                entity_code="ECB_EA",
                indicator_id="KR.MRR_FR.LEV",
                value=curr_ecb,
                unit="percent",
                frequency=Frequency.DAILY,
                observation_date=d,
                publication_date=d,
                observation_timestamp=ts,
                publication_timestamp=pub_ts,
                retrieved_at=pub_ts,
                classification=DataClassification.REAL_VERIFIED,
                availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            )
        )

        # US Treasury 1M yield
        curr_treasury += float(rng.normal(0.0, 0.03))
        obs.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                source_id="us_treasury",
                entity_code="USD",
                indicator_id="DGS1MO",
                value=max(0.1, curr_treasury),
                unit="percent",
                frequency=Frequency.DAILY,
                observation_date=d,
                publication_date=d,
                observation_timestamp=ts,
                publication_timestamp=pub_ts,
                retrieved_at=pub_ts,
                classification=DataClassification.REAL_VERIFIED,
                availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            )
        )

    return obs


# =============================================================================
# 1. Factor Construction & Transformations
# =============================================================================


def test_log_returns_and_price_reconstruction():
    """Verify log return calculation and exact mathematical price reconstruction."""
    prices = [1.00, 1.05, 1.02, 1.10]
    returns = compute_log_returns(prices)
    assert len(returns) == 3
    assert returns[0] == pytest.approx(math.log(1.05 / 1.00), rel=1e-12)
    assert returns[1] == pytest.approx(math.log(1.02 / 1.05), rel=1e-12)

    # Reconstruct
    reconstructed = reconstruct_price_levels(1.00, returns)
    assert len(reconstructed) == len(prices)
    for p_orig, p_rec in zip(prices, reconstructed):
        assert p_rec == pytest.approx(p_orig, rel=1e-12)
        assert p_rec > 0.0  # Prices must remain strictly positive


def test_log_returns_rejects_negative_or_zero_price():
    """compute_log_returns must raise ValueError on non-positive prices."""
    with pytest.raises(ValueError, match="strictly positive"):
        compute_log_returns([1.0, -0.5, 1.1])
    with pytest.raises(ValueError, match="strictly positive"):
        compute_log_returns([1.0, 0.0, 1.1])


def test_rate_differences_and_reconstruction():
    """Verify interest rate difference calculation in bps and level reconstruction."""
    rates = [2.00, 2.25, 2.25, 2.50]  # percent
    diffs_bps = compute_differences(rates, in_bps=True)
    assert len(diffs_bps) == 3
    assert diffs_bps[0] == pytest.approx(25.0, rel=1e-12)
    assert diffs_bps[1] == pytest.approx(0.0, rel=1e-12)
    assert diffs_bps[2] == pytest.approx(25.0, rel=1e-12)

    reconstructed = reconstruct_rate_levels(2.00, diffs_bps, in_bps=True)
    assert len(reconstructed) == len(rates)
    for r_orig, r_rec in zip(rates, reconstructed):
        assert r_rec == pytest.approx(r_orig, rel=1e-12)


def test_factor_panel_construction_and_alignment():
    """build_fx_carry_factor_panel aligns calendars without look-ahead or synthetic data."""
    obs = make_synthetic_obs_series(num_days=300)
    panel = build_fx_carry_factor_panel(obs)

    assert panel.is_aligned is True
    assert panel.effective_sample_size > 150
    assert len(panel.dates) == panel.effective_sample_size
    assert "FX_EUR_USD_LOGRET" in panel.values
    assert "RATE_DIFF_EUR_BORROW_BPS" in panel.values
    assert "YIELD_DIFF_USD_1M_BPS" in panel.values

    # Check that lengths match across all factors
    for fname, series in panel.values.items():
        assert len(series) == panel.effective_sample_size


# =============================================================================
# 2. Calibration & Holdout Split
# =============================================================================


def test_chronological_calibration_holdout_split():
    """split_calibration_holdout preserves chronological sequence without shuffling."""
    obs = make_synthetic_obs_series(start_date=date(2020, 1, 1), num_days=600)
    panel = build_fx_carry_factor_panel(obs)

    split_date = date(2021, 6, 30)
    calib, holdout = split_calibration_holdout(panel, calibration_end=split_date)

    assert max(calib.dates) <= split_date
    assert min(holdout.dates) > split_date
    assert len(calib.dates) + len(holdout.dates) == len(panel.dates)

    report = calibrate_factor_panel(calib, holdout, min_observations=50)
    assert report.is_sufficient is True
    assert report.calibration_sample_size == len(calib.dates)
    assert report.holdout_sample_size == len(holdout.dates)
    assert len(report.factor_names) == len(calib.values)


# =============================================================================
# 3. Bootstrap Engines (IID, Moving-Block, Stationary)
# =============================================================================


def test_iid_bootstrap_reproducibility():
    """IID bootstrap produces identical output given identical random seeds."""
    obs = make_synthetic_obs_series(num_days=200)
    panel = build_fx_carry_factor_panel(obs)

    b1 = HistoricalBootstrapSampler(panel, method=BootstrapMethod.IID, random_seed=42)
    b2 = HistoricalBootstrapSampler(panel, method=BootstrapMethod.IID, random_seed=42)

    p1 = b1.generate_path(0, horizon=30)
    p2 = b2.generate_path(0, horizon=30)

    assert p1.fx_rates == pytest.approx(p2.fx_rates, rel=1e-12)
    assert p1.borrowing_rates == pytest.approx(p2.borrowing_rates, rel=1e-12)
    assert p1.investment_rates == pytest.approx(p2.investment_rates, rel=1e-12)


def test_moving_block_bootstrap_preserves_joint_factors():
    """Moving-block bootstrap samples contiguous blocks preserving joint multivariate factors."""
    obs = make_synthetic_obs_series(num_days=300)
    panel = build_fx_carry_factor_panel(obs)

    sampler = HistoricalBootstrapSampler(panel, method=BootstrapMethod.MOVING_BLOCK, block_size=10, random_seed=99)
    indices = sampler.sample_indices(horizon=30)

    assert len(indices) == 30
    # Slices within blocks must be contiguous
    for b in range(3):
        block = indices[b * 10 : (b + 1) * 10]
        diffs = np.diff(block)
        assert np.all(diffs == 1)


def test_stationary_bootstrap_generates_positive_prices():
    """Stationary bootstrap (Politis & Romano 1994) reconstructs strictly positive FX prices."""
    obs = make_synthetic_obs_series(num_days=300)
    panel = build_fx_carry_factor_panel(obs)

    sampler = HistoricalBootstrapSampler(panel, method=BootstrapMethod.STATIONARY, block_size=15, random_seed=777)
    paths = sampler.generate_paths(num_paths=5, horizon=50)

    assert len(paths) == 5
    for p in paths:
        assert p.steps == 50
        assert len(p.fx_rates) == 51
        assert all(rate > 0.0 for rate in p.fx_rates)
        assert all(r >= 0.0 for r in p.borrowing_rates)
        assert all(y >= 0.0 for y in p.investment_rates)


# =============================================================================
# 4. Parametric Multivariate Models & PSD Repair
# =============================================================================


def test_positive_semidefinite_repair():
    """ensure_positive_semidefinite repairs non-PSD matrices and records adjustment."""
    # Construct a non-PSD matrix with a negative eigenvalue
    non_psd = np.array([
        [1.0, 0.99, 0.99],
        [0.99, 1.0, 0.99],
        [0.99, 0.99, 0.5],
    ])
    eigvals_orig = np.linalg.eigvalsh(non_psd)
    assert np.min(eigvals_orig) < 0.0

    repaired, was_repaired, diff = ensure_positive_semidefinite(non_psd)
    assert was_repaired is True
    assert diff > 0.0

    eigvals_rep = np.linalg.eigvalsh(repaired)
    assert np.min(eigvals_rep) >= 1e-8


def test_multivariate_gaussian_model():
    """MultivariateGaussianModel generates paths with expected dimension and positive prices."""
    obs = make_synthetic_obs_series(num_days=300)
    panel = build_fx_carry_factor_panel(obs)

    gauss = MultivariateGaussianModel(panel, random_seed=42)
    paths = gauss.generate_paths(num_paths=5, horizon=40)

    assert len(paths) == 5
    for p in paths:
        assert len(p.fx_rates) == 41
        assert all(rate > 0.0 for rate in p.fx_rates)


def test_multivariate_student_t_model():
    """MultivariateStudentTModel estimates finite degrees of freedom and samples heavy tails."""
    obs = make_synthetic_obs_series(num_days=300)
    panel = build_fx_carry_factor_panel(obs)

    t_model = MultivariateStudentTModel(panel, random_seed=42)
    assert t_model.nu > 2.0  # Must be > 2 for finite variance

    paths = t_model.generate_paths(num_paths=5, horizon=40)
    assert len(paths) == 5
    for p in paths:
        assert len(p.fx_rates) == 41
        assert all(rate > 0.0 for rate in p.fx_rates)


# =============================================================================
# 5. Volatility Regimes & Transition Matrix
# =============================================================================


def test_volatility_regime_classification_and_transitions():
    """VolatilityRegimeClassifier creates valid Markov transition probability matrix."""
    obs = make_synthetic_obs_series(num_days=500)
    panel = build_fx_carry_factor_panel(obs)

    classifier = VolatilityRegimeClassifier(panel, rolling_window=30)
    report = classifier.build_report()

    assert report.is_sufficient is True
    # Row probabilities in transition matrix must sum to 1.0
    for s1, row in report.transition_matrix.items():
        assert sum(row.values()) == pytest.approx(1.0, rel=1e-6)

    sampler = RegimeConditionedSampler(panel, classifier, random_seed=123)
    paths = sampler.generate_paths(num_paths=3, horizon=30)
    assert len(paths) == 3
    for p in paths:
        assert p.regimes is not None
        assert len(p.regimes) == 30


# =============================================================================
# 6. Deterministic Stress Scenarios
# =============================================================================


def test_deterministic_stress_shocks():
    """apply_stress_scenario applies shocks accurately to a baseline path."""
    horizon = 10
    base = ScenarioPath(
        path_id=0,
        steps=horizon,
        fx_rates=[1.10] * (horizon + 1),
        borrowing_rates=[0.03] * (horizon + 1),
        investment_rates=[0.05] * (horizon + 1),
        is_synthetic=True,
    )

    stress = StressScenario(
        name="Test Shock After Entry",
        description="FX -10%, Borrowing +200 bps, Yield -100 bps",
        fx_shock_pct=-0.10,
        borrowing_rate_shock_bps=200.0,
        investment_rate_shock_bps=-100.0,
        shock_timing="after_entry",
        shock_step=1,
    )

    stressed = apply_stress_scenario(base, stress)
    assert stressed.fx_rates[0] == pytest.approx(1.10, rel=1e-12)
    # In provider quote terms (USD per EUR), adverse USD shock of -10% divides provider quote by 0.90
    assert stressed.fx_rates[1] == pytest.approx(1.10 / 0.90, rel=1e-12)
    # In canonical terms (EUR per USD), canonical rate depreciates by exactly 10%
    assert (1.0 / stressed.fx_rates[1]) == pytest.approx((1.0 / 1.10) * 0.90, rel=1e-12)
    assert stressed.borrowing_rates[1] == pytest.approx(0.03 + 0.02, rel=1e-12)
    assert stressed.investment_rates[1] == pytest.approx(0.05 - 0.01, rel=1e-12)

    stress_pre = StressScenario(
        name="Test Shock Pre Entry",
        description="FX -10% pre-entry",
        fx_shock_pct=-0.10,
        shock_timing="pre_entry",
    )
    stressed_pre = apply_stress_scenario(base, stress_pre)
    assert stressed_pre.fx_rates[0] == pytest.approx(1.10 / 0.90, rel=1e-12)


def test_standard_stress_scenarios_suite():
    """build_standard_stress_scenarios builds required single and compound scenarios."""
    scenarios = build_standard_stress_scenarios()
    assert len(scenarios) >= 12
    categories = {s.category for s in scenarios}
    assert "single_factor" in categories
    assert "compound" in categories
    assert "liquidity" in categories


# =============================================================================
# 7. Financial Strategy Integration & Double-Entry Ledger Parity
# =============================================================================


def test_deterministic_no_randomness_strategy_parity():
    """A flat constant path produces exact double-entry ledger reconciliation residual <= 1e-10."""
    horizon = 60
    flat_path = ScenarioPath(
        path_id=0,
        steps=horizon,
        fx_rates=[1.10] * (horizon + 1),
        borrowing_rates=[0.02] * (horizon + 1),
        investment_rates=[0.05] * (horizon + 1),
        is_synthetic=True,
    )

    strategy = CarryTradeScenarioStrategy(tenor_days=30, rebalance_days=30)
    result = strategy.evaluate_path(flat_path, initial_capital_a=100_000.0)

    # Must reconcile exactly: Net Profit == Pure Gross - Financing - Frictions + Cash Yield
    assert result.reconciliation_exact is True
    assert result.reconciliation_residual_a <= 1e-10
    # With a positive 300 bps yield spread (5% - 2%) and flat FX, profit must be positive
    assert result.total_return > 0.0


def test_strategy_double_entry_reconciliation_across_volatile_path():
    """Simulated volatile paths must always reconcile exactly (residual <= 1e-10)."""
    obs = make_synthetic_obs_series(num_days=300)
    panel = build_fx_carry_factor_panel(obs)

    sampler = HistoricalBootstrapSampler(panel, method=BootstrapMethod.MOVING_BLOCK, random_seed=42)
    paths = sampler.generate_paths(num_paths=10, horizon=90)

    strategy = CarryTradeScenarioStrategy(tenor_days=30, rebalance_days=30)
    for p in paths:
        ev = strategy.evaluate_path(p, initial_capital_a=100_000.0)
        assert ev.reconciliation_exact is True
        assert ev.reconciliation_residual_a <= 1e-10


# =============================================================================
# 8. Monte Carlo Engine & Risk Metrics
# =============================================================================


def test_monte_carlo_engine_execution_and_metrics():
    """MonteCarloEngine executes end-to-end and computes distribution metrics & SEs."""
    obs = make_synthetic_obs_series(num_days=300)

    cfg = SimulationConfig(
        simulation_id="TEST_RUN",
        model_type=SimulationModelType.HISTORICAL_BOOTSTRAP,
        bootstrap_method=BootstrapMethod.MOVING_BLOCK,
        num_paths=50,
        horizon_steps=60,
        random_seed=42,
    )

    engine = MonteCarloEngine(config=cfg, observations=obs)
    res = engine.run()

    assert res.simulation_id == "TEST_RUN"
    assert res.data_classification == DataClassification.SIMULATED
    assert res.distribution_metrics.num_paths == 50
    assert res.distribution_metrics.all_paths_reconciled is True
    assert res.distribution_metrics.prob_loss_se >= 0.0
    assert "best" in res.representative_paths
    assert "median" in res.representative_paths
    assert "worst" in res.representative_paths


def test_monte_carlo_engine_deterministic_stress_tests():
    """run_deterministic_stress_tests evaluates strategy across stress scenarios."""
    obs = make_synthetic_obs_series(num_days=300)
    cfg = SimulationConfig(num_paths=10, horizon_steps=30)
    engine = MonteCarloEngine(config=cfg, observations=obs)

    stress_res = engine.run_deterministic_stress_tests()
    assert len(stress_res) >= 12
    for r in stress_res:
        assert "scenario_name" in r
        assert "total_return" in r
        assert r["reconciliation_exact"] is True


def test_monte_carlo_convergence_report():
    """evaluate_convergence verifies standard errors diminish as sample size increases."""
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
        for i in range(200)
    ]

    report = evaluate_convergence(evals, checkpoints=[50, 100, 200])
    assert len(report.checkpoints) == 3
    # SE of proportion at N=200 should be lower than at N=50: sqrt(p(1-p)/N)
    se_50 = report.checkpoints[0].prob_loss_se
    se_200 = report.checkpoints[2].prob_loss_se
    assert se_200 < se_50
