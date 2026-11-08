"""Phase 4.1.2.2.3.4 Regression & Integrity Test Suite.

Validates:
1. Workstream A: Complete FX Metadata Coherence
   - Mutual consistency across base_currency, quote_currency, quote_convention, and raw unit.
   - Comprehensive combination matrix:
     * EUR/USD with QUOTE_PER_BASE and quote_per_base
     * USD/EUR with QUOTE_PER_BASE and quote_per_base
     * EUR/USD with BASE_PER_QUOTE and EUR_per_USD
     * USD/EUR with BASE_PER_QUOTE and USD_per_EUR
     * EUR/USD with QUOTE_PER_BASE and USD_per_EUR
     * USD/EUR with QUOTE_PER_BASE and EUR_per_USD
     * Contradictory combinations failing closed with descriptive ValueError
     * Generic quote_per_base with missing currencies failing closed with descriptive ValueError
     * Generic quote_per_base with contradictory quote_convention failing closed with descriptive ValueError
     * Generic base_per_quote with contradictory quote_convention failing closed with descriptive ValueError
     * Pair symbol contradicting explicit base/quote currencies failing closed with descriptive ValueError
     * Identical currencies rejection (base == quote)
     * Unsupported currency pair rejection when EUR/USD required
     * Valid raw fallback through resolve_canonical_initial_fx and _normalize_fx_quote_to_usd_per_eur
2. Workstream B: Numerical Correlation Policy & Finite Input Guarantees
   - Shared VARIANCE_DEGENERACY_THRESHOLD = 1e-12 preserved
   - Exact zero variance (sigma == 0.0): mathematically undefined correlation (NaN)
   - Below threshold (9.99e-13): near-zero variance, numerically unreliable correlation (NaN)
   - Exactly at threshold (1.00e-12): valid correlation
   - Safely above threshold (1.01e-12): valid correlation
   - Rejection of non-finite inputs (NaN, Inf) with ValueError in check_factor_variance and calibrate_factor_panel
   - No global warning suppression
3. Workstream C: Research Result Invariance Evidence & Lineage Reconciliation
   - Accurate sample count assertions (calibration: 989 transitions / 990 levels; holdout: 247 transitions / 248 levels)
   - Initial market levels (as of 2024-01-02T16:00:00Z: S_0 = 1.095602, r_b = 0.0450, r_i = 0.0557)
   - Holdout boundary initialization (as of 2023-12-29: S_0 = 1.104997, r_b = 0.0450, r_i = 0.0555)
   - Zero-difference invariance assertions against committed Phase 4.1.2.2.3 baseline artifacts
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
import warnings

import numpy as np
import pytest

from core.currency import (
    QuoteConvention,
    validate_and_normalize_fx_metadata,
)
from data.db.engine import make_engine, make_session_factory
from data.repository import Repository
from data.schemas import (
    DataClassification,
    DataObservation,
    Frequency,
    ObservationKind,
)
from simulation.monte_carlo.calibration import (
    VARIANCE_DEGENERACY_THRESHOLD,
    calibrate_factor_panel,
    check_factor_variance,
    split_calibration_holdout,
)
from simulation.monte_carlo.factors import (
    _normalize_fx_quote_to_usd_per_eur,
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
    yield calib_panel, holdout_panel, observations
    engine.dispose()


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
        aligned_level_count=len(ld),
        transition_count=len(d),
        first_level_date=ld[0],
        last_level_date=ld[-1],
        first_transition_date=d[0],
        last_transition_date=d[-1],
        calendar_name="TARGET2_USFED_JOINT",
        effective_sample_size=len(d),
        is_aligned=True,
    )


# =============================================================================
# Workstream A: Complete FX Metadata Coherence & Combination Matrix
# =============================================================================


class TestWorkstreamACompleteFXMetadataCoherence:
    """Test full combination matrix for mutual consistency across FX metadata fields."""

    def test_1_eur_usd_quote_per_base_with_quote_per_base_unit(self):
        """EUR/USD with QUOTE_PER_BASE and generic quote_per_base unit resolves canonically."""
        meta = validate_and_normalize_fx_metadata(
            base_currency="EUR",
            quote_currency="USD",
            quote_convention=QuoteConvention.QUOTE_PER_BASE,
            unit="quote_per_base",
            value=1.1050,
            require_eur_usd_pair=True,
        )
        assert meta.base_currency == "EUR"
        assert meta.quote_currency == "USD"
        assert meta.quote_convention == QuoteConvention.QUOTE_PER_BASE
        assert meta.unit == "quote_per_base"
        assert math.isclose(meta.canonical_usd_per_eur, 1.1050, rel_tol=1e-9)

    def test_2_usd_eur_quote_per_base_with_quote_per_base_unit(self):
        """USD/EUR with QUOTE_PER_BASE and generic quote_per_base unit inverts to canonical."""
        meta = validate_and_normalize_fx_metadata(
            base_currency="USD",
            quote_currency="EUR",
            quote_convention=QuoteConvention.QUOTE_PER_BASE,
            unit="quote_per_base",
            value=0.9050,
            require_eur_usd_pair=True,
        )
        assert meta.base_currency == "USD"
        assert meta.quote_currency == "EUR"
        assert meta.quote_convention == QuoteConvention.QUOTE_PER_BASE
        assert meta.unit == "quote_per_base"
        assert math.isclose(meta.canonical_usd_per_eur, 1.0 / 0.9050, rel_tol=1e-9)

    def test_3_eur_usd_base_per_quote_with_eur_per_usd_unit(self):
        """EUR/USD with BASE_PER_QUOTE and EUR_per_USD unit inverts to canonical."""
        meta = validate_and_normalize_fx_metadata(
            base_currency="EUR",
            quote_currency="USD",
            quote_convention=QuoteConvention.BASE_PER_QUOTE,
            unit="EUR_per_USD",
            value=0.9050,
            require_eur_usd_pair=True,
        )
        assert meta.base_currency == "EUR"
        assert meta.quote_currency == "USD"
        assert meta.quote_convention == QuoteConvention.BASE_PER_QUOTE
        assert meta.unit == "EUR_per_USD"
        assert math.isclose(meta.canonical_usd_per_eur, 1.0 / 0.9050, rel_tol=1e-9)

    def test_4_usd_eur_base_per_quote_with_usd_per_eur_unit(self):
        """USD/EUR with BASE_PER_QUOTE and USD_per_EUR unit resolves canonically as-is."""
        meta = validate_and_normalize_fx_metadata(
            base_currency="USD",
            quote_currency="EUR",
            quote_convention=QuoteConvention.BASE_PER_QUOTE,
            unit="USD_per_EUR",
            value=1.1050,
            require_eur_usd_pair=True,
        )
        assert meta.base_currency == "USD"
        assert meta.quote_currency == "EUR"
        assert meta.quote_convention == QuoteConvention.BASE_PER_QUOTE
        assert meta.unit == "USD_per_EUR"
        assert math.isclose(meta.canonical_usd_per_eur, 1.1050, rel_tol=1e-9)

    def test_5_eur_usd_quote_per_base_with_usd_per_eur_unit(self):
        """EUR/USD with QUOTE_PER_BASE and explicit USD_per_EUR unit resolves canonically."""
        meta = validate_and_normalize_fx_metadata(
            base_currency="EUR",
            quote_currency="USD",
            quote_convention=QuoteConvention.QUOTE_PER_BASE,
            unit="USD_per_EUR",
            value=1.1050,
            require_eur_usd_pair=True,
        )
        assert meta.base_currency == "EUR"
        assert meta.quote_currency == "USD"
        assert meta.quote_convention == QuoteConvention.QUOTE_PER_BASE
        assert meta.unit == "USD_per_EUR"
        assert math.isclose(meta.canonical_usd_per_eur, 1.1050, rel_tol=1e-9)

    def test_6_usd_eur_quote_per_base_with_eur_per_usd_unit(self):
        """USD/EUR with QUOTE_PER_BASE and explicit EUR_per_USD unit inverts to canonical."""
        meta = validate_and_normalize_fx_metadata(
            base_currency="USD",
            quote_currency="EUR",
            quote_convention=QuoteConvention.QUOTE_PER_BASE,
            unit="EUR_per_USD",
            value=0.9050,
            require_eur_usd_pair=True,
        )
        assert meta.base_currency == "USD"
        assert meta.quote_currency == "EUR"
        assert meta.quote_convention == QuoteConvention.QUOTE_PER_BASE
        assert meta.unit == "EUR_per_USD"
        assert math.isclose(meta.canonical_usd_per_eur, 1.0 / 0.9050, rel_tol=1e-9)

    def test_7_contradictory_combinations_fail_closed(self):
        """Contradictory combinations of explicit unit, currencies, and quote convention fail closed."""
        # 1. EUR/USD with QUOTE_PER_BASE but unit EUR_per_USD
        with pytest.raises(ValueError, match="contradicts base_currency='EUR' and quote_currency='USD'"):
            validate_and_normalize_fx_metadata(
                base_currency="EUR",
                quote_currency="USD",
                quote_convention=QuoteConvention.QUOTE_PER_BASE,
                unit="EUR_per_USD",
                value=0.91,
            )

        # 2. USD/EUR with QUOTE_PER_BASE but unit USD_per_EUR
        with pytest.raises(ValueError, match="contradicts base_currency='USD' and quote_currency='EUR'"):
            validate_and_normalize_fx_metadata(
                base_currency="USD",
                quote_currency="EUR",
                quote_convention=QuoteConvention.QUOTE_PER_BASE,
                unit="USD_per_EUR",
                value=1.10,
            )

        # 3. EUR/USD with BASE_PER_QUOTE but unit USD_per_EUR
        with pytest.raises(ValueError, match="contradicts base_currency='EUR' and quote_currency='USD'"):
            validate_and_normalize_fx_metadata(
                base_currency="EUR",
                quote_currency="USD",
                quote_convention=QuoteConvention.BASE_PER_QUOTE,
                unit="USD_per_EUR",
                value=1.10,
            )

        # 4. USD/EUR with BASE_PER_QUOTE but unit EUR_per_USD
        with pytest.raises(ValueError, match="contradicts base_currency='USD' and quote_currency='EUR'"):
            validate_and_normalize_fx_metadata(
                base_currency="USD",
                quote_currency="EUR",
                quote_convention=QuoteConvention.BASE_PER_QUOTE,
                unit="EUR_per_USD",
                value=0.91,
            )

    def test_8_generic_units_contradictions_and_missing_currencies(self):
        """Generic quote_per_base and base_per_quote enforce declared convention and fail on missing currencies."""
        # Contradictory generic quote_per_base under BASE_PER_QUOTE
        with pytest.raises(ValueError, match="generic unit 'quote_per_base' contradicts declared quote_convention"):
            validate_and_normalize_fx_metadata(
                base_currency="EUR",
                quote_currency="USD",
                quote_convention=QuoteConvention.BASE_PER_QUOTE,
                unit="quote_per_base",
            )

        # Contradictory generic base_per_quote under QUOTE_PER_BASE
        with pytest.raises(ValueError, match="generic unit 'base_per_quote' contradicts declared quote_convention"):
            validate_and_normalize_fx_metadata(
                base_currency="EUR",
                quote_currency="USD",
                quote_convention=QuoteConvention.QUOTE_PER_BASE,
                unit="base_per_quote",
            )

        # Missing quote currency with generic unit fails closed
        with pytest.raises(ValueError, match="missing base or quote currency metadata"):
            validate_and_normalize_fx_metadata(
                base_currency="EUR",
                quote_currency=None,
                quote_convention=QuoteConvention.QUOTE_PER_BASE,
                unit="quote_per_base",
            )

        # Missing base currency with generic unit fails closed
        with pytest.raises(ValueError, match="missing base or quote currency metadata"):
            validate_and_normalize_fx_metadata(
                base_currency=None,
                quote_currency="USD",
                quote_convention=QuoteConvention.QUOTE_PER_BASE,
                unit="quote_per_base",
            )

    def test_9_pair_symbol_contradicting_explicit_currencies(self):
        """Pair symbol contradicting explicit base/quote currencies raises descriptive ValueError."""
        with pytest.raises(ValueError, match="Contradictory FX pair metadata: pair 'EUR/USD' implies EUR/USD which contradicts"):
            validate_and_normalize_fx_metadata(
                base_currency="USD",
                quote_currency="EUR",
                quote_convention=QuoteConvention.QUOTE_PER_BASE,
                unit="EUR_per_USD",
                pair="EUR/USD",  # Explicit pair parameter contradicts base=USD, quote=EUR
            )

    def test_10_identical_currencies_rejection(self):
        """Identical base and quote currencies are rejected immediately."""
        with pytest.raises(ValueError, match="base_currency and quote_currency are identical"):
            validate_and_normalize_fx_metadata(
                base_currency="USD",
                quote_currency="USD",
                quote_convention=QuoteConvention.QUOTE_PER_BASE,
                unit="quote_per_base",
            )

    def test_11_unsupported_currency_pair_when_required(self):
        """Unsupported currency pair (e.g. GBP/USD) fails closed when require_eur_usd_pair=True."""
        with pytest.raises(ValueError, match="Contradictory FX currency metadata.*currencies"):
            validate_and_normalize_fx_metadata(
                base_currency="GBP",
                quote_currency="USD",
                quote_convention=QuoteConvention.QUOTE_PER_BASE,
                unit="USD_per_GBP",
                require_eur_usd_pair=True,
            )

    def test_12_data_observation_identical_semantics(self):
        """DataObservation enforces identical validation semantics through the shared helper."""
        # Valid EUR/USD
        obs_valid = DataObservation(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="frankfurter",
            entity_code="EUR/USD",
            value=1.1050,
            unit="quote_per_base",
            frequency=Frequency.DAILY,
            base_currency="EUR",
            quote_currency="USD",
            quote_convention=QuoteConvention.QUOTE_PER_BASE,
            observation_date=date(2023, 12, 29),
            retrieved_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        assert obs_valid.base_currency == "EUR"
        assert obs_valid.quote_currency == "USD"
        assert obs_valid.quote_convention == QuoteConvention.QUOTE_PER_BASE

        # Contradictory unit in DataObservation
        with pytest.raises(ValueError, match="contradicts base_currency='EUR' and quote_currency='USD'"):
            DataObservation(
                kind=ObservationKind.EXCHANGE_RATE,
                source_id="frankfurter",
                entity_code="EUR/USD",
                value=0.91,
                unit="EUR_per_USD",
                frequency=Frequency.DAILY,
                base_currency="EUR",
                quote_currency="USD",
                quote_convention=QuoteConvention.QUOTE_PER_BASE,
                observation_date=date(2023, 12, 29),
                retrieved_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )

    def test_13_normalize_fx_quote_identical_semantics(self):
        """_normalize_fx_quote_to_usd_per_eur delegates directly and enforces identical semantics."""
        obs = DataObservation(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="frankfurter",
            entity_code="EUR/USD",
            value=1.1050,
            unit="USD_per_EUR",
            frequency=Frequency.DAILY,
            base_currency="EUR",
            quote_currency="USD",
            quote_convention=QuoteConvention.QUOTE_PER_BASE,
            observation_date=date(2023, 12, 29),
            retrieved_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        canonical = _normalize_fx_quote_to_usd_per_eur(obs)
        assert math.isclose(canonical, 1.1050, rel_tol=1e-9)

    def test_14_raw_fallback_in_resolve_canonical_initial_fx(self):
        """resolve_canonical_initial_fx raw fallback validates through row provenance."""
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
            quote_convention="quote_per_base",
            data_classification=DataClassification.REAL_VERIFIED,
        )
        panel = make_dummy_panel(
            factors=[factor],
            canonical_levels={},
            raw_levels={"FX_EUR_USD_LOGRET": [1.1050]},
            row_provenance={"FX_EUR_USD_LOGRET": [prov]},
        )
        initial_fx = resolve_canonical_initial_fx(panel, date(2023, 12, 29))
        assert math.isclose(initial_fx, 1.1050, rel_tol=1e-9)


# =============================================================================
# Workstream B: Numerical Correlation Policy & Boundary Tests
# =============================================================================


class TestWorkstreamBNumericalCorrelationPolicy:
    """Test standard deviation boundary conditions (1e-12 threshold) and non-finite rejection."""

    def test_1_exact_zero_variance(self):
        """Exact zero variance (sigma == 0.0) is mathematically undefined (is_exact_zero=True)."""
        series = np.array([5.0, 5.0, 5.0, 5.0, 5.0], dtype=np.float64)
        std, is_exact, is_near = check_factor_variance(series, threshold=VARIANCE_DEGENERACY_THRESHOLD)
        assert std == 0.0
        assert is_exact is True
        assert is_near is False

    def test_2_near_zero_variance_immediately_below_threshold(self):
        """Standard deviation immediately below threshold (9.99e-13) is numerically unreliable (is_near_zero=True)."""
        base_val = 1.0
        delta = 9.99e-13
        series = np.array([base_val - delta, base_val, base_val + delta], dtype=np.float64)
        std, is_exact, is_near = check_factor_variance(series, threshold=VARIANCE_DEGENERACY_THRESHOLD)
        assert std < VARIANCE_DEGENERACY_THRESHOLD
        assert is_exact is False
        assert is_near is True

    def test_3_variance_exactly_at_threshold(self):
        """Standard deviation exactly at threshold (1.00e-12) is treated as valid non-degenerate correlation."""
        # Scale array to achieve exact sample standard deviation of 1.0e-12
        raw = np.array([-1.0, 0.0, 1.0], dtype=np.float64)
        raw_std = np.std(raw, ddof=1)
        target_series = raw * (VARIANCE_DEGENERACY_THRESHOLD / raw_std)
        std, is_exact, is_near = check_factor_variance(target_series, threshold=VARIANCE_DEGENERACY_THRESHOLD)
        assert math.isclose(std, VARIANCE_DEGENERACY_THRESHOLD, rel_tol=1e-12)
        assert is_exact is False
        assert is_near is False

    def test_4_variance_immediately_above_threshold(self):
        """Standard deviation immediately above threshold (1.01e-12) is treated as valid."""
        raw = np.array([-1.0, 0.0, 1.0], dtype=np.float64)
        raw_std = np.std(raw, ddof=1)
        target_series = raw * ((1.01 * VARIANCE_DEGENERACY_THRESHOLD) / raw_std)
        std, is_exact, is_near = check_factor_variance(target_series, threshold=VARIANCE_DEGENERACY_THRESHOLD)
        assert std >= VARIANCE_DEGENERACY_THRESHOLD
        assert is_exact is False
        assert is_near is False

    def test_5_reject_nan_in_check_factor_variance(self):
        """Non-finite inputs (NaN) raise ValueError in check_factor_variance."""
        series = np.array([1.0, np.nan, 2.0], dtype=np.float64)
        with pytest.raises(ValueError, match="Factor series contains non-finite values"):
            check_factor_variance(series)

    def test_6_reject_inf_in_check_factor_variance(self):
        """Non-finite inputs (Inf) raise ValueError in check_factor_variance."""
        series = np.array([1.0, np.inf, 2.0], dtype=np.float64)
        with pytest.raises(ValueError, match="Factor series contains non-finite values"):
            check_factor_variance(series)

    def test_7_reject_non_finite_in_calibrate_factor_panel(self):
        """Non-finite series in factor panel raises ValueError during calibration."""
        factor = MarketFactor(
            factor_id="F1",
            category=FactorCategory.FX_RETURN,
            asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY,
            original_unit="USD_per_EUR",
            normalized_unit="log_return",
            source_id="ecb",
            series_id="F1",
            transformation=TransformationMethod.LOG_RETURN,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        dates = [date(2023, 1, 1), date(2023, 1, 2), date(2023, 1, 3)]
        panel = FactorPanel(
            factors=[factor],
            dates=dates,
            level_dates=dates,
            values={"F1": [0.01, np.nan, 0.02]},
            raw_levels={},
            canonical_levels={},
            aligned_level_count=3,
            transition_count=3,
            first_level_date=dates[0],
            last_level_date=dates[-1],
            first_transition_date=dates[0],
            last_transition_date=dates[-1],
            calendar_name="JOINT",
            effective_sample_size=3,
            is_aligned=True,
        )
        with pytest.raises(ValueError, match="contains non-finite values"):
            calibrate_factor_panel(panel, min_observations=2)

    def test_8_no_global_warning_suppression(self):
        """Verify that global warning filters do not contain unconditional 'ignore' rules."""
        filters = warnings.filters
        global_ignores = [f for f in filters if f[0] == "ignore" and f[1] is None and f[2] is Warning]
        assert len(global_ignores) == 0, f"Found active global warning suppression filter: {global_ignores}"


# =============================================================================
# Workstream C: Research Result Invariance Evidence & Closure Reconciliation
# =============================================================================


class TestWorkstreamCResearchResultInvarianceEvidence:
    """Test zero-difference invariance against committed baseline research artifacts."""

    def test_1_reconcile_sample_counts(self, real_data_panels):
        """Reconcile calibration and holdout transition and level sample counts."""
        calib_panel, holdout_panel, _ = real_data_panels
        manifest_path = Path("data/results/phase_4_1_2_2_3/simulation_manifest.json")
        assert manifest_path.exists(), f"Baseline artifact missing: {manifest_path}"
        manifest = json.loads(manifest_path.read_bytes().decode("utf-8"))

        # Baseline calibration counts
        assert len(calib_panel.dates) == 989, f"Expected 989 calibration transition dates, got {len(calib_panel.dates)}"
        assert len(calib_panel.level_dates) == 990, f"Expected 990 calibration level dates, got {len(calib_panel.level_dates)}"
        assert calib_panel.first_level_date == date(2020, 1, 6)
        assert calib_panel.last_level_date == date(2023, 12, 29)
        assert calib_panel.first_transition_date == date(2020, 1, 7)
        assert calib_panel.last_transition_date == date(2023, 12, 29)

        # Baseline holdout counts
        assert len(holdout_panel.dates) == 247, f"Expected 247 holdout transition dates, got {len(holdout_panel.dates)}"
        assert len(holdout_panel.level_dates) == 248, f"Expected 248 holdout level dates, got {len(holdout_panel.level_dates)}"
        assert holdout_panel.first_level_date == date(2023, 12, 29)
        assert holdout_panel.last_level_date == date(2024, 12, 31)
        assert holdout_panel.first_transition_date == date(2024, 1, 2)
        assert holdout_panel.last_transition_date == date(2024, 12, 31)

        # Manifest reconciliation
        calib_window = manifest.get("calibration_window", {})
        assert calib_window.get("transition_count") == 989
        assert calib_window.get("aligned_level_count") == 990
        holdout_window = manifest.get("holdout_window", {})
        assert holdout_window.get("transition_count") == 247
        assert holdout_window.get("aligned_level_count") == 248

    def test_2_reconcile_initial_market_levels_vs_holdout_boundary(self, real_data_panels):
        """Verify distinction between grounded initial market levels (2024-01-02) and holdout boundary (2023-12-29)."""
        calib_panel, _, observations = real_data_panels
        manifest_path = Path("data/results/phase_4_1_2_2_3/simulation_manifest.json")
        manifest = json.loads(manifest_path.read_bytes().decode("utf-8"))

        # Grounded initial market levels as of decision timestamp 2024-01-02T16:00:00Z
        levels_report = resolve_initial_market_levels(
            observations=observations,
            as_of_decision_timestamp=datetime(2024, 1, 2, 16, 0, 0, tzinfo=timezone.utc),
            pit_mode=PITMode.ESTIMATED_LAG,
        )
        assert math.isclose(levels_report.initial_fx_rate, 1.095602, abs_tol=1e-6)
        assert math.isclose(levels_report.initial_borrowing_rate, 0.0450, abs_tol=1e-6)
        assert math.isclose(levels_report.initial_investment_rate, 0.0557, abs_tol=1e-6)

        # Holdout boundary initial levels from calibration panel as of 2023-12-29
        boundary_fx = resolve_canonical_initial_fx(calib_panel, date(2023, 12, 29))
        assert math.isclose(boundary_fx, 1.104997, abs_tol=1e-6)

        # Invariance against baseline manifest
        init_conds = manifest.get("initial_market_levels", {})
        assert math.isclose(levels_report.initial_fx_rate, init_conds.get("initial_fx_rate"), abs_tol=1e-9)
        assert math.isclose(levels_report.initial_borrowing_rate, init_conds.get("initial_borrowing_rate"), abs_tol=1e-9)
        assert math.isclose(levels_report.initial_investment_rate, init_conds.get("initial_investment_rate"), abs_tol=1e-9)

        holdout_init = manifest.get("holdout_predictive_initialization", {})
        assert math.isclose(boundary_fx, holdout_init.get("initial_fx_rate"), abs_tol=1e-9)

    def test_3_reconcile_covariance_and_correlation_matrices(self, real_data_panels):
        """Assert exact zero-difference numerical invariance for calibration covariance and correlation."""
        calib_panel, holdout_panel, obs = real_data_panels
        report = calibrate_factor_panel(calib_panel, holdout_panel, raw_observations=obs)

        calib_artifact_path = Path("data/results/phase_4_1_2_2_3/calibration_report.json")
        baseline = json.loads(calib_artifact_path.read_bytes().decode("utf-8"))

        curr_cov = np.array(report.covariance_matrix, dtype=np.float64)
        base_cov = np.array(baseline["covariance_matrix"], dtype=np.float64)
        cov_max_diff = float(np.max(np.abs(curr_cov - base_cov)))
        assert cov_max_diff <= 1e-9, f"Covariance matrix diff exceeds tolerance: {cov_max_diff:.2e}"

        curr_corr = np.array(report.correlation_matrix, dtype=np.float64)
        base_corr = np.array(baseline["correlation_matrix"], dtype=np.float64)
        corr_max_diff = float(np.max(np.abs(curr_corr - base_corr)))
        assert corr_max_diff <= 1e-9, f"Correlation matrix diff exceeds tolerance: {corr_max_diff:.2e}"

    def test_4_reconcile_holdout_correlation_shifts(self, real_data_panels):
        """Assert exact zero-difference numerical invariance for holdout correlation shifts."""
        calib_panel, holdout_panel, _ = real_data_panels
        diag = evaluate_factor_holdout_diagnostics(
            calibration_panel=calib_panel,
            holdout_panel=holdout_panel,
            predictive_paths=[],
        )

        diag_path = Path("data/results/phase_4_1_2_2_3/factor_holdout_diagnostics.json")
        baseline = json.loads(diag_path.read_bytes().decode("utf-8"))

        base_shifts = baseline["correlation_shifts"]
        for pair_key, base_val in base_shifts.items():
            curr_val = diag.correlation_shifts[pair_key]
            diff = abs(curr_val - base_val)
            assert diff <= 1e-9, f"Holdout correlation shift mismatch for {pair_key}: diff={diff:.2e}"

    def test_5_reconcile_portfolio_holdout_status(self):
        """Verify portfolio holdout status is strictly UNAVAILABLE."""
        diag = evaluate_portfolio_holdout_diagnostics()
        assert diag.status == "UNAVAILABLE"
        assert diag.is_available is False
        assert "SIMULATED_RESEARCH_PROXY" in diag.reason
        assert any("UNAVAILABLE" in note for note in diag.notes)
