"""Phase 4.1.2.2.3.8 Regression Test Suite: Namespace Grammar & Final Repository Lineage Sign-Off.

Mathematics first. Data second. Prediction third. AI last.

Validates:
1. Non-Pair Namespace Grammar:
   - Rejection of malformed namespace representations across all operational layers:
     * 'FX_EUR_US' (2-letter quote currency 'US')
     * 'FX_EUR_USD_EXTRA' (unrecognized transformation 'EXTRA')
     * 'IR_USD_US' (invalid tenor 'US' mimicking a currency pair)
     * 'KR_EUR_USD' (KR namespace representing ECB key rates cannot contain currency pairs)
     * 'ECB_EUR_USD' (central bank namespace cannot contain currency pairs)
     * 'FED_USD_EUR' (central bank namespace cannot contain currency pairs)
     * 'FX_EUR_USD_' (empty/trailing component)
     * 'FX_EUR_US_LOGRET' (malformed quote currency length 2 in 4-token factor)
     * 'IR_USD_1M_EXTRA' (extra components in IR factor)
     * 'KR_EUR_US' (KR namespace with malformed pair)
   - Preservation of legitimate identifiers:
     * 'FX_EUR_USD_LOGRET' (valid factor log return)
     * 'IR_USD_1M' (valid interest rate factor)
     * 'ECB_EA' (valid ECB economic entity)
     * 'KR.MRR_FR.LEV' (valid ECB SDMX key)
     * 'KR.DFR.LEV' (valid ECB SDMX key)
     * 'FED_USA' (valid Federal Reserve entity)
     * 'FED_H15_CALENDAR' (valid Federal Reserve calendar)
     * 'FX_EUR_USD_LOGRET__vs__RATE_DIFF_EUR_BORROW_BPS' (valid interaction factor)
2. Five validation layers tested:
   - Layer 1: validate_and_normalize_fx_metadata().
   - Layer 2: DataObservation validation.
   - Layer 3: _normalize_fx_quote_to_usd_per_eur().
   - Layer 4: resolve_canonical_initial_fx().
   - Layer 5a: build_fx_carry_factor_panel() corrupted observation rejection.
   - Layer 5b: build_fx_carry_factor_panel() malformed fx_entity rejection.
3. Strict vs Lenient extraction semantics:
   - strict=False returns None for valid non-pairs, raises ValueError for malformed ones.
   - strict=True raises ValueError for all non-pairs.
4. Slash precedence preservation from Phase 4.1.2.2.3.7.
5. Exact baseline sample counts, window dates, numerical parity (<= 1e-9),
   and portfolio holdout status UNAVAILABLE.
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
from simulation.monte_carlo.calibration import calibrate_factor_panel, split_calibration_holdout
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


INVALID_NAMESPACE_REPRESENTATIONS = [
    "FX_EUR_US",
    "FX_EUR_USD_EXTRA",
    "IR_USD_US",
    "KR_EUR_USD",
    "ECB_EUR_USD",
    "FED_USD_EUR",
    "FX_EUR_USD_",
    "FX_EUR_US_LOGRET",
    "IR_USD_1M_EXTRA",
    "KR_EUR_US",
]

LEGITIMATE_NAMESPACE_REPRESENTATIONS = [
    "FX_EUR_USD_LOGRET",
    "IR_USD_1M",
    "ECB_EA",
    "KR.MRR_FR.LEV",
    "KR.DFR.LEV",
    "FED_USA",
    "FED_H15_CALENDAR",
    "FX_EUR_USD_LOGRET__vs__RATE_DIFF_EUR_BORROW_BPS",
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
        pit_mode=PITMode.ESTIMATED_LAG,
        effective_sample_size=len(d),
    )


# =============================================================================
# Workstream A: Namespace Grammar & Multi-Layer Rejection
# =============================================================================


class TestWorkstreamANamespaceGrammar:
    """Test non-pair namespace grammar validation and preservation across layers."""

    @pytest.mark.parametrize("bad_repr", INVALID_NAMESPACE_REPRESENTATIONS)
    def test_extract_pair_codes_rejects_malformed_namespaces_strict_false(self, bad_repr: str):
        """_extract_pair_codes with strict=False fails closed for malformed namespace identifiers."""
        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            _extract_pair_codes(bad_repr, strict=False)

    @pytest.mark.parametrize("bad_repr", INVALID_NAMESPACE_REPRESENTATIONS)
    def test_extract_pair_codes_rejects_malformed_namespaces_strict_true(self, bad_repr: str):
        """_extract_pair_codes with strict=True fails closed for malformed namespace identifiers."""
        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            _extract_pair_codes(bad_repr, strict=True)

    @pytest.mark.parametrize("good_repr", LEGITIMATE_NAMESPACE_REPRESENTATIONS)
    def test_extract_pair_codes_preserves_legitimate_namespaces_strict_false(self, good_repr: str):
        """_extract_pair_codes with strict=False returns None for legitimate non-pair entities."""
        assert _extract_pair_codes(good_repr, strict=False) is None

    @pytest.mark.parametrize("good_repr", LEGITIMATE_NAMESPACE_REPRESENTATIONS)
    def test_extract_pair_codes_rejects_legitimate_namespaces_strict_true(self, good_repr: str):
        """_extract_pair_codes with strict=True raises ValueError for non-pairs since they are not FX pairs."""
        with pytest.raises(ValueError, match="Malformed FX pair metadata"):
            _extract_pair_codes(good_repr, strict=True)

    @pytest.mark.parametrize("bad_repr", INVALID_NAMESPACE_REPRESENTATIONS)
    def test_layer1_direct_validation_rejects_malformed_namespaces(self, bad_repr: str):
        """Layer 1: validate_and_normalize_fx_metadata rejects malformed namespace entity codes."""
        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            validate_and_normalize_fx_metadata(
                entity_code=bad_repr,
                unit="quote_per_base",
                value=1.10,
                require_currencies=False,
            )

    @pytest.mark.parametrize("bad_repr", INVALID_NAMESPACE_REPRESENTATIONS)
    def test_layer1_direct_validation_with_explicit_currencies_rejects_malformed_namespaces(self, bad_repr: str):
        """Layer 1: Rejection occurs even when valid base and quote currencies are explicitly provided."""
        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            validate_and_normalize_fx_metadata(
                base_currency="EUR",
                quote_currency="USD",
                entity_code=bad_repr,
                unit="USD_per_EUR",
                quote_convention=QuoteConvention.QUOTE_PER_BASE,
                value=1.10,
            )

    @pytest.mark.parametrize("bad_repr", INVALID_NAMESPACE_REPRESENTATIONS)
    def test_layer2_data_observation_validation_rejects_malformed_namespaces(self, bad_repr: str):
        """Layer 2: DataObservation validation fails closed for malformed namespace entity codes."""
        with pytest.raises(ValidationError) as exc_info:
            DataObservation(
                kind=ObservationKind.EXCHANGE_RATE,
                source_id="frankfurter",
                entity_code=bad_repr,
                value=1.1050,
                unit="quote_per_base",
                frequency=Frequency.DAILY,
                observation_date=date(2023, 12, 29),
                retrieved_at=datetime(2023, 12, 29, tzinfo=timezone.utc),
            )
        assert "Malformed pair-like FX identifier" in str(exc_info.value)

    @pytest.mark.parametrize("bad_repr", INVALID_NAMESPACE_REPRESENTATIONS)
    def test_layer3_quote_normalization_rejects_malformed_namespaces(self, bad_repr: str):
        """Layer 3: _normalize_fx_quote_to_usd_per_eur rejects malformed namespace entity codes."""
        obs = DataObservation.model_construct(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="frankfurter",
            entity_code=bad_repr,
            base_currency="EUR",
            quote_currency="USD",
            quote_convention=QuoteConvention.QUOTE_PER_BASE,
            value=1.1050,
            unit="quote_per_base",
            frequency=Frequency.DAILY,
            observation_date=date(2023, 12, 29),
            retrieved_at=datetime(2023, 12, 29, tzinfo=timezone.utc),
        )
        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            _normalize_fx_quote_to_usd_per_eur(obs)

    @pytest.mark.parametrize("bad_repr", INVALID_NAMESPACE_REPRESENTATIONS)
    def test_layer4_holdout_boundary_resolver_rejects_malformed_namespaces(self, bad_repr: str):
        """Layer 4: resolve_canonical_initial_fx rejects malformed entity code in provenance."""
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

    @pytest.mark.parametrize("bad_repr", INVALID_NAMESPACE_REPRESENTATIONS)
    def test_layer5a_end_to_end_panel_rejects_corrupted_raw_observation(self, real_data_panels, bad_repr: str):
        """Layer 5a: build_fx_carry_factor_panel rejects raw observation with malformed entity code."""
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

    @pytest.mark.parametrize("bad_repr", INVALID_NAMESPACE_REPRESENTATIONS)
    def test_layer5b_end_to_end_panel_rejects_malformed_fx_entity(self, real_data_panels, bad_repr: str):
        """Layer 5b: build_fx_carry_factor_panel rejects malformed fx_entity."""
        _, _, observations = real_data_panels
        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            build_fx_carry_factor_panel(
                observations=observations,
                start_date=date(2020, 1, 1),
                end_date=date(2023, 12, 31),
                fx_entity=bad_repr,
            )

    def test_preservation_of_legitimate_ecb_ea_in_metadata_normalization(self):
        """Direct normalization accepts legitimate ECB_EA non-pair entity code."""
        meta = validate_and_normalize_fx_metadata(
            base_currency="EUR",
            quote_currency="USD",
            entity_code="ECB_EA",
            unit="USD_per_EUR",
            quote_convention=QuoteConvention.QUOTE_PER_BASE,
            value=1.10,
        )
        assert meta.base_currency == "EUR"
        assert meta.quote_currency == "USD"
        assert meta.canonical_usd_per_eur == 1.10


# =============================================================================
# Workstream B: Slash Precedence Preservation from Phase 4.1.2.2.3.7
# =============================================================================


class TestSlashPrecedencePreservation:
    """Verify that Phase 4.1.2.2.3.7 slash precedence remains completely intact."""

    @pytest.mark.parametrize(
        "bad_slash_repr",
        [
            "USD/EUR.",
            "EUR/USD.extra",
            "FX_EUR/USD/",
            "EUR/US",
            "EU/USD",
        ],
    )
    def test_slash_syntax_strictly_precedes_prefixes_and_dots(self, bad_slash_repr: str):
        """Any identifier containing '/' fails closed under Rule 1 before Rule 2 is evaluated."""
        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            _extract_pair_codes(bad_slash_repr, strict=False)

        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            _extract_pair_codes(bad_slash_repr, strict=True)

    def test_clean_slash_pairs_extract_correctly(self):
        """Valid slash pairs extract accurately in both strict modes."""
        assert _extract_pair_codes("EUR/USD", strict=False) == ("EUR", "USD")
        assert _extract_pair_codes("EUR/USD", strict=True) == ("EUR", "USD")
        assert _extract_pair_codes("USD/EUR", strict=False) == ("USD", "EUR")
        assert _extract_pair_codes("USD/EUR", strict=True) == ("USD", "EUR")


# =============================================================================
# Workstream C: Research Invariance, Calibration & Holdout Integrity
# =============================================================================


class TestResearchInvarianceAndBaselineIntegrity:
    """Validate sample counts, dates, numerical parity, and holdout status UNAVAILABLE."""

    def test_calibration_and_holdout_exact_dates_and_counts(self, real_data_panels):
        """Verify calibration and holdout panel dates, level counts, and transition counts."""
        calib_panel, holdout_panel, _ = real_data_panels

        # Calibration window
        assert len(calib_panel.level_dates) == 990
        assert len(calib_panel.dates) == 989
        assert calib_panel.level_dates[0] == date(2020, 1, 6)
        assert calib_panel.level_dates[-1] == date(2023, 12, 29)
        assert calib_panel.dates[0] == date(2020, 1, 7)
        assert calib_panel.dates[-1] == date(2023, 12, 29)

        # Holdout window
        assert len(holdout_panel.level_dates) == 248
        assert len(holdout_panel.dates) == 247
        assert holdout_panel.level_dates[0] == date(2023, 12, 29)
        assert holdout_panel.level_dates[-1] == date(2024, 12, 31)
        assert holdout_panel.dates[0] == date(2024, 1, 2)
        assert holdout_panel.dates[-1] == date(2024, 12, 31)

        # Total aligned unique dates
        all_unique_dates = sorted(set(calib_panel.level_dates) | set(holdout_panel.level_dates))
        assert len(all_unique_dates) == 1237
        assert all_unique_dates[0] == date(2020, 1, 6)
        assert all_unique_dates[-1] == date(2024, 12, 31)

        total_transitions = len(calib_panel.dates) + len(holdout_panel.dates)
        assert total_transitions == 1236

    def test_canonical_initial_fx_resolution(self, real_data_panels):
        """Initial FX level on boundary date 2023-12-29 resolves to canonical ~1.1050 USD per EUR."""
        calib_panel, _, _ = real_data_panels
        initial_fx = resolve_canonical_initial_fx(calib_panel, boundary_date=date(2023, 12, 29))
        assert abs(initial_fx - 1.104996795509293) <= 1e-9

    def test_reconcile_covariance_and_correlation_matrices(self, real_data_panels):
        """Empirical factor covariance matches baseline within cross-platform parity tolerance <= 1e-9."""
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

    def test_reconcile_holdout_correlation_shifts(self, real_data_panels):
        """Holdout correlation shifts match baseline within tolerance <= 1e-9."""
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

    def test_portfolio_holdout_status_unavailable(self):
        """Portfolio holdout diagnostics remain strictly UNAVAILABLE pending complete Phase 5."""
        diag = evaluate_portfolio_holdout_diagnostics()
        assert diag.status == "UNAVAILABLE"
        assert diag.is_available is False
        assert "SIMULATED_RESEARCH_PROXY" in diag.reason
