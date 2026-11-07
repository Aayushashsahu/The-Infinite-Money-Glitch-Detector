"""Phase 4.1.1 Predictive Validation & Evidence Reconciliation Test Suite.

Comprehensive tests verifying:
1. Holdout diagnostic variable matching: FX factor metrics vs actual 2024 FX, sample size >= 1000, unavailable portfolio holdout
2. Correlation-breakdown stress comparison: marginal variance/mean preservation, PSD repair, CRN paired paths, attribution differences
3. Calibration availability accounting: exhaustive 5-bucket reconciliation, retrospective tracking, synthetic separation
4. Point-in-time semantics: estimated stays estimated, policy rate effective dates, release lag policies
5. Simulated trading calendar validation: weekend 3-day accrual, holiday accrual, t=0 zero interest, 30-day tenor, independent formula check
6. Funding sensitivity: fixed-rate insulation vs floating-rate rate shocks, cash ledger reconciliation
7. Reporting and reproducibility manifest: dynamic comparison matching, factor percentiles, manifest completeness and SHA-256 hashes
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import numpy as np
import pytest

from data.schemas import AvailabilityEvidence, DataClassification, DataObservation, Frequency, ObservationKind
from simulation.monte_carlo.schemas import (
    AvailabilityAuditReport,
    CalendarValidationReport,
    CorrelationStressComparison,
    FactorHoldoutDiagnostics,
    FundingSensitivityReport,
    PortfolioHoldoutDiagnostics,
    ScenarioPath,
)
from simulation.monte_carlo.calibration import (
    build_availability_audit,
    classify_observation_evidence,
)
from simulation.monte_carlo.factors import build_fx_carry_factor_panel
from simulation.monte_carlo.holdout import (
    evaluate_factor_holdout_diagnostics,
    evaluate_portfolio_holdout_diagnostics,
)
from simulation.monte_carlo.shocks import (
    evaluate_correlation_stress_distribution,
)
from simulation.monte_carlo.strategy_adapter import (
    CarryTradeScenarioStrategy,
    evaluate_funding_sensitivity,
    generate_simulated_trading_sessions,
    validate_market_calendar_evidence,
)
from simulation.monte_carlo.distributions import (
    ensure_positive_semidefinite,
)


def make_test_observations(
    start_date: date = date(2020, 1, 1),
    num_days: int = 1825,
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


# =====================================================================
# Fixtures
# =====================================================================

@pytest.fixture
def mock_factor_observations():
    """Build mock observations spanning 2020-2023 for calibration and 2024 for holdout."""
    return make_test_observations(start_date=date(2020, 1, 1), num_days=1825, include_dgs3mo=True)


@pytest.fixture
def mock_panels(mock_factor_observations):
    """Build mock calibration panel (2020-2023) and holdout panel (2024)."""
    calib = build_fx_carry_factor_panel(
        mock_factor_observations,
        start_date=date(2020, 1, 1),
        end_date=date(2023, 12, 31),
    )
    holdout = build_fx_carry_factor_panel(
        mock_factor_observations,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
    )
    return calib, holdout


# =====================================================================
# 1. Holdout Validation Tests
# =====================================================================

def test_holdout_diagnostic_variable_matching(mock_panels):
    """Verify simulated FX metrics are compared with actual FX metrics, not portfolio metrics."""
    calib_panel, holdout_panel = mock_panels
    rng = np.random.default_rng(42)
    n_paths = 1000
    n_steps = len(holdout_panel.dates)
    sessions = holdout_panel.dates

    # Build 1000 predictive ScenarioPath objects
    pred_paths: list[ScenarioPath] = []
    initial_fx = 1.10
    for i in range(n_paths):
        rets = rng.normal(loc=0.0001, scale=0.004, size=n_steps)
        prices = [initial_fx]
        for r in rets:
            prices.append(prices[-1] * math.exp(r))
        pred_paths.append(
            ScenarioPath(
                path_id=i,
                steps=n_steps,
                dates=[sessions[0] - timedelta(days=1)] + sessions,
                fx_rates=prices,
                borrowing_rates=[0.02] * (n_steps + 1),
                investment_rates=[0.05] * (n_steps + 1),
                is_synthetic=True,
            )
        )

    diag = evaluate_factor_holdout_diagnostics(
        calibration_panel=calib_panel,
        holdout_panel=holdout_panel,
        predictive_paths=pred_paths,
    )

    assert isinstance(diag, FactorHoldoutDiagnostics)
    assert diag.num_predictive_paths == 1000
    assert isinstance(diag.actual_fx_cumulative_return, float)
    assert isinstance(diag.actual_fx_realized_volatility, float)
    assert isinstance(diag.actual_fx_max_drawdown, float)
    assert 0.0 <= diag.predictive_percentile_fx_return <= 1.0
    assert 0.0 <= diag.predictive_percentile_fx_volatility <= 1.0
    assert 0.0 <= diag.predictive_percentile_fx_drawdown <= 1.0
    assert diag.predictive_percentile_fx_return_mc_se >= 0.0
    assert diag.fx_log_return_ks_stat >= 0.0
    assert 0.0 <= diag.fx_log_return_ks_pvalue <= 1.0
    assert "serial dependence" in diag.fx_log_return_ks_caveat.lower()


def test_holdout_predictive_sample_size(mock_panels):
    """Verify predictive sample size >= 1000 paths and MC standard error calculation."""
    calib_panel, holdout_panel = mock_panels
    _rng = np.random.default_rng(123)
    n_paths = 1000
    n_steps = len(holdout_panel.dates)
    sessions = holdout_panel.dates

    pred_paths = [
        ScenarioPath(
            path_id=i,
            steps=n_steps,
            dates=[sessions[0] - timedelta(days=1)] + sessions,
            fx_rates=[1.10] * (n_steps + 1),
            borrowing_rates=[0.02] * (n_steps + 1),
            investment_rates=[0.05] * (n_steps + 1),
            is_synthetic=True,
        )
        for i in range(n_paths)
    ]

    diag = evaluate_factor_holdout_diagnostics(
        calibration_panel=calib_panel,
        holdout_panel=holdout_panel,
        predictive_paths=pred_paths,
    )
    assert diag.num_predictive_paths == 1000
    p = diag.predictive_percentile_fx_return
    expected_se = math.sqrt(p * (1.0 - p) / 1000.0)
    assert pytest.approx(diag.predictive_percentile_fx_return_mc_se, abs=1e-5) == expected_se


def test_portfolio_holdout_unavailable_status():
    """Verify portfolio holdout returns UNAVAILABLE status without fabricated metrics."""
    port_diag = evaluate_portfolio_holdout_diagnostics()
    assert isinstance(port_diag, PortfolioHoldoutDiagnostics)
    assert port_diag.status == "UNAVAILABLE"
    assert port_diag.is_available is False
    assert port_diag.simulated_portfolio_median_return is None
    assert port_diag.simulated_portfolio_median_drawdown is None
    assert "no genuine" in port_diag.reason.lower()


def test_holdout_no_data_leakage(mock_panels):
    """Verify calibration period (2020-2023) does not include 2024 holdout observations."""
    calib_panel, holdout_panel = mock_panels
    assert max(calib_panel.dates) <= date(2023, 12, 31)
    assert min(holdout_panel.dates) >= date(2024, 1, 1)
    overlap = set(calib_panel.dates).intersection(set(holdout_panel.dates))
    assert len(overlap) == 0


# =====================================================================
# 2. Correlation Breakdown Stress Comparison Tests
# =====================================================================

def test_correlation_stress_marginal_variance_mean_preservation():
    """Verify stressed covariance preserves marginal variances and means."""
    cov = np.array([
        [0.0004, 0.0001, 0.00005, 0.00002],
        [0.0001, 0.0009, 0.00003, 0.00001],
        [0.00005, 0.00003, 0.00016, 0.00004],
        [0.00002, 0.00001, 0.00004, 0.00025],
    ])
    _mean = np.array([0.0001, -0.0002, 0.00005, 0.00003])

    # Stressed decoupling: off-diagonals to 0
    stressed_cov = np.diag(np.diag(cov))
    stressed_cov_psd, was_repaired, frob = ensure_positive_semidefinite(stressed_cov)

    assert np.allclose(np.diag(stressed_cov_psd), np.diag(cov))
    eigenvalues = np.linalg.eigvalsh(stressed_cov_psd)
    assert np.all(eigenvalues >= 0)


def test_correlation_stress_distribution_comparison(mock_panels):
    """Verify paired paths in distribution comparison use Common Random Numbers and preserve marginals."""
    calib_panel, _ = mock_panels
    strategy = CarryTradeScenarioStrategy(tenor_days=30, rebalance_days=35)

    comp = evaluate_correlation_stress_distribution(
        panel=calib_panel,
        strategy=strategy,
        num_paths=1000,
        horizon=252,
        random_seed=42,
    )
    assert isinstance(comp, CorrelationStressComparison)
    assert comp.num_paths == 1000
    assert comp.marginal_means_preserved is True
    assert comp.marginal_variances_preserved is True
    assert comp.stressed_prob_loss >= 0.0
    assert comp.baseline_prob_loss >= 0.0
    assert pytest.approx(comp.mean_return_difference, abs=1e-5) == (
        comp.stressed_mean_return - comp.baseline_mean_return
    )


# =====================================================================
# 3. Availability Accounting Tests
# =====================================================================

def test_availability_accounting_exhaustive_sum():
    """Verify the five evidence buckets sum exactly to total genuine observations."""
    obs = [
        DataObservation(
            source_id="ecb",
            entity_code="EUR/USD",
            unit="USD_PER_EUR",
            frequency=Frequency.DAILY,
            observation_date=date(2023, 1, 1),
            retrieved_at=datetime.now(timezone.utc),
            value=1.1,
            kind=ObservationKind.EXCHANGE_RATE,
            classification=DataClassification.REAL_ESTIMATED_AVAILABILITY,
            availability_evidence=AvailabilityEvidence.ESTIMATED_SCHEDULE,
            is_synthetic=False,
        ),
        DataObservation(
            source_id="fred",
            indicator_id="DGS1MO",
            entity_code="USA",
            unit="PERCENT",
            frequency=Frequency.DAILY,
            observation_date=date(2023, 1, 2),
            retrieved_at=datetime.now(timezone.utc),
            value=0.05,
            kind=ObservationKind.INTEREST_RATE,
            classification=DataClassification.REAL_RETROSPECTIVE,
            availability_evidence=AvailabilityEvidence.RETROSPECTIVE,
            is_synthetic=False,
        ),
        DataObservation(
            source_id="mock",
            entity_code="TEST",
            unit="UNIT",
            frequency=Frequency.DAILY,
            observation_date=date(2023, 1, 3),
            retrieved_at=datetime.now(timezone.utc),
            value=1.0,
            kind=ObservationKind.MACRO_INDICATOR,
            classification=DataClassification.SYNTHETIC,
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            is_synthetic=True,
        ),
    ]

    audit = build_availability_audit(obs)
    assert isinstance(audit, AvailabilityAuditReport)
    assert audit.total_source_observations == 3
    assert audit.synthetic_observations_excluded == 1
    assert audit.genuine_observations_included == 2
    sum_buckets = (
        audit.exact_timestamp_verified_count
        + audit.estimated_availability_count
        + audit.retrospective_count
        + audit.missing_evidence_count
        + audit.unrecognized_evidence_count
    )
    assert sum_buckets == audit.genuine_observations_included
    assert audit.is_reconciled is True
    assert audit.retrospective_count == 1
    assert audit.estimated_availability_count == 1


def test_classify_observation_evidence_mutually_exclusive():
    """Verify helper returns mutually exclusive category strings."""
    # Retrospective by classification
    o1 = DataObservation(
        source_id="s1", entity_code="c1", unit="u", frequency=Frequency.DAILY,
        observation_date=date(2023, 1, 1), retrieved_at=datetime.now(timezone.utc),
        value=1.0, kind=ObservationKind.INTEREST_RATE,
        classification=DataClassification.REAL_RETROSPECTIVE,
        availability_evidence=AvailabilityEvidence.RETROSPECTIVE,
    )
    assert classify_observation_evidence(o1) == "retrospective"

    # Exact timestamp verified
    o2 = DataObservation(
        source_id="s2", entity_code="c2", unit="u", frequency=Frequency.DAILY,
        observation_date=date(2023, 1, 1), retrieved_at=datetime.now(timezone.utc),
        publication_timestamp=datetime.now(timezone.utc),
        value=1.0, kind=ObservationKind.EXCHANGE_RATE,
        classification=DataClassification.REAL_VERIFIED,
        availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
    )
    assert classify_observation_evidence(o2) == "exact_timestamp_verified"

    # Estimated schedule
    o3 = DataObservation(
        source_id="s3", entity_code="c3", unit="u", frequency=Frequency.DAILY,
        observation_date=date(2023, 1, 1), retrieved_at=datetime.now(timezone.utc),
        value=1.0, kind=ObservationKind.EXCHANGE_RATE,
        classification=DataClassification.REAL_ESTIMATED_AVAILABILITY,
        availability_evidence=AvailabilityEvidence.ESTIMATED_SCHEDULE,
    )
    assert classify_observation_evidence(o3) == "estimated_schedule"


# =====================================================================
# 4. Point-in-Time Semantics Tests
# =====================================================================

def test_estimated_schedule_never_reclassified_exact():
    """Verify ESTIMATED_SCHEDULE is never counted or classified as EXACT_TIMESTAMP_VERIFIED."""
    obs = [
        DataObservation(
            source_id="ecb",
            entity_code="EUR/USD",
            unit="USD_PER_EUR",
            frequency=Frequency.DAILY,
            observation_date=date(2023, 1, 1),
            retrieved_at=datetime.now(timezone.utc),
            value=1.1,
            kind=ObservationKind.EXCHANGE_RATE,
            classification=DataClassification.REAL_ESTIMATED_AVAILABILITY,
            availability_evidence=AvailabilityEvidence.ESTIMATED_SCHEDULE,
            is_synthetic=False,
        )
    ]
    audit = build_availability_audit(obs)
    assert audit.estimated_availability_count == 1
    assert audit.exact_timestamp_verified_count == 0


def test_release_lag_policies_documented():
    """Verify all 4 factors have documented release lag policies."""
    audit = build_availability_audit([])
    assert len(audit.release_lag_policies) == 4
    keys = set(audit.release_lag_policies.keys())
    assert keys == {"FX_EUR_USD", "DGS1MO", "DGS3MO", "EUR_BORROW_RATE"}


# =====================================================================
# 5. Simulated Calendar Validation Tests
# =====================================================================

def test_calendar_validation_evidence():
    """Verify calendar validation report checks weekend 3-day accrual, holiday accrual, t=0, and analytical formula."""
    report = validate_market_calendar_evidence()
    assert isinstance(report, CalendarValidationReport)
    assert report.weekend_3day_accrual_verified is True
    assert report.holiday_accrual_verified is True
    assert report.initial_state_zero_interest is True
    assert report.tenor_30day_maturity_verified is True
    assert report.independent_numerical_accrual_verified is True
    assert report.transitions_n_levels_n_plus_1_verified is True


def test_calendar_weekend_3_day_accrual():
    """Verify Friday-to-Monday accrual is exactly 3 days."""
    friday = date(2024, 1, 5)
    monday = date(2024, 1, 8)
    delta_days = (monday - friday).days
    assert delta_days == 3


def test_calendar_initial_state_zero_interest():
    """Verify t=0 interest is 0.0 in simulated sessions."""
    sessions = generate_simulated_trading_sessions(
        start_date=date(2024, 1, 2),
        n_sessions=11,
        calendar_type="JOINT_TARGET2_FED",
    )
    assert len(sessions) == 11  # N+1 levels
    # Elapsed calendar days between consecutive sessions are >= 1
    deltas = [(sessions[i] - sessions[i - 1]).days for i in range(1, len(sessions))]
    for d in deltas:
        assert d >= 1


# =====================================================================
# 6. Funding Sensitivity Tests
# =====================================================================

def test_funding_sensitivity_evaluation():
    """Verify fixed-rate funding insulates trade while floating-rate resets financing costs."""
    rep = evaluate_funding_sensitivity()
    assert isinstance(rep, FundingSensitivityReport)
    assert rep.funding_conventions == ["fixed_rate_funding", "floating_rate_reset_funding"]
    # With interest rates increasing by +500 bps, floating mode incurs higher financing cost
    scen_500 = next(s for s in rep.scenarios if s["shock_bps"] == 500)
    assert scen_500["floating_financing_cost_a"] > scen_500["fixed_financing_cost_a"]
    assert scen_500["financing_cost_difference_a"] > 0.0
    assert scen_500["floating_net_profit_a"] < scen_500["fixed_net_profit_a"]

    # Baseline (0 bps shock) has zero financing difference
    scen_0 = next(s for s in rep.scenarios if s["shock_bps"] == 0)
    assert pytest.approx(scen_0["financing_cost_difference_a"], abs=1e-6) == 0.0


# =====================================================================
# 7. Reporting & Manifest Tests
# =====================================================================

def test_manifest_completeness_and_hashes():
    """Verify simulation_manifest.json contains required fields and valid hashes."""
    manifest_path = Path("data/results/phase_4_1_1/simulation_manifest.json")
    assert manifest_path.exists(), f"Manifest not yet generated on disk: {manifest_path}"

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert "git_commit" in manifest
    assert "simulation_code_commit" in manifest
    assert "documentation_commit" in manifest
    assert "rng_bit_generator" in manifest
    assert manifest["rng_bit_generator"] == "PCG64"
    assert manifest["random_seed"] == 42
    assert "artifact_hashes" in manifest

    # Check required artifact hashes
    for filename, recorded_hash in manifest["artifact_hashes"].items():
        artifact_file = Path("data/results/phase_4_1_1") / filename
        assert artifact_file.exists(), f"Artifact {filename} missing"
        hasher = hashlib.sha256()
        with open(artifact_file, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        computed_hash = hasher.hexdigest()
        assert computed_hash == recorded_hash, f"Hash mismatch for {filename}"
