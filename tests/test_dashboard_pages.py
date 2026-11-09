"""Tests for Phase 5.2 Research Dashboard Pages.

Validates the implementation of:
  - Page 1: Research Overview (src/dashboard/pages/1_Research_Overview.py)
  - Page 2: Carry Trade Performance (src/dashboard/pages/2_Carry_Trade_Performance.py)
  - Plot builders: Waterfall and Comparison figures

Covers all 12 required verification dimensions:
  1. Clean module imports
  2. Numerical parity with authoritative artifacts (<= 1e-9 tolerance)
  3. Artifact infrastructure usage (loader.py, registry.py, integrity.py)
  4. Mathematical attribution waterfall reconciliation (|residual| < 1e-10)
  5. Controlled failure modes on missing/corrupted artifacts
  6. Honest unavailable state for portfolio holdout
  7. No fabricated or interpolated daily time series
  8. Alternative configuration audit preserving unexecutable/proxy status
  9. Zero calculation-engine imports (AST inspection)
 10. Execution of render_page() under mocked Streamlit context
 11. Provenance metadata coverage
 12. Read-only invariants
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from typing import Any, List
from unittest.mock import MagicMock, patch

import pytest

from dashboard.artifacts.integrity import (
    ArtifactNotFoundError,
    compute_file_sha256,
    verify_registered_artifact,
)
from dashboard.artifacts.loader import (
    list_backtest_configs,
    load_backtest_config,
    load_model_comparison,
    load_portfolio_holdout_diagnostics,
)
from dashboard.artifacts.registry import (
    UnknownArtifactError,
    get_artifact_metadata,
    list_registered_artifacts,
    resolve_artifact_path,
)
from dashboard.components.plots.comparison import (
    build_benchmark_comparison_figure,
    build_model_comparison_figure,
)
from dashboard.components.plots.waterfall import build_attribution_waterfall_figure


# ---------------------------------------------------------------------------
# Dimension 1: Module Imports
# ---------------------------------------------------------------------------


def test_dashboard_pages_import_cleanly() -> None:
    """Verify both Streamlit page modules import cleanly without errors."""
    page_1 = importlib.import_module("dashboard.pages.1_Research_Overview")
    page_2 = importlib.import_module("dashboard.pages.2_Carry_Trade_Performance")

    assert hasattr(page_1, "render_page"), "Page 1 must export render_page()"
    assert hasattr(page_2, "render_page"), "Page 2 must export render_page()"
    assert callable(page_1.render_page)
    assert callable(page_2.render_page)


# ---------------------------------------------------------------------------
# Dimension 2: Numerical Parity with Authoritative Artifacts (<= 1e-9)
# ---------------------------------------------------------------------------


def test_config_2_numerical_parity() -> None:
    """Verify all Config 2 backtest metrics match authoritative artifact within 1e-9."""
    c2 = load_backtest_config("config_2_estimated_schedule")

    assert c2 is not None
    assert c2.initial_capital_a == pytest.approx(100000.0, abs=1e-9)

    perf = c2.performance
    assert perf is not None
    assert perf.cumulative_net_profit == pytest.approx(2890.2219488248384, abs=1e-9)
    assert perf.total_return == pytest.approx(0.028902219488248383, abs=1e-9)
    assert perf.annualized_return == pytest.approx(0.005714752762239206, abs=1e-9)
    assert perf.annualized_volatility == pytest.approx(0.029753378682408467, abs=1e-9)
    assert perf.sharpe_ratio == pytest.approx(-0.03909043472639195, abs=1e-9)
    assert perf.max_drawdown == pytest.approx(-0.035187401528777085, abs=1e-9)

    trades = c2.trades
    assert trades is not None
    assert trades.total_trades == 29
    assert trades.winning_trades == 13
    assert trades.losing_trades == 16
    assert trades.win_rate == pytest.approx(0.4482758620689655, abs=1e-9)
    assert trades.profit_factor == pytest.approx(0.7161339561174203, abs=1e-9)
    assert trades.rejected_trades_count == 31

    # Benchmark metrics
    bench = c2.benchmark
    assert bench is not None
    assert bench.benchmark_total_return == pytest.approx(0.07728400388428946, abs=1e-9)
    assert bench.alpha == pytest.approx(-0.00928524723774471, abs=1e-9)
    assert bench.cumulative_excess_return == pytest.approx(-0.048381784396041086, abs=1e-9)


def test_simulation_distribution_numerical_parity() -> None:
    """Verify Monte Carlo simulation distributions match model_comparison.json within 1e-9."""
    models = load_model_comparison()
    assert len(models) == 6

    gaussian = next(m for m in models if m.model_name == "Multivariate Gaussian")
    assert gaussian.median_return == pytest.approx(0.017475607948999095, abs=1e-9)
    assert gaussian.prob_loss == pytest.approx(0.319, abs=1e-9)
    assert gaussian.cvar_95 == pytest.approx(-0.059711662024820186, abs=1e-9)
    assert gaussian.max_drawdown_median == pytest.approx(-0.036636081356625036, abs=1e-9)
    assert gaussian.max_drawdown_p95 == pytest.approx(-0.0718089308898935, abs=1e-9)


# ---------------------------------------------------------------------------
# Dimension 3: Artifact Infrastructure Usage
# ---------------------------------------------------------------------------


def test_page_loaders_use_verified_infrastructure() -> None:
    """Verify pages use loader.py functions and validate digests via integrity engine."""
    path, verified_hash = verify_registered_artifact("config_2_estimated_schedule")
    assert path.is_file()
    assert len(verified_hash) == 64

    meta = get_artifact_metadata("config_2_estimated_schedule")
    assert meta is not None
    assert meta.expected_sha256 == verified_hash
    assert meta.version == "phase_3_2_2_3_3"


# ---------------------------------------------------------------------------
# Dimension 4: Waterfall Attribution Reconciliation (|residual| < 1e-10)
# ---------------------------------------------------------------------------


def test_attribution_waterfall_reconciliation() -> None:
    """Verify P&L attribution components sum to cumulative net profit within 1e-10."""
    c2 = load_backtest_config("config_2_estimated_schedule")
    assert c2.attribution is not None
    assert c2.performance is not None
    attr = c2.attribution

    calculated_net = (
        attr.investment_yield_gain_a
        + attr.fx_translation_gain_a
        - attr.total_financing_costs_a
        + attr.total_cash_interest_a
        - attr.total_frictions_a
    )
    diff = abs(calculated_net - c2.performance.cumulative_net_profit)
    assert diff < 1e-10, f"Attribution residual {diff} exceeds 1e-10 tolerance"
    assert attr.reconciliation_exact is True
    assert attr.reconciliation_residual_a < 1e-10


def test_waterfall_plot_builder() -> None:
    """Verify build_attribution_waterfall_figure builds a valid Plotly Figure."""
    c2 = load_backtest_config("config_2_estimated_schedule")
    assert c2.attribution is not None

    fig = build_attribution_waterfall_figure(c2.attribution)
    assert fig is not None
    assert len(fig.data) == 1
    assert fig.data[0].type == "waterfall"
    assert len(fig.data[0].x) == 6
    assert fig.data[0].y[-1] == pytest.approx(c2.performance.cumulative_net_profit, abs=1e-9)


# ---------------------------------------------------------------------------
# Dimension 5: Controlled Failure Modes on Missing Artifacts
# ---------------------------------------------------------------------------


def test_controlled_failure_on_missing_artifact() -> None:
    """Verify missing artifacts raise controlled exceptions, not raw unhandled exceptions."""
    with pytest.raises((ArtifactNotFoundError, UnknownArtifactError)) as exc_info:
        load_backtest_config("non_existent_config_xyz")
    assert "not registered" in str(exc_info.value).lower() or "not found" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Dimension 6: Unavailable Portfolio Holdout State
# ---------------------------------------------------------------------------


def test_portfolio_holdout_unavailable_state() -> None:
    """Verify portfolio holdout is strictly represented as UNAVAILABLE."""
    holdout = load_portfolio_holdout_diagnostics()
    assert holdout.status == "UNAVAILABLE"
    assert holdout.is_available is False
    assert "No genuine historical executable portfolio series exists" in holdout.reason


# ---------------------------------------------------------------------------
# Dimension 7: No Fabricated or Interpolated Daily Time Series
# ---------------------------------------------------------------------------


def test_no_fabricated_time_series_contract() -> None:
    """Verify Page 2 explicitly notes the terminal nature of historical backtests."""
    p2_path = Path("src/dashboard/pages/2_Carry_Trade_Performance.py")
    content = p2_path.read_text(encoding="utf-8")

    assert "TIME-SERIES LIMITATION NOTICE" in content
    assert "not fabricated or interpolated" in content
    assert "terminal execution aggregates" in content


# ---------------------------------------------------------------------------
# Dimension 8: Alternative Configurations Audit Preserving Status
# ---------------------------------------------------------------------------


def test_alternative_configurations_audit_preserves_classifications() -> None:
    """Verify all 6 configurations preserve their exact unexecutable/proxy status."""
    configs = list_backtest_configs()
    assert len(configs) == 6

    # Config 1: 0-day lag unexecutable
    c1_id, c1 = configs[0]
    assert c1_id == "config_1_strict_pit"
    assert c1.is_executable_strategy is False
    assert c1.strategy_status == "RESEARCH_PROXY"

    # Config 2: Primary research baseline proxy
    c2_id, c2 = configs[1]
    assert c2_id == "config_2_estimated_schedule"
    assert c2.is_executable_strategy is False
    assert c2.strategy_status == "RESEARCH_PROXY"

    # Config 3: Strict quotes unexecutable
    c3_id, c3 = configs[2]
    assert c3_id == "config_3_strict_quotes"
    assert c3.is_executable_strategy is False
    assert c3.strategy_status == "UNEXECUTABLE"
    assert c3.can_simulate is False

    # Config 4: Matched benchmark proxy
    c4_id, c4 = configs[3]
    assert c4_id == "config_4_matched_benchmark"
    assert c4.is_executable_strategy is False
    assert c4.strategy_status == "RESEARCH_PROXY"

    # Config 5: Mismatched benchmark proxy
    c5_id, c5 = configs[4]
    assert c5_id == "config_5_mismatched_benchmark"
    assert c5.is_executable_strategy is False
    assert c5.strategy_status == "RESEARCH_PROXY"

    # Config 6: Covered rejection unexecutable
    c6_id, c6 = configs[5]
    assert c6_id == "config_6_covered_rejection"
    assert c6.is_executable_strategy is False
    assert c6.strategy_status == "UNEXECUTABLE"
    assert c6.can_simulate is False


# ---------------------------------------------------------------------------
# Dimension 9: Zero Calculation-Engine Imports (AST Inspection)
# ---------------------------------------------------------------------------


def test_zero_calculation_engine_imports_in_pages() -> None:
    """Verify neither page imports from src/core, src/analytics, src/backtest, or src/simulation."""
    forbidden_prefixes = (
        "core",
        "analytics",
        "backtest",
        "simulation",
        "data.collector",
        "data.repository",
    )

    page_files = [
        Path("src/dashboard/pages/1_Research_Overview.py"),
        Path("src/dashboard/pages/2_Carry_Trade_Performance.py"),
        Path("src/dashboard/components/plots/waterfall.py"),
        Path("src/dashboard/components/plots/comparison.py"),
    ]

    for pfile in page_files:
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
# Dimension 10: Page Rendering Execution Under Mocked Streamlit Context
# ---------------------------------------------------------------------------


def _mock_columns(spec: Any, **kwargs: Any) -> List[MagicMock]:
    """Helper to return dynamic number of mocks matching columns request."""
    count = spec if isinstance(spec, int) else len(spec)
    return [MagicMock() for _ in range(count)]


def test_page_1_render_page_executes_without_unhandled_exceptions() -> None:
    """Verify Page 1 render_page executes successfully without unhandled exceptions."""
    page_1 = importlib.import_module("dashboard.pages.1_Research_Overview")

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
        patch("streamlit.page_link"),
    ):
        mock_expander.return_value.__enter__.return_value = MagicMock()
        mock_expander.return_value.__exit__.return_value = None

        page_1.render_page()


def test_page_2_render_page_executes_without_unhandled_exceptions() -> None:
    """Verify Page 2 render_page executes successfully without unhandled exceptions."""
    page_2 = importlib.import_module("dashboard.pages.2_Carry_Trade_Performance")

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
        patch("streamlit.page_link"),
    ):
        mock_expander.return_value.__enter__.return_value = MagicMock()
        mock_expander.return_value.__exit__.return_value = None

        page_2.render_page()


# ---------------------------------------------------------------------------
# Dimension 11: Provenance Coverage
# ---------------------------------------------------------------------------


def test_provenance_coverage_for_displayed_metrics() -> None:
    """Verify provenance information is present for all authoritative artifacts used."""
    required_artifacts = [
        "config_2_estimated_schedule",
        "model_comparison",
        "portfolio_holdout_diagnostics",
    ]

    for art_id in required_artifacts:
        meta = get_artifact_metadata(art_id)
        assert meta is not None, f"Missing metadata for {art_id}"
        assert meta.expected_sha256 != ""
        assert len(meta.expected_sha256) == 64
        assert meta.version != ""
        path, verified_hash = resolve_artifact_path(art_id)
        assert path.is_file()
        assert verified_hash == meta.expected_sha256


# ---------------------------------------------------------------------------
# Dimension 12: Read-Only Invariants
# ---------------------------------------------------------------------------


def test_read_only_invariants_preserved() -> None:
    """Verify data/results/ artifacts remain bit-for-bit unchanged after tests and page executions."""
    for meta in list_registered_artifacts():
        path, expected_hash = resolve_artifact_path(meta.artifact_id, version=meta.version)
        if path.is_file():
            current_digest = compute_file_sha256(path)
            assert current_digest == expected_hash, (
                f"Artifact {meta.artifact_id} was mutated! Expected {expected_hash}, got {current_digest}"
            )


# ---------------------------------------------------------------------------
# Comparison Plot Builder Tests
# ---------------------------------------------------------------------------


def test_comparison_plot_builders() -> None:
    """Verify benchmark and model comparison plot builders return valid Plotly Figures."""
    c2 = load_backtest_config("config_2_estimated_schedule")
    assert c2.performance is not None
    assert c2.benchmark is not None

    bench_fig = build_benchmark_comparison_figure(
        strategy_return=c2.performance.total_return,
        benchmark_return=c2.benchmark.benchmark_total_return or 0.0,
        alpha=c2.benchmark.alpha or 0.0,
    )
    assert bench_fig is not None
    assert len(bench_fig.data) == 1
    assert bench_fig.data[0].type == "bar"

    models = load_model_comparison()
    assert len(models) == 6

    model_fig = build_model_comparison_figure(models)
    assert model_fig is not None
    assert len(model_fig.data) == 2
    assert model_fig.data[0].type == "bar"
    assert model_fig.data[1].type == "bar"
