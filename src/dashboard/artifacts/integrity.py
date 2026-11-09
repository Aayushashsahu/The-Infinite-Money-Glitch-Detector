"""Cryptographic Artifact Integrity Engine for Phase 5 Dashboard.

Provides byte-level SHA-256 checksum verification against registered digests.
Prevents corrupted, tampered, or incomplete research artifacts from entering
the dashboard execution environment.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional, Tuple, Union

from dashboard.artifacts.registry import (
    resolve_artifact_path,
)


class ArtifactIntegrityError(ValueError):
    """Raised when an artifact\'s actual SHA-256 checksum does not match its expected digest."""


class ArtifactNotFoundError(FileNotFoundError):
    """Raised when an artifact file does not exist on disk."""


def compute_file_sha256(file_path: Union[str, Path], chunk_size: int = 65536) -> str:
    """Compute the SHA-256 hex digest of a file by streaming its bytes.

    Args:
        file_path: Path to the target file.
        chunk_size: Streaming chunk size in bytes (default: 64KB).

    Returns:
        64-character lowercase hexadecimal SHA-256 digest.

    Raises:
        ArtifactNotFoundError: If file_path does not exist or is not a file.
    """
    path = Path(file_path).resolve()
    if not path.is_file():
        raise ArtifactNotFoundError(f"Artifact file not found: '{path}'")

    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def verify_file_sha256(
    file_path: Union[str, Path],
    expected_sha256: str,
) -> str:
    """Verify that a file\'s actual SHA-256 matches the expected digest.

    Args:
        file_path: Path to the target file.
        expected_sha256: The reference 64-character SHA-256 digest.

    Returns:
        The verified SHA-256 hex digest.

    Raises:
        ArtifactNotFoundError: If the file does not exist.
        ArtifactIntegrityError: If the computed digest does not match expected_sha256.
    """
    actual_sha256 = compute_file_sha256(file_path)
    clean_expected = expected_sha256.strip().lower()

    if actual_sha256 != clean_expected:
        raise ArtifactIntegrityError(
            f"Artifact integrity verification failed for '{file_path}'.\n"
            f"  Expected: {clean_expected}\n"
            f"  Actual:   {actual_sha256}\n"
            "The artifact has been altered, corrupted, or truncated on disk."
        )

    return actual_sha256


def verify_registered_artifact(
    artifact_id: str,
    version: Optional[str] = None,
    base_dir: Optional[Path] = None,
) -> Tuple[Path, str]:
    """Resolve and verify a registered artifact against its registry digest.

    Args:
        artifact_id: Registered artifact identifier.
        version: Target version string (optional).
        base_dir: Project root directory (optional).

    Returns:
        Tuple of (resolved_path, verified_sha256).

    Raises:
        UnknownArtifactError: If artifact_id is not recognized in registry.
        ArtifactNotFoundError: If resolved path does not exist on disk.
        ArtifactIntegrityError: If file hash does not match registry.
    """
    path, expected_digest = resolve_artifact_path(artifact_id, version=version, base_dir=base_dir)
    verified_digest = verify_file_sha256(path, expected_digest)
    return path, verified_digest
