"""Authoritative Research Artifact Registry for Phase 5 Dashboard.

Provides a versioned, cryptographically verified registry of all 23 authoritative
JSON research artifacts from Phase 4 (simulation & holdout) and Phase 3 (backtesting).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class UnknownArtifactError(KeyError):
    """Raised when an unknown artifact identifier or version is requested."""


@dataclass(frozen=True)
class ArtifactMetadata:
    """Metadata descriptor for a registered research artifact."""

    artifact_id: str
    version: str
    relative_path: str
    expected_sha256: str
    description: str
    schema_type: str


# Phase 4.1.2.2.3 Authoritative Research Artifacts (Simulation, Factor Panel, Holdout)
_PHASE_4_ARTIFACTS: Dict[str, ArtifactMetadata] = {
    "calibration_report": ArtifactMetadata(
        artifact_id="calibration_report",
        version="phase_4_1_2_2_3",
        relative_path="data/results/phase_4_1_2_2_3/calibration_report.json",
        expected_sha256="a8994f4d70c6e5ecccd230fe91e41882f0a409da5fe33ef816dc1954ab6e3060",
        description="Empirical 4-factor panel covariance and correlation calibration report",
        schema_type="CalibrationReportSchema",
    ),
    "factor_panel_manifest": ArtifactMetadata(
        artifact_id="factor_panel_manifest",
        version="phase_4_1_2_2_3",
        relative_path="data/results/phase_4_1_2_2_3/factor_panel_manifest.json",
        expected_sha256="f15aa918aff4a4dd11d65f4b90c487cbfb8ee5b64a307948f15df7ded873befe",
        description="Daily 4-factor panel levels and transitions (1,237 dates)",
        schema_type="FactorPanelManifestSchema",
    ),
    "model_comparison": ArtifactMetadata(
        artifact_id="model_comparison",
        version="phase_4_1_2_2_3",
        relative_path="data/results/phase_4_1_2_2_3/model_comparison.json",
        expected_sha256="5cc589f97423e8666aaa6434182b802dc8e918cc323d74502fe0982314aa4ea4",
        description="Comparative metrics across 6 Monte Carlo distribution models",
        schema_type="ModelComparisonSchema",
    ),
    "gaussian_results": ArtifactMetadata(
        artifact_id="gaussian_results",
        version="phase_4_1_2_2_3",
        relative_path="data/results/phase_4_1_2_2_3/gaussian_results.json",
        expected_sha256="c342d16015f4e66dde68d2f77e2d7a8338826c232af122a526547c85dc90bb34",
        description="Multivariate Gaussian simulation results and representative paths",
        schema_type="MonteCarloResultSchema",
    ),
    "bootstrap_results": ArtifactMetadata(
        artifact_id="bootstrap_results",
        version="phase_4_1_2_2_3",
        relative_path="data/results/phase_4_1_2_2_3/bootstrap_results.json",
        expected_sha256="2f95dcf80ec095a1e39d2424e28c6598d5b71d2f10fbf9733b1e46bbd27d1eee",
        description="Moving-Block Bootstrap (20d) simulation results",
        schema_type="MonteCarloResultSchema",
    ),
    "student_t_results": ArtifactMetadata(
        artifact_id="student_t_results",
        version="phase_4_1_2_2_3",
        relative_path="data/results/phase_4_1_2_2_3/student_t_results.json",
        expected_sha256="cc06de387576f71beecfc9f800cb2487b8bc06610074087ab34ae68413736bab",
        description="Multivariate Student-t (nu=7.74) simulation results",
        schema_type="MonteCarloResultSchema",
    ),
    "regime_results": ArtifactMetadata(
        artifact_id="regime_results",
        version="phase_4_1_2_2_3",
        relative_path="data/results/phase_4_1_2_2_3/regime_results.json",
        expected_sha256="a239aa72bc32470966c7ba566bc7718389dd641b63ce0396b9e5c7f4caa394d3",
        description="Regime-conditioned (20th/80th volatility) simulation results",
        schema_type="MonteCarloResultSchema",
    ),
    "convergence_report": ArtifactMetadata(
        artifact_id="convergence_report",
        version="phase_4_1_2_2_3",
        relative_path="data/results/phase_4_1_2_2_3/convergence_report.json",
        expected_sha256="bf14c44a7885afc26e5277de170890b0b1be8a4c74bd1763e7b58b8b7da7c614",
        description="Asymptotic convergence verification across N=100..1000 paths",
        schema_type="ConvergenceReportSchema",
    ),
    "stress_test_results": ArtifactMetadata(
        artifact_id="stress_test_results",
        version="phase_4_1_2_2_3",
        relative_path="data/results/phase_4_1_2_2_3/stress_test_results.json",
        expected_sha256="4053f6596b8bb9aaa03373acca584fc60ebaf964e414b62acbfb4d343fe56348",
        description="19 macro stress scenarios ranking returns and drawdowns",
        schema_type="StressTestResultsSchema",
    ),
    "correlation_stress_comparison": ArtifactMetadata(
        artifact_id="correlation_stress_comparison",
        version="phase_4_1_2_2_3",
        relative_path="data/results/phase_4_1_2_2_3/correlation_stress_comparison.json",
        expected_sha256="f1ec34a7a82db91f4b416b8eb5afe00a22e4af199c3b45cbb373c7ff1a5caf84",
        description="Common Random Numbers paired correlation decoupling stress test",
        schema_type="CorrelationStressComparisonSchema",
    ),
    "funding_sensitivity": ArtifactMetadata(
        artifact_id="funding_sensitivity",
        version="phase_4_1_2_2_3",
        relative_path="data/results/phase_4_1_2_2_3/funding_sensitivity.json",
        expected_sha256="c85e8812a1bb0939ff187b49e7e063f49d0e19d22833ce3030e1ec4f0563d9d1",
        description="Fixed-rate term funding vs floating-rate reset funding sensitivity",
        schema_type="FundingSensitivitySchema",
    ),
    "holdout_diagnostics": ArtifactMetadata(
        artifact_id="holdout_diagnostics",
        version="phase_4_1_2_2_3",
        relative_path="data/results/phase_4_1_2_2_3/holdout_diagnostics.json",
        expected_sha256="822c9f4c772eec411cdd4a513f81228324e2f388a9f0a20513fdd11d4a9c5ef5",
        description="2024 out-of-sample FX realized volatility, KS test, and correlation shifts",
        schema_type="HoldoutDiagnosticsSchema",
    ),
    "factor_holdout_diagnostics": ArtifactMetadata(
        artifact_id="factor_holdout_diagnostics",
        version="phase_4_1_2_2_3",
        relative_path="data/results/phase_4_1_2_2_3/factor_holdout_diagnostics.json",
        expected_sha256="0e2b5fa1e7ddd3de28ebe997e4d9dcfc138356fc077a5d461770fbd96a9d143e",
        description="2024 factor predictive quantiles and realized FX return comparisons",
        schema_type="FactorHoldoutDiagnosticsSchema",
    ),
    "portfolio_holdout_diagnostics": ArtifactMetadata(
        artifact_id="portfolio_holdout_diagnostics",
        version="phase_4_1_2_2_3",
        relative_path="data/results/phase_4_1_2_2_3/portfolio_holdout_diagnostics.json",
        expected_sha256="0082f477222570c9ab5402f94e5d3f8c6d11bd04502106350e82d5378060be2d",
        description="Explicit UNAVAILABLE status documentation for 2024 strategy holdout",
        schema_type="PortfolioHoldoutDiagnosticsSchema",
    ),
    "availability_audit": ArtifactMetadata(
        artifact_id="availability_audit",
        version="phase_4_1_2_2_3",
        relative_path="data/results/phase_4_1_2_2_3/availability_audit.json",
        expected_sha256="d9c40f48fc47fb3346719491281d8eecb88a1647e14904fd75498f262ecbe065",
        description="Database availability audit: 8,908 total, 8,900 genuine, 8,724 estimated lag, 176 retrospective",
        schema_type="AvailabilityAuditSchema",
    ),
    "calendar_validation": ArtifactMetadata(
        artifact_id="calendar_validation",
        version="phase_4_1_2_2_3",
        relative_path="data/results/phase_4_1_2_2_3/calendar_validation.json",
        expected_sha256="bf3c68d8f64c98aa6363ba7b176d891f99e18d21cab8e58af3067b982a8b4ff0",
        description="Joint Target2/Fed calendar settlement and interest accrual audit",
        schema_type="CalendarValidationSchema",
    ),
    "simulation_manifest": ArtifactMetadata(
        artifact_id="simulation_manifest",
        version="phase_4_1_2_2_3",
        relative_path="data/results/phase_4_1_2_2_3/simulation_manifest.json",
        expected_sha256="74c951a3c43d20860433dba0b584cfa796f4b8620cc66ffa71ba70adaefe25ca",
        description="Simulation execution manifest, git commit, seed, and database SHA-256",
        schema_type="SimulationManifestSchema",
    ),
}

# Phase 3.2.2.3.3 Authoritative Backtest Artifacts (Historical 2020-2024 Backtest Baselines)
_PHASE_3_ARTIFACTS: Dict[str, ArtifactMetadata] = {
    "config_1_strict_pit": ArtifactMetadata(
        artifact_id="config_1_strict_pit",
        version="phase_3_2_2_3_3",
        relative_path="data/results/phase_3_2_2_3_3/config_1_strict_pit.json",
        expected_sha256="cab3f22da466a65ed649558cd0ba658c28e6d120d26cf0574f4e92899783f61b",
        description="Config 1: Strict Verified Point-in-Time backtest",
        schema_type="BacktestConfigSchema",
    ),
    "config_2_estimated_schedule": ArtifactMetadata(
        artifact_id="config_2_estimated_schedule",
        version="phase_3_2_2_3_3",
        relative_path="data/results/phase_3_2_2_3_3/config_2_estimated_schedule.json",
        expected_sha256="42ae54600fa8ae5acc855e6395700a1c25bbfb48d43dc3fe44326e0885c4875f",
        description="Config 2: Primary Estimated-Availability Reference-Rate carry trade backtest (+2.89% return)",
        schema_type="BacktestConfigSchema",
    ),
    "config_3_strict_quotes": ArtifactMetadata(
        artifact_id="config_3_strict_quotes",
        version="phase_3_2_2_3_3",
        relative_path="data/results/phase_3_2_2_3_3/config_3_strict_quotes.json",
        expected_sha256="a6a53169fc87e3d0d8c5643fdd554fcf3ab70d5379ad2313ab2ad573e5b1f54c",
        description="Config 3: Strict Executable Quotes Enforcement (UNEXECUTABLE rejection)",
        schema_type="BacktestConfigSchema",
    ),
    "config_4_matched_benchmark": ArtifactMetadata(
        artifact_id="config_4_matched_benchmark",
        version="phase_3_2_2_3_3",
        relative_path="data/results/phase_3_2_2_3_3/config_4_matched_benchmark.json",
        expected_sha256="a4a96c98c06120a8d1544b560450eaf174c9fb9195ca7cc2f08abf00a4e29189",
        description="Config 4: Currency-Matched Benchmark (EUR Deposit Proxy 1.5% annual)",
        schema_type="BacktestConfigSchema",
    ),
    "config_5_mismatched_benchmark": ArtifactMetadata(
        artifact_id="config_5_mismatched_benchmark",
        version="phase_3_2_2_3_3",
        relative_path="data/results/phase_3_2_2_3_3/config_5_mismatched_benchmark.json",
        expected_sha256="5ce250e8be8af537abbcb03296840843609bed6f7fb96aae45cef724c158e35c",
        description="Config 5: Currency-Mismatched Benchmark demonstration",
        schema_type="BacktestConfigSchema",
    ),
    "config_6_covered_rejection": ArtifactMetadata(
        artifact_id="config_6_covered_rejection",
        version="phase_3_2_2_3_3",
        relative_path="data/results/phase_3_2_2_3_3/config_6_covered_rejection.json",
        expected_sha256="563429fb2d38d55053fef32c799540819ffb3fe2851955c37f1fb0e1c055391b",
        description="Config 6: Covered Carry Rejection (UNEXECUTABLE forward quotes absent)",
        schema_type="BacktestConfigSchema",
    ),
}

# Aggregate Versioned Registry
_REGISTRY: Dict[str, Dict[str, ArtifactMetadata]] = {
    "phase_4_1_2_2_3": _PHASE_4_ARTIFACTS,
    "phase_3_2_2_3_3": _PHASE_3_ARTIFACTS,
}

# Total Count of Authoritative Registered Artifacts
TOTAL_REGISTERED_ARTIFACTS: int = len(_PHASE_4_ARTIFACTS) + len(_PHASE_3_ARTIFACTS)
DEFAULT_PHASE_4_VERSION: str = "phase_4_1_2_2_3"
DEFAULT_PHASE_3_VERSION: str = "phase_3_2_2_3_3"


def get_artifact_metadata(
    artifact_id: str,
    version: Optional[str] = None,
) -> ArtifactMetadata:
    """Retrieve metadata for a registered research artifact.

    Args:
        artifact_id: Registered artifact name (e.g. 'calibration_report').
        version: Target version string. If None, resolves across all versions.

    Returns:
        ArtifactMetadata descriptor.

    Raises:
        UnknownArtifactError: If artifact_id or version is not found in registry.
    """
    if version is not None:
        if version not in _REGISTRY:
            raise UnknownArtifactError(
                f"Unknown artifact version '{version}'. Supported versions: {sorted(_REGISTRY.keys())}"
            )
        artifacts = _REGISTRY[version]
        if artifact_id not in artifacts:
            raise UnknownArtifactError(
                f"Artifact '{artifact_id}' not registered under version '{version}'. Available: {sorted(artifacts.keys())}"
            )
        return artifacts[artifact_id]

    # Search across versions (default Phase 4 first, then Phase 3)
    for v in (DEFAULT_PHASE_4_VERSION, DEFAULT_PHASE_3_VERSION):
        if artifact_id in _REGISTRY[v]:
            return _REGISTRY[v][artifact_id]

    raise UnknownArtifactError(f"Artifact '{artifact_id}' not found in any registered version.")


def list_registered_artifacts(version: Optional[str] = None) -> List[ArtifactMetadata]:
    """List all registered artifacts, optionally filtered by version."""
    if version is not None:
        if version not in _REGISTRY:
            raise UnknownArtifactError(f"Unknown artifact version '{version}'.")
        return list(_REGISTRY[version].values())
    all_artifacts: List[ArtifactMetadata] = []
    for v_dict in _REGISTRY.values():
        all_artifacts.extend(v_dict.values())
    return all_artifacts


def resolve_artifact_path(
    artifact_id: str,
    version: Optional[str] = None,
    base_dir: Optional[Path] = None,
) -> Tuple[Path, str]:
    """Resolve the filesystem path and expected digest for a registered artifact.

    Args:
        artifact_id: Registered artifact key.
        version: Target version string.
        base_dir: Root directory of repository (defaults to project root).

    Returns:
        Tuple of (absolute_path, expected_sha256).
    """
    meta = get_artifact_metadata(artifact_id, version)
    if base_dir is None:
        base_dir = Path(__file__).resolve().parents[3]
    full_path = (base_dir / meta.relative_path).resolve()
    return full_path, meta.expected_sha256
