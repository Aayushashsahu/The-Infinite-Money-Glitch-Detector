"""Phase 4.1.2.2.3.10 Regression Test Suite: KR SDMX Allowlist Enforcement & Final Namespace Contract Sign-Off.

Mathematics first. Data second. Prediction third. AI last.

Validates:
1. Workstream A & B — Strict KR SDMX Allowlist Enforcement:
   - Identifiers in the 'KR.' namespace must strictly follow 'KR.<VALID_RATE_KEY>.<VALID_UNIT>'.
   - Valid ECB key rate keys: _VALID_ECB_RATE_KEYS = frozenset({"DFR", "MRR_FR", "MRR_VR", "MLF", "DF"}).
   - Valid ECB SDMX units: _VALID_ECB_SDMX_UNITS = frozenset({"LEV", "BPS", "PCT"}).
   - Full rejection of invalid rate keys, unknown lengths, digits, blank components, and invalid units:
     * 'KR.BOGUS.LEV'
     * 'KR.RATE1.LEV'
     * 'KR..LEV'
     * 'KR.UNKNOWN_RATE.LEV'
     * 'KR.MRR_FR.UNKNOWN'
     * 'KR.MRR_FR.LEV.EXTRA'
     * 'KR.MRR_FR.'
     * 'KR..'
     * 'KR.UNKNOWN.BPS'
   - Preservation of all legitimate ECB key rate series:
     * 'KR.MRR_FR.LEV'
     * 'KR.MRR_VR.LEV'
     * 'KR.DFR.LEV'
     * 'KR.MLF.LEV'
     * 'KR.DF.LEV'
     * 'KR.MRR_FR.BPS'
     * 'KR.DFR.PCT'
   - Preservation of historical rejection of pair-like KR representations:
     * 'KR_EUR_USD'
     * 'KR.EUR_USD'
     * 'KR.GBP_USD'
     * 'KR.USD_GBP'
     * 'KR.EUR.USD'
     * 'KR.GBP.USD'
     * 'KR.EUR_USD.LEV'
     * 'KR.GBP_USD.LEV'
     * 'KR.USD_GBP.LEV'
     * 'KR.EUR.LEV'

2. Multi-Layer Validation (Layers 1 through 5):
   - Layer 1: Direct validation via validate_and_normalize_fx_metadata().
   - Layer 2: DataObservation model validation.
   - Layer 3: _normalize_fx_quote_to_usd_per_eur().
   - Layer 4: resolve_canonical_initial_fx().
   - Layer 5a: build_fx_carry_factor_panel() with corrupted raw observation.
   - Layer 5b: build_fx_carry_factor_panel() with malformed fx_entity.

3. Strict vs Lenient Extraction Semantics:
   - strict=False returns None for valid KR series keys, raises ValueError for malformed ones.
   - strict=True raises ValueError("Malformed FX pair metadata") for valid non-pairs,
     and raises namespace-specific ValueError for malformed ones.

4. Research Numerical Invariance Parity:
   - Calibration and holdout date counts: 990 levels / 989 transitions, 248 levels / 247 transitions.
   - Total aligned unique dates: 1237; total transitions: 1236.
   - Boundary date 2023-12-29 initial FX level ~1.1050 USD per EUR (error <= 1e-9).
   - Covariance and correlation matrix parity <= 1e-9.
   - Holdout correlation shifts parity <= 1e-9.
   - Portfolio holdout diagnostics status strictly UNAVAILABLE pending complete Phase 5.
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


# =============================================================================
# Test Identifiers Matrix
# =============================================================================

# Workstream A & B: Legitimate ECB key rates representations
LEGITIMATE_KR_REPRESENTATIONS = [
    "KR.MRR_FR.LEV",
    "KR.MRR_VR.LEV",
    "KR.DFR.LEV",
    "KR.MLF.LEV",
    "KR.DF.LEV",
    "KR.MRR_FR.BPS",
    "KR.DFR.PCT",
]

# Workstream A & B: Invalid KR representations (unsupported keys, empty tokens, invalid units, extra components)
INVALID_KR_REPRESENTATIONS = [
    "KR.BOGUS.LEV",
    "KR.RATE1.LEV",
    "KR..LEV",
    "KR.UNKNOWN_RATE.LEV",
    "KR.MRR_FR.UNKNOWN",
    "KR.MRR_FR.LEV.EXTRA",
    "KR.MRR_FR.",
    "KR..",
    "KR.UNKNOWN.BPS",
    "KR_EUR_USD",
    "KR.EUR_USD",
    "KR.GBP_USD",
    "KR.USD_GBP",
    "KR.EUR.USD",
    "KR.GBP.USD",
    "KR.EUR_USD.LEV",
    "KR.GBP_USD.LEV",
    "KR.USD_GBP.LEV",
    "KR.EUR.LEV",
]


# =============================================================================
# Shared Fixtures
# =============================================================================


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
# Workstream A & B: KR SDMX Allowlist Extraction & Semantics
# =============================================================================


class TestWorkstreamAKRAllowlistEnforcement:
    """Verify strict allowlist enforcement for KR namespace identifiers."""

    @pytest.mark.parametrize("good_repr", LEGITIMATE_KR_REPRESENTATIONS)
    def test_strict_false_preserves_legitimate_kr_identifiers(self, good_repr: str):
        """Under strict=False, valid KR SDMX identifiers return None (valid non-pair)."""
        assert _extract_pair_codes(good_repr, strict=False) is None

    @pytest.mark.parametrize("good_repr", LEGITIMATE_KR_REPRESENTATIONS)
    def test_strict_true_rejects_valid_kr_identifiers_as_non_pairs(self, good_repr: str):
        """Under strict=True, valid KR SDMX identifiers raise ValueError because they are not pairs."""
        with pytest.raises(ValueError, match="Malformed FX pair metadata"):
            _extract_pair_codes(good_repr, strict=True)

    @pytest.mark.parametrize("bad_repr", INVALID_KR_REPRESENTATIONS)
    def test_strict_false_rejects_invalid_kr_identifiers(self, bad_repr: str):
        """Under strict=False, malformed or non-allowlisted KR identifiers raise ValueError."""
        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            _extract_pair_codes(bad_repr, strict=False)

    @pytest.mark.parametrize("bad_repr", INVALID_KR_REPRESENTATIONS)
    def test_strict_true_rejects_invalid_kr_identifiers_with_namespace_error(self, bad_repr: str):
        """Under strict=True, malformed KR identifiers fail closed with namespace-specific error."""
        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            _extract_pair_codes(bad_repr, strict=True)


# =============================================================================
# Workstream B: Multi-Layer Rejection & Validation
# =============================================================================


class TestWorkstreamBMultiLayerValidation:
    """Validate multi-layer validation across Layers 1 to 5."""

    @pytest.mark.parametrize("bad_repr", INVALID_KR_REPRESENTATIONS)
    def test_layer1_direct_validation_rejects_invalid_kr(self, bad_repr: str):
        """Layer 1: validate_and_normalize_fx_metadata rejects invalid KR representations."""
        with pytest.raises(ValueError, match="KR namespace represents ECB key rates"):
            validate_and_normalize_fx_metadata(
                entity_code=bad_repr,
                unit="quote_per_base",
                value=1.10,
                require_currencies=False,
            )

    @pytest.mark.parametrize("good_repr", LEGITIMATE_KR_REPRESENTATIONS)
    def test_layer1_direct_validation_accepts_valid_kr_when_currencies_not_required(self, good_repr: str):
        """Layer 1: validate_and_normalize_fx_metadata accepts valid KR representation when require_currencies=False."""
        meta = validate_and_normalize_fx_metadata(
            entity_code=good_repr,
            unit="quote_per_base",
            value=1.10,
            require_currencies=False,
        )
        assert meta.base_currency == ""
        assert meta.quote_currency == ""
        assert meta.quote_convention == QuoteConvention.QUOTE_PER_BASE
        assert meta.canonical_usd_per_eur is None

    @pytest.mark.parametrize("bad_repr", INVALID_KR_REPRESENTATIONS)
    def test_layer2_data_observation_rejects_invalid_kr(self, bad_repr: str):
        """Layer 2: DataObservation rejects invalid KR representations in entity_code."""
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
        assert "KR namespace represents ECB key rates" in str(exc_info.value)

    @pytest.mark.parametrize("bad_repr", INVALID_KR_REPRESENTATIONS)
    def test_layer3_quote_normalization_rejects_invalid_kr(self, bad_repr: str):
        """Layer 3: _normalize_fx_quote_to_usd_per_eur rejects observations with invalid KR entity_code."""
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

    @pytest.mark.parametrize(
        "bad_repr",
        [
            "KR.BOGUS.LEV",
            "KR.RATE1.LEV",
            "KR..LEV",
            "KR.UNKNOWN_RATE.LEV",
            "KR.MRR_FR.UNKNOWN",
            "KR.MRR_FR.LEV.EXTRA",
            "KR.MRR_FR.",
            "KR..",
            "KR.UNKNOWN.BPS",
        ],
    )
    def test_layer4_boundary_resolver_rejects_invalid_kr_provenance(self, bad_repr: str):
        """Layer 4: resolve_canonical_initial_fx rejects invalid KR entity in row provenance."""
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

    @pytest.mark.parametrize(
        "bad_repr",
        [
            "KR.BOGUS.LEV",
            "KR.RATE1.LEV",
            "KR.MRR_FR.UNKNOWN",
        ],
    )
    def test_layer5a_factor_panel_rejects_corrupted_raw_observation(self, real_data_panels, bad_repr: str):
        """Layer 5a: build_fx_carry_factor_panel rejects raw observation with malformed KR identifier."""
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

    @pytest.mark.parametrize(
        "bad_repr",
        [
            "KR.UNKNOWN_RATE.LEV",
            "KR.MRR_FR.LEV.EXTRA",
            "KR.UNKNOWN.BPS",
        ],
    )
    def test_layer5b_factor_panel_rejects_malformed_fx_entity(self, real_data_panels, bad_repr: str):
        """Layer 5b: build_fx_carry_factor_panel rejects malformed KR fx_entity."""
        _, _, observations = real_data_panels
        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            build_fx_carry_factor_panel(
                observations=observations,
                start_date=date(2020, 1, 1),
                end_date=date(2023, 12, 31),
                fx_entity=bad_repr,
            )


# =============================================================================
# Workstream C: End-to-End Invariance & Numerical Parity
# =============================================================================


class TestWorkstreamCEndToEndAndResearchParity:
    """Validate full factor pipeline numerical parity and research invariance."""

    def test_exact_dates_and_counts_invariance(self, real_data_panels):
        """Verify calibration and holdout panel dates, level counts, and transition counts."""
        calib_panel, holdout_panel, _ = real_data_panels

        # Calibration window: 990 levels, 989 transitions
        assert len(calib_panel.level_dates) == 990
        assert len(calib_panel.dates) == 989
        assert calib_panel.level_dates[0] == date(2020, 1, 6)
        assert calib_panel.level_dates[-1] == date(2023, 12, 29)
        assert calib_panel.dates[0] == date(2020, 1, 7)
        assert calib_panel.dates[-1] == date(2023, 12, 29)

        # Holdout window: 248 levels, 247 transitions
        assert len(holdout_panel.level_dates) == 248
        assert len(holdout_panel.dates) == 247
        assert holdout_panel.level_dates[0] == date(2023, 12, 29)
        assert holdout_panel.level_dates[-1] == date(2024, 12, 31)
        assert holdout_panel.dates[0] == date(2024, 1, 2)
        assert holdout_panel.dates[-1] == date(2024, 12, 31)

        # Total aligned unique dates: 1237, total transitions: 1236
        all_unique_dates = sorted(set(calib_panel.level_dates) | set(holdout_panel.level_dates))
        assert len(all_unique_dates) == 1237
        assert len(calib_panel.dates) + len(holdout_panel.dates) == 1236

    def test_canonical_initial_fx_numerical_parity(self, real_data_panels):
        """Initial FX level on boundary date 2023-12-29 resolves to canonical ~1.1050 USD per EUR."""
        calib_panel, _, _ = real_data_panels
        initial_fx = resolve_canonical_initial_fx(calib_panel, boundary_date=date(2023, 12, 29))
        assert abs(initial_fx - 1.104996795509293) <= 1e-9

    def test_calibration_covariance_and_correlation_parity(self, real_data_panels):
        """Empirical factor covariance and correlation match baseline within cross-platform tolerance <= 1e-9."""
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

    def test_holdout_correlation_shifts_parity(self, real_data_panels):
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

    def test_portfolio_holdout_status_strictly_unavailable(self):
        """Portfolio holdout diagnostics remain strictly UNAVAILABLE pending complete Phase 5."""
        diag = evaluate_portfolio_holdout_diagnostics()
        assert diag.status == "UNAVAILABLE"
        assert diag.is_available is False
        assert "SIMULATED_RESEARCH_PROXY" in diag.reason
