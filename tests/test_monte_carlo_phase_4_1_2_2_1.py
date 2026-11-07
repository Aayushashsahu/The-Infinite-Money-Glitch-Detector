"""Unit and integration tests for Phase 4.1.2.2.1 Federal Reserve Release Calendar & PIT Integrity Closure.

Verifies:
- Workstream A: Federal Reserve H.15 availability calendar, 4:15 PM ET release timing, DST transitions, Fed holidays.
- Workstream B: Fail-closed availability firewall, rejection of missing evidence, retrospective data, and invalid PIT modes.
- Workstream C: Source dispatch disentangling ECB interest rates from FX reference rates.
- Workstream D: Metadata-driven unit normalization for FX quotes and interest rates without magnitude heuristics.
- Workstream E: Dynamic grounding of initial market levels at 16:00 UTC on Jan 2, 2024 reflecting H.15 publication lag.
- Workstream F: Volatility regime horizon reconciliation (63-day rolling calibration vs 247-day holdout).
- Workstream G: Per-model checkpoint stability reporting in model comparisons and convergence report.
- Workstream H: Simulation manifest schema and report generation.
"""

from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import zoneinfo
import pytest

from backtesting.calendar import FederalReserveH15Calendar
from data.schemas import (
    AvailabilityEvidence,
    DataClassification,
    DataObservation,
    Frequency,
    ObservationKind,
)
from simulation.monte_carlo.factors import (
    _normalize_fx_quote_to_usd_per_eur,
    _normalize_rate_to_decimal,
    get_effective_availability_timestamp,
    is_observation_available_as_of,
    resolve_initial_market_levels,
)
from simulation.monte_carlo.metrics import calculate_distribution_metrics
from simulation.monte_carlo.reporting import generate_phase_4_1_2_2_1_research_report
from simulation.monte_carlo.strategy_adapter import (
    evaluate_funding_sensitivity,
    validate_market_calendar_evidence,
)
from simulation.monte_carlo.schemas import (
    ConvergenceCheckpoint,
    ConvergenceReport,
    CorrelationStressComparison,
    FactorHoldoutDiagnostics,
    InitialMarketLevelsReport,
    ModelComparisonEntry,
    MonteCarloResult,
    PathEvaluationResult,
    PITMode,
    PortfolioHoldoutDiagnostics,
    SimulationConfig,
    SimulationModelType,
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
        retrieved_at=pub_dt or datetime(2024, 1, 1, tzinfo=timezone.utc),
        publication_timestamp=pub_dt,
        availability_evidence=evidence,
        classification=classification,
        revision=rev,
    )


# ==============================================================================
# Workstream A: Federal Reserve H.15 Availability Calendar
# ==============================================================================

class TestFederalReserveH15Calendar:
    """Tests for FederalReserveH15Calendar modeling 4:15 PM ET release mechanics."""

    def test_next_business_day_weekday(self):
        cal = FederalReserveH15Calendar()
        # Monday Jan 8, 2024 -> Next business day is Tuesday Jan 9, 2024
        next_bd = cal.get_next_business_day(date(2024, 1, 8))
        assert next_bd == date(2024, 1, 9)

    def test_next_business_day_friday_to_monday(self):
        cal = FederalReserveH15Calendar()
        # Friday Jan 5, 2024 -> Next business day is Monday Jan 8, 2024
        next_bd = cal.get_next_business_day(date(2024, 1, 5))
        assert next_bd == date(2024, 1, 8)

    def test_next_business_day_over_holiday(self):
        cal = FederalReserveH15Calendar()
        # Friday Jan 12, 2024 -> Monday Jan 15 is MLK Day (Federal Reserve holiday)
        # Next business day is Tuesday Jan 16, 2024
        next_bd = cal.get_next_business_day(date(2024, 1, 12))
        assert next_bd == date(2024, 1, 16)

    def test_winter_release_timing_est(self):
        """In winter (Standard Time, UTC-5), 4:15 PM Eastern is 21:15 UTC."""
        cal = FederalReserveH15Calendar()
        # Observation date Thursday Dec 28, 2023 -> Released Friday Dec 29, 2023 at 16:15 EST = 21:15 UTC
        rel_ts = cal.get_h15_release_timestamp(date(2023, 12, 28))
        assert rel_ts == datetime(2023, 12, 29, 21, 15, tzinfo=timezone.utc)

        # Observation date Friday Dec 29, 2023 -> Released Tuesday Jan 2, 2024 (Jan 1 is New Year's Day)
        # 16:15 EST = 21:15 UTC
        rel_ts2 = cal.get_h15_release_timestamp(date(2023, 12, 29))
        assert rel_ts2 == datetime(2024, 1, 2, 21, 15, tzinfo=timezone.utc)

    def test_summer_release_timing_edt(self):
        """In summer (Daylight Saving Time, UTC-4), 4:15 PM Eastern is 20:15 UTC."""
        cal = FederalReserveH15Calendar()
        # Observation date Tuesday July 2, 2024 -> Released Wednesday July 3, 2024 at 16:15 EDT = 20:15 UTC
        rel_ts = cal.get_h15_release_timestamp(date(2024, 7, 2))
        assert rel_ts == datetime(2024, 7, 3, 20, 15, tzinfo=timezone.utc)

    def test_juneteenth_holiday_rollover(self):
        """Juneteenth (June 19) is a Federal Reserve holiday."""
        cal = FederalReserveH15Calendar()
        # 2024-06-18 (Tuesday) -> June 19 is holiday -> released Thursday June 20 at 20:15 UTC
        rel_ts = cal.get_h15_release_timestamp(date(2024, 6, 18))
        assert rel_ts == datetime(2024, 6, 20, 20, 15, tzinfo=timezone.utc)

    def test_decision_timestamp_16_utc_enforcement(self):
        """At 16:00:00 UTC on Jan 2, 2024, Dec 29 Treasury yield is NOT available."""
        obs_dec_28 = _make_obs(
            kind=ObservationKind.INTEREST_RATE,
            source_id="us_treasury",
            entity_code="US",
            indicator_id="DGS1MO",
            obs_date=date(2023, 12, 28),
            val=5.55,
        )
        obs_dec_29 = _make_obs(
            kind=ObservationKind.INTEREST_RATE,
            source_id="us_treasury",
            entity_code="US",
            indicator_id="DGS1MO",
            obs_date=date(2023, 12, 29),
            val=5.57,
        )

        decision_time = datetime(2024, 1, 2, 16, 0, 0, tzinfo=timezone.utc)

        # Dec 28 released Dec 29 at 21:15 UTC -> available
        is_avail, _ = is_observation_available_as_of(obs_dec_28, decision_time, pit_mode=PITMode.ESTIMATED_LAG)
        assert is_avail is True

        # Dec 29 released Jan 2 at 21:15 UTC -> NOT available at 16:00 UTC
        is_avail_29, _ = is_observation_available_as_of(obs_dec_29, decision_time, pit_mode=PITMode.ESTIMATED_LAG)
        assert is_avail_29 is False

        # Exactly 1 second before release: NOT available
        pre_release = datetime(2024, 1, 2, 21, 14, 59, tzinfo=timezone.utc)
        assert is_observation_available_as_of(obs_dec_29, pre_release, pit_mode=PITMode.ESTIMATED_LAG)[0] is False

        # At release timestamp: AVAILABLE
        at_release = datetime(2024, 1, 2, 21, 15, 0, tzinfo=timezone.utc)
        assert is_observation_available_as_of(obs_dec_29, at_release, pit_mode=PITMode.ESTIMATED_LAG)[0] is True


# ==============================================================================
# Workstream B: Fail-Closed Availability Firewall
# ==============================================================================

class TestFailClosedAvailabilityFirewall:
    """Tests enforcing strict fail-closed behavior for PIT availability."""

    def test_missing_evidence_rejected(self):
        obs = _make_obs(
            kind=ObservationKind.INTEREST_RATE,
            source_id="us_treasury",
            entity_code="US",
            indicator_id="DGS1MO",
            obs_date=date(2023, 12, 28),
            val=5.55,
            evidence=None,  # type: ignore[arg-type]
        )
        as_of = datetime(2024, 1, 10, tzinfo=timezone.utc)
        assert is_observation_available_as_of(obs, as_of, pit_mode=PITMode.ESTIMATED_LAG)[0] is False
        assert is_observation_available_as_of(obs, as_of, pit_mode=PITMode.STRICT_VERIFIED)[0] is False

    def test_retrospective_evidence_rejected_in_estimated_lag(self):
        obs = _make_obs(
            kind=ObservationKind.INTEREST_RATE,
            source_id="us_treasury",
            entity_code="US",
            indicator_id="DGS1MO",
            obs_date=date(2023, 12, 28),
            val=5.55,
            evidence=AvailabilityEvidence.RETROSPECTIVE,
            classification=DataClassification.REAL_RETROSPECTIVE,
        )
        as_of = datetime(2024, 1, 10, tzinfo=timezone.utc)
        assert is_observation_available_as_of(obs, as_of, pit_mode=PITMode.ESTIMATED_LAG)[0] is False
        assert is_observation_available_as_of(obs, as_of, pit_mode=PITMode.RESEARCH_ONLY)[0] is True

    def test_invalid_pit_mode_raises_value_error(self):
        obs = _make_obs(
            kind=ObservationKind.INTEREST_RATE,
            source_id="us_treasury",
            entity_code="US",
            indicator_id="DGS1MO",
            obs_date=date(2023, 12, 28),
            val=5.55,
        )
        as_of = datetime(2024, 1, 10, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="Invalid pit_mode: 'INVALID_MODE'"):
            is_observation_available_as_of(obs, as_of, pit_mode="INVALID_MODE")  # type: ignore[arg-type]

    def test_unmapped_series_fails_closed(self):
        obs = _make_obs(
            kind=ObservationKind.INTEREST_RATE,
            source_id="unknown_central_bank",
            entity_code="ZZ",
            indicator_id="UNKNOWN_RATE",
            obs_date=date(2023, 12, 28),
            val=2.50,
        )
        eff_ts = get_effective_availability_timestamp(obs)
        assert eff_ts is None

        as_of = datetime(2024, 1, 10, tzinfo=timezone.utc)
        assert is_observation_available_as_of(obs, as_of, pit_mode=PITMode.ESTIMATED_LAG)[0] is False
        assert is_observation_available_as_of(obs, as_of, pit_mode=PITMode.STRICT_VERIFIED)[0] is False


# ==============================================================================
# Workstream C: Disentangle ECB Source Dispatch
# ==============================================================================

class TestECBSourceDispatch:
    """Verifies that ECB interest rate data and ECB exchange rate data dispatch to distinct schedules."""

    def test_ecb_fx_reference_rate_dispatch(self):
        obs_fx = _make_obs(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="ecb",
            entity_code="EURUSD",
            indicator_id="ECB_REFERENCE",
            obs_date=date(2023, 12, 29),
            val=1.1050,
        )
        eff_ts = get_effective_availability_timestamp(obs_fx)
        # FX reference rate is available at 16:00 UTC on the observation date
        assert eff_ts == datetime(2023, 12, 29, 16, 0, tzinfo=timezone.utc)

    def test_ecb_interest_rate_policy_rate_dispatch(self):
        obs_rate = _make_obs(
            kind=ObservationKind.INTEREST_RATE,
            source_id="ecb",
            entity_code="EZ",
            indicator_id="KR.MRR_FR.LEV",
            obs_date=date(2023, 12, 29),
            val=4.50,
        )
        eff_ts = get_effective_availability_timestamp(obs_rate)
        # Policy rate effective from 00:00 UTC on observation date
        assert eff_ts == datetime(2023, 12, 29, 0, 0, tzinfo=timezone.utc)


# ==============================================================================
# Workstream D: Metadata-Driven Unit Normalization
# ==============================================================================

class TestMetadataDrivenUnitNormalization:
    """Tests unit normalization without magnitude heuristics."""

    def test_fx_quote_inversion_by_unit(self):
        # Explicit EUR_per_USD requires inversion regardless of value magnitude
        obs_eur_usd = _make_obs(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="ecb",
            entity_code="EURUSD",
            indicator_id="ECB_REFERENCE",
            obs_date=date(2023, 12, 29),
            val=0.90,
            unit="EUR_per_USD",
        )
        inv = _normalize_fx_quote_to_usd_per_eur(obs_eur_usd)
        assert pytest.approx(inv, rel=1e-6) == 1.0 / 0.90

        # Even if value was > 1.0, explicit unit EUR_per_USD inverts
        obs_eur_usd_high = _make_obs(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="ecb",
            entity_code="EURUSD",
            indicator_id="ECB_REFERENCE",
            obs_date=date(2023, 12, 29),
            val=1.05,
            unit="EUR_per_USD",
        )
        assert pytest.approx(_normalize_fx_quote_to_usd_per_eur(obs_eur_usd_high), rel=1e-6) == 1.0 / 1.05

    def test_fx_quote_preservation_by_unit(self):
        obs_usd_eur = _make_obs(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="frankfurter",
            entity_code="EURUSD",
            indicator_id="ECB_REFERENCE",
            obs_date=date(2023, 12, 29),
            val=1.1050,
            unit="USD_per_EUR",
        )
        assert _normalize_fx_quote_to_usd_per_eur(obs_usd_eur) == 1.1050

        # Even if value was < 1.0 (e.g. EUR/USD at parity breach 0.98), explicit unit USD_per_EUR preserves
        obs_parity_breach = _make_obs(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="frankfurter",
            entity_code="EURUSD",
            indicator_id="ECB_REFERENCE",
            obs_date=date(2022, 10, 1),
            val=0.98,
            unit="USD_per_EUR",
        )
        assert _normalize_fx_quote_to_usd_per_eur(obs_parity_breach) == 0.98

    def test_interest_rate_percent_normalization(self):
        obs_pct = _make_obs(
            kind=ObservationKind.INTEREST_RATE,
            source_id="us_treasury",
            entity_code="US",
            indicator_id="DGS1MO",
            obs_date=date(2023, 12, 28),
            val=5.55,
            unit="percent",
        )
        assert _normalize_rate_to_decimal(obs_pct) == 0.0555

        # Small percentage (0.25%) with unit="percent" divides by 100 without being mistaken for decimal
        obs_small_pct = _make_obs(
            kind=ObservationKind.INTEREST_RATE,
            source_id="us_treasury",
            entity_code="US",
            indicator_id="DGS1MO",
            obs_date=date(2020, 5, 1),
            val=0.25,
            unit="percent",
        )
        assert _normalize_rate_to_decimal(obs_small_pct) == 0.0025

    def test_interest_rate_decimal_preservation(self):
        obs_dec = _make_obs(
            kind=ObservationKind.INTEREST_RATE,
            source_id="ecb",
            entity_code="EZ",
            indicator_id="KR.MRR_FR.LEV",
            obs_date=date(2023, 12, 29),
            val=0.045,
            unit="decimal",
        )
        assert _normalize_rate_to_decimal(obs_dec) == 0.045


# ==============================================================================
# Workstream E: Dynamic Grounding of Initial Market Levels
# ==============================================================================

class TestInitialMarketLevelsGrounding:
    """Tests dynamic grounding of initial levels for Jan 2, 2024 simulation decision time."""

    def test_initial_market_levels_resolution_with_h15_lag(self):
        observations = [
            # FX Dec 29 available at 16:00 UTC on Dec 29
            _make_obs(ObservationKind.EXCHANGE_RATE, "frankfurter", "EURUSD", "ECB_REFERENCE", date(2023, 12, 29), 1.1050),
            # ECB borrowing rate Dec 29 available Dec 29 00:00 UTC
            _make_obs(ObservationKind.INTEREST_RATE, "ecb", "EZ", "KR.MRR_FR.LEV", date(2023, 12, 29), 4.50),
            # Treasury rate Dec 28 available Dec 29 21:15 UTC (5.55%)
            _make_obs(ObservationKind.INTEREST_RATE, "us_treasury", "US", "DGS1MO", date(2023, 12, 28), 5.55),
            # Treasury rate Dec 29 NOT available until Jan 2 21:15 UTC (5.57%)
            _make_obs(ObservationKind.INTEREST_RATE, "us_treasury", "US", "DGS1MO", date(2023, 12, 29), 5.57),
        ]

        init_levels = resolve_initial_market_levels(
            observations=observations,
            as_of_decision_timestamp=datetime(2024, 1, 2, 16, 0, 0, tzinfo=timezone.utc),
            pit_mode=PITMode.ESTIMATED_LAG,
            fx_entity="EURUSD",
        )

        assert init_levels.initial_fx_rate == 1.1050
        assert init_levels.initial_borrowing_rate == 0.0450
        # Crucial: Must be 0.0555 (Dec 28), NOT 0.0557 (Dec 29)
        assert init_levels.initial_investment_rate == 0.0555
        assert init_levels.investment_observation_date == date(2023, 12, 28)
        assert len(init_levels.grounding_notes) > 0


# ==============================================================================
# Workstream G: Per-Model Checkpoint Stability Reporting
# ==============================================================================

class TestPerModelCheckpointStability:
    """Tests ModelComparisonEntry and ConvergenceReport per-model stability fields."""

    def test_model_comparison_entry_has_stability_fields(self):
        entry = ModelComparisonEntry(
            model_name="Moving-Block Bootstrap (20d)",
            num_paths=1000,
            median_return=0.0210,
            mean_return=0.0195,
            std_return=0.0750,
            var_95=-0.0820,
            cvar_95=-0.1150,
            max_drawdown_median=0.0610,
            max_drawdown_p95=0.1250,
            prob_loss=0.342,
            prob_loss_se=0.015,
            prob_drawdown_10pct=0.180,
            mean_fx_drag=-0.015,
            mean_financing_drag=-0.045,
            checkpoint_stability_status="CHECKPOINT_STABILITY_ACHIEVED",
            is_converged_mean=True,
            is_converged_median=True,
            is_converged_prob_loss=True,
            is_converged_var_95=True,
            is_converged_cvar_95=True,
            is_converged_drawdown=True,
            tail_sample_size=50,
            stability_notes="All risk and return metrics demonstrated checkpoint stability at N=1000.",
        )
        assert entry.checkpoint_stability_status == "CHECKPOINT_STABILITY_ACHIEVED"
        assert entry.tail_sample_size == 50
        assert entry.is_converged_var_95 is True

    def test_convergence_report_per_model_stability_dict(self):
        report = ConvergenceReport(
            checkpoints=[
                ConvergenceCheckpoint(
                    sample_size=1000,
                    mean_return=0.02,
                    median_return=0.021,
                    prob_loss=0.34,
                    prob_loss_se=0.015,
                    var_95=-0.08,
                    cvar_95=-0.11,
                    std_return=0.075,
                    max_drawdown_median=0.06,
                    prob_drawdown_10pct=0.18,
                    tail_sample_size=50,
                    var_95_se=0.005,
                    cvar_95_se=0.008,
                )
            ],
            is_converged=True,
            final_standard_error=0.015,
            convergence_notes="Passed",
            stability_status="CHECKPOINT_STABILITY_ACHIEVED",
            tail_sample_size_final=50,
            per_model_stability={
                "Moving-Block Bootstrap (20d)": {
                    "stability_status": "CHECKPOINT_STABILITY_ACHIEVED",
                    "is_converged": True,
                    "tail_sample_size": 50,
                }
            },
        )
        assert "Moving-Block Bootstrap (20d)" in report.per_model_stability
        assert report.per_model_stability["Moving-Block Bootstrap (20d)"]["stability_status"] == "CHECKPOINT_STABILITY_ACHIEVED"


# ==============================================================================
# Workstream H: Report Generation Verification
# ==============================================================================

class TestReportGeneration:
    """Verifies that generate_phase_4_1_2_2_1_research_report renders correctly."""

    def test_report_renders_with_expected_sections(self):
        from simulation.monte_carlo.schemas import AvailabilityAuditReport

        avail_audit = AvailabilityAuditReport(
            total_source_observations=8900,
            genuine_observations_included=8724,
            synthetic_observations_excluded=176,
            date_window_exclusions=0,
            classification_exclusions=0,
            factor_alignment_exclusions=0,
            exact_timestamp_verified_count=0,
            estimated_availability_count=8724,
            retrospective_count=0,
            missing_evidence_count=0,
            unrecognized_evidence_count=0,
            is_reconciled=True,
            data_classification_label="SIMULATED_RESEARCH_PROXY",
            pit_mode="ESTIMATED_LAG",
            audit_scope_description="Audit scope",
            release_lag_policies={},
            factor_breakdown={},
        )

        init_levels = InitialMarketLevelsReport(
            as_of_decision_timestamp=datetime(2024, 1, 2, 16, 0, tzinfo=timezone.utc),
            pit_mode="ESTIMATED_LAG",
            initial_fx_rate=1.1050,
            initial_borrowing_rate=0.0450,
            initial_investment_rate=0.0555,
            fx_observation_date=date(2023, 12, 29),
            fx_source_id="frankfurter",
            fx_entity_code="EURUSD",
            fx_raw_value=1.1050,
            borrowing_observation_date=date(2023, 12, 29),
            borrowing_source_id="ecb",
            borrowing_indicator_id="KR.MRR_FR.LEV",
            borrowing_raw_value=4.50,
            investment_observation_date=date(2023, 12, 28),
            investment_source_id="us_treasury",
            investment_indicator_id="DGS1MO",
            investment_raw_value=5.55,
            grounding_notes=["Grounded initial levels with 5.55% Dec 28 investment rate."],
        )

        entries = [
            ModelComparisonEntry(
                model_name="Moving-Block Bootstrap (20d)",
                num_paths=1000,
                median_return=0.0210,
                mean_return=0.0195,
                std_return=0.0750,
                var_95=-0.0820,
                cvar_95=-0.1150,
                max_drawdown_median=0.0610,
                max_drawdown_p95=0.1250,
                prob_loss=0.342,
                prob_loss_se=0.015,
                prob_drawdown_10pct=0.180,
                mean_fx_drag=-0.015,
                mean_financing_drag=-0.045,
                checkpoint_stability_status="CHECKPOINT_STABILITY_ACHIEVED",
                is_converged_mean=True,
                is_converged_median=True,
                is_converged_prob_loss=True,
                is_converged_var_95=True,
                is_converged_cvar_95=True,
                is_converged_drawdown=True,
                tail_sample_size=50,
                stability_notes="Passed",
            )
        ]

        factor_diag = FactorHoldoutDiagnostics(
            holdout_start=date(2024, 1, 2),
            holdout_end=date(2024, 12, 31),
            holdout_days=247,
            num_predictive_paths=1000,
            actual_fx_cumulative_return=-0.05,
            actual_fx_realized_volatility=0.055,
            actual_fx_max_drawdown=0.06,
            simulated_fx_return_median=0.02,
            simulated_fx_return_p025=-0.10,
            simulated_fx_return_p975=0.12,
            simulated_fx_volatility_median=0.075,
            simulated_fx_drawdown_median=0.06,
            predictive_percentile_fx_return=0.45,
            predictive_percentile_fx_return_mc_se=0.015,
            predictive_percentile_fx_volatility=0.25,
            predictive_percentile_fx_drawdown=0.50,
            volatility_regime_classification="NORMAL_VOLATILITY",
            fx_log_return_ks_stat=0.05,
            fx_log_return_ks_pvalue=0.45,
        )

        port_diag = PortfolioHoldoutDiagnostics(
            status="UNAVAILABLE",
            reason="Live trading execution records absent",
        )

        corr_stress = CorrelationStressComparison(
            baseline_model="Moving-Block Bootstrap (20d)",
            stressed_model="Moving-Block Bootstrap (Decoupled Correlation)",
            num_paths=1000,
            baseline_mean_return=0.02,
            baseline_median_return=0.021,
            baseline_var_95=-0.08,
            baseline_cvar_95=-0.11,
            baseline_prob_loss=0.34,
            stressed_mean_return=0.018,
            stressed_median_return=0.019,
            stressed_var_95=-0.085,
            stressed_cvar_95=-0.118,
            stressed_prob_loss=0.36,
            mean_return_difference=-0.002,
            median_return_difference=-0.002,
            var_95_difference=-0.005,
            cvar_95_difference=-0.008,
            prob_loss_difference=0.02,
            baseline_median_drawdown=0.06,
            stressed_median_drawdown=0.065,
            median_drawdown_difference=0.005,
            baseline_mean_financing_cost_a=4500.0,
            stressed_mean_financing_cost_a=4500.0,
            financing_cost_difference_a=0.0,
            baseline_mean_fx_translation_a=-1500.0,
            stressed_mean_fx_translation_a=-1700.0,
            fx_translation_difference_a=-200.0,
            paired_return_difference_mean=-0.002,
            paired_return_difference_std=0.01,
            paired_return_difference_p05=-0.02,
            paired_return_difference_p50=-0.002,
            paired_return_difference_p95=0.015,
        )

        cal_val = validate_market_calendar_evidence()
        funding_sens = evaluate_funding_sensitivity()

        cfg = SimulationConfig(
            simulation_id="MC_TEST",
            model_type=SimulationModelType.HISTORICAL_BOOTSTRAP,
            num_paths=1000,
            horizon_steps=252,
            random_seed=42,
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
        dist = calculate_distribution_metrics(evaluations=evals, horizon_steps=252)
        dummy_result = MonteCarloResult(
            simulation_id="MC_TEST",
            config=cfg,
            distribution_metrics=dist,
        )

        md = generate_phase_4_1_2_2_1_research_report(
            avail_audit=avail_audit,
            model_comparisons=entries,
            factor_diag=factor_diag,
            port_diag=port_diag,
            corr_stress=corr_stress,
            cal_val=cal_val,
            funding_sens=funding_sens,
            bootstrap_result=dummy_result,
            student_t_result=dummy_result,
            regime_result=dummy_result,
            gaussian_result=dummy_result,
            manifest_info={
                "git_commit": "abcdef123456",
                "random_seed": 42,
                "pit_policy": "ESTIMATED_LAG",
                "h15_release_schedule": "4:15 PM Eastern Time on next Federal Reserve business day (ZoneInfo('America/New_York'))",
            },
            initial_levels=init_levels,
        )

        assert "# Phase 4.1.2.2.1" in md
        assert "Federal Reserve H.15" in md
        assert "Per-Model Checkpoint Stability" in md
        assert "Volatility Regime Horizons & Reconciliation" in md
        assert "5.55%" in md or "0.0555" in md


def test_phase_4_1_2_2_1_manifest_completeness_and_hashes():
    """Verify Phase 4.1.2.2.1 simulation manifest completeness and artifact SHA-256 digests."""
    results_dir = Path("data/results/phase_4_1_2_2_1")
    if not results_dir.exists():
        pytest.skip("Stage B generated artifacts not present yet; run after runner.")

    manifest_path = results_dir / "simulation_manifest.json"
    assert manifest_path.exists(), "simulation_manifest.json must exist"

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["data_classification"] == "SIMULATED_RESEARCH_PROXY"
    assert manifest["pit_policy"] == "ESTIMATED_LAG"
    assert "initial_market_levels" in manifest
    assert "h15_release_schedule" in manifest
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
        "phase_4_1_2_2_1_research_report.md",
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

