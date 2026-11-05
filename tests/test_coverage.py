"""Coverage-reporting math tests (synthetic frames, no database)."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from data.coverage import (
    country_indicator_coverage,
    insufficient_data,
    series_coverage,
)


def _frame(rows: list[tuple[str, str, str, str, str, date]], values: list[float]) -> pd.DataFrame:
    """rows: (source, kind, entity, indicator, frequency, observation_date)."""
    return pd.DataFrame(
        [
            {
                "source_id": r[0],
                "kind": r[1],
                "entity_code": r[2],
                "indicator_id": r[3],
                "frequency": r[4],
                "observation_date": r[5],
                "value": v,
            }
            for r, v in zip(rows, values)
        ]
    )


ANNUAL_ROWS = [
    ("world_bank", "macro_indicator", "USA", "CPI_YOY", "annual", date(2020, 1, 1)),
    ("world_bank", "macro_indicator", "USA", "CPI_YOY", "annual", date(2021, 1, 1)),
    ("world_bank", "macro_indicator", "USA", "CPI_YOY", "annual", date(2022, 1, 1)),
    ("world_bank", "macro_indicator", "USA", "CPI_YOY", "annual", date(2023, 1, 1)),
    ("world_bank", "macro_indicator", "USA", "CPI_YOY", "annual", date(2024, 1, 1)),
    ("world_bank", "macro_indicator", "BRA", "CPI_YOY", "annual", date(2020, 1, 1)),
    ("world_bank", "macro_indicator", "BRA", "CPI_YOY", "annual", date(2022, 1, 1)),
]


def test_series_coverage_counts_and_missing_pct() -> None:
    values = [2.1, 4.7, 8.0, 3.4, 2.9, 4.5, -1.2]  # BRA misses 2021/2023 relative to range
    df = _frame(ANNUAL_ROWS, values)
    coverage = series_coverage(df)

    usa = coverage[(coverage["entity_code"] == "USA") & (coverage["indicator_id"] == "CPI_YOY")]
    assert len(usa) == 1
    row = usa.iloc[0]
    assert row["observations"] == 5
    assert row["earliest"] == date(2020, 1, 1)
    assert row["latest"] == date(2024, 1, 1)
    assert row["missing_pct"] == 0.0  # every expected annual period present

    bra = coverage[coverage["entity_code"] == "BRA"].iloc[0]
    assert bra["observations"] == 2
    # 3 annual grid points between 2020 and 2022 inclusive; 1 absent:
    assert bra["missing_pct"] == pytest.approx(33.3, abs=0.05)  # engine rounds to 0.1 %


def test_insufficient_data_identifies_thin_series() -> None:
    values = [2.1, 4.7, 8.0, 3.4, 2.9, 4.5, -1.2]
    df = _frame(ANNUAL_ROWS, values)
    coverage = series_coverage(df)

    thin = insufficient_data(coverage, min_observations=3, min_years=3.5)
    assert set(thin["entity_code"]) == {"BRA"}  # 2 obs (3<3) and 2-year span (<3.5)

    strict_years = insufficient_data(coverage, min_observations=100, min_years=0)
    assert len(strict_years) == 2  # nothing reaches impossibly high counts


def test_coverage_empty_input_is_safe() -> None:
    empty = pd.DataFrame(
        columns=["source_id", "kind", "entity_code", "indicator_id", "frequency", "observation_date"]
    )
    assert series_coverage(empty).empty
    assert country_indicator_coverage(empty).empty
    assert insufficient_data(series_coverage(empty)).empty


def test_daily_series_coverage_uses_calendar_grid() -> None:
    rows = [
        ("fx", "exchange_rate", "USD/BRL", None, "daily", date(2024, 1, 1 + d))
        for d in range(31)
    ]
    df = _frame(rows, [4.9] * 31)
    coverage = series_coverage(df)
    row = coverage.iloc[0]
    # 31 Jan days, all weekday-present so far in this synthetic slice:
    assert row["observations"] == 31
    assert 0.0 <= row["missing_pct"] <= 100.0
