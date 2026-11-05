"""Historical-availability and coverage reporting.

Answers the Phase 2 reporting questions from the stored database:
earliest/latest observation, observation count, missing-data percentage
(gaps relative to the declared frequency between first and last
observation), per-country and per-indicator coverage, and which
entities have insufficient data for meaningful analysis.
"""

from __future__ import annotations

import pandas as pd

_FREQ_OFFSET = {
    "daily": "D",
    "weekly": "W",
    "monthly": "MS",
    "quarterly": "QS",
    "annual": "YS",
}

_MIN_YEARS_MEANINGFUL = 5.0


def _expected_periods(first: pd.Timestamp, last: pd.Timestamp, freq: str) -> int:
    """Count expected periods between first and last observation.

    Numpy length... none: pandas date_range with the frequency offset
    gives the period-aligned grid; anything shorter counts as one.
    """
    offset = _FREQ_OFFSET.get(freq)
    if offset is None or last < first:
        return 1
    first_ts = pd.Timestamp(first)  # dates may be datetime.date, not Timestamps
    last_ts = pd.Timestamp(last)
    return max(len(pd.date_range(start=first_ts.normalize(), end=last_ts.normalize(), freq=offset)), 1)


def series_coverage(observations: pd.DataFrame) -> pd.DataFrame:
    """Per-series coverage from a repository observation DataFrame.

    Args:
        observations: DataFrame as returned by
            :meth:`data.repository.Repository.load_observations` (latest
            revisions assumed).

    Returns:
        One row per (source, kind, entity, indicator, frequency): earliest,
        latest, observation count, missing %, years covered, sufficiency.
    """
    if observations.empty:
        return pd.DataFrame(
            columns=[
                "source_id", "kind", "entity_code", "indicator_id", "frequency",
                "earliest", "latest", "observations", "missing_pct",
                "years_covered", "sufficient",
            ]
        )
    grouped = observations.groupby(
        ["source_id", "kind", "entity_code", "indicator_id", "frequency"], dropna=False
    )
    rows = []
    for key, group in grouped:
        first = group["observation_date"].min()
        last = group["observation_date"].max()
        count = int(len(group))
        expected = _expected_periods(first, last, key[4])
        missing_pct = round(max(0.0, 1.0 - count / expected) * 100.0, 1) if expected > 1 else 0.0
        years = round(max(0.0, (last - first).days / 365.25), 1)
        rows.append(
            {
                "source_id": key[0],
                "kind": key[1],
                "entity_code": key[2],
                "indicator_id": key[3],
                "frequency": key[4],
                "earliest": first,
                "latest": last,
                "observations": count,
                "missing_pct": missing_pct,
                "years_covered": years,
                "sufficient": bool(years >= _MIN_YEARS_MEANINGFUL),
            }
        )
    return pd.DataFrame(rows).sort_values(["entity_code", "indicator_id"]).reset_index(drop=True)


def country_indicator_coverage(observations: pd.DataFrame) -> pd.DataFrame:
    """Country x indicator coverage matrix (observation counts)."""
    if observations.empty:
        return pd.DataFrame(columns=["entity_code", "indicator_id", "observations"])
    return (
        observations.groupby(["entity_code", "indicator_id"], dropna=False)
        .size()
        .reset_index(name="observations")
        .sort_values(["entity_code", "indicator_id"])
        .reset_index(drop=True)
    )


def insufficient_data(
    coverage: pd.DataFrame,
    min_observations: int = 5,
    min_years: float = _MIN_YEARS_MEANINGFUL,
) -> pd.DataFrame:
    """Series that do not reach minimum analysis requirements."""
    if coverage.empty:
        return coverage
    mask = (coverage["observations"] < min_observations) | (coverage["years_covered"] < min_years)
    return coverage[mask].reset_index(drop=True)
