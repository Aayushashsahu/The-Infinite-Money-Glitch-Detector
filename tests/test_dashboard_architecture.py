"""Comprehensive Verification Suite for Phase 5.1 Dashboard Architecture.

Enforces:
1. Artifact Registry Integrity: All 23 JSON artifacts exist and match SHA-256 digests.
2. Tamper Rejection: Corrupted or altered artifacts trigger ArtifactIntegrityError.
3. Missing File Handling: Non-existent paths trigger ArtifactNotFoundError.
4. Schema Validation: Strongly typed deserialization across all Phase 4 and Phase 3 models.
5. Numerical Parity: Exact equivalence <= 10^-9 against authoritative research baselines.
6. Invariant Research States: Portfolio holdout is explicitly UNAVAILABLE (is_available=False).
7. Database Read-Only Enforcement: SQLite URI ?mode=ro & PRAGMA query_only = ON reject writes.
8. Architectural Boundary Verification: AST inspection verifies zero calculation engine imports.
9. Visual & Formatting Components: Currency, percent, bps formatting and Plotly theme.
"""

from __future__ import annotations

import ast
from pathlib import Path
import sqlite3
import tempfile
import pytest

from dashboard.artifacts.db import (
    AUTHORITATIVE_DB_SHA256,
    get_database_metadata,
    get_readonly_db_connection,
    query_readonly,
    verify_db_sha256,
)
from dashboard.artifacts.integrity import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    compute_file_sha256,
    verify_file_sha256,
)
from dashboard.artifacts.loader import (
    _load_json_cached,
    list_backtest_configs,
    load_availability_audit,
    load_backtest_config,
    load_calibration_report,
    load_calendar_validation,
    load_convergence_report,
    load_correlation_stress_comparison,
    load_factor_holdout_diagnostics,
    load_factor_panel_manifest,
    load_funding_sensitivity,
    load_holdout_diagnostics,
    load_model_comparison,
    load_monte_carlo_result,
    load_portfolio_holdout_diagnostics,
    load_simulation_manifest,
    load_stress_test_results,
    verify_all_registered_artifacts,
)
from dashboard.artifacts.registry import (
    TOTAL_REGISTERED_ARTIFACTS,
    UnknownArtifactError,
    get_artifact_metadata,
    list_registered_artifacts,
    resolve_artifact_path,
)
from dashboard.components.metrics_card import format_bps, format_currency, format_percent
from dashboard.components.plots.base import (
    FONT_FAMILY,
    MONOSPACE_FONT,
    PALETTE,
    apply_institutional_theme,
    create_empty_figure,
)
import plotly.graph_objects as go


# ==============================================================================
# 1. Cryptographic Integrity & Registry Tests
# ==============================================================================


class TestArtifactIntegrity:
    """Verify cryptographic integrity and registration for all 23 authoritative artifacts."""

    def test_total_registered_artifact_count(self) -> None:
        """Total registered artifacts must equal exactly 23 (17 Phase 4 + 6 Phase 3)."""
        artifacts = list_registered_artifacts()
        assert len(artifacts) == 23
        assert TOTAL_REGISTERED_ARTIFACTS == 23

    def test_all_23_registered_artifacts_exist_and_match_sha256(self) -> None:
        """Every registered artifact must exist on disk and match its recorded SHA-256 digest."""
        verified = verify_all_registered_artifacts()
        assert len(verified) == 23
        for artifact_id, (file_path, sha256_hash) in verified.items():
            assert file_path.is_file(), f"Artifact file missing: {file_path}"
            assert len(sha256_hash) == 64, f"Invalid SHA-256 hash length for {artifact_id}"

    def test_tampered_artifact_raises_integrity_error(self) -> None:
        """Modifying a single byte in an artifact payload must raise ArtifactIntegrityError."""
        meta = get_artifact_metadata("calibration_report")
        file_path, expected_hash = resolve_artifact_path(meta.artifact_id, meta.version)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tampered_path = Path(tmp_dir) / "tampered_artifact.json"
            content = file_path.read_bytes()
            # Tamper with byte content
            tampered_content = content + b"\n/* tampered */"
            tampered_path.write_bytes(tampered_content)

            with pytest.raises(ArtifactIntegrityError) as exc_info:
                verify_file_sha256(tampered_path, expected_hash)
            assert "integrity verification failed" in str(exc_info.value).lower()

    def test_missing_artifact_raises_not_found_error(self) -> None:
        """Accessing a non-existent artifact file path must raise ArtifactNotFoundError."""
        with pytest.raises(ArtifactNotFoundError):
            compute_file_sha256(Path("data/results/non_existent_artifact_xyz.json"))

        with pytest.raises(ArtifactNotFoundError):
            _load_json_cached(
                "data/results/non_existent_artifact_xyz.json",
                "a" * 64,
                "a" * 64,
            )

    def test_unknown_artifact_id_raises_unknown_artifact_error(self) -> None:
        """Requesting an unregistered artifact ID must raise UnknownArtifactError."""
        with pytest.raises(UnknownArtifactError):
            get_artifact_metadata("unregistered_phantom_artifact")


# ==============================================================================
# 2. Schema Validation & Strongly Typed Loaders
# ==============================================================================


class TestArtifactSchemasAndLoaders:
    """Verify that all artifacts deserialize into valid, typed Pydantic models."""

    def test_load_calibration_report(self) -> None:
        report = load_calibration_report()
        assert report.calibration_sample_size == 989
        assert report.calibration_transition_count == 989
        assert report.calibration_level_count == 990
        assert len(report.factor_names) == 4
        assert report.is_sufficient is True

    def test_load_factor_panel_manifest(self) -> None:
        manifest = load_factor_panel_manifest()
        assert len(manifest.factors) == 4
        assert manifest.aligned_level_count == 1237
        assert manifest.transition_count == 1236

    def test_load_model_comparison(self) -> None:
        models = load_model_comparison()
        assert len(models) == 6
        model_names = [m.model_name for m in models]
        assert "Multivariate Gaussian" in model_names
        assert "Moving-Block Bootstrap (20d)" in model_names
        assert "Multivariate Student-t" in model_names
        assert "Regime-Conditioned Bootstrap" in model_names

    def test_load_monte_carlo_results(self) -> None:
        for model in ("gaussian", "bootstrap", "student_t", "regime"):
            res = load_monte_carlo_result(model)
            assert res.data_classification == "simulated"
            assert res.is_executable_strategy is False
            assert "total_return" in res.distribution_metrics
            assert "representative_paths" in res.model_dump()

    def test_load_convergence_report(self) -> None:
        conv = load_convergence_report()
        assert conv.is_converged is True
        assert len(conv.checkpoints) >= 4
        assert conv.final_standard_error > 0.0

    def test_load_stress_test_results(self) -> None:
        scenarios = load_stress_test_results()
        assert len(scenarios) == 19
        categories = {s.category for s in scenarios}
        assert "baseline" in categories
        assert "compound" in categories
        assert "single_factor" in categories
        assert "correlation" in categories
        assert "liquidity" in categories
        for s in scenarios:
            assert s.reconciliation_exact is True

    def test_load_correlation_stress_comparison(self) -> None:
        comp = load_correlation_stress_comparison()
        assert comp.baseline_model == "Empirical Calibration Correlation"
        assert comp.stressed_model == "Zero Off-Diagonal Decoupled Correlation"
        assert comp.num_paths == 1000

    def test_load_funding_sensitivity(self) -> None:
        funding = load_funding_sensitivity()
        assert len(funding.scenarios) == 4
        assert len(funding.funding_conventions) == 2
        assert funding.shocks_bps == [0, 100, 300, 500]
        for s in funding.scenarios:
            assert abs((s.floating_total_return - s.fixed_total_return) - s.return_difference) < 1e-9

    def test_load_holdout_diagnostics(self) -> None:
        holdout = load_holdout_diagnostics()
        assert holdout.holdout_year == 2024
        assert holdout.holdout_days == 247
        assert holdout.volatility_ratio > 0.0
        assert "FX_EUR_USD_LOGRET__vs__RATE_DIFF_EUR_BORROW_BPS" in holdout.correlation_shifts

    def test_load_factor_holdout_diagnostics(self) -> None:
        factor_holdout = load_factor_holdout_diagnostics()
        assert factor_holdout.holdout_year == 2024
        assert factor_holdout.num_predictive_paths == 1000

    def test_load_portfolio_holdout_diagnostics_unavailable(self) -> None:
        """Portfolio holdout must be explicitly UNAVAILABLE with is_available=False."""
        portfolio_holdout = load_portfolio_holdout_diagnostics()
        assert portfolio_holdout.status == "UNAVAILABLE"
        assert portfolio_holdout.is_available is False
        assert "simulated_research_proxy" in portfolio_holdout.reason.lower()

    def test_load_availability_audit(self) -> None:
        audit = load_availability_audit()
        assert audit.is_reconciled is True
        assert audit.missing_evidence_count == 0
        assert audit.retrospective_count == 176
        assert audit.genuine_observations_included == 8900
        assert "FP.CPI.TOTL.ZG" in audit.factor_breakdown

    def test_load_calendar_validation(self) -> None:
        cal = load_calendar_validation()
        assert cal.weekend_3day_accrual_verified is True
        assert cal.holiday_accrual_verified is True
        assert cal.tenor_30day_maturity_verified is True
        assert cal.independent_numerical_accrual_verified is True

    def test_load_simulation_manifest(self) -> None:
        manifest = load_simulation_manifest()
        assert manifest.random_seed == 42
        assert manifest.rng_bit_generator == "PCG64"
        assert manifest.database_sha256 == AUTHORITATIVE_DB_SHA256

    def test_load_all_phase_3_backtest_configs(self) -> None:
        configs = list_backtest_configs()
        assert len(configs) == 6
        config_dict = dict(configs)

        # Config 2 (Estimated Schedule) is our primary empirical backtest baseline
        c2 = config_dict["config_2_estimated_schedule"]
        assert c2.strategy_status == "RESEARCH_PROXY"
        assert c2.can_simulate is True
        assert c2.performance is not None
        assert c2.attribution is not None
        assert c2.attribution.reconciliation_exact is True

        # Config 6 (Covered Rejection) must be rejected
        c6 = config_dict["config_6_covered_rejection"]
        assert c6.can_simulate is False
        assert c6.is_executable_strategy is False
        assert c6.unsupported_reason is not None


# ==============================================================================
# 3. Numerical Parity Tests (<= 10^-9 Tolerance)
# ==============================================================================


class TestNumericalParity:
    """Verify that extracted dashboard metrics exactly match authoritative research numbers."""

    TOLERANCE = 1e-9

    def test_config_2_performance_parity(self) -> None:
        c2 = load_backtest_config("config_2_estimated_schedule")
        perf = c2.performance
        assert perf is not None

        # Authoritative Phase 3.2.2.3.3 metrics
        assert abs(perf.cumulative_net_profit - 2890.2219488248384) <= self.TOLERANCE
        assert abs(perf.total_return - 0.028902219488248383) <= self.TOLERANCE
        assert abs(perf.annualized_return - 0.005714752762239206) <= self.TOLERANCE
        assert abs(perf.annualized_volatility - 0.029753378682408467) <= self.TOLERANCE
        assert abs(perf.max_drawdown - (-0.035187401528777085)) <= self.TOLERANCE

    def test_config_2_attribution_parity(self) -> None:
        c2 = load_backtest_config("config_2_estimated_schedule")
        attr = c2.attribution
        assert attr is not None

        assert abs(attr.pure_gross_profit_a - (-218.7375357199321)) <= self.TOLERANCE
        assert abs(attr.investment_yield_gain_a - 5437.0294066572915) <= self.TOLERANCE
        assert abs(attr.total_financing_costs_a - 3683.868493352893) <= self.TOLERANCE
        assert abs(attr.total_frictions_a - 910.0418183389443) <= self.TOLERANCE
        assert abs(attr.total_cash_interest_a - 7702.869796236577) <= self.TOLERANCE
        assert abs(attr.reconciliation_residual_a - 3.092281986027956e-11) <= self.TOLERANCE
        assert attr.reconciliation_exact is True

    def test_gaussian_monte_carlo_parity(self) -> None:
        models = {m.model_name: m for m in load_model_comparison()}
        gaussian = models["Multivariate Gaussian"]

        assert abs(gaussian.median_return - 0.017475607948999095) <= self.TOLERANCE
        assert abs(gaussian.mean_return - 0.019788944121494532) <= self.TOLERANCE
        assert abs(gaussian.prob_loss - 0.319) <= self.TOLERANCE
        assert abs(gaussian.var_95 - (-0.045319275545030194)) <= self.TOLERANCE
        assert abs(gaussian.cvar_95 - (-0.059711662024820186)) <= self.TOLERANCE
        assert abs(gaussian.max_drawdown_median - (-0.036636081356625036)) <= self.TOLERANCE
        assert abs(gaussian.max_drawdown_p95 - (-0.0718089308898935)) <= self.TOLERANCE

    def test_calibration_and_audit_counts_parity(self) -> None:
        cal = load_calibration_report()
        audit = load_availability_audit()

        assert cal.calibration_sample_size == 989
        assert cal.calibration_transition_count == 989
        assert cal.calibration_level_count == 990
        assert audit.genuine_observations_included == 8900
        assert audit.retrospective_count == 176
        assert audit.synthetic_observations_excluded == 8


# ==============================================================================
# 4. Database Read-Only Access & Integrity Tests
# ==============================================================================


class TestDatabaseReadOnlyAccess:
    """Verify strictly read-only SQLite connectivity and digest matching."""

    def test_db_sha256_matches_authoritative_digest(self) -> None:
        verified_hash = verify_db_sha256()
        assert verified_hash == AUTHORITATIVE_DB_SHA256

    def test_database_metadata_queries_successfully(self) -> None:
        meta = get_database_metadata()
        assert meta["total_observations"] == 8908
        assert meta["total_sources"] == 5
        assert "data_observation" in meta["tables"]
        assert "currency_pair" in meta["tables"]

    def test_readonly_query_helper(self) -> None:
        rows = query_readonly("SELECT code, name FROM currency ORDER BY code ASC;")
        assert len(rows) == 2
        symbols = [r["code"] for r in rows]
        assert "EUR" in symbols
        assert "USD" in symbols

    def test_database_rejects_insert_mutation(self) -> None:
        conn = get_readonly_db_connection()
        with pytest.raises(sqlite3.OperationalError) as exc_info:
            conn.execute("INSERT INTO currency (code, name) VALUES ('XYZ', 'Test');")
        assert "readonly" in str(exc_info.value).lower()
        conn.close()

    def test_database_rejects_ddl_table_creation(self) -> None:
        conn = get_readonly_db_connection()
        with pytest.raises(sqlite3.OperationalError) as exc_info:
            conn.execute("CREATE TABLE attempt_tamper (id INT);")
        assert "readonly" in str(exc_info.value).lower()
        conn.close()


# ==============================================================================
# 5. Architectural Boundary & Zero-Recomputation AST Audit
# ==============================================================================


class TestArchitecturalBoundaries:
    """Enforce strict read-only boundary: zero calculation/simulation engine imports."""

    PROHIBITED_MODULES = {
        "simulation.monte_carlo.engine",
        "simulation.monte_carlo.regime",
        "backtesting.engine",
        "scipy.optimize",
    }

    def test_dashboard_source_contains_no_prohibited_imports(self) -> None:
        """Scan all Python modules in src/dashboard/ using AST to verify read-only boundaries."""
        dashboard_dir = Path("src/dashboard")
        assert dashboard_dir.is_dir()

        py_files = list(dashboard_dir.rglob("*.py"))
        assert len(py_files) >= 8

        for py_file in py_files:
            content = py_file.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(py_file))

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for prohibited in self.PROHIBITED_MODULES:
                            assert not alias.name.startswith(prohibited), (
                                f"Prohibited module '{alias.name}' imported in {py_file} (line {node.lineno}). "
                                "Dashboard must remain strictly read-only with zero engine recalculations."
                            )
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    for prohibited in self.PROHIBITED_MODULES:
                        assert not mod.startswith(prohibited), (
                            f"Prohibited import from '{mod}' in {py_file} (line {node.lineno}). "
                            "Dashboard must remain strictly read-only with zero engine recalculations."
                        )


# ==============================================================================
# 6. UI Formatting & Plotly Theme Tests
# ==============================================================================


class TestUIComponentsAndVisualEngine:
    """Verify number formatters and Plotly institutional styling."""

    def test_format_currency(self) -> None:
        assert format_currency(2890.22) == "+€2,890.22"
        assert format_currency(-11077.59) == "-€11,077.59"
        assert format_currency(0.0) == "€0.00"
        assert format_currency(None) == "N/A"

    def test_format_percent(self) -> None:
        assert format_percent(0.028902) == "+2.89%"
        assert format_percent(-0.035226) == "-3.52%"
        assert format_percent(0.0175, show_sign=False) == "1.75%"
        assert format_percent(None) == "N/A"

    def test_format_bps(self) -> None:
        assert format_bps(0.0093) == "+93.0 bps"
        assert format_bps(-0.0025) == "-25.0 bps"
        assert format_bps(None) == "N/A"

    def test_apply_institutional_theme(self) -> None:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=[1, 2, 3], y=[10, 20, 30], mode="lines", name="Test"))
        apply_institutional_theme(
            fig,
            title="Institutional Test Plot",
            x_title="Date",
            y_title="Return",
            height=400,
        )

        layout = fig.layout
        assert layout.title.text == "<b>Institutional Test Plot</b>"
        assert layout.height == 400
        assert layout.paper_bgcolor == PALETTE["background_paper"]
        assert layout.xaxis.gridcolor == PALETTE["grid"]
        assert layout.font.family == FONT_FAMILY
        assert layout.xaxis.tickfont.family == MONOSPACE_FONT

    def test_create_empty_figure(self) -> None:
        empty_fig = create_empty_figure("No holdout data available")
        assert len(empty_fig.layout.annotations) == 1
        assert empty_fig.layout.annotations[0].text == "No holdout data available"
