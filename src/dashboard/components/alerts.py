"""Standardized Institutional Alerts & Provenance Badges for Phase 5 Dashboard.

Provides consistent styling for warnings, errors, notifications, and provenance
verification badges.
"""

from __future__ import annotations

from typing import Optional
import streamlit as st


def render_provenance_badge(
    git_commit: str,
    db_sha256: str,
    is_clean: bool = True,
    rng_seed: Optional[int] = 42,
) -> None:
    """Render a compact research provenance footer badge."""
    clean_badge = "Clean" if is_clean else "Modified"
    short_commit = git_commit[:10] if git_commit else "N/A"
    short_db = db_sha256[:10] if db_sha256 else "N/A"

    st.caption(
        f"**Artifact Provenance:** Commit `{short_commit}` ({clean_badge}) | "
        f"Database SHA-256 `{short_db}...` | "
        f"RNG Seed `{rng_seed}` | "
        f"Mode `READ_ONLY`"
    )


def render_info_box(title: str, message: str) -> None:
    """Render an institutional informative alert block."""
    st.info(f"**{title}**\n\n{message}")


def render_warning_box(title: str, message: str) -> None:
    """Render an institutional warning alert block."""
    st.warning(f"**{title}**\n\n{message}")


def render_error_box(title: str, message: str) -> None:
    """Render an institutional error alert block."""
    st.error(f"**{title}**\n\n{message}")
