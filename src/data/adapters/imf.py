"""IMF adapter (SDMX-JSON "compact data" endpoint of the IFS database).

API facts and limitations:
- Endpoint: ``https://dataservices.imf.org/REST/SDMX_JSON.svc/CompactData``
- Series keys are ``<freq>.<ref_area>.<indicator>`` (e.g. ``M.US.ERC_XDC_USD_RATE``
  = monthly local currency per USD exchange rate).
- No API key required. NOTE: this legacy endpoint is being phased out by
  the IMF in favor of a new data portal; it may fail at any time. The
  adapter raises any failure transparently - nothing is fabricated.
- IFS exchange-rate series quote *domestic currency per USD* (units of
  the reference-area currency per 1 USD). The adapter normalizes this to
  the platform pair convention ``'{REF_AREA_CURRENCY}/{QUOTE}'``, i.e.
  value = units of ref-area currency per USD.
- Publication dates are not exposed per-observation by this endpoint;
  they remain ``None`` and must not be treated as point-in-time-safe.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from data.http import get_json
from data.schemas import (
    DataObservation,
    FetchResult,
    Frequency,
    ObservationKind,
    RawRecordInfo,
)

from .base import SourceAdapter

IMF_BASE_URL = "https://dataservices.imf.org/REST/SDMX_JSON.svc"

_FREQUENCY_MAP = {
    "A": Frequency.ANNUAL,
    "M": Frequency.MONTHLY,
    "Q": Frequency.QUARTERLY,
    "W": Frequency.WEEKLY,
    "D": Frequency.DAILY,
}

# Declared catalog: only series we can name precisely in advance.
IMF_INDICATORS: dict[str, dict[str, Any]] = {
    "ERC_XDC_USD_RATE": {
        "name": "Exchange Rates, Domestic Currency per U.S. Dollar, period average",
        "unit": "rate",
        "category": "exchange_rate",
    },
    "PCPI_IX": {
        "name": "Consumer Price Index, All Items, Index",
        "unit": "index",
        "category": "inflation",
    },
}


def _period_to_date(period: str) -> date:
    """Convert SDMX period strings 'YYYY' / 'YYYY-Qn' / 'YYYY-MM' to a date.

    The date anchors the period to its FIRST day; the observation still
    belongs to the whole period (frequency carries the semantics).
    """
    if len(period) == 4:
        return date(int(period), 1, 1)
    if "Q" in period:
        year, quarter = period.split("Q")
        return date(int(year), 3 * int(quarter) - 2, 1)
    if len(period) >= 7 and period[4] == "-":
        year, month = period[:4], period[5:7]
        return date(int(year), int(month), 1)
    raise ValueError(f"Unrecognized IMF period: {period!r}")


class ImfAdapter(SourceAdapter):
    """Adapter for IMF IFS compact-data SDMX-JSON (no key)."""

    source_id = "imf"
    display_name = "IMF International Financial Statistics"

    def fetch_series(self, series_key: str) -> FetchResult:
        """Fetch one IFS series key, e.g. ``M.US.ERC_XDC_USD_RATE``.

        Args:
            series_key: ``<freq>.<ref_area>.<indicator>``.
        """
        parts = series_key.split(".")
        if len(parts) != 3:
            raise ValueError(f"IFS series key must be '<freq>.<ref_area>.<indicator>', got {series_key!r}.")
        freq_code, ref_area, indicator_id = parts
        if indicator_id not in IMF_INDICATORS:
            raise ValueError(
                f"IMF indicator {indicator_id!r} is not in the declared catalog "
                f"(known: {sorted(IMF_INDICATORS)}); add it with an explicit unit first."
            )
        spec = IMF_INDICATORS[indicator_id]
        frequency = _FREQUENCY_MAP.get(freq_code)
        if frequency is None:
            raise ValueError(f"Unknown IMF frequency code {freq_code!r}.")

        now = datetime.now(timezone.utc)
        url = f"{IMF_BASE_URL}/CompactData/IFS/{series_key}"
        payload = get_json(self.client, url)
        dataset = (payload.get("CompactData") or {}).get("DataSet") or {}
        series_list = dataset.get("Series") or []
        observations: list[DataObservation] = []
        for series in series_list:
            series_meta = {
                "frequency_code": series.get("@FREQ"),
                "ref_area": series.get("@REF_AREA"),
                "iso_country_code": series.get("@ISOCountry"),
            }
            for obs in series.get("Obs") or []:
                value = obs.get("@OBS_VALUE")
                if value in (None, "", "NaN"):
                    continue  # missing: skipped explicitly, reported below
                observations.append(
                    DataObservation(
                        kind=ObservationKind.MACRO_INDICATOR,
                        source_id=self.source_id,
                        indicator_id=indicator_id,
                        entity_code=ref_area,
                        value=float(value),
                        unit=spec["unit"],
                        frequency=frequency,
                        observation_date=_period_to_date(str(obs["@TIME_PERIOD"])),
                        publication_date=None,  # endpoint does not expose publication dates
                        retrieved_at=now,
                        metadata=series_meta,
                    )
                )
        warning = (
            f"imf IFS {series_key}: {len(observations)} observations; legacy endpoint "
            "(dataservices.imf.org) - verify continuity against the new IMF data portal."
        )
        return FetchResult(
            observations=observations,
            raw_records=[RawRecordInfo(url=url, payload=payload, retrieved_at=now)],
            warnings=[warning],
        )

    def fetch(self, series_key: str) -> FetchResult:
        """Generic entry point demanded by the adapter contract."""
        return self.fetch_series(series_key)
