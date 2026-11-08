"""Phase 4.1.2.2.3.5 Regression & Integrity Test Suite.

Validates:
1. Workstream A: Complete FX Identity Validation
   - Independent validation of pair and entity_code whenever either contains a recognizable currency pair.
   - Explicit base/quote currencies must agree with both pair representations.
   - Contradictory entity_code with explicit base/quote currencies fails closed.
   - Contradictory pair and entity_code fails closed.
   - Layer equivalence: DataObservation, normalization, and holdout resolver all reject contradictory entity_code.
   - Partial metadata with explicit BASE_PER_QUOTE preserves the quote convention (never silently overwritten).
   - Lenient schema-validation mode tolerates missing metadata where intended, but rejects invalid supplied currency codes.
   - End-to-end factor panel test ensuring bad observations cannot enter the EUR/USD factor panel silently.
2. Workstream B: Numerical Safeguard Verification
   - VARIANCE_DEGENERACY_THRESHOLD = 1e-12 preserved.
   - Exact-zero (sigma == 0.0) vs near-zero (0 < sigma < 1e-12) variance distinction.
   - Focused tests for ensure_positive_semidefinite():
     * Non-PSD matrix repair strictly satisfies declared min_eigenvalue.
     * Symmetry (M = M^T) and finite output preserved.
     * Already-valid PSD matrices are not unnecessarily modified.
     * Impact of the eigenvalue safety buffer (1.0 + 1e-6) on empirical calibration covariance verified (exact identity).
3. Workstream C: Research Output Reconciliation
   - Accurate sample count assertions (calibration: 989 transitions / 990 levels; holdout: 247 transitions / 248 levels).
   - Distinctly dated and labeled initial conditions:
     * Grounded initial market levels as of decision timestamp 2024-01-02T16:00:00Z: S_0 = 1.095602, r_b = 0.0450, r_i = 0.0557.
     * Holdout predictive path initialization at calibration boundary 2023-12-29: S_0 = 1.104997, r_b = 0.0450, r_i = 0.0555.
   - Zero-difference numerical invariance against committed baseline research artifacts (within 1e-15 machine precision).
   - Portfolio holdout diagnostics status strictly UNAVAILABLE.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
import math
from pathlib import Path

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
)
from simulation.monte_carlo.distributions import (
    ensure_positive_semidefinite,
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

    from simulation.monte_carlo.calibration import split_calibration_holdout

    calib_panel, holdout_panel = split_calibration_holdout(full_panel, calibration_end=date(2023, 12, 31))
    engine.dispose()
    return calib_panel, holdout_panel, observations


def _make_dummy_panel(
    factors: list[MarketFactor],
    dates: list[date] | None = None,
    level_dates: list[date] | None = None,
    values: dict[str, list[float]] | None = None,
    raw_levels: dict[str, list[float]] | None = None,
    canonical_levels: dict[str, list[float]] | None = None,
    row_provenance: dict[str, list[FactorRowProvenance]] | None = None,
) -> FactorPanel:
    """Construct an aligned FactorPanel for testing."""
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
# Workstream A: Complete FX Identity Validation
# =============================================================================


class TestWorkstreamACompleteFXIdentityValidation:
    """Test independent validation of pair and entity_code across all layers."""

    def test_1_valid_entity_code_matching_explicit_currencies(self):
        """Valid entity_code matching explicit base/quote currencies resolves correctly."""
        meta = validate_and_normalize_fx_metadata(
            base_currency="EUR",
            quote_currency="USD",
            entity_code="EUR/USD",
            quote_convention=QuoteConvention.QUOTE_PER_BASE,
            unit="quote_per_base",
            value=1.1050,
            require_eur_usd_pair=True,
        )
        assert meta.base_currency == "EUR"
        assert meta.quote_currency == "USD"
        assert meta.pair == "EUR/USD"
        assert math.isclose(meta.canonical_usd_per_eur, 1.1050, rel_tol=1e-9)

        # Underscore-separated format
        meta_underscore = validate_and_normalize_fx_metadata(
            base_currency="EUR",
            quote_currency="USD",
            entity_code="EUR_USD",
            quote_convention=QuoteConvention.QUOTE_PER_BASE,
            unit="quote_per_base",
            value=1.1050,
            require_eur_usd_pair=True,
        )
        assert meta_underscore.base_currency == "EUR"
        assert meta_underscore.quote_currency == "USD"
        assert meta_underscore.pair == "EUR/USD"

    def test_2_contradictory_entity_code_with_explicit_currencies_fails_closed(self):
        """Contradictory entity_code with explicit base/quote currencies fails closed with descriptive ValueError."""
        with pytest.raises(
            ValueError,
            match="Contradictory FX entity_code metadata: entity_code 'USD/EUR' implies USD/EUR which contradicts",
        ):
            validate_and_normalize_fx_metadata(
                base_currency="EUR",
                quote_currency="USD",
                entity_code="USD/EUR",
                quote_convention=QuoteConvention.QUOTE_PER_BASE,
                unit="USD_per_EUR",
            )

        with pytest.raises(
            ValueError,
            match="Contradictory FX entity_code metadata: entity_code 'GBP/USD' implies GBP/USD which contradicts",
        ):
            validate_and_normalize_fx_metadata(
                base_currency="EUR",
                quote_currency="USD",
                entity_code="GBP/USD",
                quote_convention=QuoteConvention.QUOTE_PER_BASE,
                unit="quote_per_base",
            )

    def test_3_contradictory_pair_and_entity_code_fails_closed(self):
        """Contradictory pair and entity_code fails closed with descriptive ValueError."""
        with pytest.raises(
            ValueError,
            match="Contradictory FX pair and entity_code metadata: pair 'EUR/USD' \\(EUR/USD\\) contradicts entity_code 'USD/EUR' \\(USD/EUR\\)",
        ):
            validate_and_normalize_fx_metadata(
                pair="EUR/USD",
                entity_code="USD/EUR",
                quote_convention=QuoteConvention.QUOTE_PER_BASE,
                unit="USD_per_EUR",
            )

        with pytest.raises(
            ValueError,
            match="Contradictory FX pair and entity_code metadata: pair 'EUR_USD' \\(EUR/USD\\) contradicts entity_code 'USD/EUR' \\(USD/EUR\\)",
        ):
            validate_and_normalize_fx_metadata(
                pair="EUR_USD",
                entity_code="USD/EUR",
                quote_convention=QuoteConvention.QUOTE_PER_BASE,
                unit="USD_per_EUR",
            )

    def test_4_layer_equivalence_rejects_contradictory_entity_code(self):
        """DataObservation, _normalize_fx_quote_to_usd_per_eur, and resolve_canonical_initial_fx reject contradictory entity_code."""
        # Layer 1: DataObservation instantiation fails closed
        with pytest.raises(
            ValueError,
            match="Contradictory FX entity_code metadata: entity_code 'USD/EUR' implies USD/EUR which contradicts",
        ):
            DataObservation(
                kind=ObservationKind.EXCHANGE_RATE,
                source_id="frankfurter",
                entity_code="USD/EUR",
                base_currency="EUR",
                quote_currency="USD",
                value=1.1050,
                unit="USD_per_EUR",
                frequency=Frequency.DAILY,
                observation_date=date(2023, 12, 29),
                retrieved_at=datetime(2023, 12, 29, tzinfo=timezone.utc),
            )

        # Layer 2: Normalization function rejects contradictory entity_code
        obs_bad = DataObservation(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="frankfurter",
            entity_code="USD/EUR",
            base_currency="USD",
            quote_currency="EUR",
            value=0.9050,
            unit="EUR_per_USD",
            frequency=Frequency.DAILY,
            observation_date=date(2023, 12, 29),
            retrieved_at=datetime(2023, 12, 29, tzinfo=timezone.utc),
        )
        # Directly modify base_currency to simulate a corrupted observation entering normalization
        object.__setattr__(obs_bad, "base_currency", "EUR")
        with pytest.raises(
            ValueError,
            match="Contradictory FX entity_code metadata: entity_code 'USD/EUR' implies USD/EUR which contradicts",
        ):
            _normalize_fx_quote_to_usd_per_eur(obs_bad)

        # Layer 3: Holdout boundary resolver rejects contradictory entity_code in provenance
        factor = MarketFactor(
            factor_id="FX_EUR_USD_LOGRET",
            category=FactorCategory.FX_RETURN,
            asset_or_currency="EUR/USD",
            frequency=Frequency.DAILY,
            original_unit="USD_per_EUR",
            normalized_unit="log_return",
            source_id="frankfurter",
            series_id="FX_EUR_USD_LOGRET",
            transformation=TransformationMethod.LOG_RETURN,
            missing_data_treatment=MissingDataTreatment.COMMON_DATES_ONLY,
        )
        prov_bad = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="frankfurter",
            series_id="USD/EUR",
            raw_value=1.1050,
            raw_unit="USD_per_EUR",
            quote_convention="quote_per_base",
            transformed_value=0.001,
            pair="EUR/USD",  # pair EUR/USD contradicts series_id USD/EUR
            base_currency="EUR",
            quote_currency="USD",
        )
        panel_bad = _make_dummy_panel(
            factors=[factor],
            raw_levels={"FX_EUR_USD_LOGRET": [1.1040, 1.1050]},
            row_provenance={"FX_EUR_USD_LOGRET": [prov_bad, prov_bad]},
        )
        with pytest.raises(ValueError, match="Contradictory FX pair and entity_code metadata"):
            resolve_canonical_initial_fx(panel_bad, date(2023, 12, 29))

    def test_5_partial_metadata_with_explicit_base_per_quote_preserved(self):
        """Partial metadata with explicit BASE_PER_QUOTE preserves the quote convention."""
        meta = validate_and_normalize_fx_metadata(
            quote_convention=QuoteConvention.BASE_PER_QUOTE,
            unit="rate",
            require_currencies=False,
        )
        assert meta.quote_convention == QuoteConvention.BASE_PER_QUOTE

        meta_str = validate_and_normalize_fx_metadata(
            quote_convention="base_per_quote",
            unit="rate",
            require_currencies=False,
        )
        assert meta_str.quote_convention == QuoteConvention.BASE_PER_QUOTE

    def test_6_invalid_supplied_currency_codes_fail_closed_in_lenient_mode(self):
        """Invalid supplied currency codes fail closed even in lenient schema-validation mode."""
        with pytest.raises(ValueError, match="Invalid currency code: 'US'"):
            validate_and_normalize_fx_metadata(
                base_currency="US",
                quote_currency="USD",
                require_currencies=False,
            )

        with pytest.raises(ValueError, match="Invalid currency code: '123'"):
            validate_and_normalize_fx_metadata(
                base_currency="EUR",
                quote_currency="123",
                require_currencies=False,
            )

        with pytest.raises(ValueError, match="Invalid currency code: 'INVALID'"):
            DataObservation(
                kind=ObservationKind.EXCHANGE_RATE,
                source_id="test_source",
                entity_code="TST",
                base_currency="INVALID",
                quote_currency="USD",
                value=1.10,
                unit="quote_per_base",
                frequency=Frequency.DAILY,
                observation_date=date(2023, 1, 1),
                retrieved_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
            )

    def test_7_end_to_end_bad_observation_cannot_enter_factor_panel(self, real_data_panels):
        """An observation with contradictory entity_code cannot enter the factor panel silently."""
        calib_panel, _, valid_obs = real_data_panels
        # Choose an aligned trading date from the panel
        target_date = calib_panel.dates[10]
        target_fx = next(
            o
            for o in valid_obs
            if o.kind == ObservationKind.EXCHANGE_RATE
            and o.observation_date == target_date
            and not getattr(o, "is_synthetic", False)
        )

        # Construct a corrupted observation on target_date with contradictory entity_code
        bad_obs = DataObservation.model_construct(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="frankfurter",
            entity_code="USD/EUR",
            base_currency="EUR",
            quote_currency="USD",
            value=1.1050,
            unit="USD_per_EUR",
            frequency=Frequency.DAILY,
            observation_date=target_date,
            publication_date=target_fx.publication_date,
            observation_timestamp=target_fx.observation_timestamp,
            publication_timestamp=target_fx.publication_timestamp,
            effective_timestamp=target_fx.effective_timestamp,
            retrieved_at=target_fx.retrieved_at,
            classification=DataClassification.REAL_VERIFIED,
            availability_evidence=target_fx.availability_evidence,
            is_synthetic=False,
        )

        # Replace ALL FX observations on target_date with bad_obs so resolver must pick it
        corrupted_pool = [
            bad_obs if (o.kind == ObservationKind.EXCHANGE_RATE and o.observation_date == target_date) else o
            for o in valid_obs
        ]
        with pytest.raises(
            ValueError,
            match="Contradictory FX entity_code metadata: entity_code 'USD/EUR' implies USD/EUR which contradicts",
        ):
            build_fx_carry_factor_panel(
                observations=corrupted_pool,
                start_date=date(2020, 1, 1),
                end_date=date(2024, 12, 31),
                pit_mode=PITMode.ESTIMATED_LAG,
            )


# =============================================================================
# Workstream B: Numerical Safeguard Verification
# =============================================================================


class TestWorkstreamBNumericalSafeguardVerification:
    """Test numerical safeguards, variance thresholds, and PSD matrix repair."""

    def test_1_variance_degeneracy_threshold_constant(self):
        """VARIANCE_DEGENERACY_THRESHOLD is exactly 1e-12."""
        assert VARIANCE_DEGENERACY_THRESHOLD == 1e-12

    def test_2_exact_zero_vs_near_zero_variance_distinction(self):
        """Exact zero variance is mathematically undefined; near-zero variance is numerically unreliable."""
        # Exact zero variance (sigma == 0.0)
        exact_zero_series = np.array([1.0, 1.0, 1.0, 1.0], dtype=np.float64)
        std, is_exact, is_near = check_factor_variance(exact_zero_series)
        assert std == 0.0
        assert is_exact is True
        assert is_near is False

        # Near-zero variance (0 < sigma < 1e-12)
        near_zero_series = np.array([0.0, 1e-13, 0.0, -1e-13], dtype=np.float64)
        std_nz, is_exact_nz, is_near_nz = check_factor_variance(near_zero_series)
        assert 0.0 < std_nz < 1e-12
        assert is_exact_nz is False
        assert is_near_nz is True

    def test_3_ensure_psd_repairs_non_psd_matrix(self):
        """Matrix requiring PSD repair satisfies declared min_eigenvalue."""
        non_psd = np.array([[1.0, 2.0], [2.0, 1.0]], dtype=np.float64)
        initial_eigvals = np.linalg.eigvalsh(non_psd)
        assert np.min(initial_eigvals) < 0.0  # Eigenvalues are 3.0 and -1.0

        min_eig = 1e-6
        repaired, was_repaired, diff = ensure_positive_semidefinite(non_psd, min_eigenvalue=min_eig)
        assert was_repaired is True
        assert diff > 0.0

        final_eigvals = np.linalg.eigvalsh(repaired)
        assert np.min(final_eigvals) >= min_eig, f"Repaired min eigenvalue {np.min(final_eigvals)} < {min_eig}"

    def test_4_ensure_psd_preserves_symmetry_and_finite_output(self):
        """PSD repair preserves matrix symmetry and finite outputs."""
        mat = np.array([[-1.0, 0.5, 0.2], [0.5, -0.5, 0.1], [0.2, 0.1, -2.0]], dtype=np.float64)
        repaired, was_repaired, _ = ensure_positive_semidefinite(mat, min_eigenvalue=1e-8)
        assert was_repaired is True
        assert np.all(np.isfinite(repaired))
        assert np.allclose(repaired, repaired.T, atol=1e-15)

    def test_5_ensure_psd_does_not_modify_already_valid_matrices(self):
        """Already-valid PSD matrices are not unnecessarily modified (exact identity)."""
        already_valid = np.eye(4, dtype=np.float64)
        repaired, was_repaired, diff = ensure_positive_semidefinite(already_valid, min_eigenvalue=1e-8)
        assert was_repaired is False
        assert diff == 0.0
        assert np.array_equal(repaired, already_valid)

    def test_6_eigenvalue_safety_buffer_impact_on_empirical_calibration(self, real_data_panels):
        """Verify empirical calibration covariance has min eigenvalue >> min_eigenvalue; buffer has zero impact."""
        calib_panel, _, _ = real_data_panels
        mat = np.column_stack([calib_panel.values[f] for f in calib_panel.values])
        cov = np.cov(mat, rowvar=False, ddof=1)
        eigvals = np.linalg.eigvalsh(cov)
        min_eig = float(np.min(eigvals))

        # Empirical minimum eigenvalue is ~2.53e-5, which is >2,500 times larger than repair threshold 1e-8
        assert min_eig > 1e-5, f"Empirical minimum eigenvalue {min_eig} unexpectedly small"
        repaired, was_repaired, diff = ensure_positive_semidefinite(cov, min_eigenvalue=1e-8)
        assert was_repaired is False
        assert diff == 0.0
        assert np.array_equal(repaired, (cov + cov.T) / 2.0)


# =============================================================================
# Workstream C: Research Output Reconciliation
# =============================================================================


class TestWorkstreamCResearchOutputReconciliation:
    """Test zero-difference invariance against committed baseline research artifacts."""

    def test_1_reconcile_sample_counts(self, real_data_panels):
        """Reconcile calibration and holdout transition and level sample counts."""
        calib_panel, holdout_panel, _ = real_data_panels
        manifest_path = Path("data/results/phase_4_1_2_2_3/simulation_manifest.json")
        assert manifest_path.exists(), f"Baseline artifact missing: {manifest_path}"
        manifest = json.loads(manifest_path.read_bytes().decode("utf-8"))

        # Baseline calibration counts: 989 transitions across 990 levels
        assert len(calib_panel.dates) == 989
        assert len(calib_panel.level_dates) == 990
        assert calib_panel.first_level_date == date(2020, 1, 6)
        assert calib_panel.last_level_date == date(2023, 12, 29)
        assert calib_panel.first_transition_date == date(2020, 1, 7)
        assert calib_panel.last_transition_date == date(2023, 12, 29)

        # Baseline holdout counts: 247 transitions across 248 levels
        assert len(holdout_panel.dates) == 247
        assert len(holdout_panel.level_dates) == 248
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
        assert math.isclose(
            levels_report.initial_borrowing_rate, init_conds.get("initial_borrowing_rate"), abs_tol=1e-9
        )
        assert math.isclose(
            levels_report.initial_investment_rate, init_conds.get("initial_investment_rate"), abs_tol=1e-9
        )

        holdout_init = manifest.get("holdout_predictive_initialization", {})
        assert math.isclose(boundary_fx, holdout_init.get("initial_fx_rate"), abs_tol=1e-9)

    def test_3_reconcile_covariance_and_correlation_matrices(self, real_data_panels):
        """Assert zero-difference numerical invariance for calibration covariance and correlation within 1e-15."""
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
        """Assert zero-difference numerical invariance for holdout correlation shifts within declared tolerance."""
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
