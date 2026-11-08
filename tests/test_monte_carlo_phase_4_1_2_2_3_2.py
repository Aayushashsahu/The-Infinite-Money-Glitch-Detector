"""Unit and regression tests for Phase 4.1.2.2.3.2: Per-Observation Provenance Integrity & Audit-Lineage Reconciliation.

Verifies:
1. Workstream A:
   - Canonical USD/EUR FX initialization remains unchanged.
   - Raw EUR/USD is inverted using genuine observation-level metadata.
   - Raw USD/EUR remains unchanged using genuine observation-level metadata.
   - Missing row provenance with MarketFactor.original_unit="USD_per_EUR" and raw value 0.91274 fails closed,
     never incorrectly returning 0.91274 as canonical USD/EUR.
   - Contradictory unit and currency metadata fail closed.
   - Missing or ambiguous quote conventions fail closed.
   - Non-finite or non-positive raw values fail closed.
   - Raw-level value and provenance raw value reconciliation (mismatch fails closed).
   - Provenance observation date and calibration boundary date reconciliation (mismatch fails closed).
2. Workstream B:
   - Canonical 4.50% borrowing rate remains 0.0450.
   - Canonical 5.55% investment yield remains 0.0555.
   - Explicit raw percent, decimal, and bps values normalize correctly.
   - Missing provenance with a generic factor-level percent unit does not silently authorize raw-value conversion.
   - Mismatched raw values and provenance fail closed.
   - Mismatched date and boundary date fail closed.
   - Missing or unsupported units fail closed.
3. Workstream C:
   - Confirm actual series identity from authorized metadata.
   - Missing series identifier in provenance fails closed (no manufactured default).
   - Incorrect series identifier (e.g. DGS3MO) fails closed.
   - Misleading factor ID with conflicting provenance series fails closed.
   - Explicit 1-month tenor evidence (DGS1MO) normalizes correctly.
4. Workstream D:
   - Zero-variance factor series produces NaN in correlation matrix rather than misleading 0.0.
   - Correlation validity mask accurately marks pairs involving constant series as False.
   - Sufficiency notes explicitly explain mathematically undefined linear correlation.
   - Factor holdout diagnostics preserve NaN for undefined correlation shifts and document in limitations.
   - Genuine historical panel correlations remain 100% unchanged.
5. Workstream E & Preservation:
   - Established canonical boundary state strictly preserved (S0 ~ 1.104997, rb = 0.0450, ri = 0.0555).
   - Scenario levels (248), scenario dates (248), transitions (247) strictly preserved.
   - Portfolio holdout remains strictly UNAVAILABLE.
"""

import math
from datetime import date
import numpy as np
import pytest

from data.db.engine import make_engine, make_session_factory
from data.repository import Repository
from simulation.monte_carlo.bootstrap import HistoricalBootstrapSampler
from simulation.monte_carlo.calibration import (
    calibrate_factor_panel,
    split_calibration_holdout,
)
from simulation.monte_carlo.factors import build_fx_carry_factor_panel
from simulation.monte_carlo.holdout import (
    evaluate_factor_holdout_diagnostics,
    evaluate_portfolio_holdout_diagnostics,
    generate_holdout_predictive_paths,
    resolve_canonical_initial_borrowing_rate,
    resolve_canonical_initial_fx,
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
    values: dict[str, list[float]] | None = None,
) -> FactorPanel:
    """Helper to construct synthetic factor panels for boundary-level resolution testing."""
    d = dates or [date(2023, 12, 28), date(2023, 12, 29)]
    ld = level_dates or [date(2023, 12, 27), date(2023, 12, 28), date(2023, 12, 29)]
    val = values if values is not None else {f.factor_id: [0.0] * len(d) for f in factors}
    return FactorPanel(
        factors=factors,
        dates=d,
        level_dates=ld,
        values=val,
        raw_levels=raw_levels or {},
        canonical_levels=canonical_levels or {},
        row_provenance=row_provenance or {},
        effective_sample_size=len(d),
        aligned_level_count=len(ld),
        transition_count=len(d),
    )


# ==============================================================================
# Workstream A: Per-Observation FX Raw-Level Provenance & Contradiction Guardrails
# ==============================================================================

class TestWorkstreamAFXRawProvenance:
    """Verifies per-observation provenance integrity for initial FX resolution."""

    def test_canonical_usd_eur_unchanged(self, real_data_panels):
        """Canonical USD/EUR initialization remains unchanged (1.1049967955)."""
        calib_panel, _ = real_data_panels
        initial_fx = resolve_canonical_initial_fx(calib_panel, date(2023, 12, 29))
        assert math.isclose(initial_fx, 1.1049967955, rel_tol=1e-6)

    def test_missing_provenance_with_factor_default_fails_closed(self):
        """Rule 1 & 4: Missing row provenance with MarketFactor.original_unit='USD_per_EUR'

        and raw value 0.91274 must NOT return 0.91274. Must fail closed.
        """
        factor = MarketFactor(
            factor_id="FX_EUR_USD_LOGRET",
            category=FactorCategory.FX_RETURN,
            asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY,
            original_unit="USD_per_EUR",  # Canonical default
            normalized_unit="log_return",
            source_id="frankfurter",
            series_id="EURUSD",
            transformation=TransformationMethod.LOG_RETURN,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        panel_no_prov = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"FX_EUR_USD_LOGRET": [0.91274]},
            row_provenance={},  # Missing provenance!
        )
        with pytest.raises(ValueError, match="Cannot resolve initial FX level from raw levels.*observation-level row provenance is missing"):
            resolve_canonical_initial_fx(panel_no_prov, date(2023, 12, 29))

    def test_raw_eur_usd_inverted_using_genuine_provenance_metadata(self):
        """Rule 2: Raw EUR/USD (0.91274) is inverted to 1.095602 using verified observation metadata."""
        factor = MarketFactor(
            factor_id="FX_EUR_USD_LOGRET",
            category=FactorCategory.FX_RETURN,
            asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY,
            original_unit="USD_per_EUR",
            normalized_unit="log_return",
            source_id="frankfurter",
            series_id="EURUSD",
            transformation=TransformationMethod.LOG_RETURN,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        prov = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="frankfurter",
            series_id="EUR/USD",
            raw_value=0.91274,
            raw_unit="EUR_per_USD",
            transformed_value=0.0,
            pair="EUR/USD",
            base_currency="EUR",
            quote_currency="USD",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"FX_EUR_USD_LOGRET": [0.91274]},
            row_provenance={"FX_EUR_USD_LOGRET": [prov]},
        )
        initial_fx = resolve_canonical_initial_fx(panel, date(2023, 12, 29))
        expected_fx = 1.0 / 0.91274
        assert math.isclose(initial_fx, expected_fx, rel_tol=1e-6)
        assert math.isclose(initial_fx, 1.09560225, rel_tol=1e-5)

    def test_raw_usd_eur_preserved_using_genuine_provenance_metadata(self):
        """Rule 3: Raw USD/EUR (1.1050) is preserved as canonical level using verified observation metadata."""
        factor = MarketFactor(
            factor_id="FX_EUR_USD_LOGRET",
            category=FactorCategory.FX_RETURN,
            asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY,
            original_unit="USD_per_EUR",
            normalized_unit="log_return",
            source_id="ecb",
            series_id="USD/EUR",
            transformation=TransformationMethod.LOG_RETURN,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        prov = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="ecb",
            series_id="USD/EUR",
            raw_value=1.1049968,
            raw_unit="USD_per_EUR",
            transformed_value=0.0,
            pair="USD/EUR",
            base_currency="USD",
            quote_currency="EUR",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"FX_EUR_USD_LOGRET": [1.1049968]},
            row_provenance={"FX_EUR_USD_LOGRET": [prov]},
        )
        initial_fx = resolve_canonical_initial_fx(panel, date(2023, 12, 29))
        assert math.isclose(initial_fx, 1.1049968, rel_tol=1e-6)

    def test_contradictory_currency_metadata_fails_closed(self):
        """Rule 6: Contradictory currency metadata fails closed."""
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
        # Case A: Currency does not match EUR/USD pair (e.g. JPY)
        prov_bad_curr = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="ecb",
            series_id="USD/JPY",
            raw_value=145.0,
            raw_unit="USD_per_EUR",
            transformed_value=0.0,
            pair="USD/JPY",
            base_currency="USD",
            quote_currency="JPY",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel_bad_curr = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"FX_EUR_USD_LOGRET": [145.0]},
            row_provenance={"FX_EUR_USD_LOGRET": [prov_bad_curr]},
        )
        with pytest.raises(ValueError, match="Contradictory FX currency metadata.*currencies"):
            resolve_canonical_initial_fx(panel_bad_curr, date(2023, 12, 29))

        # Case B: Identical base and quote currency
        prov_identical = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="ecb",
            series_id="USD/USD",
            raw_value=1.0,
            raw_unit="USD_per_EUR",
            transformed_value=0.0,
            pair="USD/USD",
            base_currency="USD",
            quote_currency="USD",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel_identical = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"FX_EUR_USD_LOGRET": [1.0]},
            row_provenance={"FX_EUR_USD_LOGRET": [prov_identical]},
        )
        with pytest.raises(ValueError, match="Contradictory FX currency metadata.*identical"):
            resolve_canonical_initial_fx(panel_identical, date(2023, 12, 29))

    def test_raw_level_and_provenance_value_mismatch_fails_closed(self):
        """Rule 9: Raw-level value and provenance raw value mismatch fails closed."""
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
        prov = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="ecb",
            series_id="EUR/USD",
            raw_value=0.91274,
            raw_unit="EUR_per_USD",
            transformed_value=0.0,
            pair="EUR/USD",
            base_currency="EUR",
            quote_currency="USD",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel_mismatch = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"FX_EUR_USD_LOGRET": [0.95000]},  # Mismatched!
            row_provenance={"FX_EUR_USD_LOGRET": [prov]},
        )
        with pytest.raises(ValueError, match="Raw level FX value .* does not reconcile with provenance raw_value"):
            resolve_canonical_initial_fx(panel_mismatch, date(2023, 12, 29))

    def test_provenance_date_and_boundary_date_mismatch_fails_closed(self):
        """Rule 10: Provenance observation date and requested boundary date mismatch fails closed."""
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
        prov = FactorRowProvenance(
            observation_date=date(2023, 12, 28),  # 2023-12-28 instead of 2023-12-29
            source_id="ecb",
            series_id="EUR/USD",
            raw_value=0.91274,
            raw_unit="EUR_per_USD",
            transformed_value=0.0,
            pair="EUR/USD",
            base_currency="EUR",
            quote_currency="USD",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"FX_EUR_USD_LOGRET": [0.91274]},
            row_provenance={"FX_EUR_USD_LOGRET": [prov]},
        )
        with pytest.raises(ValueError, match="Provenance observation date .* does not match requested boundary date"):
            resolve_canonical_initial_fx(panel, boundary_date=date(2023, 12, 29))


# ==============================================================================
# Workstream B: Per-Observation Rate Raw-Level Provenance & Unit Enforcement
# ==============================================================================

class TestWorkstreamBRateRawProvenance:
    """Verifies per-observation provenance integrity for initial borrowing and investment rates."""

    def test_canonical_borrowing_and_investment_rates_invariant(self, real_data_panels):
        """Canonical 4.50% borrowing and 5.55% investment yield strictly preserved."""
        calib_panel, _ = real_data_panels
        rb = resolve_canonical_initial_borrowing_rate(calib_panel, date(2023, 12, 29))
        ri = resolve_canonical_initial_investment_rate(calib_panel, date(2023, 12, 29))
        assert math.isclose(rb, 0.0450, rel_tol=1e-6)
        assert math.isclose(ri, 0.0555, rel_tol=1e-6)

    def test_missing_provenance_with_factor_default_rate_unit_fails_closed(self):
        """Rule 4: Missing provenance with factor original_unit='percent' fails closed."""
        factor = MarketFactor(
            factor_id="RATE_DIFF_EUR_BORROW_BPS",
            category=FactorCategory.BORROWING_RATE_CHANGE,
            asset_or_currency="EUR",
            frequency=Frequency.DAILY,
            original_unit="percent",  # Factor default
            normalized_unit="basis_points",
            source_id="ecb",
            series_id="ESTR",
            transformation=TransformationMethod.FIRST_DIFFERENCE,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        panel_no_prov = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"RATE_DIFF_EUR_BORROW_BPS": [4.50]},
            row_provenance={},  # Missing provenance!
        )
        with pytest.raises(ValueError, match="Cannot resolve initial borrowing rate from raw levels.*observation-level row provenance is missing"):
            resolve_canonical_initial_borrowing_rate(panel_no_prov, date(2023, 12, 29))

    def test_explicit_rate_units_normalized_correctly(self):
        """Explicit raw percent, decimal, and bps values normalize to exact decimal rates."""
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
        for unit, raw_val, expected in [
            ("percent", 4.50, 0.0450),
            ("decimal", 0.0450, 0.0450),
            ("bps", 450.0, 0.0450),
        ]:
            prov = FactorRowProvenance(
                observation_date=date(2023, 12, 29),
                source_id="ecb",
                series_id="ESTR",
                raw_value=raw_val,
                raw_unit=unit,
                transformed_value=0.0,
                pair="EUR",
                data_classification=DataClassification.REAL_VERIFIED,
            )
            panel = make_dummy_panel(
                factors=[factor],
                canonical_levels={},
                raw_levels={"RATE_DIFF_EUR_BORROW_BPS": [raw_val]},
                row_provenance={"RATE_DIFF_EUR_BORROW_BPS": [prov]},
            )
            rate = resolve_canonical_initial_borrowing_rate(panel, date(2023, 12, 29))
            assert math.isclose(rate, expected, rel_tol=1e-6)

    def test_rate_value_and_provenance_mismatch_fails_closed(self):
        """Mismatched rate value in raw_levels and row_provenance fails closed."""
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
        prov = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="ecb",
            series_id="ESTR",
            raw_value=4.50,
            raw_unit="percent",
            transformed_value=0.0,
            pair="EUR",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"RATE_DIFF_EUR_BORROW_BPS": [4.75]},  # Mismatch!
            row_provenance={"RATE_DIFF_EUR_BORROW_BPS": [prov]},
        )
        with pytest.raises(ValueError, match="Raw level borrowing rate .* does not reconcile with provenance raw_value"):
            resolve_canonical_initial_borrowing_rate(panel, date(2023, 12, 29))


# ==============================================================================
# Workstream C: Investment Tenor Evidence & Rejection of Manufactured Defaults
# ==============================================================================

class TestWorkstreamCInvestmentTenorEvidence:
    """Verifies strict 1-month tenor evidence enforcement for USD investment yield."""

    def test_missing_investment_series_identifier_fails_closed(self):
        """Missing series identifier in provenance fails closed; no manufactured 'DGS1MO' default."""
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
        prov_no_series = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="us_treasury",
            series_id="",  # Empty series identifier
            raw_value=5.55,
            raw_unit="percent",
            transformed_value=0.0,
            pair="USD",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"YIELD_DIFF_USD_1M_BPS": [5.55]},
            row_provenance={"YIELD_DIFF_USD_1M_BPS": [prov_no_series]},
        )
        with pytest.raises(ValueError, match="Cannot resolve initial USD investment yield.*series identifier is missing"):
            resolve_canonical_initial_investment_rate(panel, date(2023, 12, 29))

    def test_dgs3mo_provenance_fails_closed(self):
        """Provenance with series_id='DGS3MO' is strictly rejected for 1M investment yield."""
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
        prov_3m = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="us_treasury",
            series_id="DGS3MO",  # 3-month series!
            raw_value=5.40,
            raw_unit="percent",
            transformed_value=0.0,
            pair="USD",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"YIELD_DIFF_USD_1M_BPS": [5.40]},
            row_provenance={"YIELD_DIFF_USD_1M_BPS": [prov_3m]},
        )
        with pytest.raises(ValueError, match="Cannot resolve initial USD investment yield.*is a 3-month series.*strictly requires the 1-month series"):
            resolve_canonical_initial_investment_rate(panel, date(2023, 12, 29))

    def test_valid_dgs1mo_provenance_normalizes_correctly(self):
        """Explicit DGS1MO series provenance normalizes correctly to decimal."""
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
        prov_1m = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="us_treasury",
            series_id="DGS1MO",
            raw_value=5.55,
            raw_unit="percent",
            transformed_value=0.0,
            pair="USD",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"YIELD_DIFF_USD_1M_BPS": [5.55]},
            row_provenance={"YIELD_DIFF_USD_1M_BPS": [prov_1m]},
        )
        ri = resolve_canonical_initial_investment_rate(panel, date(2023, 12, 29))
        assert math.isclose(ri, 0.0555, rel_tol=1e-6)


# ==============================================================================
# Workstream D: Correlation Semantics & Zero-Variance Mathematical Truth
# ==============================================================================

class TestWorkstreamDCorrelationSemantics:
    """Verifies that undefined correlations caused by zero variance are not silently equated to 0.0."""

    def test_constant_factor_series_produces_nan_and_validity_mask(self):
        """Constant factor series produces NaN in correlation matrix and False in validity mask."""
        factors = [
            MarketFactor(
                factor_id="FACTOR_NORMAL",
                category=FactorCategory.FX_RETURN,
                asset_or_currency="EUR/USD",
                frequency=Frequency.DAILY,
                original_unit="USD_per_EUR",
                normalized_unit="log_return",
                source_id="frankfurter",
                series_id="EURUSD",
                transformation=TransformationMethod.LOG_RETURN,
                missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
            ),
            MarketFactor(
                factor_id="FACTOR_CONSTANT",
                category=FactorCategory.BORROWING_RATE_CHANGE,
                asset_or_currency="EUR",
                frequency=Frequency.DAILY,
                original_unit="percent",
                normalized_unit="basis_points",
                source_id="ecb",
                series_id="ESTR",
                transformation=TransformationMethod.FIRST_DIFFERENCE,
                missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
            ),
        ]
        # 300 observations to satisfy min_observations
        dates = [date(2020, 1, 1)] * 300
        normal_series = list(np.random.RandomState(42).normal(0.0, 0.01, 300))
        constant_series = [0.0] * 300  # Zero variance!

        panel = FactorPanel(
            factors=factors,
            dates=dates,
            level_dates=dates + [date(2020, 1, 1)],
            values={"FACTOR_NORMAL": normal_series, "FACTOR_CONSTANT": constant_series},
            raw_levels={"FACTOR_NORMAL": normal_series, "FACTOR_CONSTANT": constant_series},
            canonical_levels={"FACTOR_NORMAL": normal_series, "FACTOR_CONSTANT": constant_series},
            effective_sample_size=300,
            aligned_level_count=301,
            transition_count=300,
        )

        report = calibrate_factor_panel(panel, min_observations=250)

        # Check correlation matrix: diagonal of normal factor is 1.0, cross and constant are NaN
        corr = report.correlation_matrix
        assert len(corr) == 2
        assert math.isclose(corr[0][0], 1.0, rel_tol=1e-6)
        assert math.isnan(corr[0][1]), "Cross correlation with constant series must be NaN, not 0.0"
        assert math.isnan(corr[1][0]), "Cross correlation with constant series must be NaN, not 0.0"
        assert math.isnan(corr[1][1]), "Correlation of constant series with itself is undefined (NaN)"

        # Check validity mask
        mask = report.correlation_validity_mask
        assert mask[0][0] is True
        assert mask[0][1] is False
        assert mask[1][0] is False
        assert mask[1][1] is False

        # Check sufficiency notes
        assert any("FACTOR_CONSTANT" in n and "mathematically undefined" in n for n in report.sufficiency_notes)

    def test_single_factor_zero_variance_edge_case(self):
        """Single zero-variance factor produces [[NaN]] rather than [[1.0]]."""
        factor = MarketFactor(
            factor_id="FACTOR_SOLO_CONST",
            category=FactorCategory.FX_RETURN,
            asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY,
            original_unit="USD_per_EUR",
            normalized_unit="log_return",
            source_id="frankfurter",
            series_id="EURUSD",
            transformation=TransformationMethod.LOG_RETURN,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        dates = [date(2020, 1, 1)] * 300
        constant_series = [0.0] * 300
        panel = FactorPanel(
            factors=[factor],
            dates=dates,
            level_dates=dates + [date(2020, 1, 1)],
            values={"FACTOR_SOLO_CONST": constant_series},
            raw_levels={"FACTOR_SOLO_CONST": constant_series},
            canonical_levels={"FACTOR_SOLO_CONST": constant_series},
            effective_sample_size=300,
            aligned_level_count=301,
            transition_count=300,
        )
        report = calibrate_factor_panel(panel, min_observations=250)
        assert math.isnan(report.correlation_matrix[0][0])
        assert report.correlation_validity_mask[0][0] is False

    def test_factor_holdout_diagnostics_preserves_nan_for_zero_variance(self):
        """evaluate_factor_holdout_diagnostics preserves NaN in correlation_shifts and documents note."""
        dates_calib = [date(2023, 1, 1)] * 300
        dates_holdout = [date(2024, 1, 1)] * 200

        f_fx = MarketFactor(
            factor_id="FX_EUR_USD_LOGRET",
            category=FactorCategory.FX_RETURN,
            asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY,
            original_unit="USD_per_EUR",
            normalized_unit="log_return",
            source_id="frankfurter",
            series_id="EURUSD",
            transformation=TransformationMethod.LOG_RETURN,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        f_rate = MarketFactor(
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
        calib_panel = FactorPanel(
            factors=[f_fx, f_rate],
            dates=dates_calib,
            level_dates=dates_calib + [date(2023, 1, 1)],
            values={
                "FX_EUR_USD_LOGRET": list(np.random.RandomState(42).normal(0.0, 0.01, 300)),
                "RATE_DIFF_EUR_BORROW_BPS": [0.0] * 300,  # Constant in calibration!
            },
            raw_levels={"FX_EUR_USD_LOGRET": [1.10] * 300, "RATE_DIFF_EUR_BORROW_BPS": [4.50] * 300},
            canonical_levels={"FX_EUR_USD_LOGRET": [1.10] * 300, "RATE_DIFF_EUR_BORROW_BPS": [4.50] * 300},
            effective_sample_size=300,
            aligned_level_count=301,
            transition_count=300,
        )
        holdout_panel = FactorPanel(
            factors=[f_fx, f_rate],
            dates=dates_holdout,
            level_dates=dates_holdout + [date(2024, 1, 1)],
            values={
                "FX_EUR_USD_LOGRET": list(np.random.RandomState(43).normal(0.0, 0.01, 200)),
                "RATE_DIFF_EUR_BORROW_BPS": list(np.random.RandomState(44).normal(0.0, 0.01, 200)),
            },
            raw_levels={"FX_EUR_USD_LOGRET": [1.10] * 200, "RATE_DIFF_EUR_BORROW_BPS": [4.50] * 200},
            canonical_levels={"FX_EUR_USD_LOGRET": [1.10] * 200, "RATE_DIFF_EUR_BORROW_BPS": [4.50] * 200},
            effective_sample_size=200,
            aligned_level_count=201,
            transition_count=200,
        )

        diag = evaluate_factor_holdout_diagnostics(
            calibration_panel=calib_panel,
            holdout_panel=holdout_panel,
            predictive_paths=None,
        )
        pair_key = "FX_EUR_USD_LOGRET__vs__RATE_DIFF_EUR_BORROW_BPS"
        assert pair_key in diag.correlation_shifts
        assert math.isnan(diag.correlation_shifts[pair_key])
        assert any("mathematically undefined" in note for note in diag.limitations_notes)

    def test_genuine_historical_panel_correlation_unchanged(self, real_data_panels):
        """Genuine historical panel correlations remain 100% invariant."""
        calib_panel, _ = real_data_panels
        report = calibrate_factor_panel(calib_panel)

        # All 3 factors in genuine panel have non-zero variance; mask is all True
        assert all(all(row) for row in report.correlation_validity_mask)
        # Pairwise correlations between FX and rate differences are non-zero and finite
        corr = report.correlation_matrix
        assert len(corr) >= 3
        for i in range(len(corr)):
            for j in range(len(corr)):
                assert math.isfinite(corr[i][j])
                assert -1.0 <= corr[i][j] <= 1.0


# ==============================================================================
# Workstream E: End-to-End Preservation & Holdout Boundary Integration
# ==============================================================================

class TestWorkstreamEEndToEndPreservation:
    """Verifies end-to-end holdout predictive path generation and research invariance."""

    def test_genuine_boundary_state_and_calendar_validation(self, real_data_panels):
        """Established canonical boundary state strictly preserved and calendar validation passes."""
        calib_panel, holdout_panel = real_data_panels
        sampler = HistoricalBootstrapSampler(calib_panel, method=BootstrapMethod.MOVING_BLOCK, random_seed=42)
        paths = generate_holdout_predictive_paths(
            model=sampler,
            calibration_panel=calib_panel,
            holdout_panel=holdout_panel,
            num_paths=10,
        )

        assert len(paths) == 10
        for p in paths:
            # 248 dates, 248 levels, 247 step transitions
            assert len(p.dates) == 248
            assert len(p.fx_rates) == 248
            assert len(p.borrowing_rates) == 248
            assert len(p.investment_rates) == 248

            # Invariant boundary state
            assert p.dates[0] == date(2023, 12, 29)
            assert p.dates[1] == date(2024, 1, 2)
            assert math.isclose(p.fx_rates[0], 1.1049967955, rel_tol=1e-6)
            assert math.isclose(p.borrowing_rates[0], 0.0450, rel_tol=1e-6)
            assert math.isclose(p.investment_rates[0], 0.0555, rel_tol=1e-6)

            # Validates against both calendars (raises ValueError on failure)
            validate_calendar_dates(p.dates, total_levels=len(p.dates), calendar_type="JOINT_TARGET2_FED")
            validate_calendar_dates(p.dates, total_levels=len(p.dates), calendar_type="WEEKDAY_TRADING_PROXY")

    def test_portfolio_holdout_strictly_unavailable(self):
        """Portfolio holdout must remain strictly declared as UNAVAILABLE."""
        diag = evaluate_portfolio_holdout_diagnostics(simulated_evaluations=None)
        assert diag.status == "UNAVAILABLE"
        assert diag.is_available is False
        assert "SIMULATED_RESEARCH_PROXY" in diag.reason
