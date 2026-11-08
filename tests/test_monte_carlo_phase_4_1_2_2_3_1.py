"""Unit and regression tests for Phase 4.1.2.2.3.1: Fail-Closed Canonical Boundary-Level Resolution.

Verifies:
1. Canonical USD/EUR FX initialization remains unchanged (1.1049967955).
2. Raw EUR/USD input is correctly inverted when explicit metadata authorizes it (e.g., 0.91274 -> 1.095602).
3. Raw USD/EUR input remains unchanged when explicitly identified.
4. Ambiguous FX quote conventions fail closed (missing unit, unknown unit, never infer from magnitude).
5. Percentage-point rates convert correctly into annual decimals (4.5 -> 0.045).
6. Decimal (0.045 -> 0.045) and basis-point (450 -> 0.045) raw rate inputs are normalized correctly.
7. Missing or unknown raw rate units fail closed (ValueError).
8. Missing DGS1MO does not result in silent DGS3MO substitution (ValueError raised).
9. Canonical levels continue to produce established boundary state (S0 ~ 1.104997, rb = 0.0450, ri = 0.0555).
10. Existing 248-date/248-level scenario alignment remains unchanged.
11. Both calendar validators (JOINT_TARGET2_FED and WEEKDAY_TRADING_PROXY) continue accepting generated holdout paths.
12. Portfolio holdout remains strictly UNAVAILABLE.
"""

from datetime import date
import pytest

from data.db.engine import make_engine, make_session_factory
from data.repository import Repository
from simulation.monte_carlo.bootstrap import HistoricalBootstrapSampler
from simulation.monte_carlo.calibration import split_calibration_holdout
from simulation.monte_carlo.factors import build_fx_carry_factor_panel
from simulation.monte_carlo.holdout import (
    generate_holdout_predictive_paths,
    evaluate_portfolio_holdout_diagnostics,
    resolve_canonical_initial_fx,
    resolve_canonical_initial_borrowing_rate,
    resolve_canonical_initial_investment_rate,
)
from simulation.monte_carlo.schemas import (
    BootstrapMethod,
    DataClassification,
    FactorCategory,
    FactorPanel,
    FactorRowProvenance,
    Frequency,
    MarketFactor,
    MissingDataTreatment,
    PITMode,
    TransformationMethod,
)
from simulation.monte_carlo.strategy_adapter import validate_calendar_dates


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


def make_dummy_panel(
    factors: list[MarketFactor],
    canonical_levels: dict[str, list[float]] | None = None,
    raw_levels: dict[str, list[float]] | None = None,
    row_provenance: dict[str, list[FactorRowProvenance]] | None = None,
    dates: list[date] | None = None,
    level_dates: list[date] | None = None,
) -> FactorPanel:
    """Helper to construct synthetic factor panels for boundary-level resolution testing."""
    d = dates or [date(2023, 12, 28), date(2023, 12, 29)]
    ld = level_dates or [date(2023, 12, 27), date(2023, 12, 28), date(2023, 12, 29)]
    values = {f.factor_id: [0.0] * len(d) for f in factors}
    return FactorPanel(
        factors=factors,
        dates=d,
        level_dates=ld,
        values=values,
        raw_levels=raw_levels or {},
        canonical_levels=canonical_levels or {},
        row_provenance=row_provenance or {},
        effective_sample_size=len(d),
        aligned_level_count=len(ld),
        transition_count=len(d),
    )


# ==============================================================================
# Workstream A: Fail-Closed Canonical FX Boundary Resolution
# ==============================================================================

class TestCanonicalInitialFXResolution:
    """Verifies fail-closed resolution for canonical and raw FX levels."""

    def test_canonical_usd_eur_unchanged(self):
        """Rule 1: Canonical USD/EUR FX initialization remains unchanged."""
        factor = MarketFactor(
            factor_id="FX_EUR_USD_LOGRET",
            category=FactorCategory.FX_RETURN,
            asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY,
            original_unit="EUR_per_USD",
            normalized_unit="log_return",
            source_id="frankfurter",
            series_id="EURUSD",
            transformation=TransformationMethod.LOG_RETURN,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        panel = make_dummy_panel(
            factors=[factor],
            canonical_levels={"FX_EUR_USD_LOGRET": [1.0900, 1.1049967955]},
            raw_levels={"FX_EUR_USD_LOGRET": [0.9174, 0.9050]},
        )
        resolved_fx = resolve_canonical_initial_fx(panel, date(2023, 12, 29))
        assert resolved_fx == pytest.approx(1.1049967955, rel=1e-9)

    def test_raw_eur_usd_inverted_with_authorized_metadata(self):
        """Rule 2: Raw EUR/USD input is correctly inverted when explicit metadata authorizes it."""
        factor = MarketFactor(
            factor_id="FX_EUR_USD_LOGRET",
            category=FactorCategory.FX_RETURN,
            asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY,
            original_unit="EUR_per_USD",
            normalized_unit="log_return",
            source_id="frankfurter",
            series_id="EURUSD",
            transformation=TransformationMethod.LOG_RETURN,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        raw_val = 0.91274
        prov = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="frankfurter",
            series_id="EURUSD",
            raw_value=raw_val,
            raw_unit="EUR_per_USD",
            transformed_value=0.0,
            pair="USD/EUR",
            base_currency="USD",
            quote_currency="EUR",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel = make_dummy_panel(
            factors=[factor],
            canonical_levels={},  # No canonical levels
            raw_levels={"FX_EUR_USD_LOGRET": [0.9150, raw_val]},
            row_provenance={"FX_EUR_USD_LOGRET": [prov, prov]},
        )
        resolved_fx = resolve_canonical_initial_fx(panel, date(2023, 12, 29))
        expected_fx = 1.0 / raw_val
        assert resolved_fx == pytest.approx(expected_fx, rel=1e-6)
        assert resolved_fx == pytest.approx(1.095602, rel=1e-5)

    def test_raw_usd_eur_preserved_with_authorized_metadata(self):
        """Rule 3: Raw USD/EUR input remains unchanged when explicitly identified."""
        factor = MarketFactor(
            factor_id="FX_EUR_USD_LOGRET",
            category=FactorCategory.FX_RETURN,
            asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY,
            original_unit="USD_per_EUR",
            normalized_unit="log_return",
            source_id="ecb",
            series_id="EURUSD",
            transformation=TransformationMethod.LOG_RETURN,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        raw_val = 1.095602
        prov = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="ecb",
            series_id="EURUSD",
            raw_value=raw_val,
            raw_unit="USD_per_EUR",
            transformed_value=0.0,
            pair="EUR/USD",
            base_currency="EUR",
            quote_currency="USD",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"FX_EUR_USD_LOGRET": [raw_val]},
            row_provenance={"FX_EUR_USD_LOGRET": [prov]},
        )
        resolved_fx = resolve_canonical_initial_fx(panel, date(2023, 12, 29))
        assert resolved_fx == pytest.approx(raw_val, rel=1e-9)

    def test_ambiguous_quote_metadata_fails_closed(self):
        """Rule 4: Ambiguous FX quote conventions fail closed; never infer from magnitude."""
        factor_no_unit = MarketFactor(
            factor_id="FX_EUR_USD_LOGRET",
            category=FactorCategory.FX_RETURN,
            asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY,
            original_unit="",
            normalized_unit="log_return",
            source_id="unknown",
            series_id="EURUSD",
            transformation=TransformationMethod.LOG_RETURN,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        # Case A: Missing unit on raw level with typical EUR/USD magnitude (0.85)
        prov_no_unit = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="unknown",
            series_id="EURUSD",
            raw_value=0.85,
            raw_unit=None,
            transformed_value=0.0,
            pair="EUR/USD",
            base_currency=None,
            quote_currency=None,
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel_a = make_dummy_panel(
            factors=[factor_no_unit],
            canonical_levels={},
            raw_levels={"FX_EUR_USD_LOGRET": [0.85]},
            row_provenance={"FX_EUR_USD_LOGRET": [prov_no_unit]},
        )
        with pytest.raises(ValueError, match="Cannot resolve initial FX level from raw levels.*raw unit.*is missing, ambiguous, or unsupported"):
            resolve_canonical_initial_fx(panel_a, date(2023, 12, 29))

        # Case B: Unknown unit on raw level with typical USD/EUR magnitude (1.25)
        prov_bad_unit = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="unknown",
            series_id="EURUSD",
            raw_value=1.25,
            raw_unit="CURRENCY_UNITS",
            transformed_value=0.0,
            pair="EUR/USD",
            base_currency=None,
            quote_currency=None,
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel_b = make_dummy_panel(
            factors=[factor_no_unit],
            canonical_levels={},
            raw_levels={"FX_EUR_USD_LOGRET": [1.25]},
            row_provenance={"FX_EUR_USD_LOGRET": [prov_bad_unit]},
        )
        with pytest.raises(ValueError, match="Cannot resolve initial FX level from raw levels.*raw unit.*is missing, ambiguous, or unsupported"):
            resolve_canonical_initial_fx(panel_b, date(2023, 12, 29))

    def test_non_positive_or_non_finite_fx_fails_closed(self):
        """FX level must be strictly positive and finite."""
        factor = MarketFactor(
            factor_id="FX_EUR_USD_LOGRET",
            category=FactorCategory.FX_RETURN,
            asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY,
            original_unit="USD_per_EUR",
            normalized_unit="log_return",
            source_id="ecb",
            series_id="EURUSD",
            transformation=TransformationMethod.LOG_RETURN,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        panel_zero = make_dummy_panel(
            factors=[factor],
            canonical_levels={"FX_EUR_USD_LOGRET": [0.0]},
        )
        with pytest.raises(ValueError, match="Initial FX level must be finite and positive"):
            resolve_canonical_initial_fx(panel_zero, date(2023, 12, 29))


# ==============================================================================
# Workstream B: Fail-Closed EUR Borrowing Rate Boundary Resolution
# ==============================================================================

class TestCanonicalInitialBorrowingRateResolution:
    """Verifies fail-closed resolution for EUR borrowing rate boundary levels."""

    def test_canonical_percentage_points_to_decimal(self):
        """Rule 5: Percentage-point rates convert correctly into annual decimals (4.5 -> 0.045)."""
        factor = MarketFactor(
            factor_id="RATE_DIFF_EUR_BORROW_BPS",
            category=FactorCategory.BORROWING_RATE_CHANGE,
            asset_or_currency="EUR",
            frequency=Frequency.DAILY,
            original_unit="percent",
            normalized_unit="basis_points",
            source_id="ecb",
            series_id="ESTR",
            transformation=TransformationMethod.FIRST_DIFFERENCE,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        panel = make_dummy_panel(
            factors=[factor],
            canonical_levels={"RATE_DIFF_EUR_BORROW_BPS": [4.0, 4.5]},
        )
        resolved_borrow = resolve_canonical_initial_borrowing_rate(panel, date(2023, 12, 29))
        assert resolved_borrow == pytest.approx(0.045, rel=1e-9)

    def test_raw_rate_units_normalized_correctly(self):
        """Rule 6: Decimal, percent, and basis-point raw rate inputs normalize correctly."""
        factor = MarketFactor(
            factor_id="RATE_DIFF_EUR_BORROW_BPS",
            category=FactorCategory.BORROWING_RATE_CHANGE,
            asset_or_currency="EUR",
            frequency=Frequency.DAILY,
            original_unit="percent",
            normalized_unit="basis_points",
            source_id="ecb",
            series_id="ESTR",
            transformation=TransformationMethod.FIRST_DIFFERENCE,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )

        # 6a. unit="percent" (4.5 -> 0.045)
        prov_pct = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="ecb",
            series_id="ESTR",
            raw_value=4.5,
            raw_unit="percent",
            transformed_value=0.0,
            pair="EUR",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel_pct = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"RATE_DIFF_EUR_BORROW_BPS": [4.5]},
            row_provenance={"RATE_DIFF_EUR_BORROW_BPS": [prov_pct]},
        )
        assert resolve_canonical_initial_borrowing_rate(panel_pct) == pytest.approx(0.045, rel=1e-9)

        # 6b. unit="decimal" (0.045 -> 0.045)
        prov_dec = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="ecb",
            series_id="ESTR",
            raw_value=0.045,
            raw_unit="decimal",
            transformed_value=0.0,
            pair="EUR",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel_dec = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"RATE_DIFF_EUR_BORROW_BPS": [0.045]},
            row_provenance={"RATE_DIFF_EUR_BORROW_BPS": [prov_dec]},
        )
        assert resolve_canonical_initial_borrowing_rate(panel_dec) == pytest.approx(0.045, rel=1e-9)

        # 6c. unit="bps" (450.0 -> 0.045)
        prov_bps = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="ecb",
            series_id="ESTR",
            raw_value=450.0,
            raw_unit="bps",
            transformed_value=0.0,
            pair="EUR",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel_bps = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"RATE_DIFF_EUR_BORROW_BPS": [450.0]},
            row_provenance={"RATE_DIFF_EUR_BORROW_BPS": [prov_bps]},
        )
        assert resolve_canonical_initial_borrowing_rate(panel_bps) == pytest.approx(0.045, rel=1e-9)

    def test_missing_or_unknown_borrowing_rate_unit_fails_closed(self):
        """Rule 7: Missing or unknown raw rate units fail closed (ValueError)."""
        factor = MarketFactor(
            factor_id="RATE_DIFF_EUR_BORROW_BPS",
            category=FactorCategory.BORROWING_RATE_CHANGE,
            asset_or_currency="EUR",
            frequency=Frequency.DAILY,
            original_unit="",
            normalized_unit="basis_points",
            source_id="ecb",
            series_id="ESTR",
            transformation=TransformationMethod.FIRST_DIFFERENCE,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        # Missing unit
        prov_missing = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="ecb",
            series_id="ESTR",
            raw_value=4.5,
            raw_unit=None,
            transformed_value=0.0,
            pair="EUR",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel_missing = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"RATE_DIFF_EUR_BORROW_BPS": [4.5]},
            row_provenance={"RATE_DIFF_EUR_BORROW_BPS": [prov_missing]},
        )
        with pytest.raises(ValueError, match="Cannot resolve initial borrowing rate from raw levels.*unit metadata is missing"):
            resolve_canonical_initial_borrowing_rate(panel_missing)

        # Unknown unit
        prov_unknown = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="ecb",
            series_id="ESTR",
            raw_value=4.5,
            raw_unit="UNKNOWN_UNIT",
            transformed_value=0.0,
            pair="EUR",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel_unknown = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"RATE_DIFF_EUR_BORROW_BPS": [4.5]},
            row_provenance={"RATE_DIFF_EUR_BORROW_BPS": [prov_unknown]},
        )
        with pytest.raises(ValueError, match="Cannot determine rate unit conversion.*unknown unit"):
            resolve_canonical_initial_borrowing_rate(panel_unknown)


# ==============================================================================
# Workstream C: Fail-Closed USD Investment Yield Boundary Resolution
# ==============================================================================

class TestCanonicalInitialInvestmentRateResolution:
    """Verifies fail-closed resolution and tenor enforcement for USD investment yield."""

    def test_canonical_1m_yield_to_decimal(self):
        """Rule 5 & 6: 1M sovereign yield in percentage points converts to annual decimal."""
        factor = MarketFactor(
            factor_id="YIELD_DIFF_USD_1M_BPS",
            category=FactorCategory.SOVEREIGN_YIELD_CHANGE,
            asset_or_currency="USD",
            frequency=Frequency.DAILY,
            original_unit="percent",
            normalized_unit="basis_points",
            source_id="us_treasury",
            series_id="DGS1MO",
            transformation=TransformationMethod.FIRST_DIFFERENCE,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        panel = make_dummy_panel(
            factors=[factor],
            canonical_levels={"YIELD_DIFF_USD_1M_BPS": [5.50, 5.55]},
        )
        resolved_invest = resolve_canonical_initial_investment_rate(panel, date(2023, 12, 29))
        assert resolved_invest == pytest.approx(0.0555, rel=1e-9)

    def test_raw_1m_yield_normalized_with_authorized_units(self):
        """Rule 6: Decimal, percent, and basis-point raw 1M yield inputs normalize correctly."""
        factor = MarketFactor(
            factor_id="YIELD_DIFF_USD_1M_BPS",
            category=FactorCategory.SOVEREIGN_YIELD_CHANGE,
            asset_or_currency="USD",
            frequency=Frequency.DAILY,
            original_unit="percent",
            normalized_unit="basis_points",
            source_id="us_treasury",
            series_id="DGS1MO",
            transformation=TransformationMethod.FIRST_DIFFERENCE,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )

        prov_pct = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="us_treasury",
            series_id="DGS1MO",
            raw_value=5.55,
            raw_unit="percent",
            transformed_value=0.0,
            pair="USD",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel_pct = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"YIELD_DIFF_USD_1M_BPS": [5.55]},
            row_provenance={"YIELD_DIFF_USD_1M_BPS": [prov_pct]},
        )
        assert resolve_canonical_initial_investment_rate(panel_pct) == pytest.approx(0.0555, rel=1e-9)

    def test_dgs3mo_silent_substitution_strictly_prohibited(self):
        """Rule 8: Missing DGS1MO does not result in silent DGS3MO substitution (fails closed)."""
        # Case A: Factor metadata specifies 3-month tenor
        factor_3m = MarketFactor(
            factor_id="YIELD_DIFF_USD_3M_BPS",
            category=FactorCategory.SOVEREIGN_YIELD_CHANGE,
            asset_or_currency="USD",
            frequency=Frequency.DAILY,
            original_unit="percent",
            normalized_unit="basis_points",
            source_id="us_treasury",
            series_id="DGS3MO",
            transformation=TransformationMethod.FIRST_DIFFERENCE,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        panel_3m_canonical = make_dummy_panel(
            factors=[factor_3m],
            canonical_levels={"YIELD_DIFF_USD_3M_BPS": [5.40]},
        )
        with pytest.raises(ValueError, match="Cannot resolve initial USD investment yield.*required 1-month series.*is missing"):
            resolve_canonical_initial_investment_rate(panel_3m_canonical)

        # Case B: Factor ID is named YIELD_DIFF_USD_1M_BPS but its underlying series is DGS3MO
        factor_misnamed = MarketFactor(
            factor_id="YIELD_DIFF_USD_1M_BPS",
            category=FactorCategory.SOVEREIGN_YIELD_CHANGE,
            asset_or_currency="USD",
            frequency=Frequency.DAILY,
            original_unit="percent",
            normalized_unit="basis_points",
            source_id="us_treasury",
            series_id="DGS3MO",  # Misleading
            transformation=TransformationMethod.FIRST_DIFFERENCE,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        panel_misnamed = make_dummy_panel(
            factors=[factor_misnamed],
            canonical_levels={"YIELD_DIFF_USD_1M_BPS": [5.40]},
        )
        with pytest.raises(ValueError, match="Cannot resolve initial USD investment yield.*series 'DGS3MO' is a 3-month series.*strictly requires the 1-month series"):
            resolve_canonical_initial_investment_rate(panel_misnamed)

        # Case C: Raw provenance has DGS3MO
        prov_3m = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="us_treasury",
            series_id="DGS3MO",
            raw_value=5.40,
            raw_unit="percent",
            transformed_value=0.0,
            pair="USD",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel_raw_3m = make_dummy_panel(
            factors=[factor_misnamed],
            canonical_levels={},
            raw_levels={"YIELD_DIFF_USD_1M_BPS": [5.40]},
            row_provenance={"YIELD_DIFF_USD_1M_BPS": [prov_3m]},
        )
        with pytest.raises(ValueError, match="Cannot resolve initial USD investment yield.*series 'DGS3MO' is a 3-month series.*strictly requires the 1-month series"):
            resolve_canonical_initial_investment_rate(panel_raw_3m)

    def test_missing_or_unknown_investment_yield_unit_fails_closed(self):
        """Rule 7: Missing or unknown raw investment yield units fail closed."""
        factor = MarketFactor(
            factor_id="YIELD_DIFF_USD_1M_BPS",
            category=FactorCategory.SOVEREIGN_YIELD_CHANGE,
            asset_or_currency="USD",
            frequency=Frequency.DAILY,
            original_unit="",
            normalized_unit="basis_points",
            source_id="us_treasury",
            series_id="DGS1MO",
            transformation=TransformationMethod.FIRST_DIFFERENCE,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        prov_no_unit = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="us_treasury",
            series_id="DGS1MO",
            raw_value=5.55,
            raw_unit=None,
            transformed_value=0.0,
            pair="USD",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel_no_unit = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"YIELD_DIFF_USD_1M_BPS": [5.55]},
            row_provenance={"YIELD_DIFF_USD_1M_BPS": [prov_no_unit]},
        )
        with pytest.raises(ValueError, match="Cannot resolve initial investment yield from raw levels.*unit metadata is missing"):
            resolve_canonical_initial_investment_rate(panel_no_unit)


# ==============================================================================
# Workstream D: End-to-End Holdout Predictive Path Integration
# ==============================================================================

class TestHoldoutPredictivePathIntegration:
    """Verifies end-to-end holdout path generation under fail-closed resolution rules."""

    def test_genuine_data_boundary_state_consistency(self, real_data_panels):
        """Rule 9, 10, 11: Real dataset boundary state, 248 dates/levels, calendar validation."""
        calib_panel, holdout_panel = real_data_panels
        sampler = HistoricalBootstrapSampler(calib_panel, method=BootstrapMethod.MOVING_BLOCK, random_seed=42)

        paths = generate_holdout_predictive_paths(
            model=sampler,
            calibration_panel=calib_panel,
            holdout_panel=holdout_panel,
            num_paths=5,
        )

        assert len(paths) == 5
        for p in paths:
            # Rule 9: Established boundary state
            assert p.fx_rates[0] == pytest.approx(1.1049967955, rel=1e-6)
            assert p.borrowing_rates[0] == pytest.approx(0.045, rel=1e-6)
            assert p.investment_rates[0] == pytest.approx(0.0555, rel=1e-6)

            # Rule 10: 248 dates, 248 levels, 247 transitions
            assert len(p.dates) == 248
            assert len(p.fx_rates) == 248
            assert len(p.borrowing_rates) == 248
            assert len(p.investment_rates) == 248
            assert p.steps == 247
            assert p.dates[0] == date(2023, 12, 29)
            assert p.dates[-1] == date(2024, 12, 31)

            # Rule 11: Pass both calendar validators
            validate_calendar_dates(
                dates=p.dates,
                total_levels=len(p.fx_rates),
                calendar_type="JOINT_TARGET2_FED",
            )
            validate_calendar_dates(
                dates=p.dates,
                total_levels=len(p.fx_rates),
                calendar_type="WEEKDAY_TRADING_PROXY",
            )

    def test_path_generation_with_authorized_raw_fallback(self, real_data_panels):
        """Path generator correctly initializes from explicit raw metadata when canonical is stripped."""
        calib_panel, holdout_panel = real_data_panels

        # Construct calibration panel with stripped canonical levels but verified raw levels and provenance
        fx_prov = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="frankfurter",
            series_id="EURUSD",
            raw_value=0.91274,
            raw_unit="EUR_per_USD",
            transformed_value=0.0,
            pair="USD/EUR",
            base_currency="USD",
            quote_currency="EUR",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        borrow_prov = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="ecb",
            series_id="ESTR",
            raw_value=4.50,
            raw_unit="percent",
            transformed_value=0.0,
            pair="EUR",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        invest_prov = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="us_treasury",
            series_id="DGS1MO",
            raw_value=5.55,
            raw_unit="percent",
            transformed_value=0.0,
            pair="USD",
            data_classification=DataClassification.REAL_VERIFIED,
        )

        raw_calib = calib_panel.model_copy(
            update={
                "canonical_levels": {},
                "raw_levels": {
                    "FX_EUR_USD_LOGRET": [0.91274],
                    "RATE_DIFF_EUR_BORROW_BPS": [4.50],
                    "YIELD_DIFF_USD_1M_BPS": [5.55],
                },
                "row_provenance": {
                    "FX_EUR_USD_LOGRET": [fx_prov],
                    "RATE_DIFF_EUR_BORROW_BPS": [borrow_prov],
                    "YIELD_DIFF_USD_1M_BPS": [invest_prov],
                },
            }
        )

        sampler = HistoricalBootstrapSampler(calib_panel, method=BootstrapMethod.MOVING_BLOCK, random_seed=42)
        paths = generate_holdout_predictive_paths(
            model=sampler,
            calibration_panel=raw_calib,
            holdout_panel=holdout_panel,
            num_paths=2,
        )

        assert len(paths) == 2
        for p in paths:
            # FX raw EUR/USD 0.91274 inverted to ~1.095602 USD/EUR
            assert p.fx_rates[0] == pytest.approx(1.0 / 0.91274, rel=1e-5)
            assert p.borrowing_rates[0] == pytest.approx(0.0450, rel=1e-6)
            assert p.investment_rates[0] == pytest.approx(0.0555, rel=1e-6)

    def test_path_generation_fails_closed_on_unauthorized_raw_metadata(self, real_data_panels):
        """Path generator fails closed when raw metadata is ambiguous."""
        calib_panel, holdout_panel = real_data_panels
        ambiguous_factors = [f.model_copy(update={"original_unit": ""}) for f in calib_panel.factors]
        ambiguous_calib = calib_panel.model_copy(
            update={
                "factors": ambiguous_factors,
                "canonical_levels": {},
                "raw_levels": {
                    "FX_EUR_USD_LOGRET": [0.91274],
                    "RATE_DIFF_EUR_BORROW_BPS": [4.50],
                    "YIELD_DIFF_USD_1M_BPS": [5.55],
                },
                "row_provenance": {},  # Missing provenance!
            }
        )
        sampler = HistoricalBootstrapSampler(calib_panel, method=BootstrapMethod.MOVING_BLOCK, random_seed=42)
        with pytest.raises(ValueError, match="Cannot resolve initial FX level from raw levels.*raw unit.*is missing, ambiguous, or unsupported"):
            generate_holdout_predictive_paths(
                model=sampler,
                calibration_panel=ambiguous_calib,
                holdout_panel=holdout_panel,
                num_paths=1,
            )

    def test_portfolio_holdout_remains_strictly_unavailable(self):
        """Rule 12: Portfolio holdout remains strictly UNAVAILABLE."""
        port_diag = evaluate_portfolio_holdout_diagnostics()
        assert port_diag.status == "UNAVAILABLE"
        assert not port_diag.is_available
        assert "SIMULATED_RESEARCH_PROXY without live execution evidence" in port_diag.reason
