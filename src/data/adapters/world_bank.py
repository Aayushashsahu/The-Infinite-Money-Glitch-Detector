"""World Bank API v2 adapter (keyless, CC BY-4.0 attribution license).

API facts:
- Endpoint: ``https://api.worldbank.org/v2``.
- Country series are annual and are delivered *without* publication
  (metadata) dates. To stay honest we therefore set
  ``publication_date = None``: consumers must treat these observations
  as NOT point-in-time-safe.
- Pagination is global (pages interleave countries), so we deliberately
  fetch ONE country at a time and paginate per country.
- Missing values arrive as JSON ``null``: skipped and reported in
  ``FetchResult.warnings``, never forward-filled.
- The API exposes no revision identifiers, so every re-ingest arrives
  as ``revision 0`` and the repository layer detects value changes.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from data.http import get_json
from data.schemas import (
    CountryInfo,
    DataObservation,
    FetchResult,
    Frequency,
    ObservationKind,
    RawRecordInfo,
)

from .base import SourceAdapter

WORLD_BANK_BASE_URL = "https://api.worldbank.org/v2"

# Curated static lookup (reference data, not API output); the WB country
# endpoint does not expose currency codes. Tiny on purpose: countries
# without an entry get currency_code=None plus an explicit warning, so
# nothing is ever guessed silently.
_CURRENCY_BY_ISO3 = {
    "USA": "USD",
    "JPN": "JPY",
    "BRA": "BRL",
    "DEU": "EUR",
}

WORLD_BANK_INDICATORS: dict[str, dict[str, Any]] = {
    "FP.CPI.TOTL.ZG": {
        "name": "Inflation, consumer prices (annual %)",
        "unit": "percent",
        "frequency": Frequency.ANNUAL,
        "category": "inflation",
    },
    "NY.GDP.MKTP.KD.ZG": {
        "name": "GDP growth (annual %)",
        "unit": "percent",
        "frequency": Frequency.ANNUAL,
        "category": "growth",
    },
}


def _year_to_date(year_text: str) -> date:
    """World Bank dates are 4-digit year strings; annual obs anchored to Jan 1."""
    try:
        return date(int(year_text), 1, 1)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"World Bank date is not a year: {year_text!r}") from exc


class WorldBankAdapter(SourceAdapter):
    """Adapter for the World Bank API v2 (no key required)."""

    source_id = "world_bank"
    display_name = "World Bank Open Data (API v2)"

    def fetch_indicator(self, indicator_id: str, countries: list[str], per_page: int = 20_000) -> FetchResult:
        """Fetch one annual indicator, one country per request.

        Args:
            indicator_id: World Bank series code, e.g. ``FP.CPI.TOTL.ZG``.
            countries: ISO3 codes.
            per_page: Page size; defaults to a single page per country.
        """
        if indicator_id not in WORLD_BANK_INDICATORS:
            raise ValueError(
                f"Indicator {indicator_id!r} is not in the declared World Bank catalog "
                f"(known: {sorted(WORLD_BANK_INDICATORS)}). Add it with an explicit unit and frequency first."
            )
        spec = WORLD_BANK_INDICATORS[indicator_id]
        now = datetime.now(timezone.utc)
        observations: list[DataObservation] = []
        raw_records: list[RawRecordInfo] = []
        warnings: list[str] = []
        skipped_missing = 0

        for iso3 in countries:
            url = f"{WORLD_BANK_BASE_URL}/country/{iso3}/indicator/{indicator_id}"
            payload = get_json(self.client, url, params={"format": "json", "per_page": per_page})
            raw_records.append(RawRecordInfo(url=url, payload=payload, retrieved_at=now))
            if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
                raise ValueError(f"Unexpected World Bank response shape for {url}.")
            for item in payload[1]:
                if item.get("value") is None:
                    skipped_missing += 1
                    continue  # missing year: never fabricated
                meta: dict[str, Any] = {}
                if item.get("country") and item["country"].get("value"):
                    meta["country_name"] = item["country"]["value"]
                observations.append(
                    DataObservation(
                        kind=ObservationKind.MACRO_INDICATOR,
                        source_id=self.source_id,
                        indicator_id=indicator_id,
                        entity_code=item.get("countryiso3code") or iso3,
                        value=float(item["value"]),
                        unit=spec["unit"],
                        frequency=spec["frequency"],
                        observation_date=_year_to_date(item["date"]),
                        publication_date=None,  # not provided by the API (documented)
                        retrieved_at=now,
                        metadata=meta,
                    )
                )
        # The API returns newest year first; normalise to chronological order
        # (the quality engine flags out-of-order batches, and consumers expect
        # ascending series).
        observations.sort(key=lambda o: (o.entity_code, o.observation_date))
        if skipped_missing:
            warnings.append(
                f"world_bank {indicator_id}: {skipped_missing} observations had no value "
                "(missing data is skipped, never forward-filled)."
            )
        return FetchResult(observations=observations, raw_records=raw_records, warnings=warnings)

    def fetch(self, indicator_id: str, countries: list[str], per_page: int = 20_000) -> FetchResult:
        """Generic entry point demanded by the adapter contract."""
        return self.fetch_indicator(indicator_id, countries, per_page)

    def fetch_country_metadata(self, countries: list[str]) -> tuple[list[CountryInfo], FetchResult]:
        """Fetch country records; ISO3 comes from the endpoint's ``id`` field."""
        now = datetime.now(timezone.utc)
        url = f"{WORLD_BANK_BASE_URL}/country/" + ";".join(countries)
        payload = get_json(self.client, url, params={"format": "json", "per_page": 500})
        if not isinstance(payload, list) or len(payload) < 2:
            raise ValueError(f"Unexpected World Bank country response for {url}.")
        infos: list[CountryInfo] = []
        for item in payload[1] or []:
            infos.append(
                CountryInfo(
                    iso3=item["id"],
                    name=item.get("name", ""),
                    currency_code=_CURRENCY_BY_ISO3.get(item["id"]),
                )
            )
        missing_fx = [i.iso3 for i in infos if i.currency_code is None]
        warnings = (
            [f"world_bank: no curated currency mapping for {missing_fx} (currency_code left null)."]
            if missing_fx
            else []
        )
        return infos, FetchResult(
            raw_records=[RawRecordInfo(url=f"{WORLD_BANK_BASE_URL}{url}", payload=payload, retrieved_at=now)],
            warnings=warnings,
        )
