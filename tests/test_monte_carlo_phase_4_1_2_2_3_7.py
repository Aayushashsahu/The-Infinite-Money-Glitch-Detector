"""Phase 4.1.2.2.3.7 Regression Test Suite: FX Identifier Exception Precedence & Final Sign-Off.

Mathematics first. Data second. Prediction third. AI last.

Validates:
1. Slash-delimited pair syntax takes strict precedence over any namespace prefix or dot exemption.
2. Malformed identifiers are rejected across all operational layers:
   - 'USD/EUR.'
   - 'EUR/USD.extra'
   - 'FX_EUR/USD/'
   - 'EUR_USD.extra'
   - 'EUR_USD_'
   - 'USD/EUR.' combined with explicit EUR/USD currencies.
   - 'EUR/USD.extra' combined with explicit currencies and QUOTE_PER_BASE.
3. Five validation layers tested:
   - Layer 1: validate_and_normalize_fx_metadata().
   - Layer 2: DataObservation validation.
   - Layer 3: _normalize_fx_quote_to_usd_per_eur().
   - Layer 4: resolve_canonical_initial_fx().
   - Layer 5: build_fx_carry_factor_panel() end-to-end (raw obs & fx_entity).
4. Legitimate identifiers preserved:
   - 'EUR/USD', 'USD/EUR', 'EUR_USD', 'USD_EUR'
   - 'KR.MRR_FR.LEV', 'ECB_EA', 'FX_EUR_USD_LOGRET', 'IR_USD_1M'
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


INVALID_PRECEDENCE_REPRESENTATIONS = [
    "USD/EUR.",
    "EUR/USD.extra",
    "FX_EUR/USD/",
    "EUR_USD.extra",
    "EUR_USD_",
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
# Workstream A: Precedence & Dotted Identifier Validation
# =============================================================================


class TestWorkstreamAPrecedenceValidation:
    """Test slash precedence and dotted/prefix identifier rejection across all 5 layers."""

    @pytest.mark.parametrize("bad_repr", INVALID_PRECEDENCE_REPRESENTATIONS)
    def test_1_direct_validation_rejects_malformed_representations(self, bad_repr: str):
        """Layer 1: validate_and_normalize_fx_metadata rejects malformed representations."""
        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            validate_and_normalize_fx_metadata(
                entity_code=bad_repr,
                unit="quote_per_base",
                value=1.10,
                require_currencies=False,
            )

    @pytest.mark.parametrize("bad_repr", INVALID_PRECEDENCE_REPRESENTATIONS)
    def test_2_direct_validation_with_explicit_currencies_rejects_malformed_representations(self, bad_repr: str):
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

    def test_2b_usd_eur_dot_with_explicit_eur_usd_fails_closed(self):
        """USD/EUR. combined with explicit EUR/USD currencies fails closed with ValueError."""
        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            validate_and_normalize_fx_metadata(
                base_currency="EUR",
                quote_currency="USD",
                entity_code="USD/EUR.",
                unit="USD_per_EUR",
            )

    def test_2c_eur_usd_dot_extra_with_explicit_quote_per_base_fails_closed(self):
        """EUR/USD.extra combined with explicit currencies and QUOTE_PER_BASE fails closed."""
        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            validate_and_normalize_fx_metadata(
                base_currency="EUR",
                quote_currency="USD",
                quote_convention=QuoteConvention.QUOTE_PER_BASE,
                entity_code="EUR/USD.extra",
                unit="USD_per_EUR",
            )

    @pytest.mark.parametrize("bad_repr", INVALID_PRECEDENCE_REPRESENTATIONS)
    def test_3_data_observation_validation_rejects_malformed_representations(self, bad_repr: str):
        """Layer 2: DataObservation validation fails closed for malformed FX exchange rate observations."""
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

    @pytest.mark.parametrize("bad_repr", INVALID_PRECEDENCE_REPRESENTATIONS)
    def test_4_quote_normalization_rejects_malformed_raw_observation(self, bad_repr: str):
        """Layer 3: _normalize_fx_quote_to_usd_per_eur rejects malformed entity codes."""
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

    @pytest.mark.parametrize("bad_repr", INVALID_PRECEDENCE_REPRESENTATIONS)
    def test_5_holdout_boundary_resolver_rejects_malformed_provenance_key(self, bad_repr: str):
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

    @pytest.mark.parametrize("bad_repr", INVALID_PRECEDENCE_REPRESENTATIONS)
    def test_6_end_to_end_factor_panel_rejects_malformed_raw_observation(self, real_data_panels, bad_repr: str):
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

    @pytest.mark.parametrize("bad_repr", INVALID_PRECEDENCE_REPRESENTATIONS)
    def test_7_end_to_end_factor_panel_rejects_malformed_fx_entity(self, real_data_panels, bad_repr: str):
        """Layer 5b: build_fx_carry_factor_panel rejects malformed fx_entity."""
        _, _, observations = real_data_panels
        with pytest.raises(ValueError, match="Malformed pair-like FX identifier"):
            build_fx_carry_factor_panel(
                observations=observations,
                start_date=date(2020, 1, 1),
                end_date=date(2023, 12, 31),
                fx_entity=bad_repr,
            )

    def test_8_preserve_legitimate_identifiers(self):
        """Preserve valid pairs and legitimate non-pair entities."""
        # Valid pairs return (base, quote)
        assert _extract_pair_codes("EUR/USD") == ("EUR", "USD")
        assert _extract_pair_codes("USD/EUR") == ("USD", "EUR")
        assert _extract_pair_codes("EUR_USD") == ("EUR", "USD")
        assert _extract_pair_codes("USD_EUR") == ("USD", "EUR")

        # Legitimate non-pair identifiers return None under strict=False
        assert _extract_pair_codes("KR.MRR_FR.LEV", strict=False) is None
        assert _extract_pair_codes("ECB_EA", strict=False) is None
        assert _extract_pair_codes("FX_EUR_USD_LOGRET", strict=False) is None
        assert _extract_pair_codes("IR_USD_1M", strict=False) is None

        # When strict=True, non-pairs fail closed with descriptive ValueError
        for non_pair in ["KR.MRR_FR.LEV", "ECB_EA", "FX_EUR_USD_LOGRET", "IR_USD_1M"]:
            with pytest.raises(ValueError, match="Malformed FX pair metadata"):
                _extract_pair_codes(non_pair, strict=True)


# =============================================================================
# Workstream B: Test Fixture Integrity
# =============================================================================


class TestWorkstreamBTestFixtureIntegrity:
    """Verify conftest.py make_obs() scoping and validation integrity."""

    def test_1_normal_observations_use_standard_validation(self):
        """Normal make_obs() calls use standard DataObservation validation."""
        from conftest import make_obs

        # Standard valid observation creates successfully
        obs = make_obs(kind=ObservationKind.MACRO_INDICATOR, value=2.5)
        assert isinstance(obs, DataObservation)
        assert obs.value == 2.5

        # Malformed observation without special scoping fails closed with ValidationError
        with pytest.raises(ValidationError):
            make_obs(kind=ObservationKind.EXCHANGE_RATE, entity_code="USD/EUR.")

    def test_2_us_brl_explicit_bypass_preserved_for_quality_pipeline(self):
        """US/BRL is specifically bypassed for data-quality pipeline flag detection tests."""
        from conftest import make_obs

        # US/BRL constructs without raising ValidationError
        obs_bad = make_obs(kind=ObservationKind.EXCHANGE_RATE, entity_code="US/BRL")
        assert isinstance(obs_bad, DataObservation)
        assert obs_bad.entity_code == "US/BRL"


# =============================================================================
# Workstream C & D: Research Parity & Date Boundary Invariance
# =============================================================================


class TestWorkstreamDResearchParityAndLineage:
    """Verify research invariance, date boundaries, and UNAVAILABLE portfolio holdout."""

    def test_1_reconcile_calibration_and_holdout_exact_dates(self, real_data_panels):
        """Exact empirical window dates match the reconciled closure specification."""
        calib_panel, holdout_panel, _ = real_data_panels

        # Calibration window
        assert calib_panel.aligned_level_count == 990
        assert calib_panel.transition_count == 989
        assert calib_panel.first_level_date == date(2020, 1, 6)
        assert calib_panel.last_level_date == date(2023, 12, 29)
        assert calib_panel.first_transition_date == date(2020, 1, 7)
        assert calib_panel.last_transition_date == date(2023, 12, 29)

        # Holdout window
        assert holdout_panel.aligned_level_count == 248
        assert holdout_panel.transition_count == 247
        assert holdout_panel.first_level_date == date(2023, 12, 29)
        assert holdout_panel.last_level_date == date(2024, 12, 31)
        assert holdout_panel.first_transition_date == date(2024, 1, 2)
        assert holdout_panel.last_transition_date == date(2024, 12, 31)

        # Total unique aligned level dates accounting for shared 2023-12-29 boundary
        unique_level_dates = set(calib_panel.level_dates).union(set(holdout_panel.level_dates))
        assert len(unique_level_dates) == 1237
        assert calib_panel.transition_count + holdout_panel.transition_count == 1236

    def test_2_reconcile_covariance_and_correlation_matrices(self, real_data_panels):
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

    def test_3_reconcile_holdout_correlation_shifts(self, real_data_panels):
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

    def test_4_portfolio_holdout_diagnostics_remain_strictly_unavailable(self):
        """Portfolio holdout diagnostics remain strictly UNAVAILABLE."""
        diag = evaluate_portfolio_holdout_diagnostics()
        assert diag.status == "UNAVAILABLE"
        assert diag.is_available is False
        assert "SIMULATED_RESEARCH_PROXY" in diag.reason
