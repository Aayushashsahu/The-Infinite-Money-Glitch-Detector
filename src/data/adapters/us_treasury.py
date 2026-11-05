"""US Department of the Treasury Daily Par Yield Curve Rates Adapter.

Provides genuine, traceable, keyless daily risk-free rates and constant
maturity yields directly from the official United States Department of the
Treasury (home.treasury.gov).

Quotation convention:
- entity_code = 'USD'
- unit = 'percent'
- publication_date = observation_date (Treasury publishes end-of-day market
  close yield curve rates same-day at ~15:30-16:00 ET).
- classification = REAL_VERIFIED
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import io
from typing import Any
import pandas as pd

from data.adapters.base import SourceAdapter
from data.http import get_text
from data.schemas import (
    DataClassification,
    DataObservation,
    FetchResult,
    Frequency,
    ObservationKind,
    RawRecordInfo,
)

US_TREASURY_BASE_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv"
)

TREASURY_SERIES_CATALOG: dict[str, dict[str, str]] = {
    "1 Mo": {
        "indicator_id": "DGS1MO",
        "name": "1-Month Treasury Constant Maturity Rate",
        "tenor": "1M",
    },
    "3 Mo": {
        "indicator_id": "DGS3MO",
        "name": "3-Month Treasury Constant Maturity Rate (Risk-Free Benchmark)",
        "tenor": "3M",
    },
    "6 Mo": {
        "indicator_id": "DGS6MO",
        "name": "6-Month Treasury Constant Maturity Rate",
        "tenor": "6M",
    },
    "1 Yr": {
        "indicator_id": "DGS1YR",
        "name": "1-Year Treasury Constant Maturity Rate",
        "tenor": "1Y",
    },
}


class UsTreasuryAdapter(SourceAdapter):
    """Daily historical risk-free Treasury yield curve rates from home.treasury.gov."""

    source_id = "us_treasury"
    display_name = "U.S. Department of the Treasury"

    @classmethod
    def parse_csv(
        cls,
        text: str,
        tenor: str = "3 Mo",
        indicator_id: str | None = None,
        retrieved_at: datetime | None = None,
    ) -> list[DataObservation]:
        """Parse raw Treasury CSV text into verified DataObservation instances."""
        now = retrieved_at or datetime.now(timezone.utc)
        df = pd.read_csv(io.StringIO(text))

        spec = TREASURY_SERIES_CATALOG.get(
            tenor,
            {"indicator_id": f"DGS_{tenor.replace(' ', '_')}", "name": f"{tenor} Treasury Rate"},
        )
        effective_indicator = indicator_id or spec["indicator_id"]

        target_col = tenor if tenor in df.columns else None
        if target_col is None:
            for col in df.columns:
                if col.strip().lower() == tenor.strip().lower():
                    target_col = col
                    break

        if target_col is None:
            return []

        observations: list[DataObservation] = []
        for _, row in df.iterrows():
            raw_date = row.get("Date")
            raw_val = row.get(target_col)
            if pd.isna(raw_date) or pd.isna(raw_val):
                continue
            val_str = str(raw_val).strip()
            if val_str in ("", ".", "N/A", "ND"):
                continue  # Market holidays / unquoted tenors: skipped, never filled

            try:
                rate_val = float(val_str)
                dt = datetime.strptime(str(raw_date).strip(), "%m/%d/%Y").date()
            except (ValueError, TypeError):
                continue

            observations.append(
                DataObservation(
                    kind=ObservationKind.INTEREST_RATE,
                    source_id=cls.source_id,
                    indicator_id=effective_indicator,
                    entity_code="USD",
                    value=rate_val,
                    unit="percent",
                    frequency=Frequency.DAILY,
                    observation_date=dt,
                    publication_date=dt,  # Treasury publishes end-of-day market close same-day
                    retrieved_at=now,
                    revision=0,
                    is_synthetic=False,
                    classification=DataClassification.REAL_VERIFIED,
                    metadata={"tenor": tenor, "series_name": spec["name"]},
                )
            )

        observations.sort(key=lambda o: o.observation_date)
        return observations

    def fetch_yield_curve_year(
        self,
        year: int,
        tenor: str = "3 Mo",
    ) -> tuple[list[DataObservation], RawRecordInfo, list[str]]:
        """Fetch daily rates for one year."""
        now = datetime.now(timezone.utc)
        url = f"{US_TREASURY_BASE_URL}/{year}/all"
        params = {
            "type": "daily_treasury_yield_curve",
            "field_tdr_date_value": str(year),
            "page": "",
            "_format": "csv",
        }
        text = get_text(self.client, url, params=params)
        observations = self.parse_csv(text, tenor=tenor, retrieved_at=now)
        raw_rec = RawRecordInfo(url=url, payload=text, retrieved_at=now)
        warning = f"us_treasury {year}: {len(observations)} daily rates for {tenor}."
        return observations, raw_rec, [warning]

    def fetch_series(
        self,
        tenor: str = "3 Mo",
        start_year: int = 2020,
        end_year: int = 2024,
    ) -> FetchResult:
        """Fetch daily rates across multiple calendar years."""
        all_obs: list[DataObservation] = []
        all_raw: list[RawRecordInfo] = []
        all_warn: list[str] = []

        for y in range(start_year, end_year + 1):
            obs, raw, warns = self.fetch_yield_curve_year(y, tenor=tenor)
            all_obs.extend(obs)
            all_raw.append(raw)
            all_warn.extend(warns)

        all_obs.sort(key=lambda o: o.observation_date)
        return FetchResult(observations=all_obs, raw_records=all_raw, warnings=all_warn)

    def fetch(self, **kwargs: Any) -> FetchResult:
        tenor = kwargs.get("tenor", "3 Mo")
        start_year = int(kwargs.get("start_year", 2020))
        end_year = int(kwargs.get("end_year", 2024))
        return self.fetch_series(tenor=tenor, start_year=start_year, end_year=end_year)
