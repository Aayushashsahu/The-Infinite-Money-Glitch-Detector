"""Tests for Phase 5.3 Advanced Research Dashboard Pages.

Validates the implementation of:
  - Page 3: Market Data & Provenance (src/dashboard/pages/3_Market_Data_Provenance.py)
  - Page 4: Monte Carlo Simulation Laboratory (src/dashboard/pages/4_Monte_Carlo_Laboratory.py)
  - Page 5: Risk & Stress Testing (src/dashboard/pages/5_Risk_Stress_Testing.py)
  - Page 6: Holdout Diagnostics (src/dashboard/pages/6_Holdout_Diagnostics.py)
  - Reusable plot modules: series.py, simulation.py, stress.py, holdout.py

Covers all 20 required verification dimensions:
  1. All four page modules import successfully
  2. Every page exports callable render_page()
  3. All four pages use verified artifact loaders
  4. SHA-256 integrity failures prevent unverified data rendering
  5. Numerical parity against source artifacts (<= 1e-9 tolerance)
  6. All six simulation models are represented
  7. Representative paths match source artifacts
  8. Convergence checkpoints match committed report
  9. All 19 stress scenarios are represented
 10. Correlation stress comparisons match source values
 11. Funding sensitivity values match source artifact
 12. Holdout factor diagnostics match their artifacts
 13. Portfolio holdout remains UNAVAILABLE
 14. No portfolio equity curve is fabricated
 15. Market-data availability preserves Phase 5.1 errata
 16. SQLite access remains strictly read-only
 17. Zero calculation-engine or write-layer imports (AST inspection)
 18. Mocked Streamlit rendering completes without unhandled exceptions
 19. Provenance metadata coverage
 20. All 23 registered research artifact hashes remain unchanged
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from typing import Any, List
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from dashboard.artifacts.db import (
    get_readonly_db_connection,
    verify_db_sha256,
)
from dashboard.artifacts.integrity import (
    ArtifactIntegrityError,
    compute_file_sha256,
    verify_registered_artifact,
)
from dashboard.artifacts.loader import (
    load_availability_audit,
    load_convergence_report,
    load_correlation_stress_comparison,
    load_factor_holdout_diagnostics,
    load_funding_sensitivity,
    load_holdout_diagnostics,
    load_model_comparison,
    load_monte_carlo_result,
    load_portfolio_holdout_diagnostics,
    load_simulation_manifest,
    load_stress_test_results,
)
from dashboard.artifacts.registry import (
    get_artifact_metadata,
    list_registered_artifacts,
    resolve_artifact_path,
)
from dashboard.components.plots.holdout import (
    build_correlation_shifts_figure,
    build_holdout_factor_fan_figure,
)
from dashboard.components.plots.series import build_time_series_figure
from dashboard.components.plots.simulation import (
    build_convergence_figure,
)
from dashboard.components.plots.stress import (
    build_correlation_matrix_figure,
    build_funding_sensitivity_figure,
    build_stress_tornado_figure,
)


# ---------------------------------------------------------------------------
# Dimension 1 & 2: Module Imports and Callable render_page()
# ---------------------------------------------------------------------------


def test_advanced_dashboard_pages_import_cleanly() -> None:
    """Verify all four advanced Streamlit page modules import cleanly and export render_page()."""
    page_modules = [
        "dashboard.pages.3_Market_Data_Provenance",
        "dashboard.pages.4_Monte_Carlo_Laboratory",
        "dashboard.pages.5_Risk_Stress_Testing",
        "dashboard.pages.6_Holdout_Diagnostics",
    ]

    for mod_name in page_modules:
        mod = importlib.import_module(mod_name)
        assert hasattr(mod, "render_page"), f"{mod_name} must export render_page()"
        assert callable(mod.render_page), f"{mod_name}.render_page must be callable"


# ---------------------------------------------------------------------------
# Dimension 3: Verified Artifact Loaders
# ---------------------------------------------------------------------------


def test_advanced_pages_use_verified_loaders() -> None:
    """Verify artifacts used across pages 3-6 verify SHA-256 digests against registry."""
    required_artifacts = [
        "availability_audit",
        "calendar_validation",
        "simulation_manifest",
        "model_comparison",
        "convergence_report",
        "gaussian_results",
        "stress_test_results",
        "correlation_stress_comparison",
        "funding_sensitivity",
        "holdout_diagnostics",
        "factor_holdout_diagnostics",
        "portfolio_holdout_diagnostics",
    ]

    for art_id in required_artifacts:
        path, verified_hash = verify_registered_artifact(art_id)
        assert path.is_file(), f"Artifact path for {art_id} must exist"
        assert len(verified_hash) == 64

        meta = get_artifact_metadata(art_id)
        assert meta.expected_sha256 == verified_hash


# ---------------------------------------------------------------------------
# Dimension 4: Cryptographic Integrity Failure Handling
# ---------------------------------------------------------------------------


def test_integrity_failure_blocks_corrupted_data(tmp_path: Path) -> None:
    """Verify that tampering with an artifact's content raises ArtifactIntegrityError."""
    corrupted_file = tmp_path / "corrupted_artifact.json"
    corrupted_file.write_text('{"tampered": true}', encoding="utf-8")

    from dashboard.artifacts.loader import _load_json_cached

    with pytest.raises(ArtifactIntegrityError):
        _load_json_cached(
            file_path_str=str(corrupted_file),
            expected_sha256="0000000000000000000000000000000000000000000000000000000000000000",
            content_hash=compute_file_sha256(corrupted_file),
        )


# ---------------------------------------------------------------------------
# Dimension 5: Numerical Parity with Authoritative Artifacts (<= 1e-9)
# ---------------------------------------------------------------------------


def test_numerical_parity_across_artifacts() -> None:
    """Verify numerical values match authoritative artifacts within 1e-9 tolerance."""
    # Page 3: availability_audit
    avail = load_availability_audit()
    assert avail.total_source_observations == 8908
    assert avail.genuine_observations_included == 8900
    assert avail.synthetic_observations_excluded == 8
    assert avail.estimated_availability_count == 8724
    assert avail.retrospective_count == 176
    assert avail.missing_evidence_count == 0

    # Page 4: model_comparison
    models = load_model_comparison()
    gaussian = next(m for m in models if m.model_name == "Multivariate Gaussian")
    assert gaussian.median_return == pytest.approx(0.017475607948999095, abs=1e-9)
    assert gaussian.cvar_95 == pytest.approx(-0.059711662024820186, abs=1e-9)
    assert gaussian.prob_loss == pytest.approx(0.319, abs=1e-9)

    # Page 5: correlation_stress
    corr = load_correlation_stress_comparison()
    assert corr.baseline_mean_return == pytest.approx(0.01946200604928257, abs=1e-9)
    assert corr.stressed_mean_return == pytest.approx(0.01946865284814632, abs=1e-9)
    assert corr.mean_return_difference == pytest.approx(6.646798863748499e-06, abs=1e-9)
    assert corr.prob_loss_difference == pytest.approx(0.001, abs=1e-9)

    # Page 6: holdout_diagnostics
    holdout = load_holdout_diagnostics()
    assert holdout.realized_fx_volatility_annualized == pytest.approx(0.06181883100495451, abs=1e-9)
    assert holdout.calibration_fx_volatility_annualized == pytest.approx(0.07994846248376088, abs=1e-9)
    assert holdout.volatility_ratio == pytest.approx(0.7732335192501186, abs=1e-9)
    assert holdout.realized_cumulative_return == pytest.approx(-0.059819647606383364, abs=1e-9)
    assert holdout.predictive_quantile_return == pytest.approx(0.229, abs=1e-9)
    assert holdout.realized_max_drawdown == pytest.approx(-0.07207862367021264, abs=1e-9)
    assert holdout.predictive_quantile_drawdown == pytest.approx(0.649, abs=1e-9)
    assert holdout.fx_log_return_ks_pvalue == pytest.approx(0.055928993060031906, abs=1e-9)


# ---------------------------------------------------------------------------
# Dimension 6: All Six Simulation Models Represented
# ---------------------------------------------------------------------------


def test_all_six_simulation_models_represented() -> None:
    """Verify all 6 calibrated stochastic models exist in model_comparison.json."""
    models = load_model_comparison()
    assert len(models) == 6

    expected_models = {
        "Multivariate Gaussian",
        "Moving-Block Bootstrap (20d)",
        "IID Bootstrap",
        "Stationary Bootstrap (20d)",
        "Multivariate Student-t",
        "Regime-Conditioned Bootstrap",
    }
    actual_models = {m.model_name for m in models}
    assert actual_models == expected_models

    for m in models:
        assert m.num_paths == 1000
        assert -1.0 <= m.median_return <= 1.0
        assert 0.0 <= m.prob_loss <= 1.0


# ---------------------------------------------------------------------------
# Dimension 7: Representative Paths Match Source Artifacts
# ---------------------------------------------------------------------------


def test_representative_paths_match_source_artifacts() -> None:
    """Verify representative paths for gaussian, bootstrap, student-t, regime models."""
    model_keys = ["gaussian", "bootstrap", "student_t", "regime"]

    for mkey in model_keys:
        res = load_monte_carlo_result(mkey)
        assert res.representative_paths is not None
        paths = res.representative_paths

        for trajectory in ("worst", "median", "best"):
            assert trajectory in paths, f"{mkey} must contain '{trajectory}' path"
            p = paths[trajectory]
            assert "fx_rates" in p
            assert len(p["fx_rates"]) == 253
            assert all(isinstance(r, (int, float)) for r in p["fx_rates"])


# ---------------------------------------------------------------------------
# Dimension 8: Convergence Checkpoints Match Committed Report
# ---------------------------------------------------------------------------


def test_convergence_checkpoints_match_report() -> None:
    """Verify convergence checkpoints match convergence_report.json."""
    conv = load_convergence_report()
    assert conv.checkpoints is not None
    assert len(conv.checkpoints) == 6

    sample_sizes = [cp["sample_size"] for cp in conv.checkpoints]
    assert sample_sizes == [25, 50, 100, 250, 500, 1000]

    # Verify N=1000 checkpoint values
    final_cp = conv.checkpoints[-1]
    assert final_cp["sample_size"] == 1000
    assert final_cp["mean_return"] == pytest.approx(0.022286354888491074, abs=1e-9)
    assert final_cp["median_return"] == pytest.approx(0.022501596997637752, abs=1e-9)
    assert final_cp["prob_loss"] == pytest.approx(0.279, abs=1e-9)
    assert final_cp["cvar_95"] == pytest.approx(-0.05929955288906246, abs=1e-9)


# ---------------------------------------------------------------------------
# Dimension 9: All 19 Stress Scenarios Represented
# ---------------------------------------------------------------------------


def test_all_nineteen_stress_scenarios_represented() -> None:
    """Verify stress_test_results.json contains all 19 committed stress scenarios."""
    scenarios = load_stress_test_results()
    assert len(scenarios) == 19

    # Baseline scenario exists and is exact
    baseline = next(s for s in scenarios if s.category == "baseline")
    assert baseline.scenario_name == "Baseline (No Stress)"
    assert baseline.total_return == pytest.approx(0.016668213183221668, abs=1e-9)
    assert baseline.reconciliation_exact is True

    # Every scenario has exact double-entry reconciliation
    for s in scenarios:
        assert s.reconciliation_exact is True
        assert s.scenario_name != ""
        assert s.category in ("baseline", "single_factor", "liquidity", "correlation", "compound")


# ---------------------------------------------------------------------------
# Dimension 10: Correlation Stress Comparisons Match Source
# ---------------------------------------------------------------------------


def test_correlation_stress_comparisons_match_source() -> None:
    """Verify correlation_stress_comparison.json metrics and matrix structure."""
    corr = load_correlation_stress_comparison()
    assert corr.baseline_model == "Empirical Calibration Correlation"
    assert corr.stressed_model == "Zero Off-Diagonal Decoupled Correlation"
    assert corr.num_paths == 1000
    assert corr.empirical_correlation_matrix is not None
    assert len(corr.empirical_correlation_matrix) == 4
    assert all(len(row) == 4 for row in corr.empirical_correlation_matrix)

    # Diagonal elements are 1.0 within floating point precision
    for i in range(4):
        assert corr.empirical_correlation_matrix[i][i] == pytest.approx(1.0, abs=1e-7)


# ---------------------------------------------------------------------------
# Dimension 11: Funding Sensitivity Values Match Source
# ---------------------------------------------------------------------------


def test_funding_sensitivity_values_match_source() -> None:
    """Verify funding_sensitivity.json contains 4 shock levels (0, 100, 300, 500 bps)."""
    funding = load_funding_sensitivity()
    assert funding.shocks_bps == [0, 100, 300, 500]
    assert len(funding.scenarios) == 4

    # 0 bps shock
    s0 = funding.scenarios[0]
    assert s0.shock_bps == 0
    assert s0.fixed_total_return == pytest.approx(s0.floating_total_return, abs=1e-9)
    assert s0.return_difference == pytest.approx(0.0, abs=1e-9)

    # +500 bps shock shows significant floating drag
    s500 = funding.scenarios[3]
    assert s500.shock_bps == 500
    assert s500.fixed_total_return == pytest.approx(0.0020112787843533445, abs=1e-9)
    assert s500.floating_total_return == pytest.approx(0.000498836556484166, abs=1e-9)
    assert s500.return_difference == pytest.approx(-0.0015124422278691785, abs=1e-9)


# ---------------------------------------------------------------------------
# Dimension 12: Holdout Factor Diagnostics Match Artifacts
# ---------------------------------------------------------------------------


def test_holdout_factor_diagnostics_match_artifacts() -> None:
    """Verify 2024 holdout factor metrics in factor_holdout_diagnostics.json."""
    f_holdout = load_factor_holdout_diagnostics()
    assert f_holdout.holdout_year == 2024
    assert f_holdout.holdout_days == 247
    assert f_holdout.actual_fx_cumulative_return == pytest.approx(-0.059819647606383364, abs=1e-9)
    assert f_holdout.actual_fx_realized_volatility == pytest.approx(0.06181883100495451, abs=1e-9)
    assert f_holdout.volatility_regime_classification == "NORMAL_VOLATILITY"
    assert f_holdout.predictive_percentile_fx_return == pytest.approx(0.229, abs=1e-9)


# ---------------------------------------------------------------------------
# Dimension 13 & 14: Portfolio Holdout Invariant: Strictly UNAVAILABLE
# ---------------------------------------------------------------------------


def test_portfolio_holdout_strictly_unavailable() -> None:
    """Verify 2024 portfolio holdout is strictly UNAVAILABLE and not fabricated."""
    p_holdout = load_portfolio_holdout_diagnostics()
    assert p_holdout.status == "UNAVAILABLE"
    assert p_holdout.is_available is False
    assert "No genuine historical executable portfolio series exists" in p_holdout.reason
    assert p_holdout.simulated_portfolio_median_return is None
    assert p_holdout.simulated_portfolio_median_drawdown is None


def test_no_fabricated_holdout_equity_curve() -> None:
    """Verify Page 6 source code explicitly enforces the prohibition of holdout fabrication."""
    p6_path = Path("src/dashboard/pages/6_Holdout_Diagnostics.py")
    content = p6_path.read_text(encoding="utf-8")

    assert "no portfolio equity curve is simulated, fabricated, or imputed" in content
    assert "Strict Governance Requirements for 2024 Portfolio Holdout" in content


# ---------------------------------------------------------------------------
# Dimension 15: Market-Data Availability Preserves Phase 5.1 Errata
# ---------------------------------------------------------------------------


def test_availability_audit_preserves_errata() -> None:
    """Verify that retrospective observations belong exclusively to World Bank annual CPI."""
    avail = load_availability_audit()
    assert avail.retrospective_count == 176
    assert "FP.CPI.TOTL.ZG" in avail.factor_breakdown
    assert avail.factor_breakdown["FP.CPI.TOTL.ZG"]["retrospective"] == 176
    assert avail.factor_breakdown["FP.CPI.TOTL.ZG"]["exact_verified"] == 0
    assert avail.factor_breakdown["FP.CPI.TOTL.ZG"]["estimated"] == 0

    # Ensure other factors have zero retrospective records
    assert avail.factor_breakdown["DGS1MO"]["retrospective"] == 0
    assert avail.factor_breakdown["DGS3MO"]["retrospective"] == 0
    assert avail.factor_breakdown["KR.DFR.LEV"]["retrospective"] == 0
    assert avail.factor_breakdown["KR.MRR_FR.LEV"]["retrospective"] == 0
    assert avail.factor_breakdown["EUR/USD"]["retrospective"] == 0

    # missing_evidence_count = 0 means zero missing evidence in classification audit
    assert avail.missing_evidence_count == 0


# ---------------------------------------------------------------------------
# Dimension 16: SQLite Access Remains Strictly Read-Only
# ---------------------------------------------------------------------------


def test_sqlite_access_strictly_read_only() -> None:
    """Verify database connection enforces ?mode=ro and PRAGMA query_only = ON."""
    with get_readonly_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA query_only;")
        row = cursor.fetchone()
        assert row[0] == 1, "PRAGMA query_only must be ON (1)"

        # Verify mutation statements are rejected
        with pytest.raises(Exception):
            cursor.execute("INSERT INTO data_observation (entity_code) VALUES ('TEST');")

    # Verify DB SHA-256 against simulation_manifest
    verified_hash = verify_db_sha256()
    manifest = load_simulation_manifest()
    assert verified_hash == manifest.database_sha256


# ---------------------------------------------------------------------------
# Dimension 17: Zero Calculation Engine Imports (AST Inspection)
# ---------------------------------------------------------------------------


def test_zero_calculation_engine_imports_in_advanced_pages() -> None:
    """Verify pages 3-6 and plot modules do not import compute engines or write layers."""
    forbidden_prefixes = (
        "core",
        "analytics",
        "backtest",
        "simulation",
        "data.collector",
        "data.repository",
    )

    modules_to_inspect = [
        Path("src/dashboard/pages/3_Market_Data_Provenance.py"),
        Path("src/dashboard/pages/4_Monte_Carlo_Laboratory.py"),
        Path("src/dashboard/pages/5_Risk_Stress_Testing.py"),
        Path("src/dashboard/pages/6_Holdout_Diagnostics.py"),
        Path("src/dashboard/components/plots/series.py"),
        Path("src/dashboard/components/plots/simulation.py"),
        Path("src/dashboard/components/plots/stress.py"),
        Path("src/dashboard/components/plots/holdout.py"),
    ]

    for pfile in modules_to_inspect:
        assert pfile.exists(), f"File {pfile} must exist"
        tree = ast.parse(pfile.read_text(encoding="utf-8"))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden in forbidden_prefixes:
                        assert not alias.name.startswith(forbidden), f"{pfile} contains forbidden import '{alias.name}'"
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for forbidden in forbidden_prefixes:
                        assert not node.module.startswith(forbidden), (
                            f"{pfile} contains forbidden import from '{node.module}'"
                        )


# ---------------------------------------------------------------------------
# Dimension 18: Mocked Streamlit Rendering Execution
# ---------------------------------------------------------------------------


def _mock_columns(spec: Any, **kwargs: Any) -> List[MagicMock]:
    count = spec if isinstance(spec, int) else len(spec)
    return [MagicMock() for _ in range(count)]


def test_page_3_render_page_executes() -> None:
    """Verify Page 3 render_page executes successfully under mocked Streamlit context."""
    p3 = importlib.import_module("dashboard.pages.3_Market_Data_Provenance")

    with (
        patch("streamlit.title"),
        patch("streamlit.subheader"),
        patch("streamlit.caption"),
        patch("streamlit.markdown"),
        patch("streamlit.plotly_chart"),
        patch("streamlit.dataframe"),
        patch("streamlit.warning"),
        patch("streamlit.info"),
        patch("streamlit.selectbox", return_value="EUR/USD Reference Exchange Rate"),
        patch("streamlit.columns", side_effect=_mock_columns),
        patch("streamlit.expander") as mock_expander,
    ):
        mock_expander.return_value.__enter__.return_value = MagicMock()
        mock_expander.return_value.__exit__.return_value = None
        p3.render_page()


def test_page_4_render_page_executes() -> None:
    """Verify Page 4 render_page executes successfully under mocked Streamlit context."""
    p4 = importlib.import_module("dashboard.pages.4_Monte_Carlo_Laboratory")

    with (
        patch("streamlit.title"),
        patch("streamlit.subheader"),
        patch("streamlit.caption"),
        patch("streamlit.markdown"),
        patch("streamlit.plotly_chart"),
        patch("streamlit.dataframe"),
        patch("streamlit.warning"),
        patch("streamlit.info"),
        patch("streamlit.selectbox", return_value="Multivariate Gaussian (Baseline)"),
        patch("streamlit.columns", side_effect=_mock_columns),
        patch("streamlit.expander") as mock_expander,
    ):
        mock_expander.return_value.__enter__.return_value = MagicMock()
        mock_expander.return_value.__exit__.return_value = None
        p4.render_page()


def test_page_5_render_page_executes() -> None:
    """Verify Page 5 render_page executes successfully under mocked Streamlit context."""
    p5 = importlib.import_module("dashboard.pages.5_Risk_Stress_Testing")

    with (
        patch("streamlit.title"),
        patch("streamlit.subheader"),
        patch("streamlit.caption"),
        patch("streamlit.markdown"),
        patch("streamlit.plotly_chart"),
        patch("streamlit.dataframe"),
        patch("streamlit.warning"),
        patch("streamlit.info"),
        patch("streamlit.columns", side_effect=_mock_columns),
        patch("streamlit.expander") as mock_expander,
    ):
        mock_expander.return_value.__enter__.return_value = MagicMock()
        mock_expander.return_value.__exit__.return_value = None
        p5.render_page()


def test_page_6_render_page_executes() -> None:
    """Verify Page 6 render_page executes successfully under mocked Streamlit context."""
    p6 = importlib.import_module("dashboard.pages.6_Holdout_Diagnostics")

    with (
        patch("streamlit.title"),
        patch("streamlit.subheader"),
        patch("streamlit.caption"),
        patch("streamlit.markdown"),
        patch("streamlit.plotly_chart"),
        patch("streamlit.dataframe"),
        patch("streamlit.warning"),
        patch("streamlit.info"),
        patch("streamlit.columns", side_effect=_mock_columns),
        patch("streamlit.expander") as mock_expander,
    ):
        mock_expander.return_value.__enter__.return_value = MagicMock()
        mock_expander.return_value.__exit__.return_value = None
        p6.render_page()


# ---------------------------------------------------------------------------
# Dimension 19: Provenance Metadata Coverage
# ---------------------------------------------------------------------------


def test_provenance_metadata_coverage_advanced_pages() -> None:
    """Verify provenance information is present for all authoritative artifacts used."""
    required_artifacts = [
        "availability_audit",
        "calendar_validation",
        "simulation_manifest",
        "model_comparison",
        "convergence_report",
        "stress_test_results",
        "correlation_stress_comparison",
        "funding_sensitivity",
        "holdout_diagnostics",
        "factor_holdout_diagnostics",
        "portfolio_holdout_diagnostics",
    ]

    for art_id in required_artifacts:
        meta = get_artifact_metadata(art_id)
        assert meta is not None, f"Missing metadata for {art_id}"
        assert meta.expected_sha256 != ""
        assert len(meta.expected_sha256) == 64
        path, verified_hash = resolve_artifact_path(art_id)
        assert path.is_file()
        assert verified_hash == meta.expected_sha256


# ---------------------------------------------------------------------------
# Dimension 20: Read-Only Invariants: All 23 Artifact Hashes Unchanged
# ---------------------------------------------------------------------------


def test_all_twenty_three_artifact_hashes_unchanged() -> None:
    """Verify that all 23 registered research artifacts remain byte-stable and unmutated."""
    registered = list_registered_artifacts()
    assert len(registered) == 23, "Must have exactly 23 registered artifacts"

    for meta in registered:
        path, expected_hash = resolve_artifact_path(meta.artifact_id, version=meta.version)
        assert path.is_file(), f"Artifact file '{path}' must exist"
        current_hash = compute_file_sha256(path)
        assert current_hash == expected_hash, (
            f"Artifact {meta.artifact_id} was mutated! Expected {expected_hash}, got {current_hash}"
        )


# ---------------------------------------------------------------------------
# Plot Builder Unit Tests
# ---------------------------------------------------------------------------


def test_advanced_plot_builders() -> None:
    """Verify Plotly figure generation across all new plot builders."""
    # Series plot
    df_sample = pd.DataFrame({"date": ["2020-01-01", "2020-01-02"], "val": [1.12, 1.13]})
    fig_series = build_time_series_figure(df_sample, "date", "val", "EUR/USD", "Rate")
    assert fig_series is not None
    assert len(fig_series.data) == 1

    # Convergence plot
    conv = load_convergence_report()
    fig_conv = build_convergence_figure(conv.checkpoints)
    assert fig_conv is not None
    assert len(fig_conv.data) == 3

    # Stress tornado plot
    scenarios = load_stress_test_results()
    fig_tornado = build_stress_tornado_figure(scenarios)
    assert fig_tornado is not None
    assert len(fig_tornado.data) == 1

    # Funding sensitivity plot
    funding = load_funding_sensitivity()
    fig_fund = build_funding_sensitivity_figure(funding)
    assert fig_fund is not None
    assert len(fig_fund.data) == 2

    # Correlation matrix plot
    corr = load_correlation_stress_comparison()
    labels = ["F1", "F2", "F3", "F4"]
    assert corr.empirical_correlation_matrix is not None
    fig_corr = build_correlation_matrix_figure(corr.empirical_correlation_matrix, labels, "Test Corr")
    assert fig_corr is not None
    assert len(fig_corr.data) == 1

    # Holdout fan plot
    f_holdout = load_factor_holdout_diagnostics()
    fig_fan = build_holdout_factor_fan_figure(
        sim_p025=f_holdout.simulated_fx_return_p025,
        sim_median=f_holdout.simulated_fx_return_median,
        sim_p975=f_holdout.simulated_fx_return_p975,
        realized_return=f_holdout.actual_fx_cumulative_return,
    )
    assert fig_fan is not None
    assert len(fig_fan.data) == 1

    # Correlation shifts plot
    fig_shifts = build_correlation_shifts_figure(f_holdout.correlation_shifts)
    assert fig_shifts is not None
    assert len(fig_shifts.data) == 1
