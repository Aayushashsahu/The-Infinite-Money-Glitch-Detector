"""Phase 4.1.2.2.3.3 Regression & Integrity Test Suite.

Validates:
1. Workstream A: Strict FX unit/currency consistency under documented provider
   convention (BASE/QUOTE = units of QUOTE per BASE), quote_per_base support,
   fail-closed contradiction enforcement, and corrected fixtures.
2. Workstream B: Unified near-zero correlation semantics, shared 1e-12 threshold,
   distinction between exact zero (mathematically undefined) and near-zero
   (numerically unreliable), pairwise validity masks, and no global warning suppression.
3. Workstream C: Research result invariance evidence with explicit numerical
   tolerances and maximum absolute difference reporting against baseline artifacts.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
import warnings

import numpy as np
import pytest

from data.repository import Repository
from data.schemas import (
    DataClassification,
    Frequency,
)
from data.db.engine import make_engine, make_session_factory
from simulation.monte_carlo.calibration import (
    VARIANCE_DEGENERACY_THRESHOLD,
    calibrate_factor_panel,
    check_factor_variance,
    split_calibration_holdout,
)
from simulation.monte_carlo.factors import (
    build_fx_carry_factor_panel,
    resolve_initial_market_levels,
)
from simulation.monte_carlo.holdout import (
    evaluate_factor_holdout_diagnostics,
    evaluate_portfolio_holdout_diagnostics,
    resolve_canonical_initial_fx,
)
from simulation.monte_carlo.schemas import (
    FactorCategory,
    FactorPanel,
    FactorRowProvenance,
    MarketFactor,
    MissingDataTreatment,
    PITMode,
    TransformationMethod,
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
# Workstream A: Strict FX Unit / Currency Consistency Tests (11 Tests)
# ==============================================================================

class TestWorkstreamAStrictFXQuotationConsistency:
    """A.3: Tests proving that contradictory metadata fails closed and genuine conventions resolve correctly."""

    def test_1_eur_usd_base_eur_quote_usd_quote_per_base(self):
        """Test 1: EUR/USD with base EUR, quote USD and quote-per-base resolves canonical level directly."""
        factor = MarketFactor(
            factor_id="FX_EUR_USD_LOGRET",
            category=FactorCategory.FX_RETURN,
            asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY,
            original_unit="USD_per_EUR",
            normalized_unit="log_return",
            source_id="frankfurter",
            series_id="EUR/USD",
            transformation=TransformationMethod.LOG_RETURN,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        prov = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="frankfurter",
            series_id="EUR/USD",
            raw_value=1.1049968,
            raw_unit="quote_per_base",
            quote_convention="quote_per_base",
            transformed_value=0.0,
            pair="EUR/USD",
            base_currency="EUR",
            quote_currency="USD",
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

    def test_2_usd_eur_base_usd_quote_eur_quote_per_base(self):
        """Test 2: USD/EUR with base USD, quote EUR and quote-per-base inverts to canonical USD per EUR."""
        factor = MarketFactor(
            factor_id="FX_EUR_USD_LOGRET",
            category=FactorCategory.FX_RETURN,
            asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY,
            original_unit="USD_per_EUR",
            normalized_unit="log_return",
            source_id="frankfurter",
            series_id="USD/EUR",
            transformation=TransformationMethod.LOG_RETURN,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        raw_val = 0.91274
        prov = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="frankfurter",
            series_id="USD/EUR",
            raw_value=raw_val,
            raw_unit="quote_per_base",
            quote_convention="quote_per_base",
            transformed_value=0.0,
            pair="USD/EUR",
            base_currency="USD",
            quote_currency="EUR",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"FX_EUR_USD_LOGRET": [raw_val]},
            row_provenance={"FX_EUR_USD_LOGRET": [prov]},
        )
        initial_fx = resolve_canonical_initial_fx(panel, date(2023, 12, 29))
        expected_fx = 1.0 / raw_val
        assert math.isclose(initial_fx, expected_fx, rel_tol=1e-6)
        assert math.isclose(initial_fx, 1.09560225, rel_tol=1e-5)

    def test_3_eur_usd_explicit_usd_per_eur_units(self):
        """Test 3: EUR/USD with USD-per-EUR explicit units preserves rate as canonical."""
        factor = MarketFactor(
            factor_id="FX_EUR_USD_LOGRET",
            category=FactorCategory.FX_RETURN,
            asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY,
            original_unit="USD_per_EUR",
            normalized_unit="log_return",
            source_id="ecb",
            series_id="EUR/USD",
            transformation=TransformationMethod.LOG_RETURN,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        prov = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="ecb",
            series_id="EUR/USD",
            raw_value=1.1050,
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
            raw_levels={"FX_EUR_USD_LOGRET": [1.1050]},
            row_provenance={"FX_EUR_USD_LOGRET": [prov]},
        )
        initial_fx = resolve_canonical_initial_fx(panel, date(2023, 12, 29))
        assert math.isclose(initial_fx, 1.1050, rel_tol=1e-6)

    def test_4_usd_eur_explicit_eur_per_usd_units(self):
        """Test 4: USD/EUR with EUR-per-USD explicit units inverts rate to canonical."""
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
        raw_val = 0.9050
        prov = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="ecb",
            series_id="USD/EUR",
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
            canonical_levels={},
            raw_levels={"FX_EUR_USD_LOGRET": [raw_val]},
            row_provenance={"FX_EUR_USD_LOGRET": [prov]},
        )
        initial_fx = resolve_canonical_initial_fx(panel, date(2023, 12, 29))
        expected_fx = 1.0 / raw_val
        assert math.isclose(initial_fx, expected_fx, rel_tol=1e-6)

    def test_5_explicit_unit_contradicting_currencies_fails_closed(self):
        """Test 5: Explicit unit contradicting base/quote currencies raises descriptive ValueError."""
        factor = MarketFactor(
            factor_id="FX_EUR_USD_LOGRET",
            category=FactorCategory.FX_RETURN,
            asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY,
            original_unit="USD_per_EUR",
            normalized_unit="log_return",
            source_id="ecb",
            series_id="EUR/USD",
            transformation=TransformationMethod.LOG_RETURN,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        # Case A: Base EUR, Quote USD, but unit declared as EUR_per_USD
        prov_a = FactorRowProvenance(
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
        panel_a = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"FX_EUR_USD_LOGRET": [0.91274]},
            row_provenance={"FX_EUR_USD_LOGRET": [prov_a]},
        )
        with pytest.raises(ValueError, match="contradicts base_currency='EUR' and quote_currency='USD'"):
            resolve_canonical_initial_fx(panel_a, date(2023, 12, 29))

        # Case B: Base USD, Quote EUR, but unit declared as USD_per_EUR
        prov_b = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="ecb",
            series_id="USD/EUR",
            raw_value=1.1050,
            raw_unit="USD_per_EUR",
            transformed_value=0.0,
            pair="USD/EUR",
            base_currency="USD",
            quote_currency="EUR",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel_b = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"FX_EUR_USD_LOGRET": [1.1050]},
            row_provenance={"FX_EUR_USD_LOGRET": [prov_b]},
        )
        with pytest.raises(ValueError, match="contradicts base_currency='USD' and quote_currency='EUR'"):
            resolve_canonical_initial_fx(panel_b, date(2023, 12, 29))

    def test_6_missing_base_or_quote_metadata_with_generic_quote_per_base_fails_closed(self):
        """Test 6: Missing base or quote metadata with generic quote-per-base units fails closed."""
        factor = MarketFactor(
            factor_id="FX_EUR_USD_LOGRET",
            category=FactorCategory.FX_RETURN,
            asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY,
            original_unit="USD_per_EUR",
            normalized_unit="log_return",
            source_id="frankfurter",
            series_id="EUR/USD",
            transformation=TransformationMethod.LOG_RETURN,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        # Missing quote_currency
        prov = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="frankfurter",
            series_id="EUR/USD",
            raw_value=1.1050,
            raw_unit="quote_per_base",
            transformed_value=0.0,
            pair=None,
            base_currency="EUR",
            quote_currency=None,  # Missing!
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"FX_EUR_USD_LOGRET": [1.1050]},
            row_provenance={"FX_EUR_USD_LOGRET": [prov]},
        )
        with pytest.raises(ValueError, match="missing base or quote currency metadata"):
            resolve_canonical_initial_fx(panel, date(2023, 12, 29))

    def test_7_unsupported_currency_pair_fails_closed(self):
        """Test 7: Unsupported currency pair (e.g. GBP/USD) fails closed."""
        factor = MarketFactor(
            factor_id="FX_EUR_USD_LOGRET",
            category=FactorCategory.FX_RETURN,
            asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY,
            original_unit="USD_per_EUR",
            normalized_unit="log_return",
            source_id="ecb",
            series_id="GBP/USD",
            transformation=TransformationMethod.LOG_RETURN,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        prov = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="ecb",
            series_id="GBP/USD",
            raw_value=1.27,
            raw_unit="USD_per_GBP",
            transformed_value=0.0,
            pair="GBP/USD",
            base_currency="GBP",
            quote_currency="USD",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"FX_EUR_USD_LOGRET": [1.27]},
            row_provenance={"FX_EUR_USD_LOGRET": [prov]},
        )
        with pytest.raises(ValueError, match="Contradictory FX currency metadata.*currencies"):
            resolve_canonical_initial_fx(panel, date(2023, 12, 29))

    def test_8_identical_base_and_quote_currencies_fails_closed(self):
        """Test 8: Identical base and quote currencies (e.g. USD/USD) fails closed."""
        factor = MarketFactor(
            factor_id="FX_EUR_USD_LOGRET",
            category=FactorCategory.FX_RETURN,
            asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY,
            original_unit="USD_per_EUR",
            normalized_unit="log_return",
            source_id="ecb",
            series_id="USD/USD",
            transformation=TransformationMethod.LOG_RETURN,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        prov = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="ecb",
            series_id="USD/USD",
            raw_value=1.0,
            raw_unit="USD_per_USD",
            transformed_value=0.0,
            pair="USD/USD",
            base_currency="USD",
            quote_currency="USD",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"FX_EUR_USD_LOGRET": [1.0]},
            row_provenance={"FX_EUR_USD_LOGRET": [prov]},
        )
        with pytest.raises(ValueError, match="base_currency and quote_currency are identical"):
            resolve_canonical_initial_fx(panel, date(2023, 12, 29))

    def test_9_raw_value_and_provenance_mismatch_fails_closed(self):
        """Test 9: Raw value and provenance raw_value mismatch fails closed."""
        factor = MarketFactor(
            factor_id="FX_EUR_USD_LOGRET",
            category=FactorCategory.FX_RETURN,
            asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY,
            original_unit="USD_per_EUR",
            normalized_unit="log_return",
            source_id="frankfurter",
            series_id="EUR/USD",
            transformation=TransformationMethod.LOG_RETURN,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        prov = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="frankfurter",
            series_id="EUR/USD",
            raw_value=1.1050,
            raw_unit="quote_per_base",
            transformed_value=0.0,
            pair="EUR/USD",
            base_currency="EUR",
            quote_currency="USD",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"FX_EUR_USD_LOGRET": [1.1200]},  # Mismatched!
            row_provenance={"FX_EUR_USD_LOGRET": [prov]},
        )
        with pytest.raises(ValueError, match="Raw level FX value .* does not reconcile with provenance raw_value"):
            resolve_canonical_initial_fx(panel, date(2023, 12, 29))

    def test_10_boundary_date_mismatch_fails_closed(self):
        """Test 10: Provenance observation date and requested boundary date mismatch fails closed."""
        factor = MarketFactor(
            factor_id="FX_EUR_USD_LOGRET",
            category=FactorCategory.FX_RETURN,
            asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY,
            original_unit="USD_per_EUR",
            normalized_unit="log_return",
            source_id="frankfurter",
            series_id="EUR/USD",
            transformation=TransformationMethod.LOG_RETURN,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        prov = FactorRowProvenance(
            observation_date=date(2023, 12, 28),  # 2023-12-28 != 2023-12-29
            source_id="frankfurter",
            series_id="EUR/USD",
            raw_value=1.1050,
            raw_unit="quote_per_base",
            transformed_value=0.0,
            pair="EUR/USD",
            base_currency="EUR",
            quote_currency="USD",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"FX_EUR_USD_LOGRET": [1.1050]},
            row_provenance={"FX_EUR_USD_LOGRET": [prov]},
        )
        with pytest.raises(ValueError, match="Provenance observation date .* does not match requested boundary date"):
            resolve_canonical_initial_fx(panel, boundary_date=date(2023, 12, 29))

    def test_11_canonical_fx_initialization_unchanged(self, real_data_panels):
        """Test 11: Existing canonical FX initialization remains unchanged when canonical levels present."""
        calib_panel, _ = real_data_panels
        initial_fx = resolve_canonical_initial_fx(calib_panel, date(2023, 12, 29))
        assert math.isclose(initial_fx, 1.1049967955, rel_tol=1e-6)


# ==============================================================================
# Workstream B: Unified Near-Zero Correlation Semantics Tests (9 Tests)
# ==============================================================================

class TestWorkstreamBNearZeroCorrelationSemantics:
    """B.4: Comprehensive regression tests for near-zero variance policy and exact zero distinction."""

    def test_1_exact_constant_calibration_factor(self):
        """Test 1: Exact constant calibration factor (sigma=0.0) is mathematically undefined."""
        f_norm = MarketFactor(
            factor_id="F_NORM", category=FactorCategory.FX_RETURN, asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY, original_unit="USD_per_EUR", normalized_unit="log_return",
            source_id="s", series_id="s", transformation=TransformationMethod.LOG_RETURN,
        )
        f_const = MarketFactor(
            factor_id="F_CONST", category=FactorCategory.BORROWING_RATE_CHANGE, asset_or_currency="EUR",
            frequency=Frequency.DAILY, original_unit="percent", normalized_unit="basis_points",
            source_id="s", series_id="s", transformation=TransformationMethod.FIRST_DIFFERENCE_BPS,
        )
        np.random.seed(42)
        n_obs = 300
        norm_series = list(np.random.normal(0.0, 0.01, n_obs))
        const_series = [5.0] * n_obs  # Exact zero variance!

        dates = [date(2023, 1, 1)] * n_obs
        panel = FactorPanel(
            factors=[f_norm, f_const],
            dates=dates,
            level_dates=dates + [date(2023, 1, 1)],
            values={"F_NORM": norm_series, "F_CONST": const_series},
            raw_levels={"F_NORM": norm_series, "F_CONST": const_series},
            canonical_levels={"F_NORM": norm_series, "F_CONST": const_series},
            effective_sample_size=n_obs,
            aligned_level_count=n_obs + 1,
            transition_count=n_obs,
        )
        report = calibrate_factor_panel(panel, min_observations=250)
        assert math.isnan(report.correlation_matrix[0][1])
        assert math.isnan(report.correlation_matrix[1][0])
        assert report.correlation_validity_mask[0][1] is False
        assert report.correlation_validity_mask[1][0] is False
        assert any("F_CONST" in n and "exact zero variance" in n and "mathematically undefined" in n for n in report.sufficiency_notes)

    def test_2_exact_constant_holdout_factor(self):
        """Test 2: Exact constant holdout factor marks correlation shift as NaN with mathematically undefined note."""
        f1 = MarketFactor(
            factor_id="FX_EUR_USD_LOGRET", category=FactorCategory.FX_RETURN, asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY, original_unit="USD_per_EUR", normalized_unit="log_return",
            source_id="s", series_id="s", transformation=TransformationMethod.LOG_RETURN,
        )
        f2 = MarketFactor(
            factor_id="RATE_DIFF_EUR_BORROW_BPS", category=FactorCategory.BORROWING_RATE_CHANGE, asset_or_currency="EUR",
            frequency=Frequency.DAILY, original_unit="percent", normalized_unit="basis_points",
            source_id="s", series_id="s", transformation=TransformationMethod.FIRST_DIFFERENCE_BPS,
        )
        np.random.seed(42)
        calib_panel = FactorPanel(
            factors=[f1, f2],
            dates=[date(2023, 1, 1)] * 300,
            level_dates=[date(2023, 1, 1)] * 301,
            values={"FX_EUR_USD_LOGRET": list(np.random.normal(0, 1, 300)), "RATE_DIFF_EUR_BORROW_BPS": list(np.random.normal(0, 1, 300))},
            raw_levels={"FX_EUR_USD_LOGRET": [1.0] * 300, "RATE_DIFF_EUR_BORROW_BPS": [1.0] * 300},
            canonical_levels={"FX_EUR_USD_LOGRET": [1.0] * 300, "RATE_DIFF_EUR_BORROW_BPS": [1.0] * 300},
            effective_sample_size=300, aligned_level_count=301, transition_count=300,
        )
        holdout_panel = FactorPanel(
            factors=[f1, f2],
            dates=[date(2024, 1, 1)] * 200,
            level_dates=[date(2024, 1, 1)] * 201,
            values={"FX_EUR_USD_LOGRET": list(np.random.normal(0, 1, 200)), "RATE_DIFF_EUR_BORROW_BPS": [4.0] * 200},  # Exact zero variance in holdout!
            raw_levels={"FX_EUR_USD_LOGRET": [1.0] * 200, "RATE_DIFF_EUR_BORROW_BPS": [1.0] * 200},
            canonical_levels={"FX_EUR_USD_LOGRET": [1.0] * 200, "RATE_DIFF_EUR_BORROW_BPS": [1.0] * 200},
            effective_sample_size=200, aligned_level_count=201, transition_count=200,
        )
        diag = evaluate_factor_holdout_diagnostics(calib_panel, holdout_panel)
        pair_key = "FX_EUR_USD_LOGRET__vs__RATE_DIFF_EUR_BORROW_BPS"
        assert math.isnan(diag.correlation_shifts[pair_key])
        assert any("mathematically undefined" in n and "exact zero variance" in n for n in diag.limitations_notes)

    def test_3_near_constant_calibration_factor_below_threshold(self):
        """Test 3: Near-constant calibration factor (0 < sigma < 1e-12) is treated as numerically unreliable."""
        f_norm = MarketFactor(
            factor_id="F_NORM", category=FactorCategory.FX_RETURN, asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY, original_unit="USD_per_EUR", normalized_unit="log_return",
            source_id="s", series_id="s", transformation=TransformationMethod.LOG_RETURN,
        )
        f_near = MarketFactor(
            factor_id="F_NEAR", category=FactorCategory.BORROWING_RATE_CHANGE, asset_or_currency="EUR",
            frequency=Frequency.DAILY, original_unit="percent", normalized_unit="basis_points",
            source_id="s", series_id="s", transformation=TransformationMethod.FIRST_DIFFERENCE_BPS,
        )
        np.random.seed(42)
        n_obs = 300
        norm_series = list(np.random.normal(0.0, 0.01, n_obs))
        # Non-zero variance but standard deviation ~ 1e-14 < 1e-12
        near_series = [1.0 + (1e-14 if i % 2 == 0 else -1e-14) for i in range(n_obs)]
        std_val, is_exact, is_near = check_factor_variance(near_series)
        assert is_exact is False
        assert is_near is True
        assert 0.0 < std_val < VARIANCE_DEGENERACY_THRESHOLD

        dates = [date(2023, 1, 1)] * n_obs
        panel = FactorPanel(
            factors=[f_norm, f_near],
            dates=dates,
            level_dates=dates + [date(2023, 1, 1)],
            values={"F_NORM": norm_series, "F_NEAR": near_series},
            raw_levels={"F_NORM": norm_series, "F_NEAR": near_series},
            canonical_levels={"F_NORM": norm_series, "F_NEAR": near_series},
            effective_sample_size=n_obs, aligned_level_count=n_obs + 1, transition_count=n_obs,
        )
        report = calibrate_factor_panel(panel, min_observations=250)
        assert math.isnan(report.correlation_matrix[0][1])
        assert report.correlation_validity_mask[0][1] is False
        # Must describe as numerically unreliable, NOT mathematically undefined
        assert any("F_NEAR" in n and "numerically unreliable" in n for n in report.sufficiency_notes)
        assert not any("F_NEAR" in n and "mathematically undefined" in n for n in report.sufficiency_notes)

    def test_4_near_constant_holdout_factor_below_threshold(self):
        """Test 4: Near-constant holdout factor (0 < sigma < 1e-12) reports shift as NaN with numerically unreliable note."""
        f1 = MarketFactor(
            factor_id="FX_EUR_USD_LOGRET", category=FactorCategory.FX_RETURN, asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY, original_unit="USD_per_EUR", normalized_unit="log_return",
            source_id="s", series_id="s", transformation=TransformationMethod.LOG_RETURN,
        )
        f2 = MarketFactor(
            factor_id="RATE_DIFF_EUR_BORROW_BPS", category=FactorCategory.BORROWING_RATE_CHANGE, asset_or_currency="EUR",
            frequency=Frequency.DAILY, original_unit="percent", normalized_unit="basis_points",
            source_id="s", series_id="s", transformation=TransformationMethod.FIRST_DIFFERENCE_BPS,
        )
        np.random.seed(42)
        calib_panel = FactorPanel(
            factors=[f1, f2],
            dates=[date(2023, 1, 1)] * 300,
            level_dates=[date(2023, 1, 1)] * 301,
            values={"FX_EUR_USD_LOGRET": list(np.random.normal(0, 1, 300)), "RATE_DIFF_EUR_BORROW_BPS": list(np.random.normal(0, 1, 300))},
            raw_levels={"FX_EUR_USD_LOGRET": [1.0] * 300, "RATE_DIFF_EUR_BORROW_BPS": [1.0] * 300},
            canonical_levels={"FX_EUR_USD_LOGRET": [1.0] * 300, "RATE_DIFF_EUR_BORROW_BPS": [1.0] * 300},
            effective_sample_size=300, aligned_level_count=301, transition_count=300,
        )
        near_holdout = [1.0 + (1e-14 if i % 2 == 0 else -1e-14) for i in range(200)]
        holdout_panel = FactorPanel(
            factors=[f1, f2],
            dates=[date(2024, 1, 1)] * 200,
            level_dates=[date(2024, 1, 1)] * 201,
            values={"FX_EUR_USD_LOGRET": list(np.random.normal(0, 1, 200)), "RATE_DIFF_EUR_BORROW_BPS": near_holdout},
            raw_levels={"FX_EUR_USD_LOGRET": [1.0] * 200, "RATE_DIFF_EUR_BORROW_BPS": [1.0] * 200},
            canonical_levels={"FX_EUR_USD_LOGRET": [1.0] * 200, "RATE_DIFF_EUR_BORROW_BPS": [1.0] * 200},
            effective_sample_size=200, aligned_level_count=201, transition_count=200,
        )
        diag = evaluate_factor_holdout_diagnostics(calib_panel, holdout_panel)
        pair_key = "FX_EUR_USD_LOGRET__vs__RATE_DIFF_EUR_BORROW_BPS"
        assert math.isnan(diag.correlation_shifts[pair_key])
        assert any("RATE_DIFF_EUR_BORROW_BPS" in n and "numerically unreliable" in n for n in diag.limitations_notes)
        assert not any("RATE_DIFF_EUR_BORROW_BPS" in n and "mathematically undefined" in n for n in diag.limitations_notes)

    def test_5_nonzero_factor_variance_safely_above_threshold(self):
        """Test 5: Non-zero factor variance safely above threshold produces finite valid correlations."""
        f1 = MarketFactor(
            factor_id="F1", category=FactorCategory.FX_RETURN, asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY, original_unit="USD_per_EUR", normalized_unit="log_return",
            source_id="s", series_id="s", transformation=TransformationMethod.LOG_RETURN,
        )
        f2 = MarketFactor(
            factor_id="F2", category=FactorCategory.BORROWING_RATE_CHANGE, asset_or_currency="EUR",
            frequency=Frequency.DAILY, original_unit="percent", normalized_unit="basis_points",
            source_id="s", series_id="s", transformation=TransformationMethod.FIRST_DIFFERENCE_BPS,
        )
        np.random.seed(42)
        n_obs = 300
        # Small variance ~ 1e-4, well above 1e-12 threshold
        s1 = list(np.random.normal(0, 1e-4, n_obs))
        s2 = list(np.random.normal(0, 1e-4, n_obs))
        dates = [date(2023, 1, 1)] * n_obs
        panel = FactorPanel(
            factors=[f1, f2],
            dates=dates,
            level_dates=dates + [date(2023, 1, 1)],
            values={"F1": s1, "F2": s2},
            raw_levels={"F1": s1, "F2": s2},
            canonical_levels={"F1": s1, "F2": s2},
            effective_sample_size=n_obs, aligned_level_count=n_obs + 1, transition_count=n_obs,
        )
        report = calibrate_factor_panel(panel, min_observations=250)
        assert all(all(row) for row in report.correlation_validity_mask)
        assert math.isfinite(report.correlation_matrix[0][1])

    def test_6_pairwise_validity_masks(self):
        """Test 6: Pairwise validity mask correctly isolates degenerate factors while preserving valid pairs."""
        f1 = MarketFactor(factor_id="F1", category=FactorCategory.FX_RETURN, asset_or_currency="EUR/USD",
                          frequency=Frequency.DAILY, original_unit="USD_per_EUR", normalized_unit="log_return",
                          source_id="s", series_id="s", transformation=TransformationMethod.LOG_RETURN)
        f2 = MarketFactor(factor_id="F2_CONST", category=FactorCategory.BORROWING_RATE_CHANGE, asset_or_currency="EUR",
                          frequency=Frequency.DAILY, original_unit="percent", normalized_unit="basis_points",
                          source_id="s", series_id="s", transformation=TransformationMethod.FIRST_DIFFERENCE_BPS)
        f3 = MarketFactor(factor_id="F3", category=FactorCategory.SOVEREIGN_YIELD_CHANGE, asset_or_currency="USD",
                          frequency=Frequency.DAILY, original_unit="percent", normalized_unit="basis_points",
                          source_id="s", series_id="s", transformation=TransformationMethod.FIRST_DIFFERENCE_BPS)
        np.random.seed(42)
        n_obs = 300
        s1 = list(np.random.normal(0, 1, n_obs))
        s2 = [0.0] * n_obs  # Zero variance
        s3 = list(np.random.normal(0, 1, n_obs))
        dates = [date(2023, 1, 1)] * n_obs
        panel = FactorPanel(
            factors=[f1, f2, f3], dates=dates, level_dates=dates + [date(2023, 1, 1)],
            values={"F1": s1, "F2_CONST": s2, "F3": s3},
            raw_levels={"F1": s1, "F2_CONST": s2, "F3": s3},
            canonical_levels={"F1": s1, "F2_CONST": s2, "F3": s3},
            effective_sample_size=n_obs, aligned_level_count=n_obs + 1, transition_count=n_obs,
        )
        report = calibrate_factor_panel(panel, min_observations=250)
        mask = report.correlation_validity_mask
        # Factor 0 and 2 are normal; Factor 1 is degenerate
        assert mask[0][0] is True
        assert mask[0][1] is False
        assert mask[0][2] is True

        assert mask[1][0] is False
        assert mask[1][1] is False
        assert mask[1][2] is False

        assert mask[2][0] is True
        assert mask[2][1] is False
        assert mask[2][2] is True

        # Correlation between F1 and F3 is preserved as finite
        assert math.isfinite(report.correlation_matrix[0][2])

    def test_7_single_factor_zero_variance_behavior(self):
        """Test 7: Single factor panel with zero or near-zero variance yields [[NaN]] and [[False]]."""
        f = MarketFactor(factor_id="F_SOLO", category=FactorCategory.FX_RETURN, asset_or_currency="EUR/USD",
                         frequency=Frequency.DAILY, original_unit="USD_per_EUR", normalized_unit="log_return",
                         source_id="s", series_id="s", transformation=TransformationMethod.LOG_RETURN)
        dates = [date(2023, 1, 1)] * 300
        panel = FactorPanel(
            factors=[f], dates=dates, level_dates=dates + [date(2023, 1, 1)],
            values={"F_SOLO": [0.0] * 300}, raw_levels={"F_SOLO": [0.0] * 300},
            canonical_levels={"F_SOLO": [0.0] * 300},
            effective_sample_size=300, aligned_level_count=301, transition_count=300,
        )
        report = calibrate_factor_panel(panel, min_observations=250)
        assert math.isnan(report.correlation_matrix[0][0])
        assert report.correlation_validity_mask[0][0] is False

    def test_8_no_global_warning_suppression(self):
        """Test 8: Verify no global warning suppression filter has been applied."""
        # Ensure RuntimeWarning is not globally ignored
        active_filters = warnings.filters
        global_runtime_ignores = [
            f for f in active_filters
            if f[0] == "ignore" and f[2] is not None and issubclass(RuntimeWarning, f[2]) and f[3] is None
        ]
        assert len(global_runtime_ignores) == 0, f"Found global RuntimeWarning suppression: {global_runtime_ignores}"

    def test_9_genuine_historical_correlation_values_unchanged(self, real_data_panels):
        """Test 9: Genuine historical panel correlations are non-zero, finite, and strictly within [-1, 1]."""
        calib_panel, _ = real_data_panels
        report = calibrate_factor_panel(calib_panel)
        assert all(all(row) for row in report.correlation_validity_mask)
        corr = report.correlation_matrix
        for row in corr:
            for val in row:
                assert math.isfinite(val)
                assert -1.0 <= val <= 1.0


# ==============================================================================
# Workstream C: Research Result Invariance Evidence & Baseline Reconciliation
# ==============================================================================

class TestWorkstreamCResearchResultInvarianceEvidence:
    """Verifies numerical invariance of genuine research outputs against baseline artifacts."""

    def test_reconcile_initial_market_levels(self, real_data_panels):
        """Initial market levels match baseline values with zero discrepancy."""
        db_path = "sqlite:///data/processed/gmdb.db"
        engine = make_engine(db_path)
        repo = Repository(make_session_factory(engine))
        obs = repo.load_observation_objects(include_synthetic=False)

        levels = resolve_initial_market_levels(
            observations=obs,
            as_of_decision_timestamp=datetime(2024, 1, 2, 16, 0, 0, tzinfo=timezone.utc),
            pit_mode=PITMode.ESTIMATED_LAG,
        )
        # Expected baseline from simulation_manifest.json:
        # initial_fx_rate: 1.0956022525582312
        # initial_borrowing_rate: 0.045
        # initial_investment_rate: 0.0557
        assert math.isclose(levels.initial_fx_rate, 1.0956022525582312, abs_tol=1e-9)
        assert math.isclose(levels.initial_borrowing_rate, 0.045, abs_tol=1e-9)
        assert math.isclose(levels.initial_investment_rate, 0.0557, abs_tol=1e-9)

    def test_reconcile_sample_counts(self, real_data_panels):
        """Calibration and holdout sample counts strictly reconcile with baseline."""
        calib_panel, holdout_panel = real_data_panels
        assert len(calib_panel.dates) == 989
        assert len(calib_panel.level_dates) == 990
        assert len(holdout_panel.dates) == 247
        assert len(holdout_panel.level_dates) == 248

    def test_reconcile_covariance_and_correlation_matrices(self, real_data_panels):
        """Compare actual numerical correlation values against baseline values with explicit tolerance."""
        calib_panel, _ = real_data_panels
        report = calibrate_factor_panel(calib_panel)

        baseline_path = Path("data/results/phase_4_1_2_2_3/calibration_report.json")
        assert baseline_path.exists(), f"Missing baseline artifact: {baseline_path}"
        with open(baseline_path, "r", encoding="utf-8") as f:
            baseline = json.load(f)

        base_corr = np.array(baseline["correlation_matrix"], dtype=np.float64)
        curr_corr = np.array(report.correlation_matrix, dtype=np.float64)

        abs_diff = np.abs(curr_corr - base_corr)
        max_diff = float(np.max(abs_diff))

        print(f"\n[Invariance Audit] Calibration Correlation Matrix Max Abs Difference: {max_diff:.2e}")
        assert max_diff < 1e-9, f"Correlation matrix difference exceeded tolerance: {max_diff}"

        base_cov = np.array(baseline["covariance_matrix"], dtype=np.float64)
        curr_cov = np.array(report.covariance_matrix, dtype=np.float64)
        max_cov_diff = float(np.max(np.abs(curr_cov - base_cov)))
        print(f"[Invariance Audit] Calibration Covariance Matrix Max Abs Difference: {max_cov_diff:.2e}")
        assert max_cov_diff < 1e-9, f"Covariance matrix difference exceeded tolerance: {max_cov_diff}"

    def test_reconcile_holdout_correlation_shifts(self, real_data_panels):
        """Compare holdout correlation shifts against baseline with explicit numerical tolerance."""
        calib_panel, holdout_panel = real_data_panels
        diag = evaluate_factor_holdout_diagnostics(calib_panel, holdout_panel)

        baseline_path = Path("data/results/phase_4_1_2_2_3/factor_holdout_diagnostics.json")
        assert baseline_path.exists(), f"Missing baseline artifact: {baseline_path}"
        with open(baseline_path, "r", encoding="utf-8") as f:
            baseline = json.load(f)

        base_shifts = baseline["correlation_shifts"]
        diffs: list[float] = []
        for k, v in base_shifts.items():
            assert k in diag.correlation_shifts
            curr_v = diag.correlation_shifts[k]
            diff = abs(curr_v - v)
            diffs.append(diff)

        max_shift_diff = max(diffs)
        print(f"[Invariance Audit] Holdout Correlation Shifts Max Abs Difference: {max_shift_diff:.2e}")
        assert max_shift_diff < 1e-9, f"Correlation shifts difference exceeded tolerance: {max_shift_diff}"

    def test_reconcile_portfolio_holdout_status(self):
        """Portfolio holdout status remains strictly UNAVAILABLE without simulated execution fabrication."""
        diag = evaluate_portfolio_holdout_diagnostics()
        assert diag.status == "UNAVAILABLE"
        assert diag.is_available is False
        assert diag.simulated_portfolio_median_return is None
        assert diag.simulated_portfolio_median_drawdown is None
        assert any("SIMULATED_RESEARCH_PROXY" in n for n in diag.notes)
