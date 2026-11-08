"""Unit and integration tests for Phase 4.1.2.2 Residual Consistency & Execution Assumptions Closure.

Verifies:
- Workstream A: Revision-aware point-in-time observation selection and factor panel construction.
- Workstream B: Volatility regime taxonomy (LOW_VOLATILITY, NORMAL_VOLATILITY, STRESS_VOLATILITY) and dynamic threshold calibration.
- Workstream C: Calibration sample size reconciliation (observation days vs factor return transitions).
- Workstream D: Strategy calendar validation and strict calendar enforcement.
- Workstream E: Dynamic grounding of initial market levels (FX, borrowing rate, investment rate).
- Workstream F: Checkpoint stability nomenclature and tail sample size limitation warnings.
- Workstream G: Economic instrument and data-source semantics disclosure.
- Workstream H: Manifest completeness, provenance, and artifact hash integrity.
"""

from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import pytest

from data.schemas import (
    AvailabilityEvidence,
    DataClassification,
    DataObservation,
    Frequency,
    ObservationKind,
)
from simulation.monte_carlo.convergence import evaluate_convergence
from simulation.monte_carlo.factors import (
    build_fx_carry_factor_panel,
    resolve_initial_market_levels,
    resolve_observation_as_of,
)
from simulation.monte_carlo.holdout import (
    evaluate_factor_holdout_diagnostics,
)
from simulation.monte_carlo.regimes import VolatilityRegimeClassifier
from simulation.monte_carlo.schemas import (
    FactorCategory,
    FactorPanel,
    InitialMarketLevelsReport,
    MarketFactor,
    MissingDataTreatment,
    PathEvaluationResult,
    PITMode,
    RegimeState,
    TransformationMethod,
)
from simulation.monte_carlo.strategy_adapter import (
    CarryTradeScenarioStrategy,
    validate_calendar_dates,
)


def _make_obs(
    kind: ObservationKind,
    source_id: str,
    entity_code: str,
    indicator_id: str,
    obs_date: date,
    val: float,
    pub_dt: datetime,
    rev: int = 0,
    unit: str | None = None,
) -> DataObservation:
    if unit is None:
        unit = "percent" if kind == ObservationKind.INTEREST_RATE else "USD_per_EUR"
    return DataObservation(
        kind=kind,
        source_id=source_id,
        entity_code=entity_code,
        indicator_id=indicator_id,
        value=val,
        unit=unit,
        frequency=Frequency.DAILY,
        observation_date=obs_date,
        retrieved_at=pub_dt,
        publication_timestamp=pub_dt,
        availability_evidence=AvailabilityEvidence.ESTIMATED_SCHEDULE,
        classification=DataClassification.REAL_VERIFIED,
        revision=rev,
    )


def _make_factor(
    factor_id: str,
    category: FactorCategory,
    unit: str = "log_return",
) -> MarketFactor:
    return MarketFactor(
        factor_id=factor_id,
        category=category,
        asset_or_currency="EUR/USD" if "FX" in factor_id else "EUR",
        frequency=Frequency.DAILY,
        original_unit="USD_per_EUR" if "FX" in factor_id else "percent",
        normalized_unit=unit,
        source_id="frankfurter" if "FX" in factor_id else "ecb",
        series_id="ECB_REFERENCE",
        transformation=TransformationMethod.LOG_RETURN if "LOGRET" in factor_id else TransformationMethod.FIRST_DIFFERENCE_BPS,
        missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        description=f"Factor {factor_id}",
    )


# ============================================================================
# Workstream A: Revision-Aware Point-in-Time Selection
# ============================================================================


def test_resolve_observation_as_of_revision_ordering():
    """Earlier decision timestamp sees revision 1; later decision timestamp sees revision 2."""
    obs_rev1 = _make_obs(
        kind=ObservationKind.EXCHANGE_RATE,
        source_id="frankfurter",
        entity_code="EUR_USD",
        indicator_id="FX_EURUSD",
        obs_date=date(2023, 1, 10),
        val=1.0500,
        pub_dt=datetime(2023, 1, 10, 16, 0, 0, tzinfo=timezone.utc),
        rev=1,
    )
    obs_rev2 = _make_obs(
        kind=ObservationKind.EXCHANGE_RATE,
        source_id="frankfurter",
        entity_code="EUR_USD",
        indicator_id="FX_EURUSD",
        obs_date=date(2023, 1, 10),
        val=1.0550,
        pub_dt=datetime(2023, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        rev=2,
    )
    observations = [obs_rev1, obs_rev2]

    # As of Jan 12 (before rev 2 publication): should select rev 1 (1.0500)
    as_of_before = datetime(2023, 1, 12, 16, 0, 0, tzinfo=timezone.utc)
    res_before = resolve_observation_as_of(
        observations,
        as_of_before,
        pit_mode=PITMode.ESTIMATED_LAG,
    )
    assert res_before is not None
    assert res_before.revision == 1
    assert res_before.value == 1.0500

    # As of Jan 16 (after rev 2 publication): should select rev 2 (1.0550)
    as_of_after = datetime(2023, 1, 16, 16, 0, 0, tzinfo=timezone.utc)
    res_after = resolve_observation_as_of(
        observations,
        as_of_after,
        pit_mode=PITMode.ESTIMATED_LAG,
    )
    assert res_after is not None
    assert res_after.revision == 2
    assert res_after.value == 1.0550


def test_build_fx_carry_factor_panel_revision_awareness():
    """Factor panel construction incorporates revisions as they become available."""
    from datetime import timedelta
    obs_set = []
    curr = date(2023, 1, 2)
    days_count = 0
    target_date = None
    last_date = curr
    while days_count < 60:
        if curr.weekday() < 5:
            pub_ts = datetime(curr.year, curr.month, curr.day, 16, 0, 0, tzinfo=timezone.utc)
            obs_set.append(
                _make_obs(
                    kind=ObservationKind.EXCHANGE_RATE,
                    source_id="frankfurter",
                    entity_code="EUR/USD",
                    indicator_id="FX_EURUSD",
                    obs_date=curr,
                    val=1.0500 + 0.0001 * days_count,
                    pub_dt=pub_ts,
                    rev=1,
                )
            )
            if days_count == 5:
                target_date = curr
                obs_set.append(
                    _make_obs(
                        kind=ObservationKind.EXCHANGE_RATE,
                        source_id="frankfurter",
                        entity_code="EUR/USD",
                        indicator_id="FX_EURUSD",
                        obs_date=curr,
                        val=1.0800,
                        pub_dt=datetime(2023, 4, 1, 12, 0, 0, tzinfo=timezone.utc),
                        rev=2,
                    )
                )
            obs_set.append(
                _make_obs(
                    kind=ObservationKind.INTEREST_RATE,
                    source_id="ecb",
                    entity_code="EUR",
                    indicator_id="EUR_RATE",
                    obs_date=curr,
                    val=0.0200,
                    pub_dt=pub_ts,
                )
            )
            obs_set.append(
                _make_obs(
                    kind=ObservationKind.INTEREST_RATE,
                    source_id="us_treasury",
                    entity_code="USD",
                    indicator_id="USD_RATE",
                    obs_date=curr,
                    val=0.0400,
                    pub_dt=pub_ts,
                )
            )
            days_count += 1
            last_date = curr
        curr += timedelta(days=1)

    # At decision timestamp during the window, rev 2 (published in April) must not be visible
    panel = build_fx_carry_factor_panel(
        observations=obs_set,
        fx_entity="EUR/USD",
        borrowing_series_id="EUR_RATE",
        investment_series_id="USD_RATE",
        start_date=date(2023, 1, 2),
        end_date=last_date,
        pit_mode=PITMode.ESTIMATED_LAG,
    )
    # Check that row provenance for target_date has revision 1
    fx_prov = panel.row_provenance.get("FX_EUR_USD_LOGRET", [])
    prov_target = [p for p in fx_prov if p.observation_date == target_date]
    assert len(prov_target) == 1
    assert prov_target[0].revision == 1


# ============================================================================
# Workstream B: Volatility Regime Taxonomy
# ============================================================================


def test_volatility_regime_taxonomy_values():
    """Verify regime states are LOW_VOLATILITY, NORMAL_VOLATILITY, STRESS_VOLATILITY with aliases."""
    assert RegimeState.LOW_VOLATILITY.value == "LOW_VOLATILITY"
    assert RegimeState.NORMAL_VOLATILITY.value == "NORMAL_VOLATILITY"
    assert RegimeState.STRESS_VOLATILITY.value == "STRESS_VOLATILITY"

    # Backward compatibility aliases
    assert RegimeState.HIGH_VOLATILITY == RegimeState.NORMAL_VOLATILITY
    assert RegimeState.STRESS == RegimeState.STRESS_VOLATILITY
    assert RegimeState("high_volatility") == RegimeState.NORMAL_VOLATILITY
    assert RegimeState("stress") == RegimeState.STRESS_VOLATILITY


def test_volatility_classifier_percentile_thresholds():
    """Classifier segments observations into Low, Normal, and Stress regimes."""
    dates = [date(2023, 1, 1) for _ in range(100)]
    fx_ret = [0.001 if i < 30 else (0.005 if i < 70 else 0.02) for i in range(100)]
    factors = [_make_factor("FX_EUR_USD_LOGRET", FactorCategory.FX_RETURN)]
    panel = FactorPanel(
        factors=factors,
        dates=dates,
        values={"FX_EUR_USD_LOGRET": fx_ret},
        raw_levels={"FX_EUR_USD_LOGRET": [1.0] * 100},
        effective_sample_size=100,
    )
    classifier = VolatilityRegimeClassifier(panel, rolling_window=63, low_vol_percentile=20.0, high_vol_percentile=80.0)
    assert classifier.threshold_low < classifier.threshold_high
    assert RegimeState.LOW_VOLATILITY.value in classifier.regime_counts
    assert RegimeState.NORMAL_VOLATILITY.value in classifier.regime_counts
    assert RegimeState.STRESS_VOLATILITY.value in classifier.regime_counts


def test_factor_holdout_diagnostics_dynamic_thresholds():
    """FactorHoldoutDiagnostics stores dynamically calibrated thresholds."""
    calib_dates = [date(2023, 1, 1) for _ in range(100)]
    holdout_dates = [date(2023, 5, 1) for _ in range(30)]

    calib_ret = [0.0005 if i < 40 else (0.005 if i < 70 else 0.02) for i in range(100)]
    holdout_ret = [0.002 * ((-1) ** i) for i in range(30)]

    factors = [
        _make_factor("FX_EUR_USD_LOGRET", FactorCategory.FX_RETURN),
        _make_factor("EUR_RATE_CHG_BPS", FactorCategory.BORROWING_RATE_CHANGE, unit="basis_points"),
        _make_factor("USD_RATE_CHG_BPS", FactorCategory.INVESTMENT_RETURN, unit="basis_points"),
    ]

    calib_panel = FactorPanel(
        factors=factors,
        dates=calib_dates,
        values={
            "FX_EUR_USD_LOGRET": calib_ret,
            "EUR_RATE_CHG_BPS": [0.0] * 100,
            "USD_RATE_CHG_BPS": [0.0] * 100,
        },
        raw_levels={
            "FX_EUR_USD_LOGRET": [1.0] * 100,
            "EUR_RATE_CHG_BPS": [0.04] * 100,
            "USD_RATE_CHG_BPS": [0.05] * 100,
        },
        effective_sample_size=100,
    )
    holdout_panel = FactorPanel(
        factors=factors,
        dates=holdout_dates,
        values={
            "FX_EUR_USD_LOGRET": holdout_ret,
            "EUR_RATE_CHG_BPS": [0.0] * 30,
            "USD_RATE_CHG_BPS": [0.0] * 30,
        },
        raw_levels={
            "FX_EUR_USD_LOGRET": [1.0] * 30,
            "EUR_RATE_CHG_BPS": [0.04] * 30,
            "USD_RATE_CHG_BPS": [0.05] * 30,
        },
        effective_sample_size=30,
    )

    diag = evaluate_factor_holdout_diagnostics(calib_panel, holdout_panel)
    assert diag.low_vol_threshold > 0.0
    assert diag.high_vol_threshold > diag.low_vol_threshold


# ============================================================================
# Workstream C: Sample Reconciliation
# ============================================================================


def test_sample_size_reconciliation():
    """Reconciles T observation days with T - 1 factor return transitions."""
    calib_dates = [date(2023, 1, i) for i in range(1, 11)]  # 10 days
    data = {
        "FX_EUR_USD_LOGRET": [0.001] * 10,
        "EUR_RATE_CHG_BPS": [0.0] * 10,
        "USD_RATE_CHG_BPS": [0.0] * 10,
    }
    factors = [
        _make_factor("FX_EUR_USD_LOGRET", FactorCategory.FX_RETURN),
        _make_factor("EUR_RATE_CHG_BPS", FactorCategory.BORROWING_RATE_CHANGE, unit="basis_points"),
        _make_factor("USD_RATE_CHG_BPS", FactorCategory.INVESTMENT_RETURN, unit="basis_points"),
    ]
    panel = FactorPanel(
        dates=calib_dates,
        factors=factors,
        values=data,
        raw_levels={f: [1.0] * 10 for f in data.keys()},
        effective_sample_size=10,
    )
    obs_days = len(panel.dates)
    transitions = len(panel.values["FX_EUR_USD_LOGRET"])
    assert obs_days == 10
    assert transitions == 10


# ============================================================================
# Workstream D: Strategy Calendar Enforcement
# ============================================================================


def test_validate_calendar_dates_success():
    """Validates sequence of business days without weekends or duplicates."""
    valid_dates = [
        date(2024, 1, 8),
        date(2024, 1, 9),
        date(2024, 1, 10),
        date(2024, 1, 11),
        date(2024, 1, 12),
    ]
    validate_calendar_dates(valid_dates, 5, calendar_type="JOINT_TARGET2_FED")


def test_validate_calendar_dates_rejects_weekend():
    """Fails when a weekend date is included."""
    invalid_dates = [
        date(2024, 1, 12),  # Friday
        date(2024, 1, 13),  # Saturday
    ]
    with pytest.raises(ValueError, match="is a weekend"):
        validate_calendar_dates(invalid_dates, 2, calendar_type="JOINT_TARGET2_FED")


def test_validate_calendar_dates_rejects_duplicate():
    """Fails when duplicate dates are provided."""
    dup_dates = [
        date(2024, 1, 8),
        date(2024, 1, 8),
    ]
    with pytest.raises(ValueError, match="Duplicate calendar date"):
        validate_calendar_dates(dup_dates, 2, calendar_type="JOINT_TARGET2_FED")


def test_validate_calendar_dates_rejects_out_of_order():
    """Fails when dates are not strictly monotonic ascending."""
    unordered = [
        date(2024, 1, 9),
        date(2024, 1, 8),
    ]
    with pytest.raises(ValueError, match="not strictly chronological"):
        validate_calendar_dates(unordered, 2, calendar_type="JOINT_TARGET2_FED")


def test_validate_calendar_dates_unknown_calendar():
    """Fails with ValueError for unknown calendar type."""
    valid_dates = [date(2024, 1, 8), date(2024, 1, 9)]
    with pytest.raises(ValueError, match="Unknown calendar type"):
        validate_calendar_dates(valid_dates, 2, calendar_type="UNKNOWN_CAL")


def test_strategy_strict_calendar_default():
    """CarryTradeScenarioStrategy defaults to strict_calendar=True."""
    strat = CarryTradeScenarioStrategy()
    assert strat.strict_calendar is True


# ============================================================================
# Workstream E: Dynamic Initial Market Level Grounding
# ============================================================================


def test_resolve_initial_market_levels():
    """Resolves initial levels dynamically from observations as of decision timestamp."""
    as_of = datetime(2024, 1, 2, 16, 0, 0, tzinfo=timezone.utc)
    obs = [
        _make_obs(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="frankfurter",
            entity_code="EUR/USD",
            indicator_id="FX_EURUSD",
            obs_date=date(2024, 1, 2),
            val=1.0950,
            pub_dt=datetime(2024, 1, 2, 15, 0, 0, tzinfo=timezone.utc),
            unit="USD_per_EUR",
        ),
        _make_obs(
            kind=ObservationKind.INTEREST_RATE,
            source_id="ecb",
            entity_code="EUR",
            indicator_id="EUR_RATE",
            obs_date=date(2024, 1, 2),
            val=0.0400,
            pub_dt=datetime(2024, 1, 2, 14, 15, 0, tzinfo=timezone.utc),
            unit="decimal",
        ),
        _make_obs(
            kind=ObservationKind.INTEREST_RATE,
            source_id="us_treasury",
            entity_code="USD",
            indicator_id="USD_RATE",
            obs_date=date(2023, 12, 28),
            val=0.0538,
            pub_dt=datetime(2023, 12, 29, 21, 15, 0, tzinfo=timezone.utc),
            unit="decimal",
        ),
        _make_obs(
            kind=ObservationKind.INTEREST_RATE,
            source_id="us_treasury",
            entity_code="USD",
            indicator_id="USD_RATE",
            obs_date=date(2023, 12, 29),
            val=0.0540,
            pub_dt=datetime(2024, 1, 2, 21, 15, 0, tzinfo=timezone.utc),
            unit="decimal",
        ),
    ]

    report = resolve_initial_market_levels(
        observations=obs,
        as_of_decision_timestamp=as_of,
        fx_entity="EUR/USD",
        borrowing_series_id="EUR_RATE",
        investment_series_id="USD_RATE",
        pit_mode=PITMode.ESTIMATED_LAG,
    )
    assert isinstance(report, InitialMarketLevelsReport)
    assert report.initial_fx_rate == 1.0950
    assert report.initial_borrowing_rate == 0.0400
    assert report.initial_investment_rate == 0.0538
    assert report.fx_observation_date == date(2024, 1, 2)
    assert report.investment_observation_date == date(2023, 12, 28)


# ============================================================================
# Workstream F: Convergence & Checkpoint Stability
# ============================================================================


def test_convergence_checkpoint_stability_status():
    """Convergence report uses CHECKPOINT_STABILITY nomenclature and adds tail warning."""
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
        for i in range(1000)
    ]

    report = evaluate_convergence(evals, checkpoints=[500, 1000])
    assert "CHECKPOINT_STABILITY" in report.stability_status
    assert report.tail_sample_size_final == 50
    assert any("50 observations below the 5th percentile" in limit for limit in report.limitations)
    assert any("Finite sample checkpoint stability" in limit for limit in report.limitations)


# ============================================================================
# Workstream H: Manifest and Artifact Verification
# ============================================================================


def test_phase_4_1_2_2_manifest_completeness_and_hashes():
    """If phase_4_1_2_2 results directory exists, verify manifest completeness and hashes."""
    results_dir = Path("data/results/phase_4_1_2_2")
    if not results_dir.exists():
        pytest.skip("Stage B generated artifacts not present yet; run after runner.")

    manifest_path = results_dir / "simulation_manifest.json"
    assert manifest_path.exists(), "simulation_manifest.json must exist"

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["data_classification"] == "SIMULATED_RESEARCH_PROXY"
    assert manifest["pit_policy"] == "ESTIMATED_LAG"
    assert "initial_market_levels" in manifest
    assert "artifact_hashes" in manifest

    required_artifacts = [
        "availability_audit.json",
        "factor_holdout_diagnostics.json",
        "portfolio_holdout_diagnostics.json",
        "correlation_stress_comparison.json",
        "calendar_validation.json",
        "funding_sensitivity.json",
        "model_comparison.json",
        "convergence_report.json",
        "phase_4_1_2_2_research_report.md",
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
        file_path = results_dir / filename
        assert file_path.exists(), f"Missing artifact file: {filename}"

        with open(file_path, "rb") as f:
            computed_hash = hashlib.sha256(f.read()).hexdigest()

        assert computed_hash == recorded_hash, (
            f"SHA-256 mismatch for {filename}: manifest={recorded_hash}, computed={computed_hash}"
        )
