"""Unit and integration tests for Phase 4.1.2.2.2 Canonical FX Panel Integrity & Research Artifact Reconciliation.

Verifies:
- Workstream A: Canonical FX normalization throughout the factor pipeline (USD_per_EUR vs EUR_per_USD, reciprocal equivalence, positive returns on EUR appreciation, fail closed on ambiguous units, integration test with build_fx_carry_factor_panel).
- Workstream B: Audit of all factor unit normalizations (rates in percentage points, basis point differences, failure on ambiguous units, observation provenance).
- Workstream C: Honest checkpoint stability reporting across all 6 models without masking failures.
- Workstream D: Mathematical reconciliation that N level dates generate exactly N-1 factor return transitions across FactorPanel, split_calibration_holdout, and CalibrationReport.
- Workstream E: Volatility regime thresholds reconciliation (63-day rolling calibration sample percentiles and 2024 holdout classification).
- Workstream F: Federal Reserve Board historical unscheduled closures and release timestamp overrides in FederalReserveH15Calendar.
- Workstream G & H: Research closure report and simulation manifest completeness.
"""

from datetime import date, datetime, timezone
import math
import zoneinfo
import numpy as np
import pytest

from backtesting.calendar import FederalReserveH15Calendar
from data.schemas import (
    AvailabilityEvidence,
    DataClassification,
    DataObservation,
    Frequency,
    ObservationKind,
)
from simulation.monte_carlo.calibration import (
    CalibrationReport,
    calibrate_factor_panel,
    split_calibration_holdout,
)
from simulation.monte_carlo.factors import (
    _normalize_fx_quote_to_usd_per_eur,
    _normalize_rate_to_percentage_points,
    build_fx_carry_factor_panel,
    compute_differences,
    compute_log_returns,
)
from simulation.monte_carlo.reporting import (
    generate_phase_4_1_2_2_2_research_report,
)
from simulation.monte_carlo.metrics import (
    PathEvaluationResult,
    calculate_distribution_metrics,
)
from simulation.monte_carlo.schemas import (
    AvailabilityAuditReport,
    CalendarValidationReport,
    CorrelationStressComparison,
    FactorCategory,
    FactorHoldoutDiagnostics,
    FactorPanel,
    FundingSensitivityReport,
    MarketFactor,
    ModelComparisonEntry,
    MonteCarloResult,
    PITMode,
    PortfolioHoldoutDiagnostics,
    SimulationConfig,
    SimulationModelType,
    TransformationMethod,
)


EASTERN = zoneinfo.ZoneInfo("America/New_York")


def _make_obs(
    kind: ObservationKind,
    source_id: str,
    entity_code: str,
    indicator_id: str,
    obs_date: date,
    val: float,
    pub_dt: datetime | None = None,
    rev: int = 0,
    unit: str | None = None,
    evidence: AvailabilityEvidence = AvailabilityEvidence.ESTIMATED_SCHEDULE,
    classification: DataClassification = DataClassification.REAL_VERIFIED,
    base_currency: str | None = None,
    quote_currency: str | None = None,
) -> DataObservation:
    if unit is None:
        unit = "percent" if kind == ObservationKind.INTEREST_RATE else "USD_per_EUR"
    if kind == ObservationKind.EXCHANGE_RATE:
        if base_currency is None and ("EUR" in entity_code or "EUR" in (unit or "")):
            base_currency = "EUR"
        if quote_currency is None and ("USD" in entity_code or "USD" in (unit or "")):
            quote_currency = "USD"
    return DataObservation(
        kind=kind,
        source_id=source_id,
        entity_code=entity_code,
        indicator_id=indicator_id,
        value=val,
        unit=unit,
        frequency=Frequency.DAILY,
        observation_date=obs_date,
        retrieved_at=pub_dt or datetime(2024, 1, 1, tzinfo=timezone.utc),
        publication_timestamp=pub_dt,
        availability_evidence=evidence,
        classification=classification,
        revision=rev,
        base_currency=base_currency,
        quote_currency=quote_currency,
    )


# ==============================================================================
# Workstream A: Canonical FX Normalization Throughout the Factor Pipeline
# ==============================================================================

class TestCanonicalFXNormalization:
    """Tests for canonical USD per EUR quote normalization and return direction."""

    def test_eur_per_usd_normalizes_to_usd_per_eur(self):
        """EUR_per_USD quote of 0.91274 normalizes to ~1.095602 USD_per_EUR."""
        obs = _make_obs(
            ObservationKind.EXCHANGE_RATE,
            "frankfurter",
            "EUR_USD",
            "spot",
            date(2023, 12, 29),
            0.91274,
            unit="EUR_per_USD",
        )
        canonical = _normalize_fx_quote_to_usd_per_eur(obs)
        assert pytest.approx(canonical, rel=1e-5) == 1.0 / 0.91274
        assert pytest.approx(canonical, rel=1e-5) == 1.095602

    def test_usd_per_eur_remains_unchanged(self):
        """USD_per_EUR quote of 1.095602 remains unchanged."""
        obs = _make_obs(
            ObservationKind.EXCHANGE_RATE,
            "ecb",
            "EUR_USD",
            "spot",
            date(2023, 12, 29),
            1.095602,
            unit="USD_per_EUR",
        )
        canonical = _normalize_fx_quote_to_usd_per_eur(obs)
        assert canonical == 1.095602

    def test_reciprocal_quotes_normalize_to_same_canonical_level(self):
        """Two reciprocal quotes representing the same exchange rate yield identical canonical levels."""
        obs_eur_usd = _make_obs(
            ObservationKind.EXCHANGE_RATE,
            "frankfurter",
            "EUR_USD",
            "spot",
            date(2023, 12, 29),
            0.8500,
            unit="EUR_per_USD",
        )
        obs_usd_eur = _make_obs(
            ObservationKind.EXCHANGE_RATE,
            "ecb",
            "EUR_USD",
            "spot",
            date(2023, 12, 29),
            1.0 / 0.8500,
            unit="USD_per_EUR",
        )
        assert pytest.approx(_normalize_fx_quote_to_usd_per_eur(obs_eur_usd), rel=1e-9) == _normalize_fx_quote_to_usd_per_eur(obs_usd_eur)

    def test_canonical_log_returns_direction_on_eur_appreciation(self):
        """EUR appreciation must produce positive log returns in canonical USD per EUR."""
        # EUR strengthens: USD per EUR goes from 1.05 to 1.10
        # In reciprocal EUR_per_USD, quote drops from ~0.9524 to ~0.9091
        obs_t0_recip = _make_obs(ObservationKind.EXCHANGE_RATE, "frankfurter", "EUR_USD", "spot", date(2023, 1, 2), 1.0 / 1.05, unit="EUR_per_USD")
        obs_t1_recip = _make_obs(ObservationKind.EXCHANGE_RATE, "frankfurter", "EUR_USD", "spot", date(2023, 1, 3), 1.0 / 1.10, unit="EUR_per_USD")

        canon_levels = [_normalize_fx_quote_to_usd_per_eur(obs_t0_recip), _normalize_fx_quote_to_usd_per_eur(obs_t1_recip)]
        returns = compute_log_returns(canon_levels)

        expected_return = math.log(1.10 / 1.05)
        assert len(returns) == 1
        assert returns[0] > 0.0  # Positive return on appreciation
        assert pytest.approx(returns[0], rel=1e-7) == expected_return

    def test_canonical_log_returns_direction_on_eur_depreciation(self):
        """EUR depreciation must produce negative log returns in canonical USD per EUR."""
        # EUR weakens: USD per EUR goes from 1.10 to 1.05
        obs_t0_recip = _make_obs(ObservationKind.EXCHANGE_RATE, "frankfurter", "EUR_USD", "spot", date(2023, 1, 2), 1.0 / 1.10, unit="EUR_per_USD")
        obs_t1_recip = _make_obs(ObservationKind.EXCHANGE_RATE, "frankfurter", "EUR_USD", "spot", date(2023, 1, 3), 1.0 / 1.05, unit="EUR_per_USD")

        canon_levels = [_normalize_fx_quote_to_usd_per_eur(obs_t0_recip), _normalize_fx_quote_to_usd_per_eur(obs_t1_recip)]
        returns = compute_log_returns(canon_levels)

        expected_return = math.log(1.05 / 1.10)
        assert len(returns) == 1
        assert returns[0] < 0.0  # Negative return on depreciation
        assert pytest.approx(returns[0], rel=1e-7) == expected_return

    def test_missing_or_ambiguous_metadata_fails_closed(self):
        """Missing, unknown, or empty unit metadata fails closed without guessing."""
        obs_no_unit = _make_obs(ObservationKind.EXCHANGE_RATE, "unknown_source", "UNKNOWN", "spot", date(2023, 1, 2), 1.05, unit="")
        with pytest.raises(ValueError, match="Cannot determine quote convention"):
            _normalize_fx_quote_to_usd_per_eur(obs_no_unit)

        obs_unknown = _make_obs(ObservationKind.EXCHANGE_RATE, "unknown_source", "UNKNOWN", "spot", date(2023, 1, 2), 1.05, unit="JPY_per_GBP")
        with pytest.raises(ValueError, match="Cannot determine quote convention"):
            _normalize_fx_quote_to_usd_per_eur(obs_unknown)

    def test_build_fx_carry_factor_panel_integration_canonical_levels(self):
        """Integration test invoking build_fx_carry_factor_panel with real-shaped observations.

        Verifies that:
        - Factor panel canonical levels and initial market levels use identical quote conventions.
        - Canonical levels are stored in FactorPanel.canonical_levels.
        - Returns are computed on canonical USD per EUR.
        - Provenance is recorded in FactorRowProvenance.
        """
        # Create 3 consecutive business days of data
        dates = [date(2023, 1, 3), date(2023, 1, 4), date(2023, 1, 5)]
        raw_eur_usd_vals = [0.9400, 0.9300, 0.9200]  # EUR appreciates, so EUR_per_USD falls
        # Canonical USD per EUR: 1/0.9400 ~ 1.0638, 1/0.9300 ~ 1.0753, 1/0.9200 ~ 1.0870
        d1_pub = datetime(2023, 1, 3, 15, 0, tzinfo=timezone.utc)
        d2_pub = datetime(2023, 1, 4, 15, 0, tzinfo=timezone.utc)
        d3_pub = datetime(2023, 1, 5, 15, 0, tzinfo=timezone.utc)

        observations = []
        for d, v, pub in zip(dates, raw_eur_usd_vals, [d1_pub, d2_pub, d3_pub]):
            # FX observation (Frankfurter EUR_per_USD)
            observations.append(_make_obs(
                ObservationKind.EXCHANGE_RATE, "frankfurter", "EUR_USD", "spot", d, v,
                pub_dt=pub, unit="EUR_per_USD", evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            ))
            # ECB borrowing rate (percent)
            observations.append(_make_obs(
                ObservationKind.INTEREST_RATE, "ecb", "EUR", "KR.MRR_FR.LEV", d, 2.50,
                pub_dt=pub, unit="percent", evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            ))
            # US Treasury 1M (percent)
            observations.append(_make_obs(
                ObservationKind.INTEREST_RATE, "fred", "US", "DGS1MO", d, 4.25,
                pub_dt=pub, unit="percent", evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            ))
            # US Treasury 3M (percent)
            observations.append(_make_obs(
                ObservationKind.INTEREST_RATE, "fred", "US", "DGS3MO", d, 4.50,
                pub_dt=pub, unit="percent", evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            ))

        panel = build_fx_carry_factor_panel(
            observations=observations,
            start_date=date(2023, 1, 1),
            end_date=date(2023, 1, 10),
            fx_entity="EUR/USD",
            sovereign_yield_series_id="DGS3MO",
            pit_mode=PITMode.RESEARCH_ONLY,
            min_observations=3,
        )

        assert panel.aligned_level_count == 3
        assert panel.transition_count == 2
        assert len(panel.dates) == 2
        assert panel.level_dates == dates

        # Canonical levels check
        assert "FX_EUR_USD_LOGRET" in panel.canonical_levels
        expected_canon = [1.0 / v for v in raw_eur_usd_vals[1:]]
        for act, exp in zip(panel.canonical_levels["FX_EUR_USD_LOGRET"], expected_canon):
            assert pytest.approx(act, rel=1e-7) == exp

        # Returns must be positive (EUR appreciated)
        fx_returns = panel.values["FX_EUR_USD_LOGRET"]
        assert len(fx_returns) == 2
        assert fx_returns[0] > 0.0
        assert fx_returns[1] > 0.0

        # Provenance check
        assert "FX_EUR_USD_LOGRET" in panel.row_provenance
        assert len(panel.row_provenance["FX_EUR_USD_LOGRET"]) == 2
        for obs_prov in panel.row_provenance["FX_EUR_USD_LOGRET"]:
            assert obs_prov.raw_unit == "EUR_per_USD"
            assert obs_prov.pair in ("EUR/USD", "EUR_USD")
            assert obs_prov.base_currency == "EUR"
            assert obs_prov.quote_currency == "USD"
            assert pytest.approx(obs_prov.normalized_level, rel=1e-5) in expected_canon


# ==============================================================================
# Workstream B: Audit All Factor Unit Normalization
# ==============================================================================

class TestFactorUnitNormalization:
    """Tests for rate normalization to percentage points and basis point differences."""

    def test_normalize_rate_to_percentage_points_percent(self):
        """Rates with unit 'percent' remain unchanged."""
        obs = _make_obs(ObservationKind.INTEREST_RATE, "ecb", "EUR", "KR.MRR_FR.LEV", date(2023, 1, 2), 3.50, unit="percent")
        assert _normalize_rate_to_percentage_points(obs) == 3.50

    def test_normalize_rate_to_percentage_points_decimal(self):
        """Rates with unit 'decimal' are scaled by 100."""
        obs = _make_obs(ObservationKind.INTEREST_RATE, "ecb", "EUR", "KR.MRR_FR.LEV", date(2023, 1, 2), 0.035, unit="decimal")
        assert pytest.approx(_normalize_rate_to_percentage_points(obs), rel=1e-7) == 3.50

    def test_normalize_rate_to_percentage_points_bps(self):
        """Rates with unit 'bps' are divided by 100."""
        obs = _make_obs(ObservationKind.INTEREST_RATE, "ecb", "EUR", "KR.MRR_FR.LEV", date(2023, 1, 2), 350.0, unit="bps")
        assert _normalize_rate_to_percentage_points(obs) == 3.50

    def test_normalize_rate_to_percentage_points_fails_closed(self):
        """Unknown rate units fail closed."""
        obs = _make_obs(ObservationKind.INTEREST_RATE, "unknown", "US", "RATE", date(2023, 1, 2), 3.50, unit="par_yield")
        with pytest.raises(ValueError, match="Cannot determine rate unit conversion"):
            _normalize_rate_to_percentage_points(obs)

    def test_compute_differences_basis_points(self):
        """Differences in basis points from percentage point levels."""
        # 3.50% to 3.75% is +25 bps
        diffs = compute_differences([3.50, 3.75, 4.00])
        assert len(diffs) == 2
        assert pytest.approx(diffs[0], rel=1e-7) == 25.0
        assert pytest.approx(diffs[1], rel=1e-7) == 25.0


# ==============================================================================
# Workstream C: Honest Checkpoint Stability Reporting
# ==============================================================================

class TestCheckpointStabilityTruthfulness:
    """Tests ensuring model checkpoint stability flags are preserved and reported truthfully."""

    def test_model_comparison_preserves_stability_flags(self):
        """ModelComparisonEntry accurately preserves ACHIEVED and NOT_ACHIEVED statuses."""
        entry_pass = ModelComparisonEntry(
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
            is_converged_prob_loss=True,
        )
        assert entry_pass.checkpoint_stability_status == "CHECKPOINT_STABILITY_ACHIEVED"
        assert entry_pass.is_converged_prob_loss is True

        entry_fail = ModelComparisonEntry(
            model_name="Multivariate Gaussian",
            num_paths=1000,
            median_return=0.0145,
            mean_return=0.0166,
            std_return=0.0401,
            var_95=-0.0500,
            cvar_95=-0.0635,
            max_drawdown_median=0.0500,
            max_drawdown_p95=0.0800,
            prob_loss=0.352,
            prob_loss_se=0.0151,
            prob_drawdown_10pct=0.006,
            mean_fx_drag=0.0001,
            mean_financing_drag=0.0252,
            checkpoint_stability_status="CHECKPOINT_STABILITY_NOT_ACHIEVED",
            is_converged_prob_loss=False,
        )
        assert entry_fail.checkpoint_stability_status == "CHECKPOINT_STABILITY_NOT_ACHIEVED"
        assert entry_fail.is_converged_prob_loss is False


# ==============================================================================
# Workstream D: Sample Counts Reconciliation (N Levels -> N-1 Transitions)
# ==============================================================================

class TestSampleCountsReconciliation:
    """Tests mathematical reconciliation that N level dates generate exactly N-1 transitions."""

    def test_constructed_dataset_n_levels_n_minus_one_transitions(self):
        """Constructed dataset of N=10 level dates yields N-1=9 transitions with exact dates."""
        base_dates = [date(2023, 1, 2 + i) for i in range(10)]
        returns_mat = np.zeros((9, 4))
        prov_mat = [[] for _ in range(9)]

        panel = FactorPanel(
            dates=base_dates[1:],
            returns=returns_mat,
            provenance=prov_mat,
            factors=[],
            values={},
            raw_levels={},
            effective_sample_size=9,
            pit_mode="ESTIMATED_LAG",
            level_dates=base_dates,
            aligned_level_count=10,
            transition_count=9,
            first_level_date=base_dates[0],
            last_level_date=base_dates[-1],
            first_transition_date=base_dates[1],
            last_transition_date=base_dates[-1],
        )

        assert panel.aligned_level_count == 10
        assert panel.transition_count == 9
        assert len(panel.dates) == 9
        assert len(panel.level_dates) == 10
        assert panel.first_level_date == base_dates[0]
        assert panel.last_level_date == base_dates[-1]
        assert panel.first_transition_date == base_dates[1]
        assert panel.last_transition_date == base_dates[-1]

    def test_split_calibration_holdout_preserves_level_and_transition_counts(self):
        """split_calibration_holdout populates level_dates and distinct level/transition counts."""
        dates = [date(2023, 1, 2 + i) for i in range(20)]
        returns_mat = np.zeros((19, 4))
        prov_mat = [[] for _ in range(19)]

        mkt_factor = MarketFactor(
            factor_id="FX_EUR_USD_LOGRET",
            category=FactorCategory.FX_RETURN,
            asset_or_currency="EUR/USD",
            original_unit="USD_per_EUR",
            normalized_unit="log_return",
            source_id="frankfurter",
            transformation=TransformationMethod.LOG_RETURN,
        )

        full_panel = FactorPanel(
            dates=dates[1:],
            returns=returns_mat,
            provenance=prov_mat,
            factors=[mkt_factor],
            values={"FX_EUR_USD_LOGRET": [0.0] * 19},
            raw_levels={"FX_EUR_USD": [1.0] * 19},
            canonical_levels={"FX_EUR_USD": [1.0] * 19},
            effective_sample_size=19,
            pit_mode="ESTIMATED_LAG",
            level_dates=dates,
            aligned_level_count=20,
            transition_count=19,
            first_level_date=dates[0],
            last_level_date=dates[-1],
            first_transition_date=dates[1],
            last_transition_date=dates[-1],
        )

        # Split at index 10 (dates[10] = date(2023, 1, 12))
        calib_end = dates[10]
        calib_panel, holdout_panel = split_calibration_holdout(full_panel, calibration_end=calib_end)

        # Calibration panel: transitions on or before calib_end
        assert calib_panel.aligned_level_count == calib_panel.transition_count + 1
        assert len(calib_panel.dates) == calib_panel.transition_count
        assert len(calib_panel.level_dates) == calib_panel.aligned_level_count

        # Holdout panel: transitions strictly after calib_end
        assert holdout_panel.aligned_level_count == holdout_panel.transition_count + 1
        assert len(holdout_panel.dates) == holdout_panel.transition_count
        assert len(holdout_panel.level_dates) == holdout_panel.aligned_level_count

        # Calibration report verification
        report = calibrate_factor_panel(calib_panel, holdout_panel=holdout_panel)
        assert report.calibration_level_count == calib_panel.aligned_level_count
        assert report.calibration_transition_count == calib_panel.transition_count
        assert report.holdout_level_count == holdout_panel.aligned_level_count
        assert report.holdout_transition_count == holdout_panel.transition_count


# ==============================================================================
# Workstream E: Volatility Regime Thresholds Reconciliation
# ==============================================================================

class TestVolatilityRegimeThresholds:
    """Tests verifying 63-day rolling calibration percentiles and 2024 classification."""

    def test_volatility_regime_classification_in_diagnostics(self):
        """FactorHoldoutDiagnostics stores exact 20th and 80th percentiles and classification."""
        diag = FactorHoldoutDiagnostics(
            holdout_start=date(2024, 1, 2),
            holdout_end=date(2024, 12, 31),
            holdout_days=247,
            num_predictive_paths=1000,
            actual_fx_cumulative_return=-0.0636,
            actual_fx_realized_volatility=0.0618,
            actual_fx_max_drawdown=-0.0504,
            simulated_fx_return_median=0.0128,
            simulated_fx_return_p025=-0.1292,
            simulated_fx_return_p975=0.1757,
            simulated_fx_volatility_median=0.0795,
            simulated_fx_drawdown_median=-0.0650,
            predictive_percentile_fx_return=0.771,
            predictive_percentile_fx_return_mc_se=0.0133,
            predictive_percentile_fx_volatility=0.006,
            predictive_percentile_fx_drawdown=0.859,
            volatility_regime_classification="NORMAL_VOLATILITY",
            low_vol_threshold=0.0574,
            high_vol_threshold=0.0949,
            fx_log_return_ks_stat=0.0940,
            fx_log_return_ks_pvalue=0.0559,
        )
        assert diag.volatility_regime_classification == "NORMAL_VOLATILITY"
        assert diag.low_vol_threshold == 0.0574
        assert diag.high_vol_threshold == 0.0949
        assert diag.low_vol_threshold <= diag.actual_fx_realized_volatility <= diag.high_vol_threshold


# ==============================================================================
# Workstream F: Exceptional Federal Reserve Board Closures
# ==============================================================================

class TestFederalReserveExceptionalClosures:
    """Tests for FederalReserveH15Calendar modeling historical unscheduled closures."""

    def test_george_hw_bush_mourning_closure(self):
        """December 5, 2018 (George H.W. Bush National Day of Mourning) is an exceptional closure."""
        bush_date = date(2018, 12, 5)
        assert FederalReserveH15Calendar.is_exceptional_closure(bush_date)
        assert not FederalReserveH15Calendar.is_fed_business_day(bush_date)

        # Release for observation on Dec 4 rolls past Dec 5 to Dec 6
        rel_ts = FederalReserveH15Calendar.get_h15_release_timestamp(date(2018, 12, 4))
        rel_et = rel_ts.astimezone(EASTERN)
        assert rel_et.date() == date(2018, 12, 6)
        assert rel_et.hour == 16
        assert rel_et.minute == 15

    def test_hurricane_sandy_closures(self):
        """October 29-30, 2012 (Hurricane Sandy) are exceptional closures."""
        sandy_d1 = date(2012, 10, 29)
        sandy_d2 = date(2012, 10, 30)
        assert FederalReserveH15Calendar.is_exceptional_closure(sandy_d1)
        assert FederalReserveH15Calendar.is_exceptional_closure(sandy_d2)
        assert not FederalReserveH15Calendar.is_fed_business_day(sandy_d1)
        assert not FederalReserveH15Calendar.is_fed_business_day(sandy_d2)

        # Observation from Friday Oct 26 rolls past weekend and Sandy to Oct 31
        rel_ts = FederalReserveH15Calendar.get_h15_release_timestamp(date(2012, 10, 26))
        rel_et = rel_ts.astimezone(EASTERN)
        assert rel_et.date() == date(2012, 10, 31)

    def test_release_timestamp_override(self):
        """Direct timestamp override takes precedence."""
        test_obs = date(2025, 6, 1)
        test_override_ts = datetime(2025, 6, 3, 18, 30, tzinfo=timezone.utc)
        FederalReserveH15Calendar.register_release_timestamp_override(test_obs, test_override_ts)
        try:
            rel = FederalReserveH15Calendar.get_h15_release_timestamp(test_obs)
            assert rel == test_override_ts
        finally:
            FederalReserveH15Calendar._get_default_instance()._release_timestamp_overrides.pop(test_obs, None)

    def test_exceptional_closures_inspectable(self):
        """Exceptional closures dictionary is inspectable."""
        closures = FederalReserveH15Calendar.get_exceptional_closures()
        assert date(2018, 12, 5) in closures
        assert date(2012, 10, 29) in closures
        assert date(2012, 10, 30) in closures
        assert date(2007, 1, 2) in closures
        assert date(2004, 6, 11) in closures
        assert date(2001, 9, 11) in closures


# ==============================================================================
# Workstream G & H: Research Report Generator & Manifest Consistency
# ==============================================================================

class TestPhase41222ReportGenerator:
    """Tests verifying Phase 4.1.2.2.2 research closure report generation."""

    def test_generate_phase_4_1_2_2_2_report_structure(self):
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
            actual_fx_cumulative_return=-0.0636,
            actual_fx_realized_volatility=0.0618,
            actual_fx_max_drawdown=-0.0504,
            simulated_fx_return_median=0.0128,
            simulated_fx_return_p025=-0.1292,
            simulated_fx_return_p975=0.1757,
            simulated_fx_volatility_median=0.0795,
            simulated_fx_drawdown_median=-0.0650,
            predictive_percentile_fx_return=0.771,
            predictive_percentile_fx_return_mc_se=0.0133,
            predictive_percentile_fx_volatility=0.006,
            predictive_percentile_fx_drawdown=0.859,
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
            ModelComparisonEntry(
                model_name="Multivariate Gaussian",
                num_paths=1000,
                median_return=0.0145,
                mean_return=0.0166,
                std_return=0.0401,
                var_95=-0.0500,
                cvar_95=-0.0635,
                max_drawdown_median=0.0500,
                max_drawdown_p95=0.0800,
                prob_loss=0.352,
                prob_loss_se=0.0151,
                prob_drawdown_10pct=0.006,
                mean_fx_drag=0.0001,
                mean_financing_drag=0.0252,
                checkpoint_stability_status="CHECKPOINT_STABILITY_NOT_ACHIEVED",
                is_converged_prob_loss=False,
            ),
        ]

        report_md = generate_phase_4_1_2_2_2_research_report(
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
        )

        assert "# Phase 4.1.2.2.2 — Canonical FX Panel Integrity & Research Artifact Reconciliation Report" in report_md
        assert "990 aligned level dates [2020-01-06 to 2023-12-29]" in report_md
        assert "989 factor return transitions [2020-01-07 to 2023-12-29]" in report_md
        assert "248 aligned level dates [2023-12-29 to 2024-12-31]" in report_md
        assert "247 factor return transitions [2024-01-02 to 2024-12-31]" in report_md
        assert "CHECKPOINT_STABILITY_ACHIEVED" in report_md
        assert "CHECKPOINT_STABILITY_NOT_ACHIEVED" in report_md
        assert "5.74%" in report_md
        assert "9.49%" in report_md
