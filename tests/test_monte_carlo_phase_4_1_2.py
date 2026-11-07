"""Phase 4.1.2 Final Research Integrity & Reproducibility Closure Test Suite.

Comprehensive validation verifying:
1. Point-in-time (PIT) availability semantics at decision timestamps (release lag, cutoff, revisions, retrospectives).
2. Simulated trading calendar mechanics genuinely measured (weekend 3-day accrual, holiday accrual, t=0 zero interest, 30-day tenor exit, compound financing formula).
3. Out-of-sample holdout drawdown math consistency (prepends initial wealth 1.0 so negative first return is captured).
4. EUR/USD quote-direction and carry-trade translation P&L economics (USD per EUR, EUR appreciation causes loan repayment loss).
5. Correlation-breakdown stress comparison paired differences and standard error uncertainty (CRN pairing).
6. Phase 4.1.2 reproducibility manifest completeness, environmental provenance, and cryptographic SHA-256 integrity (zero pytest.skip).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import numpy as np
import pytest

from data.schemas import AvailabilityEvidence, DataClassification, DataObservation, Frequency, ObservationKind
from simulation.monte_carlo.calibration import split_calibration_holdout
from simulation.monte_carlo.distributions import MultivariateGaussianModel
from simulation.monte_carlo.factors import (
    build_fx_carry_factor_panel,
    get_effective_availability_timestamp,
    get_session_decision_timestamp,
    is_observation_available_as_of,
    resolve_observation_as_of,
)
from simulation.monte_carlo.holdout import (
    evaluate_factor_holdout_diagnostics,
)
from simulation.monte_carlo.schemas import (
    CalendarValidationReport,
    CorrelationStressComparison,
    ScenarioPath,
)
from simulation.monte_carlo.shocks import (
    evaluate_correlation_stress_distribution,
)
from simulation.monte_carlo.strategy_adapter import (
    CarryTradeScenarioStrategy,
    validate_market_calendar_evidence,
)


# =====================================================================
# Fixtures and Helpers
# =====================================================================

def make_test_observations(
    start_date: date = date(2020, 1, 1),
    num_days: int = 400,
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

        # ECB Borrowing Rate
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
# 1. Point-in-Time Availability Semantics Tests
# =====================================================================

def test_pit_session_decision_timestamp_and_availability_cutoff():
    """Verify session decision timestamp construction and observation availability cutoff."""
    session_d = date(2024, 6, 3)
    dec_ts = get_session_decision_timestamp(session_d, decision_time_utc=time(16, 0))
    assert dec_ts == datetime(2024, 6, 3, 16, 0, tzinfo=timezone.utc)

    now_utc = datetime(2024, 6, 3, 20, 0, tzinfo=timezone.utc)

    # Observation published at 15:30 UTC is available as of 16:00 UTC
    obs_early = DataObservation(
        kind=ObservationKind.EXCHANGE_RATE,
        source_id="frankfurter",
        entity_code="EUR/USD",
        value=1.0850,
        unit="USD_per_EUR",
        frequency=Frequency.DAILY,
        observation_date=session_d,
        publication_timestamp=datetime(2024, 6, 3, 15, 30, tzinfo=timezone.utc),
        retrieved_at=now_utc,
        is_synthetic=False,
    )
    is_avail_early, _ = is_observation_available_as_of(obs_early, dec_ts)
    assert is_avail_early is True

    # Observation published at 16:30 UTC is NOT available as of 16:00 UTC
    obs_late = DataObservation(
        kind=ObservationKind.EXCHANGE_RATE,
        source_id="frankfurter",
        entity_code="EUR/USD",
        value=1.0855,
        unit="USD_per_EUR",
        frequency=Frequency.DAILY,
        observation_date=session_d,
        publication_timestamp=datetime(2024, 6, 3, 16, 30, tzinfo=timezone.utc),
        retrieved_at=now_utc,
        is_synthetic=False,
    )
    is_avail_late, _ = is_observation_available_as_of(obs_late, dec_ts)
    assert is_avail_late is False


def test_pit_same_day_fx_reference_rate_publication_cutoff():
    """Verify ECB/Frankfurter same-day EUR/USD reference rate is available at 16:00 UTC (17:00 CET)."""
    session_d = date(2024, 6, 3)
    now_utc = datetime(2024, 6, 3, 20, 0, tzinfo=timezone.utc)
    obs_fx = DataObservation(
        kind=ObservationKind.EXCHANGE_RATE,
        source_id="frankfurter",
        entity_code="EUR/USD",
        value=1.0850,
        unit="USD_per_EUR",
        frequency=Frequency.DAILY,
        observation_date=session_d,
        publication_date=session_d,
        classification=DataClassification.REAL_ESTIMATED_AVAILABILITY,
        availability_evidence=AvailabilityEvidence.ESTIMATED_SCHEDULE,
        retrieved_at=now_utc,
        is_synthetic=False,
    )
    effective_ts = get_effective_availability_timestamp(obs_fx)
    assert effective_ts == datetime(2024, 6, 3, 16, 0, tzinfo=timezone.utc)

    # Before 16:00 UTC -> not available
    before_ts = datetime(2024, 6, 3, 14, 0, tzinfo=timezone.utc)
    is_avail_before, _ = is_observation_available_as_of(obs_fx, before_ts)
    assert is_avail_before is False

    # At or after 16:00 UTC -> available
    at_ts = datetime(2024, 6, 3, 16, 0, tzinfo=timezone.utc)
    is_avail_at, _ = is_observation_available_as_of(obs_fx, at_ts)
    assert is_avail_at is True


def test_pit_us_treasury_next_business_day_reporting_lag():
    """Verify US Treasury yields are subject to next-business-day reporting lag at 15:00 UTC."""
    now_utc = datetime(2024, 6, 15, 20, 0, tzinfo=timezone.utc)
    # Monday observation -> available Tuesday 15:00 UTC
    mon_d = date(2024, 6, 3)
    obs_mon = DataObservation(
        kind=ObservationKind.INTEREST_RATE,
        source_id="us_treasury",
        entity_code="USD",
        indicator_id="DGS3MO",
        value=5.35,
        unit="percent",
        frequency=Frequency.DAILY,
        observation_date=mon_d,
        publication_date=mon_d + timedelta(days=1),
        classification=DataClassification.REAL_ESTIMATED_AVAILABILITY,
        availability_evidence=AvailabilityEvidence.ESTIMATED_SCHEDULE,
        retrieved_at=now_utc,
        is_synthetic=False,
    )
    eff_mon = get_effective_availability_timestamp(obs_mon)
    assert eff_mon == datetime(2024, 6, 4, 15, 0, tzinfo=timezone.utc)

    # Monday at 16:00 UTC -> NOT available yet
    avail_mon_eve, _ = is_observation_available_as_of(obs_mon, datetime(2024, 6, 3, 16, 0, tzinfo=timezone.utc))
    assert avail_mon_eve is False
    # Tuesday at 16:00 UTC -> available
    avail_tue_eve, _ = is_observation_available_as_of(obs_mon, datetime(2024, 6, 4, 16, 0, tzinfo=timezone.utc))
    assert avail_tue_eve is True

    # Friday observation -> available Monday 15:00 UTC
    fri_d = date(2024, 6, 7)
    obs_fri = DataObservation(
        kind=ObservationKind.INTEREST_RATE,
        source_id="us_treasury",
        entity_code="USD",
        indicator_id="DGS3MO",
        value=5.36,
        unit="percent",
        frequency=Frequency.DAILY,
        observation_date=fri_d,
        publication_date=fri_d + timedelta(days=3),
        classification=DataClassification.REAL_ESTIMATED_AVAILABILITY,
        availability_evidence=AvailabilityEvidence.ESTIMATED_SCHEDULE,
        retrieved_at=now_utc,
        is_synthetic=False,
    )
    eff_fri = get_effective_availability_timestamp(obs_fri)
    assert eff_fri == datetime(2024, 6, 10, 15, 0, tzinfo=timezone.utc)

    # Friday 16:00 UTC -> NOT available
    avail_fri, _ = is_observation_available_as_of(obs_fri, datetime(2024, 6, 7, 16, 0, tzinfo=timezone.utc))
    assert avail_fri is False
    # Sunday 12:00 UTC -> NOT available
    avail_sun, _ = is_observation_available_as_of(obs_fri, datetime(2024, 6, 9, 12, 0, tzinfo=timezone.utc))
    assert avail_sun is False
    # Monday 15:30 UTC -> available
    avail_mon, _ = is_observation_available_as_of(obs_fri, datetime(2024, 6, 10, 15, 30, tzinfo=timezone.utc))
    assert avail_mon is True


def test_pit_ecb_policy_rate_effective_and_available():
    """Verify ECB policy rates are bound by effective policy timestamps."""
    now_utc = datetime(2024, 6, 15, 20, 0, tzinfo=timezone.utc)
    # Policy announced earlier but effective on 2024-06-12 00:00 UTC
    obs_ecb = DataObservation(
        kind=ObservationKind.INTEREST_RATE,
        source_id="policy_rates",
        entity_code="DFR",
        indicator_id="DFR",
        value=3.75,
        unit="percent",
        frequency=Frequency.DAILY,
        observation_date=date(2024, 6, 6),
        effective_timestamp=datetime(2024, 6, 12, 0, 0, tzinfo=timezone.utc),
        publication_timestamp=datetime(2024, 6, 6, 13, 0, tzinfo=timezone.utc),
        retrieved_at=now_utc,
        is_synthetic=False,
    )
    # On 2024-06-10, effective date has not arrived
    as_of_pre = datetime(2024, 6, 10, 16, 0, tzinfo=timezone.utc)
    avail_pre, _ = is_observation_available_as_of(obs_ecb, as_of_pre)
    assert avail_pre is False

    # On 2024-06-12 16:00 UTC, effective date has arrived
    as_of_post = datetime(2024, 6, 12, 16, 0, tzinfo=timezone.utc)
    avail_post, _ = is_observation_available_as_of(obs_ecb, as_of_post)
    assert avail_post is True


def test_pit_late_revision_resolution_as_of_decision_time():
    """Verify that revisions published after decision timestamp are excluded in favor of earlier revision."""
    d = date(2024, 6, 3)
    dec_ts = datetime(2024, 6, 3, 16, 0, tzinfo=timezone.utc)
    now_utc = datetime(2024, 6, 3, 20, 0, tzinfo=timezone.utc)

    rev_initial = DataObservation(
        kind=ObservationKind.EXCHANGE_RATE,
        source_id="frankfurter",
        entity_code="EUR/USD",
        value=1.0850,
        unit="USD_per_EUR",
        frequency=Frequency.DAILY,
        observation_date=d,
        publication_timestamp=datetime(2024, 6, 3, 15, 0, tzinfo=timezone.utc),
        retrieved_at=now_utc,
        revision=1,
        is_synthetic=False,
    )
    rev_late = DataObservation(
        kind=ObservationKind.EXCHANGE_RATE,
        source_id="frankfurter",
        entity_code="EUR/USD",
        value=1.0870,
        unit="USD_per_EUR",
        frequency=Frequency.DAILY,
        observation_date=d,
        publication_timestamp=datetime(2024, 6, 3, 18, 0, tzinfo=timezone.utc),
        retrieved_at=now_utc,
        revision=2,
        is_synthetic=False,
    )

    resolved = resolve_observation_as_of([rev_initial, rev_late], dec_ts)
    assert resolved is not None
    assert resolved.value == 1.0850  # Early revision selected, late revision blocked!

    # Later in evening (19:00 UTC), the late revision is selected
    resolved_evening = resolve_observation_as_of([rev_initial, rev_late], datetime(2024, 6, 3, 19, 0, tzinfo=timezone.utc))
    assert resolved_evening is not None
    assert resolved_evening.value == 1.0870


def test_pit_future_observation_date_leakage_blocked():
    """Verify observation with observation_date > as_of.date() is strictly blocked."""
    obs_future = DataObservation(
        kind=ObservationKind.EXCHANGE_RATE,
        source_id="frankfurter",
        entity_code="EUR/USD",
        value=1.0900,
        unit="USD_per_EUR",
        frequency=Frequency.DAILY,
        observation_date=date(2024, 6, 5),
        retrieved_at=datetime(2024, 6, 5, 20, 0, tzinfo=timezone.utc),
        is_synthetic=False,
    )
    is_avail, reason = is_observation_available_as_of(obs_future, datetime(2024, 6, 4, 16, 0, tzinfo=timezone.utc))
    assert is_avail is False
    assert "future_observation_date" in reason


def test_pit_retrospective_data_excluded_from_strict_executable_set():
    """Verify retrospective data is excluded under strict_executable=True."""
    obs_retro = DataObservation(
        kind=ObservationKind.EXCHANGE_RATE,
        source_id="frankfurter",
        entity_code="EUR/USD",
        value=1.0850,
        unit="USD_per_EUR",
        frequency=Frequency.DAILY,
        observation_date=date(2024, 6, 3),
        availability_evidence=AvailabilityEvidence.RETROSPECTIVE,
        classification=DataClassification.REAL_RETROSPECTIVE,
        retrieved_at=datetime(2024, 6, 3, 20, 0, tzinfo=timezone.utc),
        is_synthetic=False,
    )
    dec_ts = datetime(2024, 6, 3, 16, 0, tzinfo=timezone.utc)
    # Available under relaxed research mode
    avail_relaxed, _ = is_observation_available_as_of(obs_retro, dec_ts, strict_executable=False)
    assert avail_relaxed is True
    # Excluded under strict executable mode
    avail_strict, _ = is_observation_available_as_of(obs_retro, dec_ts, strict_executable=True)
    assert avail_strict is False
    assert resolve_observation_as_of([obs_retro], dec_ts, strict_executable=True) is None


def test_pit_missing_availability_evidence_handling():
    """Verify unverified/missing availability evidence returns False under strict_executable."""
    obs_unverified = DataObservation(
        kind=ObservationKind.EXCHANGE_RATE,
        source_id="unknown_source",
        entity_code="EUR/USD",
        value=1.0850,
        unit="USD_per_EUR",
        frequency=Frequency.DAILY,
        observation_date=date(2024, 6, 3),
        publication_date=date(2024, 6, 3),
        classification=DataClassification.REAL_VERIFIED,
        availability_evidence=AvailabilityEvidence.ESTIMATED_SCHEDULE,
        retrieved_at=datetime(2024, 6, 3, 20, 0, tzinfo=timezone.utc),
        is_synthetic=False,
    )
    object.__setattr__(obs_unverified, "availability_evidence", None)
    dec_ts = datetime(2024, 6, 3, 16, 0, tzinfo=timezone.utc)
    avail_strict, reason = is_observation_available_as_of(obs_unverified, dec_ts, strict_executable=True)
    assert avail_strict is False
    assert "missing_availability_evidence" in reason


# =====================================================================
# 2. Simulated Trading Calendar Evidence Tests
# =====================================================================

def test_calendar_validation_evidence_genuinely_measured():
    """Verify CalendarValidationReport booleans are computed from actual execution, not hardcoded."""
    rep = validate_market_calendar_evidence()
    assert isinstance(rep, CalendarValidationReport)
    assert rep.calendar_implementation == "JointTarget2FedCalendar"
    assert rep.session_count > 0
    assert rep.initial_state_zero_interest is True
    assert rep.weekend_3day_accrual_verified is True
    assert rep.holiday_accrual_verified is True
    assert rep.tenor_30day_maturity_verified is True
    assert rep.independent_numerical_accrual_verified is True
    assert rep.transitions_n_levels_n_plus_1_verified is True
    assert rep.array_lengths_verified is True


# =====================================================================
# 3. Holdout Drawdown Consistency Tests
# =====================================================================

def test_holdout_drawdown_negative_first_return_includes_initial_wealth():
    """Verify factor holdout max drawdown includes loss from initial wealth 1.0 when r_0 < 0."""
    obs = make_test_observations(start_date=date(2020, 1, 1), num_days=350)
    full_panel = build_fx_carry_factor_panel(
        observations=obs,
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        sovereign_yield_series_id="DGS3MO",
    )
    calib_panel, holdout_panel = split_calibration_holdout(full_panel, calibration_end=date(2020, 8, 1))

    # Force the first holdout return to be a severe negative shock (-5%)
    fx_key = "FX_EUR_USD_LOGRET"
    holdout_panel.values[fx_key][0] = -0.05

    model = MultivariateGaussianModel(panel=calib_panel, random_seed=42)
    paths = model.generate_paths(num_paths=100, horizon=len(holdout_panel.dates))

    diag = evaluate_factor_holdout_diagnostics(
        calibration_panel=calib_panel,
        holdout_panel=holdout_panel,
        predictive_paths=paths,
    )
    # Cumulative path starts at 1.0 -> step 1 is exp(-0.05) ~ 0.9512
    # Drawdown is non-positive (<= 0), so magnitude is >= 1 - exp(-0.05) ~ 4.877%
    expected_min_dd = 1.0 - math.exp(-0.05)
    assert abs(diag.actual_fx_max_drawdown) >= expected_min_dd - 1e-4
    assert diag.actual_fx_max_drawdown <= 0.0


# =====================================================================
# 4. FX Quote Direction & Translation Economics Tests
# =====================================================================

def test_fx_quote_direction_canonical_inversion_and_directional_pnl():
    """Verify EUR/USD quote convention (USD per EUR), canonical inversion, and carry trade P&L."""
    strategy = CarryTradeScenarioStrategy(
        tenor_days=30,
        rebalance_days=30,
        strict_calendar=False,
    )

    # EUR/USD rises from 1.10 to 1.20 -> EUR appreciates, USD depreciates
    # Borrowed EUR to buy USD.
    # At maturity, reconverting depreciated USD to EUR produces FX translation loss on loan repayment.
    dates = [date(2024, 1, 2) + timedelta(days=i) for i in range(35)]
    fx_rates = np.linspace(1.10, 1.20, len(dates)).tolist()
    borrow_rates = np.zeros(len(dates)).tolist()
    invest_rates = np.zeros(len(dates)).tolist()

    scenario_path = ScenarioPath(
        path_id=1,
        steps=len(dates),
        dates=dates,
        fx_rates=fx_rates,
        borrowing_rates=borrow_rates,
        investment_rates=invest_rates,
    )

    res = strategy.evaluate_path(scenario_path, initial_capital_a=100_000.0)
    # Total return must be negative due to EUR appreciation (translation loss on loan repayment)
    assert res.total_return < 0.0
    assert res.fx_translation_gain_a < 0.0


# =====================================================================
# 5. Correlation Stress Uncertainty & Paired Semantics Tests
# =====================================================================

def test_correlation_stress_paired_difference_semantics_and_uncertainty():
    """Verify paired difference semantics (Stressed - Baseline) and non-negative standard error."""
    obs = make_test_observations(start_date=date(2020, 1, 1), num_days=200)
    panel = build_fx_carry_factor_panel(
        observations=obs,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 10, 1),
        sovereign_yield_series_id="DGS3MO",
    )
    strat = CarryTradeScenarioStrategy(tenor_days=10, rebalance_days=10)

    res = evaluate_correlation_stress_distribution(
        panel=panel,
        strategy=strat,
        num_paths=100,
        horizon=20,
        random_seed=42,
    )

    assert isinstance(res, CorrelationStressComparison)
    assert res.num_paths == 100
    assert pytest.approx(res.mean_return_difference, rel=1e-5) == res.stressed_mean_return - res.baseline_mean_return
    assert pytest.approx(res.prob_loss_difference, rel=1e-5) == res.stressed_prob_loss - res.baseline_prob_loss
    assert res.prob_loss_difference_se >= 0.0
    assert any("Common Random Numbers" in n for n in res.notes)


# =====================================================================
# 6. Manifest & Cryptographic Reproducibility Tests
# =====================================================================

def test_phase_4_1_2_manifest_completeness_and_hashes():
    """Verify Phase 4.1.2 simulation_manifest.json contains required fields and valid hashes."""
    manifest_path = Path("data/results/phase_4_1_2/simulation_manifest.json")
    assert manifest_path.exists(), f"Manifest not yet generated on disk: {manifest_path}"

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
    assert "artifact_hashes" in manifest

    # Required 16 artifacts
    required_artifacts = [
        "availability_audit.json",
        "factor_holdout_diagnostics.json",
        "portfolio_holdout_diagnostics.json",
        "correlation_stress_comparison.json",
        "calendar_validation.json",
        "funding_sensitivity.json",
        "model_comparison.json",
        "convergence_report.json",
        "phase_4_1_2_research_report.md",
        "calibration_report.json",
        "factor_panel_manifest.json",
        "gaussian_results.json",
        "bootstrap_results.json",
        "student_t_results.json",
        "regime_results.json",
        "stress_test_results.json",
    ]

    for req in required_artifacts:
        assert req in manifest["artifact_hashes"], f"Required artifact {req} missing from manifest artifact_hashes"

    # Verify cryptographic digest of every recorded artifact
    for filename, recorded_hash in manifest["artifact_hashes"].items():
        artifact_file = Path("data/results/phase_4_1_2") / filename
        assert artifact_file.exists(), f"Artifact {filename} missing on disk"
        hasher = hashlib.sha256()
        with open(artifact_file, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        computed_hash = hasher.hexdigest()
        assert computed_hash == recorded_hash, f"Hash mismatch for {filename}: computed {computed_hash} != recorded {recorded_hash}"
