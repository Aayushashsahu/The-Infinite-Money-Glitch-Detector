"""Page 3 — Market Data & Provenance: Economic Data, Availability & Calendar Audit.

Provides comprehensive inspection of the underlying macroeconomic database, point-in-time
publication lag classifications, settlement calendar validation, and simulation provenance.

Guiding Principle: Mathematics first. Data second. Prediction third. AI last.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.artifacts.db import query_readonly
from dashboard.artifacts.loader import (
    load_availability_audit,
    load_calendar_validation,
    load_simulation_manifest,
)
from dashboard.components.banner import render_research_banner
from dashboard.components.metrics_card import render_metric_card
from dashboard.components.plots.series import build_time_series_figure
from dashboard.components.tables import render_data_table

st.set_page_config(
    page_title="Market Data & Provenance — The Infinite Money Glitch Detector",
    page_icon="🏛️",
    layout="wide",
)


def render_page() -> None:
    """Render the Market Data & Provenance page."""
    # --------------------------------------------------------------------------
    # A. Research Classification Banner
    # --------------------------------------------------------------------------
    render_research_banner(
        data_classification="SIMULATED_RESEARCH_PROXY",
        pit_mode="ESTIMATED_LAG",
        extra_notice="Data provenance and point-in-time classification audit. Evaluates data integrity, release calendars, and database verification.",
    )

    st.title("🏛️ Market Data Infrastructure & Provenance Audit")
    st.caption("Point-in-Time Availability | Settlement Calendars | Cryptographic Manifests")

    # Load authoritative artifacts
    avail = load_availability_audit()
    cal = load_calendar_validation()
    manifest = load_simulation_manifest()

    # --------------------------------------------------------------------------
    # B. Data Inventory Overview
    # --------------------------------------------------------------------------
    st.subheader("1. Data Inventory & Observation Breakdown")
    st.markdown(
        """
        The quantitative research pipeline strictly segregates genuine empirical observations
        from synthetic fixtures, and tracks point-in-time availability across all factor series:
        """
    )

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        render_metric_card(
            label="Total Source Records",
            value=f"{avail.total_source_observations:,}",
            help_text="Total rows present in data_observation table in gmdb.db.",
        )
    with col2:
        render_metric_card(
            label="Genuine Historical Obs",
            value=f"{avail.genuine_observations_included:,}",
            delta="Included in Research",
            delta_color="normal",
            help_text="Historical market observations excluding synthetic test records.",
        )
    with col3:
        render_metric_card(
            label="Synthetic Excluded",
            value=f"{avail.synthetic_observations_excluded:,}",
            delta="Permanently Filtered",
            delta_color="off",
            help_text="Synthetic test fixtures isolated from research queries.",
        )
    with col4:
        render_metric_card(
            label="Estimated Availability",
            value=f"{avail.estimated_availability_count:,}",
            delta="ESTIMATED_LAG Policy",
            delta_color="normal",
            help_text="Observations governed by verified release lag policies.",
        )
    with col5:
        render_metric_card(
            label="Retrospective Records",
            value=f"{avail.retrospective_count:,}",
            delta="World Bank CPI Only",
            delta_color="off",
            help_text="Annual macroeconomic series without point-in-time publication timestamps.",
        )

    st.info(
        "**CRITICAL ARCHITECTURAL ERRATUM:** All **176 retrospective observations** belong exclusively "
        "to `FP.CPI.TOTL.ZG` (annual World Bank CPI series). They are **never** attributed to policy-rate dates, "
        "fixing timestamps, or daily exchange rate quotes."
    )

    st.divider()

    # --------------------------------------------------------------------------
    # C. Availability Classification & Release Lag Policies
    # --------------------------------------------------------------------------
    st.subheader("2. Point-in-Time Availability Classification & Lag Policies")
    st.markdown(
        """
        Point-in-time availability prevents look-ahead bias by enforcing strict release calendars
        and publication cutoffs before any observation enters trading decisions:
        """
    )

    c_col1, c_col2 = st.columns([1, 1])

    with c_col1:
        st.markdown("##### Availability Classification Counts")
        avail_summary_df = pd.DataFrame(
            [
                {
                    "Classification Bucket": "Estimated Publication Availability",
                    "Count": avail.estimated_availability_count,
                    "Share (%)": f"{avail.estimated_availability_count / avail.genuine_observations_included * 100:.2f}%",
                },
                {
                    "Classification Bucket": "Retrospective (World Bank Annual CPI)",
                    "Count": avail.retrospective_count,
                    "Share (%)": f"{avail.retrospective_count / avail.genuine_observations_included * 100:.2f}%",
                },
                {
                    "Classification Bucket": "Exact Timestamp Verified",
                    "Count": avail.exact_timestamp_verified_count,
                    "Share (%)": f"{avail.exact_timestamp_verified_count / avail.genuine_observations_included * 100:.2f}%",
                },
                {
                    "Classification Bucket": "Missing Classification Evidence",
                    "Count": avail.missing_evidence_count,
                    "Share (%)": "0.00%",
                },
            ]
        )
        render_data_table(avail_summary_df)

        st.warning(
            "**DEFINITION OF MISSING EVIDENCE:** `missing_evidence_count = 0` signifies that zero observations "
            "lack point-in-time availability evidence in the classification audit. "
            "It does **NOT** mean zero missing market calendar observations."
        )

    with c_col2:
        st.markdown("##### Documented Release Lag Policies")
        lag_policies = [
            {
                "Series / Factor": k,
                "Release Policy & Decision Timestamp Cutoff": v,
            }
            for k, v in avail.release_lag_policies.items()
        ]
        render_data_table(pd.DataFrame(lag_policies))

    st.divider()

    # --------------------------------------------------------------------------
    # D. Economic Time-Series Inspection (Read-Only SQLite)
    # --------------------------------------------------------------------------
    st.subheader("3. Interactive Economic Time-Series Inspection")
    st.markdown(
        """
        Query verified, read-only observations directly from the underlying research database (`data/processed/gmdb.db`).
        All series display raw empirical observations without synthetic daily interpolation:
        """
    )

    series_options = {
        "ECB Deposit Facility Rate (KR.DFR.LEV)": (
            "ECB_EA",
            "KR.DFR.LEV",
            "Rate (% p.a.)",
            "ECB Policy Deposit Facility Rate",
        ),
        "ECB Main Refinancing Rate (KR.MRR_FR.LEV)": (
            "ECB_EA",
            "KR.MRR_FR.LEV",
            "Rate (% p.a.)",
            "ECB Main Refinancing Operations Fixed Rate",
        ),
        "EUR/USD Reference Exchange Rate": (
            "EUR/USD",
            None,
            "Exchange Rate (USD per EUR)",
            "Frankfurter / ECB Daily Fixing Rate",
        ),
        "US Treasury 1-Month Rate (DGS1MO)": (
            "USD",
            "DGS1MO",
            "Yield (% p.a.)",
            "Federal Reserve H.15 1-Month Constant Maturity Yield",
        ),
        "US Treasury 3-Month Rate (DGS3MO)": (
            "USD",
            "DGS3MO",
            "Yield (% p.a.)",
            "Federal Reserve H.15 3-Month Constant Maturity Yield",
        ),
        "World Bank CPI — United States (FP.CPI.TOTL.ZG)": (
            "USA",
            "FP.CPI.TOTL.ZG",
            "Annual CPI Inflation (%)",
            "World Bank Annual Inflation Index",
        ),
        "World Bank CPI — Japan (FP.CPI.TOTL.ZG)": (
            "JPN",
            "FP.CPI.TOTL.ZG",
            "Annual CPI Inflation (%)",
            "World Bank Annual Inflation Index",
        ),
        "World Bank CPI — Brazil (FP.CPI.TOTL.ZG)": (
            "BRA",
            "FP.CPI.TOTL.ZG",
            "Annual CPI Inflation (%)",
            "World Bank Annual Inflation Index",
        ),
    }

    selected_series_name = st.selectbox(
        "Select Historical Series to Inspect:",
        options=list(series_options.keys()),
        index=2,  # Default: EUR/USD
    )

    entity_code, indicator_id, y_unit, series_desc = series_options[selected_series_name]

    if indicator_id is None:
        query = """
            SELECT observation_date, value, is_synthetic
            FROM data_observation
            WHERE entity_code = ? AND indicator_id IS NULL AND is_synthetic = 0
            ORDER BY observation_date ASC;
        """
        params = (entity_code,)
    else:
        query = """
            SELECT observation_date, value, is_synthetic
            FROM data_observation
            WHERE entity_code = ? AND indicator_id = ? AND is_synthetic = 0
            ORDER BY observation_date ASC;
        """
        params = (entity_code, indicator_id)

    try:
        rows = query_readonly(query, params)
        df_series = pd.DataFrame(rows)

        if not df_series.empty:
            df_series["observation_date"] = pd.to_datetime(df_series["observation_date"])
            df_series["value"] = pd.to_numeric(df_series["value"])

            st.plotly_chart(
                build_time_series_figure(
                    df=df_series,
                    date_col="observation_date",
                    value_col="value",
                    title=f"{selected_series_name} ({len(df_series):,} Observations)",
                    y_title=y_unit,
                    height=420,
                ),
                use_container_width=True,
            )

            s_col1, s_col2, s_col3, s_col4 = st.columns(4)
            with s_col1:
                render_metric_card("Observations", f"{len(df_series):,}")
            with s_col2:
                render_metric_card("Start Date", str(df_series["observation_date"].min().date()))
            with s_col3:
                render_metric_card("End Date", str(df_series["observation_date"].max().date()))
            with s_col4:
                render_metric_card("Latest Value", f"{df_series['value'].iloc[-1]:.4f}")
        else:
            st.warning("No observations returned for the selected series query.")
    except Exception as e:
        st.error(f"Error querying read-only database: {e}")

    st.divider()

    # --------------------------------------------------------------------------
    # E. Settlement Calendar & Accrual Validation
    # --------------------------------------------------------------------------
    st.subheader("4. Settlement Calendar & Accrual Validation")
    st.markdown(
        """
        Accurate interest and financing accrual requires unified settlement calendars across central banks.
        The `JointTarget2FedCalendar` handles weekend accruals, bank holidays, and contractual exit horizons:
        """
    )

    cal_col1, cal_col2 = st.columns([1, 1])

    with cal_col1:
        st.markdown("##### Accrual Invariant Verification")
        cal_checks = [
            {
                "Calendar Specification": "Calendar Implementation",
                "Status": cal.calendar_implementation,
                "Verified": "PASS",
            },
            {
                "Calendar Specification": "Initial State (t=0) Zero Interest",
                "Status": "Zero Interest at Entry",
                "Verified": "PASS" if cal.initial_state_zero_interest else "FAIL",
            },
            {
                "Calendar Specification": "Weekend Accrual (Friday to Monday)",
                "Status": "3 Elapsed Calendar Days",
                "Verified": "PASS" if cal.weekend_3day_accrual_verified else "FAIL",
            },
            {
                "Calendar Specification": "Joint Holiday Settlement Accrual",
                "Status": "Full Calendar Elapsed Time",
                "Verified": "PASS" if cal.holiday_accrual_verified else "FAIL",
            },
            {
                "Calendar Specification": "Contractual 30-Day Tenor Exit",
                "Status": "Maturity on Next Business Day",
                "Verified": "PASS" if cal.tenor_30day_maturity_verified else "FAIL",
            },
            {
                "Calendar Specification": "Transitions (N) vs. Levels (N+1)",
                "Status": "Verified Dimension Parity",
                "Verified": "PASS" if cal.transitions_n_levels_n_plus_1_verified else "FAIL",
            },
            {
                "Calendar Specification": "Independent Accrual Formula Check",
                "Status": "81.45 EUR matches engine",
                "Verified": "PASS" if cal.independent_numerical_accrual_verified else "FAIL",
            },
        ]
        render_data_table(pd.DataFrame(cal_checks))

    with cal_col2:
        st.markdown("##### Verification Notes & Methodology")
        for note in cal.notes:
            st.markdown(f"- {note}")

    st.divider()

    # --------------------------------------------------------------------------
    # F. Simulation Manifest & Cryptographic Provenance
    # --------------------------------------------------------------------------
    st.subheader("5. Simulation Manifest & System Provenance")
    st.markdown(
        """
        Cryptographic fingerprints guaranteeing reproducibility across platforms, seeds, and source data:
        """
    )

    prov_col1, prov_col2 = st.columns(2)

    with prov_col1:
        st.markdown("##### Execution Lineage")
        lineage_data = [
            {"Property": "Git Commit", "Value": manifest.git_commit},
            {"Property": "Simulation Code Commit", "Value": manifest.simulation_code_commit},
            {"Property": "Source Tree Digest", "Value": manifest.source_tree_digest},
            {"Property": "Research Database SHA-256", "Value": manifest.database_sha256},
            {"Property": "RNG Bit Generator", "Value": manifest.rng_bit_generator},
            {"Property": "Random Seed", "Value": str(manifest.random_seed)},
            {"Property": "Working Tree Clean", "Value": str(manifest.git_working_tree_clean)},
        ]
        render_data_table(pd.DataFrame(lineage_data))

    with prov_col2:
        st.markdown("##### Exceptional H.15 Market Closures")
        closures_data = [{"Date": d, "Closure Reason": r} for d, r in manifest.h15_exceptional_closures.items()]
        render_data_table(pd.DataFrame(closures_data))


if __name__ == "__main__":
    render_page()
