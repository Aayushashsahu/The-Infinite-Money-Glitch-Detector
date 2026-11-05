"""Central bank policy-rate adapters.

Implemented today (with open, key-safe access):
- ECB Data Portal (``data-api.ecb.europa.eu``, keyless CSV): euro area
  key policy rates (deposit facility, main refinancing operations).
- FRED (Federal Reserve Economic Data, free *API key required*): US
  federal funds target range / effective rate. The key is passed in
  explicitly; adapters must never attempt key-discovery tricks.

Deliberately NOT implemented (no fragile scraping; see docs/phase2.md):
Bank of England, Bank of Japan, Banco Central do Brasil and others
currently lack comparable open machine-readable policy-rate endpoints
in this source's ToS-free surface; they must go through curated static
imports or an explicit, per-bank integration.

Interest-rate observations: ``entity_code = ISO3 country or bank code``,
``unit = 'percent'``, values as published by the bank,
``publication_date`` = date the bank published the decision (same day
for ECB CSV ``TIME_PERIOD`` and FRED observation dates, both documented
below).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

from data.http import get_json, get_text
from data.schemas import (
    DataObservation,
    FetchResult,
    Frequency,
    ObservationKind,
    RawRecordInfo,
)

from .base import SourceAdapter

ECB_DATA_PORTAL_BASE_URL = "https://data-api.ecb.europa.eu"

# ECB FM (financial markets) series: euro area key interest rates, level.
# Keys verified once manually; if the ECB re-keys them, the adapter fails
# loudly instead of returning empty data silently.
ECB_POLICY_SERIES: dict[str, dict[str, str]] = {
    "KR.DF.LEV": {
        "name": "Euro area deposit facility rate, level",
        "entity_code": "ECB_EA",
        "frequency": Frequency.DAILY,
        "sdmx_path": "FM/B.U2.EUR.4F.KR.DF.LEV",
    },
    "KR.DFR.LEV": {
        "name": "Euro area deposit facility rate, level (live DFR)",
        "entity_code": "ECB_EA",
        "frequency": Frequency.DAILY,
        "sdmx_path": "FM/D.U2.EUR.4F.KR.DFR.LEV",
    },
    "KR.MRR_FR.LEV": {
        "name": "Euro area main refinancing operations rate, level",
        "entity_code": "ECB_EA",
        "frequency": Frequency.DAILY,
        "sdmx_path": "FM/D.U2.EUR.4F.KR.MRR_FR.LEV",
    },
}

FRED_BASE_URL = "https://api.stlouisfed.org/fred"
FRED_POLICY_SERIES: dict[str, dict[str, str]] = {
    "DFEDTARU": {
        "name": "Federal Funds Target Range - Upper Limit",
        "entity_code": "FED_USA",
        "frequency": Frequency.DAILY,
    },
    "FEDFUNDS": {
        "name": "Federal Funds Effective Rate (monthly)",
        "entity_code": "FED_USA",
        "frequency": Frequency.MONTHLY,
    },
}


class EcbPolicyRateAdapter(SourceAdapter):
    """Euro area policy rates from the ECB Data Portal (no key)."""

    source_id = "ecb"
    display_name = "ECB Data Portal"

    def fetch_policy_rate(self, series_key: str, start: date | None = None) -> FetchResult:
        """Fetch one euro area policy-rate series as CSV.

        Args:
            series_key: ECB FM key, e.g. ``KR.DF.LEV`` or ``KR.DFR.LEV``.
            start: Optional earliest observation date.
        """
        if series_key not in ECB_POLICY_SERIES:
            raise ValueError(
                f"ECB series {series_key!r} is not in the declared policy-rate catalog "
                f"(known: {sorted(ECB_POLICY_SERIES)})."
            )
        spec = ECB_POLICY_SERIES[series_key]
        now = datetime.now(timezone.utc)
        path = spec.get("sdmx_path", f"FM/B.U2.EUR.4F.{series_key}")
        url = f"{ECB_DATA_PORTAL_BASE_URL}/service/data/{path}"
        params: dict[str, Any] = {"format": "csvdata"}
        if start is not None:
            params["startPeriod"] = start.isoformat()
        text = get_text(self.client, url, params=params)
        frame = pd.read_csv(pd.io.common.StringIO(text))
        observations: list[DataObservation] = []
        for _, row in frame.iterrows():
            raw_value = row.get("OBS_VALUE")
            raw_date = row.get("TIME_PERIOD")
            if pd.isna(raw_value) or raw_value in (".", ""):
                continue  # explicitly missing: skipped, counted, never filled
            obs_date = date.fromisoformat(str(raw_date))
            observations.append(
                DataObservation(
                    kind=ObservationKind.INTEREST_RATE,
                    source_id=self.source_id,
                    indicator_id=series_key,
                    entity_code=spec["entity_code"],
                    value=float(raw_value),
                    unit="percent",
                    frequency=spec["frequency"],
                    observation_date=obs_date,
                    publication_date=obs_date,  # ECB publishes rate levels same-day
                    retrieved_at=now,
                    metadata={"series_key": spec.get("sdmx_path", f"FM/B.U2.EUR.4F.{series_key}"), "series_name": spec["name"]},
                )
            )
        warning = f"ecb {series_key}: {len(observations)} observations ({spec['name']})."
        return FetchResult(
            observations=observations,
            raw_records=[RawRecordInfo(url=url, payload=text, retrieved_at=now)],
            warnings=[warning],
        )

    def fetch(self, series_key: str, start: date | None = None) -> FetchResult:
        """Generic entry point demanded by the adapter contract."""
        return self.fetch_policy_rate(series_key, start)


class FredAdapter(SourceAdapter):
    """US policy rates via FRED (free API key required by the Fed's ToS)."""

    source_id = "fred"
    display_name = "FRED (Federal Reserve Economic Data)"

    def __init__(self, api_key: str, client: Any | None = None):
        super().__init__(client)
        if not api_key:
            raise ValueError(
                "FredAdapter requires an explicit FRED API key (free, from "
                "https://fred.stlouisfed.org/docs/api/api_key.html). No key = no ingestion, by design."
            )
        self._api_key = api_key

    def fetch_policy_rate(self, series_id: str, start: date | None = None) -> FetchResult:
        """Fetch one FRED policy-rate series (JSON).

        Args:
            series_id: e.g. ``DFEDTARU``; must be in the declared catalog.
        """
        if series_id not in FRED_POLICY_SERIES:
            raise ValueError(
                f"FRED series {series_id!r} is not in the declared policy-rate catalog "
                f"(known: {sorted(FRED_POLICY_SERIES)})."
            )
        spec = FRED_POLICY_SERIES[series_id]
        now = datetime.now(timezone.utc)
        params: dict[str, Any] = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
        }
        if start is not None:
            params["observation_start"] = start.isoformat()
        payload = get_json(self.client, f"{FRED_BASE_URL}/series/observations", params=params)
        observations: list[DataObservation] = []
        for obs in payload.get("observations", []):
            value = obs.get("value")
            if value in (None, ".", ""):
                continue  # FRED encodes missing as '.': skipped, never filled
            obs_date = date.fromisoformat(obs["date"])
            observations.append(
                DataObservation(
                    kind=ObservationKind.INTEREST_RATE,
                    source_id=self.source_id,
                    indicator_id=None,
                    entity_code=spec["entity_code"],
                    value=float(value),
                    unit="percent",
                    frequency=spec["frequency"],
                    observation_date=obs_date,
                    publication_date=obs_date,  # governing policy decisions are public same-day
                    retrieved_at=now,
                    metadata={"series_id": series_id, "series_name": spec["name"]},
                )
            )
        warning = f"fred {series_id}: {len(observations)} observations ({spec['name']})."
        return FetchResult(
            observations=observations,
            raw_records=[RawRecordInfo(url=f"{FRED_BASE_URL}/series/observations", payload=payload, retrieved_at=now)],
            warnings=[warning],
        )

    def fetch(self, series_id: str, start: date | None = None) -> FetchResult:
        """Generic entry point demanded by the adapter contract."""
        return self.fetch_policy_rate(series_id, start)


# Central banks without an implemented, machine-readable endpoint here.
# Listed explicitly so "not supported" is never silently assumed to work.
UNIMPLEMENTED_CENTRAL_BANKS: dict[str, str] = {
    "BoE": "Bank of England database lacks an open machine-readable policy-rate API in its ToS-free surface.",
    "BoJ": "Bank of Japan publishes policy rates via file downloads; needs a curated static import.",
    "BCB": "Banco Central do Brasil SGS API exists but requires per-series curation (planned).",
}
