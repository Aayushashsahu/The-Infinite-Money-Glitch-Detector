"""Phase 4.1.2.2.3.9 Regression Test Suite: Namespace Edge-Case Closure & Final Grammar Sign-Off.

Mathematics first. Data second. Prediction third. AI last.

Validates:
1. Workstream A — Central-Bank Namespace Dotted-Suffix Validation:
   - Rejection of malformed central bank identifiers with dotted suffixes:
     * 'ECB_EUR_USD.extra'
     * 'FED_USD_EUR.extra'
     * 'ECB_EUR.extra_USD'
     * 'BOE_EUR_USD.extra'
     * 'BCB_EUR_USD.extra'
     * 'BOJ_USD_EUR.extra'
   - Preservation of legitimate central bank entities:
     * 'ECB_EA'
     * 'FED_USA'
     * 'FED_H15_CALENDAR'
     * 'ECB_REFERENCE'

2. Workstream B — FX Interaction Grammar:
   - Full left-hand and right-hand side syntax validation around '__vs__':
     * Empty RHS: 'FX_EUR_USD_LOGRET__vs__'
     * Missing components: '__vs__RATE_DIFF_EUR_BORROW_BPS', 'FX___vs__RATE_DIFF_EUR_BORROW_BPS'
     * Multiple delimiters: 'FX_EUR_USD_LOGRET__vs__RATE_DIFF_EUR_BORROW_BPS__vs__EXTRA'
     * Malformed LHS currency: 'FX_EUR_US_LOGRET__vs__RATE_DIFF_EUR_BORROW_BPS'
     * Invalid LHS transform: 'FX_EUR_USD_EXTRA__vs__RATE_DIFF_EUR_BORROW_BPS'
     * Invalid RHS syntax:
       - 'FX_EUR_USD_LOGRET__vs__INVALID_RHS'
       - 'FX_EUR_USD_LOGRET__vs__RATE_DIFF_EUR_US_BPS' (non-rate token mimicking currency)
       - 'FX_EUR_USD_LOGRET__vs__RATE_DIFF_EUR_BORROW_INVALID' (invalid rate unit)
       - 'FX_EUR_USD_LOGRET__vs__YIELD_DIFF_US_1M_BPS' (malformed currency code length 2)
       - 'FX_EUR_USD_LOGRET__vs__YIELD_DIFF_USD_INVALID_BPS' (invalid tenor)
       - 'FX_EUR_USD_LOGRET__vs__YIELD_DIFF_USD_1M_INVALID' (invalid unit)
   - Preservation of legitimate interaction factor identifiers:
     * 'FX_EUR_USD_LOGRET__vs__RATE_DIFF_EUR_BORROW_BPS'
     * 'FX_EUR_USD_LOGRET__vs__YIELD_DIFF_USD_1M_BPS'
     * 'FX_EUR_USD_LOGRET__vs__YIELD_DIFF_USD_3M_BPS'
     * 'RATE_DIFF_EUR_BORROW_BPS__vs__YIELD_DIFF_USD_1M_BPS'
     * 'RATE_DIFF_EUR_BORROW_BPS__vs__YIELD_DIFF_USD_3M_BPS'
     * 'YIELD_DIFF_USD_1M_BPS__vs__YIELD_DIFF_USD_3M_BPS'

3. Workstream C — KR Namespace Currency Pair Rejection & Key Rate Preservation:
   - Generalized currency pair rejection inside KR namespace:
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
   - Preservation of legitimate ECB key rates:
     * 'KR.MRR_FR.LEV'
     * 'KR.DFR.LEV'
     * 'KR.DF.LEV'

4. Workstream D — Multi-Layer Verification:
   - Layer 1: validate_and_normalize_fx_metadata().
   - Layer 2: DataObservation validation.
   - Layer 3: _normalize_fx_quote_to_usd_per_eur().
   - Layer 4: resolve_canonical_initial_fx().
   - Layer 5a: build_fx_carry_factor_panel() corrupted observation rejection.
   - Layer 5b: build_fx_carry_factor_panel() malformed fx_entity rejection.

5. Strict vs Lenient extraction semantics:
   - strict=False returns None for valid non-pairs, raises ValueError for malformed ones.
   - strict=True raises ValueError for all non-pairs.

6. Numerical parity preservation:
   - Calibration and holdout date counts, window bounds, initial FX level ~1.1050,
     covariance and correlation parity <= 1e-9, and portfolio holdout UNAVAILABLE.
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

# Workstream A: Central bank dotted-suffix representations
INVALID_CENTRAL_BANK_REPRESENTATIONS = [
    "ECB_EUR_USD.extra",
    "FED_USD_EUR.extra",
    "ECB_EUR.extra_USD",
    "BOE_EUR_USD.extra",
    "BCB_EUR_USD.extra",
    "BOJ_USD_EUR.extra",
]

LEGITIMATE_CENTRAL_BANK_REPRESENTATIONS = [
    "ECB_EA",
    "FED_USA",
    "FED_H15_CALENDAR",
    "ECB_REFERENCE",
]

# Workstream B: Interaction grammar representations
INVALID_INTERACTION_REPRESENTATIONS = [
    "FX_EUR_USD_LOGRET__vs__",
    "__vs__RATE_DIFF_EUR_BORROW_BPS",
    "FX___vs__RATE_DIFF_EUR_BORROW_BPS",
    "FX_EUR_USD_LOGRET__vs__RATE_DIFF_EUR_BORROW_BPS__vs__EXTRA",
    "FX_EUR_US_LOGRET__vs__RATE_DIFF_EUR_BORROW_BPS",
    "FX_EU_USD_LOGRET__vs__RATE_DIFF_EUR_BORROW_BPS",
    "FX_EUR_USD_EXTRA__vs__RATE_DIFF_EUR_BORROW_BPS",
    "FX_EUR_USD_INVALID__vs__RATE_DIFF_EUR_BORROW_BPS",
    "FX_EUR_USD_LOGRET__vs__INVALID_RHS",
    "FX_EUR_USD_LOGRET__vs__RATE_DIFF_EUR_US_BPS",
    "FX_EUR_USD_LOGRET__vs__RATE_DIFF_EUR_BORROW_INVALID",
    "FX_EUR_USD_LOGRET__vs__YIELD_DIFF_US_1M_BPS",
    "FX_EUR_USD_LOGRET__vs__YIELD_DIFF_USD_INVALID_BPS",
    "FX_EUR_USD_LOGRET__vs__YIELD_DIFF_USD_1M_INVALID",
]

LEGITIMATE_INTERACTION_REPRESENTATIONS = [
    "FX_EUR_USD_LOGRET__vs__RATE_DIFF_EUR_BORROW_BPS",
    "FX_EUR_USD_LOGRET__vs__YIELD_DIFF_USD_1M_BPS",
    "FX_EUR_USD_LOGRET__vs__YIELD_DIFF_USD_3M_BPS",
    "RATE_DIFF_EUR_BORROW_BPS__vs__YIELD_DIFF_USD_1M_BPS",
    "RATE_DIFF_EUR_BORROW_BPS__vs__YIELD_DIFF_USD_3M_BPS",
    "YIELD_DIFF_USD_1M_BPS__vs__YIELD_DIFF_USD_3M_BPS",
]

# Workstream C: KR namespace representations
INVALID_KR_REPRESENTATIONS = [
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

LEGITIMATE_KR_REPRESENTATIONS = [
    "KR.MRR_FR.LEV",
    "KR.DFR.LEV",
    "KR.DF.LEV",
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
# Workstream A: Central-Bank Namespace Dotted-Suffix Validation
# =============================================================================


class TestWorkstreamACentralBankDottedSuffix:
    """Verify fail-closed rejection of central bank currency-pair identifiers with dotted suffixes."""

    @pytest.mark.parametrize("bad_repr", INVALID_CENTRAL_BANK_REPRESENTATIONS)
    def test_extract_pair_codes_rejects_central_bank_dotted_suffix_strict_false(self, bad_repr: str):
        """_extract_pair_codes with strict=False fails closed on central bank pairs with dotted suffixes."""
        with pytest.raises(ValueError, match="central bank namespace cannot contain currency pairs"):
            _extract_pair_codes(bad_repr, strict=False)

    @pytest.mark.parametrize("bad_repr", INVALID_CENTRAL_BANK_REPRESENTATIONS)
    def test_extract_pair_codes_rejects_central_bank_dotted_suffix_strict_true(self, bad_repr: str):
        """_extract_pair_codes with strict=True fails closed on central bank pairs with dotted suffixes."""
        with pytest.raises(ValueError, match="central bank namespace cannot contain currency pairs"):
            _extract_pair_codes(bad_repr, strict=True)

    @pytest.mark.parametrize("good_repr", LEGITIMATE_CENTRAL_BANK_REPRESENTATIONS)
    def test_extract_pair_codes_preserves_legitimate_central_bank_entities(self, good_repr: str):
        """_extract_pair_codes preserves legitimate central bank non-pair entities."""
        assert _extract_pair_codes(good_repr, strict=False) is None
        with pytest.raises(ValueError, match="Malformed FX pair metadata"):
            _extract_pair_codes(good_repr, strict=True)

    @pytest.mark.parametrize("bad_repr", INVALID_CENTRAL_BANK_REPRESENTATIONS)
    def test_layer1_direct_validation_rejects_central_bank_dotted_suffix(self, bad_repr: str):
        """Layer 1: validate_and_normalize_fx_metadata rejects central bank dotted suffixes."""
        with pytest.raises(ValueError, match="central bank namespace cannot contain currency pairs"):
            validate_and_normalize_fx_metadata(
                entity_code=bad_repr,
                unit="quote_per_base",
                value=1.10,
                require_currencies=False,
            )

    @pytest.mark.parametrize("bad_repr", INVALID_CENTRAL_BANK_REPRESENTATIONS)
    def test_layer2_data_observation_validation_rejects_central_bank_dotted_suffix(self, bad_repr: str):
        """Layer 2: DataObservation validation rejects central bank dotted suffixes."""
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
        assert "central bank namespace cannot contain currency pairs" in str(exc_info.value)


# =============================================================================
# Workstream B: FX Interaction Grammar
# =============================================================================


class TestWorkstreamBFXInteractionGrammar:
    """Verify comprehensive validation of factor interaction identifiers around '__vs__'."""

    @pytest.mark.parametrize("bad_repr", INVALID_INTERACTION_REPRESENTATIONS)
    def test_extract_pair_codes_rejects_malformed_interaction_strict_false(self, bad_repr: str):
        """_extract_pair_codes with strict=False fails closed on malformed interaction factors."""
        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            _extract_pair_codes(bad_repr, strict=False)

    @pytest.mark.parametrize("bad_repr", INVALID_INTERACTION_REPRESENTATIONS)
    def test_extract_pair_codes_rejects_malformed_interaction_strict_true(self, bad_repr: str):
        """_extract_pair_codes with strict=True fails closed on malformed interaction factors."""
        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            _extract_pair_codes(bad_repr, strict=True)

    @pytest.mark.parametrize("good_repr", LEGITIMATE_INTERACTION_REPRESENTATIONS)
    def test_extract_pair_codes_preserves_legitimate_interactions(self, good_repr: str):
        """_extract_pair_codes preserves legitimate interaction factors in strict=False."""
        assert _extract_pair_codes(good_repr, strict=False) is None
        with pytest.raises(ValueError, match="Malformed FX pair metadata"):
            _extract_pair_codes(good_repr, strict=True)

    @pytest.mark.parametrize("bad_repr", INVALID_INTERACTION_REPRESENTATIONS)
    def test_layer1_direct_validation_rejects_malformed_interaction(self, bad_repr: str):
        """Layer 1: validate_and_normalize_fx_metadata rejects malformed interaction factors."""
        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            validate_and_normalize_fx_metadata(
                entity_code=bad_repr,
                unit="quote_per_base",
                value=1.10,
                require_currencies=False,
            )

    @pytest.mark.parametrize("bad_repr", INVALID_INTERACTION_REPRESENTATIONS)
    def test_layer2_data_observation_validation_rejects_malformed_interaction(self, bad_repr: str):
        """Layer 2: DataObservation validation rejects malformed interaction factors."""
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


# =============================================================================
# Workstream C: KR Namespace Generalized Semantics
# =============================================================================


class TestWorkstreamCKRNamespaceSemantics:
    """Verify complete prohibition of currency pairs inside KR namespace and preservation of key rates."""

    @pytest.mark.parametrize("bad_repr", INVALID_KR_REPRESENTATIONS)
    def test_extract_pair_codes_rejects_kr_currency_pairs_strict_false(self, bad_repr: str):
        """_extract_pair_codes with strict=False fails closed for currency pairs in KR namespace."""
        with pytest.raises(ValueError, match="KR namespace represents ECB key rates and cannot contain currency pairs"):
            _extract_pair_codes(bad_repr, strict=False)

    @pytest.mark.parametrize("bad_repr", INVALID_KR_REPRESENTATIONS)
    def test_extract_pair_codes_rejects_kr_currency_pairs_strict_true(self, bad_repr: str):
        """_extract_pair_codes with strict=True fails closed for currency pairs in KR namespace."""
        with pytest.raises(ValueError, match="KR namespace represents ECB key rates and cannot contain currency pairs"):
            _extract_pair_codes(bad_repr, strict=True)

    @pytest.mark.parametrize("good_repr", LEGITIMATE_KR_REPRESENTATIONS)
    def test_extract_pair_codes_preserves_legitimate_ecb_key_rates(self, good_repr: str):
        """_extract_pair_codes preserves legitimate ECB key rates series keys."""
        assert _extract_pair_codes(good_repr, strict=False) is None
        with pytest.raises(ValueError, match="Malformed FX pair metadata"):
            _extract_pair_codes(good_repr, strict=True)

    @pytest.mark.parametrize("bad_repr", INVALID_KR_REPRESENTATIONS)
    def test_layer1_direct_validation_rejects_kr_currency_pairs(self, bad_repr: str):
        """Layer 1: validate_and_normalize_fx_metadata rejects currency pairs in KR namespace."""
        with pytest.raises(ValueError, match="KR namespace represents ECB key rates and cannot contain currency pairs"):
            validate_and_normalize_fx_metadata(
                entity_code=bad_repr,
                unit="quote_per_base",
                value=1.10,
                require_currencies=False,
            )

    @pytest.mark.parametrize("bad_repr", INVALID_KR_REPRESENTATIONS)
    def test_layer2_data_observation_validation_rejects_kr_currency_pairs(self, bad_repr: str):
        """Layer 2: DataObservation validation rejects currency pairs in KR namespace."""
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
        assert "KR namespace represents ECB key rates and cannot contain currency pairs" in str(exc_info.value)


# =============================================================================
# Workstream D: End-to-End Pipeline & Research Invariance Parity
# =============================================================================


class TestWorkstreamDEndToEndAndResearchParity:
    """Validate full factor pipeline rejection and numerical research invariance parity."""

    @pytest.mark.parametrize(
        "bad_repr",
        [
            "ECB_EUR_USD.extra",
            "FX_EUR_USD_LOGRET__vs__RATE_DIFF_EUR_US_BPS",
            "KR.GBP_USD",
        ],
    )
    def test_layer3_quote_normalization_rejects_bad_entities(self, bad_repr: str):
        """Layer 3: _normalize_fx_quote_to_usd_per_eur rejects malformed namespace representations."""
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
            "FED_USD_EUR.extra",
            "FX_EUR_USD_LOGRET__vs__INVALID_RHS",
            "KR.USD_GBP",
        ],
    )
    def test_layer4_boundary_resolver_rejects_bad_entities(self, bad_repr: str):
        """Layer 4: resolve_canonical_initial_fx rejects malformed entity codes."""
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
            "BOE_EUR_USD.extra",
            "FX_EUR_USD_LOGRET__vs__YIELD_DIFF_US_1M_BPS",
            "KR.EUR.USD",
        ],
    )
    def test_layer5a_factor_panel_rejects_corrupted_raw_observation(self, real_data_panels, bad_repr: str):
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

    @pytest.mark.parametrize(
        "bad_repr",
        [
            "ECB_EUR.extra_USD",
            "FX_EUR_USD_LOGRET__vs__RATE_DIFF_EUR_BORROW_INVALID",
            "KR.GBP.USD",
        ],
    )
    def test_layer5b_factor_panel_rejects_malformed_fx_entity(self, real_data_panels, bad_repr: str):
        """Layer 5b: build_fx_carry_factor_panel rejects malformed fx_entity."""
        _, _, observations = real_data_panels
        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            build_fx_carry_factor_panel(
                observations=observations,
                start_date=date(2020, 1, 1),
                end_date=date(2023, 12, 31),
                fx_entity=bad_repr,
            )

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
