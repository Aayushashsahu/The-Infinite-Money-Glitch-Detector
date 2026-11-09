"""Read-Only SQLite Database Access Engine for Phase 5 Dashboard.

Provides strictly read-only, query-only connection utilities and provenance
metadata extraction for the underlying research database (data/processed/gmdb.db).

Enforces:
1. SQLite URI read-only mode (?mode=ro)
2. PRAGMA query_only = ON
3. Cryptographic SHA-256 verification against simulation_manifest.json
4. Strict rejection of any write/mutation statements
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from dashboard.artifacts.integrity import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    compute_file_sha256,
)

# Authoritative SHA-256 digest from simulation_manifest.json
AUTHORITATIVE_DB_SHA256: str = "7913ae5ced269d476a07cec3e477bfe4799743ee779203a93a4b9ef008e87ffa"
DEFAULT_DB_RELATIVE_PATH: str = "data/processed/gmdb.db"


def resolve_db_path(
    db_path: Optional[Union[str, Path]] = None,
    base_dir: Optional[Path] = None,
) -> Path:
    """Resolve the filesystem path to the research database.

    Args:
        db_path: Explicit database path (optional).
        base_dir: Root directory of repository (defaults to project root).

    Returns:
        Absolute Path to gmdb.db.

    Raises:
        ArtifactNotFoundError: If database file does not exist on disk.
    """
    if db_path is not None:
        target = Path(db_path).resolve()
    else:
        if base_dir is None:
            base_dir = Path(__file__).resolve().parents[3]
        target = (base_dir / DEFAULT_DB_RELATIVE_PATH).resolve()

    if not target.is_file():
        raise ArtifactNotFoundError(f"Research database not found at '{target}'")
    return target


def verify_db_sha256(
    db_path: Optional[Union[str, Path]] = None,
    expected_sha256: str = AUTHORITATIVE_DB_SHA256,
    base_dir: Optional[Path] = None,
) -> str:
    """Verify the research database against its registered SHA-256 digest.

    Args:
        db_path: Optional path to database file.
        expected_sha256: Expected SHA-256 hash.
        base_dir: Optional project root.

    Returns:
        Verified 64-character SHA-256 string.

    Raises:
        ArtifactIntegrityError: If computed hash does not match expected_sha256.
    """
    target = resolve_db_path(db_path=db_path, base_dir=base_dir)
    actual_hash = compute_file_sha256(target)
    clean_expected = expected_sha256.strip().lower()

    if actual_hash != clean_expected:
        raise ArtifactIntegrityError(
            f"Database integrity verification failed for '{target}'.\n"
            f"  Expected: {clean_expected}\n"
            f"  Actual:   {actual_hash}"
        )
    return actual_hash


def get_readonly_db_connection(
    db_path: Optional[Union[str, Path]] = None,
    base_dir: Optional[Path] = None,
) -> sqlite3.Connection:
    """Open a strictly read-only SQLite connection to the research database.

    Configured with:
    - URI mode ?mode=ro
    - PRAGMA query_only = ON
    - sqlite3.Row factory for dict-like column access

    Args:
        db_path: Optional path to gmdb.db.
        base_dir: Optional project root.

    Returns:
        sqlite3.Connection configured for read-only operation.
    """
    target = resolve_db_path(db_path=db_path, base_dir=base_dir)
    uri = f"file:{target.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.execute("PRAGMA query_only = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def query_readonly(
    sql: str,
    params: tuple = (),
    db_path: Optional[Union[str, Path]] = None,
    base_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Execute a read-only query and return results as a list of dicts.

    Args:
        sql: SELECT SQL statement.
        params: Query parameters.
        db_path: Optional database path.
        base_dir: Optional project root.

    Returns:
        List of row dicts.
    """
    with get_readonly_db_connection(db_path=db_path, base_dir=base_dir) as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_database_metadata(
    db_path: Optional[Union[str, Path]] = None,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Extract metadata, table names, and row counts from the research database.

    Args:
        db_path: Optional path to gmdb.db.
        base_dir: Optional project root.

    Returns:
        Dict containing table row counts, schema list, and path.
    """
    target = resolve_db_path(db_path=db_path, base_dir=base_dir)
    with get_readonly_db_connection(db_path=target) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
        tables = [row["name"] for row in cursor.fetchall()]

        counts: Dict[str, int] = {}
        for tbl in tables:
            cursor.execute(f"SELECT count(*) AS cnt FROM {tbl};")  # nosec
            counts[tbl] = int(cursor.fetchone()["cnt"])

    return {
        "db_path": str(target),
        "tables": tables,
        "row_counts": counts,
        "total_observations": counts.get("data_observation", 0),
        "total_sources": counts.get("data_source", 0),
    }
