"""Read-Only Research Artifact Loader for Phase 5 Dashboard.

Provides cached, strongly typed, cryptographically verified loaders for all 23
authoritative JSON research artifacts from Phase 4 (simulation & holdout) and
Phase 3 (backtesting).

Core Architectural Principles:
1. Strictly Read-Only:
   No recomputations of any backtest, carry-trade metric, calibration result,
   or Monte Carlo simulation.
2. Cryptographic Verification:
   Every artifact loaded is verified against its registered SHA-256 digest before
   entering the application runtime.
3. Content-Fingerprinted Caching:
   Streamlit's @st.cache_data decorator is keyed on (path, expected_hash, content_hash)
   so that any external disk modification or truncation deterministically busts the cache.
4. Strongly Typed Schemas:
   JSON payloads are deserialized directly into Pydantic models with IEEE 754 precision.
5. Invariant Research States:
   Unavailable research states (e.g., 2024 portfolio holdout) are modeled explicitly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

from dashboard.artifacts.integrity import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    compute_file_sha256,
    verify_registered_artifact,
)
from dashboard.artifacts.registry import (
    DEFAULT_PHASE_3_VERSION,
    DEFAULT_PHASE_4_VERSION,
    list_registered_artifacts,
    resolve_artifact_path,
)
from dashboard.artifacts.schemas import (
    AvailabilityAuditSchema,
    BacktestConfigSchema,
    CalibrationReportSchema,
    CalendarValidationSchema,
    ConvergenceReportSchema,
    CorrelationStressComparisonSchema,
    FactorHoldoutDiagnosticsSchema,
    FactorPanelManifestSchema,
    FundingSensitivitySchema,
    HoldoutDiagnosticsSchema,
    ModelComparisonItemSchema,
    MonteCarloResultSchema,
    PortfolioHoldoutDiagnosticsSchema,
    SimulationManifestSchema,
    StressScenarioItemSchema,
)


@st.cache_data(show_spinner=False)
def _load_json_cached(
    file_path_str: str,
    expected_sha256: str,
    content_hash: str,
) -> Any:
    """Cached low-level JSON artifact loader with content-hash cache invalidation.

    Args:
        file_path_str: Absolute path to the artifact file as a string.
        expected_sha256: Expected 64-char lowercase SHA-256 digest from registry.
        content_hash: Actual computed SHA-256 of the file content, ensuring that
            if the file is modified on disk, the cache key changes and invalidates.

    Returns:
        Deserialized JSON object (dict or list).

    Raises:
        ArtifactNotFoundError: If file_path_str does not exist.
        ArtifactIntegrityError: If content_hash does not match expected_sha256.
    """
    clean_expected = expected_sha256.strip().lower()
    clean_actual = content_hash.strip().lower()
    if clean_actual != clean_expected:
        raise ArtifactIntegrityError(
            f"Artifact integrity verification failed for '{file_path_str}'.\n"
            f"  Expected: {clean_expected}\n"
            f"  Actual:   {clean_actual}\n"
            "The artifact has been altered, corrupted, or truncated on disk."
        )

    path = Path(file_path_str)
    if not path.is_file():
        raise ArtifactNotFoundError(f"Artifact file not found: '{path}'")

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_raw_artifact(
    artifact_id: str,
    version: Optional[str] = None,
    base_dir: Optional[Path] = None,
) -> Any:
    """Load a registered JSON artifact with cryptographic integrity verification.

    Args:
        artifact_id: Registered artifact identifier.
        version: Target version string (optional).
        base_dir: Optional project root directory override.

    Returns:
        Deserialized JSON payload.
    """
    path, expected_sha256 = resolve_artifact_path(artifact_id, version, base_dir=base_dir)
    actual_sha256 = compute_file_sha256(path)
    return _load_json_cached(str(path), expected_sha256, actual_sha256)


# ==============================================================================
# Phase 4 Authoritative Typed Loaders
# ==============================================================================


def load_calibration_report(
    version: str = DEFAULT_PHASE_4_VERSION,
    base_dir: Optional[Path] = None,
) -> CalibrationReportSchema:
    """Load and validate calibration_report.json."""
    raw = load_raw_artifact("calibration_report", version=version, base_dir=base_dir)
    return CalibrationReportSchema.model_validate(raw)


def load_factor_panel_manifest(
    version: str = DEFAULT_PHASE_4_VERSION,
    base_dir: Optional[Path] = None,
) -> FactorPanelManifestSchema:
    """Load and validate factor_panel_manifest.json (3 MB factor panel)."""
    raw = load_raw_artifact("factor_panel_manifest", version=version, base_dir=base_dir)
    return FactorPanelManifestSchema.model_validate(raw)


def load_model_comparison(
    version: str = DEFAULT_PHASE_4_VERSION,
    base_dir: Optional[Path] = None,
) -> List[ModelComparisonItemSchema]:
    """Load and validate model_comparison.json."""
    raw = load_raw_artifact("model_comparison", version=version, base_dir=base_dir)
    return [ModelComparisonItemSchema.model_validate(item) for item in raw]


def load_monte_carlo_result(
    model_name: str,
    version: str = DEFAULT_PHASE_4_VERSION,
    base_dir: Optional[Path] = None,
) -> MonteCarloResultSchema:
    """Load and validate a Monte Carlo model result artifact."""
    artifact_id = model_name if model_name.endswith("_results") else f"{model_name}_results"
    raw = load_raw_artifact(artifact_id, version=version, base_dir=base_dir)
    return MonteCarloResultSchema.model_validate(raw)


def load_convergence_report(
    version: str = DEFAULT_PHASE_4_VERSION,
    base_dir: Optional[Path] = None,
) -> ConvergenceReportSchema:
    """Load and validate convergence_report.json."""
    raw = load_raw_artifact("convergence_report", version=version, base_dir=base_dir)
    return ConvergenceReportSchema.model_validate(raw)


def load_stress_test_results(
    version: str = DEFAULT_PHASE_4_VERSION,
    base_dir: Optional[Path] = None,
) -> List[StressScenarioItemSchema]:
    """Load and validate stress_test_results.json."""
    raw = load_raw_artifact("stress_test_results", version=version, base_dir=base_dir)
    return [StressScenarioItemSchema.model_validate(item) for item in raw]


def load_correlation_stress_comparison(
    version: str = DEFAULT_PHASE_4_VERSION,
    base_dir: Optional[Path] = None,
) -> CorrelationStressComparisonSchema:
    """Load and validate correlation_stress_comparison.json."""
    raw = load_raw_artifact("correlation_stress_comparison", version=version, base_dir=base_dir)
    return CorrelationStressComparisonSchema.model_validate(raw)


def load_funding_sensitivity(
    version: str = DEFAULT_PHASE_4_VERSION,
    base_dir: Optional[Path] = None,
) -> FundingSensitivitySchema:
    """Load and validate funding_sensitivity.json."""
    raw = load_raw_artifact("funding_sensitivity", version=version, base_dir=base_dir)
    return FundingSensitivitySchema.model_validate(raw)


def load_holdout_diagnostics(
    version: str = DEFAULT_PHASE_4_VERSION,
    base_dir: Optional[Path] = None,
) -> HoldoutDiagnosticsSchema:
    """Load and validate holdout_diagnostics.json."""
    raw = load_raw_artifact("holdout_diagnostics", version=version, base_dir=base_dir)
    return HoldoutDiagnosticsSchema.model_validate(raw)


def load_factor_holdout_diagnostics(
    version: str = DEFAULT_PHASE_4_VERSION,
    base_dir: Optional[Path] = None,
) -> FactorHoldoutDiagnosticsSchema:
    """Load and validate factor_holdout_diagnostics.json."""
    raw = load_raw_artifact("factor_holdout_diagnostics", version=version, base_dir=base_dir)
    return FactorHoldoutDiagnosticsSchema.model_validate(raw)


def load_portfolio_holdout_diagnostics(
    version: str = DEFAULT_PHASE_4_VERSION,
    base_dir: Optional[Path] = None,
) -> PortfolioHoldoutDiagnosticsSchema:
    """Load and validate portfolio_holdout_diagnostics.json (UNAVAILABLE status)."""
    raw = load_raw_artifact("portfolio_holdout_diagnostics", version=version, base_dir=base_dir)
    return PortfolioHoldoutDiagnosticsSchema.model_validate(raw)


def load_availability_audit(
    version: str = DEFAULT_PHASE_4_VERSION,
    base_dir: Optional[Path] = None,
) -> AvailabilityAuditSchema:
    """Load and validate availability_audit.json."""
    raw = load_raw_artifact("availability_audit", version=version, base_dir=base_dir)
    return AvailabilityAuditSchema.model_validate(raw)


def load_calendar_validation(
    version: str = DEFAULT_PHASE_4_VERSION,
    base_dir: Optional[Path] = None,
) -> CalendarValidationSchema:
    """Load and validate calendar_validation.json."""
    raw = load_raw_artifact("calendar_validation", version=version, base_dir=base_dir)
    return CalendarValidationSchema.model_validate(raw)


def load_simulation_manifest(
    version: str = DEFAULT_PHASE_4_VERSION,
    base_dir: Optional[Path] = None,
) -> SimulationManifestSchema:
    """Load and validate simulation_manifest.json."""
    raw = load_raw_artifact("simulation_manifest", version=version, base_dir=base_dir)
    return SimulationManifestSchema.model_validate(raw)


# ==============================================================================
# Phase 3 Authoritative Typed Loaders
# ==============================================================================


def load_backtest_config(
    config_id: str,
    version: str = DEFAULT_PHASE_3_VERSION,
    base_dir: Optional[Path] = None,
) -> BacktestConfigSchema:
    """Load and validate a Phase 3 backtest configuration artifact."""
    raw = load_raw_artifact(config_id, version=version, base_dir=base_dir)
    return BacktestConfigSchema.model_validate(raw)


def list_backtest_configs(
    version: str = DEFAULT_PHASE_3_VERSION,
    base_dir: Optional[Path] = None,
) -> List[Tuple[str, BacktestConfigSchema]]:
    """Load all 6 Phase 3 backtest configurations in authoritative order."""
    config_ids = [
        "config_1_strict_pit",
        "config_2_estimated_schedule",
        "config_3_strict_quotes",
        "config_4_matched_benchmark",
        "config_5_mismatched_benchmark",
        "config_6_covered_rejection",
    ]
    return [(cid, load_backtest_config(cid, version=version, base_dir=base_dir)) for cid in config_ids]


def verify_all_registered_artifacts(
    version: Optional[str] = None,
    base_dir: Optional[Path] = None,
) -> Dict[str, Tuple[Path, str]]:
    """Verify all registered artifacts on disk against their expected SHA-256 digests."""
    results: Dict[str, Tuple[Path, str]] = {}
    for meta in list_registered_artifacts(version=version):
        path, verified_hash = verify_registered_artifact(meta.artifact_id, version=meta.version, base_dir=base_dir)
        results[meta.artifact_id] = (path, verified_hash)
    return results
