"""Formatted Table Display Components for Phase 5 Dashboard.

Provides formatted DataFrame rendering and styling utilities tailored for
financial and simulation metric tables.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
import pandas as pd
import streamlit as st


def render_data_table(
    df: pd.DataFrame,
    title: Optional[str] = None,
    column_config: Optional[Dict[str, Any]] = None,
    height: Optional[int] = None,
    use_container_width: bool = True,
) -> None:
    """Render a styled interactive dataframe in Streamlit.

    Args:
        df: Pandas DataFrame to display.
        title: Optional section title.
        column_config: Streamlit column configuration dictionary.
        height: Optional fixed table height in pixels.
        use_container_width: Stretch table to container width.
    """
    if title:
        st.subheader(title)
    st.dataframe(
        df,
        column_config=column_config,
        height=height,
        use_container_width=use_container_width,
        hide_index=True,
    )
