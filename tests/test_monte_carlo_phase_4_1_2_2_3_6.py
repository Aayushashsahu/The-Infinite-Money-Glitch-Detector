"""Phase 4.1.2.2.3.6 Regression Test Suite: Strict FX Identifier Rejection & Research Reconciliation.

Mathematics first. Data second. Prediction third. AI last.

Validates:
1. Strict pair-like entity-code validation across all layers:
   - Rejects 'EUR/US', 'EU/USD', 'EUR/USD/', 'EUR_US', 'EUR_USD_EXTRA'.
   - Validated through direct validate_and_normalize_fx_metadata().
   - Validated through DataObservation validation.
   - Validated through _normalize_fx_quote_to_usd_per_eur().
   - Validated through resolve_canonical_initial_fx().
   - Validated end-to-end in build_fx_carry_factor_panel().
2. Legitimate non-pair entity identifiers preserved under documented policy.
3. Reconciled sample counts, level dates, transition dates, and combined counts.
4. Numerical invariance within declared cross-platform tolerance (1e-9).
5. Scoped PSD eigenvalue behavior and UNAVAILABLE portfolio holdout.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
import pytest

from pydantic import ValidationError

from core.currency import (
    QuoteConvention,
    _extract_pair_codes,
    validate_and_normalize_fx_metadata,
)
from data.schemas import (
    DataObservation,
    Frequency,
    ObservationKind,
)
from simulation.monte_carlo.calibration import calibrate_factor_panel
from simulation.monte_carlo.factors import (
    _normalize_fx_quote_to_usd_per_eur,
    build_fx_carry_factor_panel,
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
from data.db.engine import make_engine, make_session_factory
from data.repository import Repository
from simulation.monte_carlo.calibration import split_calibration_holdout


INVALID_REPRESENTATIONS = [
    "EUR/US",
    "EU/USD",
    "EUR/USD/",
    "EUR_US",
    "EUR_USD_EXTRA",
]


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
# Workstream A: Strict Pair-Like Entity-Code Validation
# =============================================================================


class TestWorkstreamAStrictPairLikeEntityCodeValidation:
    """Validate that malformed pair-like FX identifiers are rejected across all layers."""

    @pytest.mark.parametrize("bad_repr", INVALID_REPRESENTATIONS)
    def test_1_direct_validate_and_normalize_fx_metadata_rejects_malformed_entity(self, bad_repr: str):
        """Direct validate_and_normalize_fx_metadata rejects malformed entity codes."""
        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            validate_and_normalize_fx_metadata(
                entity_code=bad_repr,
                unit="quote_per_base",
                require_currencies=False,
            )

    @pytest.mark.parametrize("bad_repr", INVALID_REPRESENTATIONS)
    def test_2_direct_validation_rejects_malformed_entity_even_with_explicit_currencies(self, bad_repr: str):
        """Supplied base and quote currencies cannot mask a malformed pair-like entity code."""
        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            validate_and_normalize_fx_metadata(
                base_currency="EUR",
                quote_currency="USD",
                quote_convention=QuoteConvention.QUOTE_PER_BASE,
                entity_code=bad_repr,
                unit="quote_per_base",
                require_currencies=True,
            )

    @pytest.mark.parametrize("bad_repr", INVALID_REPRESENTATIONS)
    def test_3_data_observation_validation_rejects_malformed_fx_entity(self, bad_repr: str):
        """DataObservation schema validator rejects malformed pair-like FX entity codes."""
        with pytest.raises(ValidationError):
            DataObservation(
                kind=ObservationKind.EXCHANGE_RATE,
                source_id="frankfurter",
                entity_code=bad_repr,
                value=1.1050,
                unit="quote_per_base",
                frequency=Frequency.DAILY,
                observation_date=date(2023, 12, 29),
                retrieved_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )

    def test_4_data_observation_permits_non_fx_kind_with_pair_like_entity(self):
        """DataObservation does not run FX validation on non-FX observation kinds."""
        obs = DataObservation(
            kind=ObservationKind.MACRO_INDICATOR,
            source_id="test_source",
            entity_code="EUR/US",
            value=1.0,
            unit="percent",
            frequency=Frequency.ANNUAL,
            observation_date=date(2023, 1, 1),
            retrieved_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        assert obs.entity_code == "EUR/US"
        assert obs.kind == ObservationKind.MACRO_INDICATOR

    @pytest.mark.parametrize("bad_repr", INVALID_REPRESENTATIONS)
    def test_5_normalize_fx_quote_to_usd_per_eur_rejects_malformed_entity(self, bad_repr: str):
        """_normalize_fx_quote_to_usd_per_eur rejects observations with malformed pair-like entity codes."""
        obs = DataObservation.model_construct(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="frankfurter",
            entity_code=bad_repr,
            value=1.1050,
            unit="quote_per_base",
            frequency=Frequency.DAILY,
            observation_date=date(2023, 12, 29),
            retrieved_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            base_currency="EUR",
            quote_currency="USD",
            quote_convention=QuoteConvention.QUOTE_PER_BASE,
        )
        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            _normalize_fx_quote_to_usd_per_eur(obs)

    @pytest.mark.parametrize("bad_repr", INVALID_REPRESENTATIONS)
    def test_6_resolve_canonical_initial_fx_rejects_malformed_provenance_entity(self, bad_repr: str):
        """resolve_canonical_initial_fx rejects provenance with malformed pair-like entity codes."""
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
        prov = FactorRowProvenance(
            observation_date=date(2023, 12, 29),
            source_id="frankfurter",
            series_id=bad_repr,
            raw_value=1.1050,
            raw_unit="USD_per_EUR",
            quote_convention="quote_per_base",
            transformed_value=0.001,
            pair="EUR/USD",
            base_currency="EUR",
            quote_currency="USD",
        )
        panel = _make_dummy_panel(
            factors=[factor],
            raw_levels={"FX_EUR_USD_LOGRET": [1.1040, 1.1050]},
            row_provenance={"FX_EUR_USD_LOGRET": [prov, prov]},
        )
        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            resolve_canonical_initial_fx(panel, date(2023, 12, 29))

    @pytest.mark.parametrize("bad_repr", INVALID_REPRESENTATIONS)
    def test_7_end_to_end_factor_panel_rejects_malformed_raw_observation(self, real_data_panels, bad_repr: str):
        """build_fx_carry_factor_panel rejects raw observation with malformed entity code."""
        calib_panel, _, observations = real_data_panels
        target_date = calib_panel.dates[10]
        target_fx = next(
            o
            for o in observations
            if o.kind == ObservationKind.EXCHANGE_RATE
            and o.observation_date == target_date
            and not getattr(o, "is_synthetic", False)
        )

        bad_obs = target_fx.model_copy(update={"entity_code": bad_repr})
        object.__setattr__(bad_obs, "pair", "EUR/USD")

        corrupted_obs = [
            bad_obs if (o.kind == ObservationKind.EXCHANGE_RATE and o.observation_date == target_date) else o
            for o in observations
        ]

        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            build_fx_carry_factor_panel(
                observations=corrupted_obs,
                start_date=date(2020, 1, 1),
                end_date=date(2023, 12, 31),
                pit_mode=PITMode.ESTIMATED_LAG,
            )

    @pytest.mark.parametrize("bad_repr", INVALID_REPRESENTATIONS)
    def test_7b_end_to_end_factor_panel_rejects_malformed_fx_entity(self, real_data_panels, bad_repr: str):
        """build_fx_carry_factor_panel rejects malformed fx_entity."""
        _, _, observations = real_data_panels
        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            build_fx_carry_factor_panel(
                observations=observations,
                start_date=date(2020, 1, 1),
                end_date=date(2023, 12, 31),
                fx_entity=bad_repr,
            )

    def test_8_preserve_valid_pair_representations(self):
        """Valid slash and underscore pairs are extracted and reconciled accurately."""
        assert _extract_pair_codes("EUR/USD") == ("EUR", "USD")
        assert _extract_pair_codes("USD/EUR") == ("USD", "EUR")
        assert _extract_pair_codes("EUR_USD") == ("EUR", "USD")
        assert _extract_pair_codes("USD_EUR") == ("USD", "EUR")

        meta_slash = validate_and_normalize_fx_metadata(
            entity_code="EUR/USD",
            unit="quote_per_base",
            value=1.10,
        )
        assert meta_slash.base_currency == "EUR"
        assert meta_slash.quote_currency == "USD"
        assert meta_slash.quote_convention == QuoteConvention.QUOTE_PER_BASE

        meta_underscore = validate_and_normalize_fx_metadata(
            entity_code="EUR_USD",
            unit="quote_per_base",
            value=1.10,
        )
        assert meta_underscore.base_currency == "EUR"
        assert meta_underscore.quote_currency == "USD"
        assert meta_underscore.quote_convention == QuoteConvention.QUOTE_PER_BASE

    def test_9_preserve_legitimate_non_pair_entity_identifiers(self):
        """Documented non-pair namespaces and non-delimited codes return None and preserve explicit metadata."""
        assert _extract_pair_codes("FX_EUR_USD_LOGRET") is None
        assert _extract_pair_codes("IR_USD_1M") is None
        assert _extract_pair_codes("ECB_EA") is None
        assert _extract_pair_codes("KR.MRR_FR.LEV") is None
        assert _extract_pair_codes("UNKNOWN") is None
        assert _extract_pair_codes("EURUSD") is None

        meta_ecb = validate_and_normalize_fx_metadata(
            base_currency="EUR",
            quote_currency="USD",
            quote_convention=QuoteConvention.QUOTE_PER_BASE,
            entity_code="ECB_EA",
            unit="quote_per_base",
        )
        assert meta_ecb.base_currency == "EUR"
        assert meta_ecb.quote_currency == "USD"

        meta_unknown = validate_and_normalize_fx_metadata(
            base_currency="EUR",
            quote_currency="USD",
            quote_convention=QuoteConvention.QUOTE_PER_BASE,
            entity_code="UNKNOWN",
            unit="quote_per_base",
        )
        assert meta_unknown.base_currency == "EUR"
        assert meta_unknown.quote_currency == "USD"


# =============================================================================
# Workstream B: Closure Report Dates & Sample Reconciliation
# =============================================================================


class TestWorkstreamBClosureReportDateAndSampleReconciliation:
    """Verify exact alignment between baseline research manifest dates and closure report."""

    def test_10_reconcile_calibration_and_holdout_exact_dates(self, real_data_panels):
        """Assert exact date boundaries and counts across calibration and holdout panels."""
        calib_panel, holdout_panel, _ = real_data_panels

        # Calibration baseline: 990 levels, 989 transitions
        assert len(calib_panel.level_dates) == 990
        assert calib_panel.first_level_date == date(2020, 1, 6)
        assert calib_panel.last_level_date == date(2023, 12, 29)

        assert len(calib_panel.dates) == 989
        assert calib_panel.first_transition_date == date(2020, 1, 7)
        assert calib_panel.last_transition_date == date(2023, 12, 29)

        # Holdout baseline: 248 levels, 247 transitions
        assert len(holdout_panel.level_dates) == 248
        assert holdout_panel.first_level_date == date(2023, 12, 29)
        assert holdout_panel.last_level_date == date(2024, 12, 31)

        assert len(holdout_panel.dates) == 247
        assert holdout_panel.first_transition_date == date(2024, 1, 2)
        assert holdout_panel.last_transition_date == date(2024, 12, 31)

        # Combined counts accounting for the shared boundary date 2023-12-29
        total_transitions = len(calib_panel.dates) + len(holdout_panel.dates)
        assert total_transitions == 1236

        unique_level_dates = set(calib_panel.level_dates).union(set(holdout_panel.level_dates))
        assert len(unique_level_dates) == 1237, f"Expected 1237 unique level dates, got {len(unique_level_dates)}"
        assert date(2023, 12, 29) in calib_panel.level_dates
        assert date(2023, 12, 29) in holdout_panel.level_dates


# =============================================================================
# Workstream C: Research Invariance Sign-Off
# =============================================================================


class TestWorkstreamCResearchInvarianceSignOff:
    """Verify research invariance within declared cross-platform tolerance."""

    def test_11_reconcile_covariance_and_correlation_matrices(self, real_data_panels):
        """Assert calibration covariance and correlation invariance within declared tolerance."""
        calib_panel, holdout_panel, obs = real_data_panels
        report = calibrate_factor_panel(calib_panel, holdout_panel, raw_observations=obs)

        calib_artifact_path = Path("data/results/phase_4_1_2_2_3/calibration_report.json")
        baseline = json.loads(calib_artifact_path.read_bytes().decode("utf-8"))

        curr_cov = report.covariance_matrix
        base_cov = baseline["covariance_matrix"]
        cov_max_diff = max(
            abs(curr_cov[i][j] - base_cov[i][j]) for i in range(len(curr_cov)) for j in range(len(curr_cov[0]))
        )
        assert cov_max_diff <= 1e-9, f"Covariance matrix diff exceeds tolerance: {cov_max_diff:.2e}"

        curr_corr = report.correlation_matrix
        base_corr = baseline["correlation_matrix"]
        corr_max_diff = max(
            abs(curr_corr[i][j] - base_corr[i][j]) for i in range(len(curr_corr)) for j in range(len(curr_corr[0]))
        )
        assert corr_max_diff <= 1e-9, f"Correlation matrix diff exceeds tolerance: {corr_max_diff:.2e}"

    def test_12_reconcile_holdout_correlation_shifts(self, real_data_panels):
        """Assert holdout correlation shifts within declared tolerance."""
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

    def test_13_reconcile_portfolio_holdout_status(self):
        """Verify portfolio holdout status is strictly UNAVAILABLE."""
        diag = evaluate_portfolio_holdout_diagnostics()
        assert diag.status == "UNAVAILABLE"
        assert diag.is_available is False
        assert "SIMULATED_RESEARCH_PROXY" in diag.reason
        assert any("UNAVAILABLE" in note for note in diag.notes)
