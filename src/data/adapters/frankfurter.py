"""FX adapter for Frankfurter (ECB Statistical Data Warehouse mirror,
keyless, MIT-licensed project, daily ECB reference rates).

Quotation convention (normalized platform-wide): every observation is
stored as ``pair_code = '{BASE}/{QUOTE}'`` with
``value = units of QUOTE per one unit of BASE``. Frankfurter natively
returns ``units of `symbols` per one `base```, matching the convention
directly.

Publication dates: ECB reference rates for day T are published on day T
(around 16:00 CET). ``publication_date = observation_date`` is therefore
a documented, defensible convention for this source only.

Limitations: coverage starts 1999-01-04 (euro launch); weekends and ECB
closing days are genuinely absent (no forward-fill); a small set of
currencies is available (ECB basket plus re-quoting via base currency).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from data.http import get_json
from data.schemas import (
    CurrencyInfo,
    DataObservation,
    FetchResult,
    Frequency,
    ObservationKind,
    RawRecordInfo,
)

from .base import SourceAdapter

FRANKFURTER_BASE_URL = "https://api.frankfurter.app"


class FrankfurterAdapter(SourceAdapter):
    """Daily historical exchange rates via the Frankfurter API (no key)."""

    source_id = "frankfurter"
    display_name = "Frankfurter (ECB daily reference rates)"

    def fetch_series(self, base: str, quote: str, start: date, end: date) -> FetchResult:
        """Fetch daily rates for one pair over an inclusive date range.

        Args:
            base: Base currency (ISO 4217, 3 letters).
            quote: Quote currency.
            start: First date (inclusive).
            end: Last date (inclusive).
        """
        base, quote = base.upper(), quote.upper()
        if base == quote:
            raise ValueError("base and quote must differ.")
        now = datetime.now(timezone.utc)
        url = f"{FRANKFURTER_BASE_URL}/{start.isoformat()}..{end.isoformat()}"
        payload = get_json(self.client, url, params={"from": base, "to": quote})
        rates: dict[str, dict[str, float]] = payload.get("rates", {})
        observations = [
            DataObservation(
                kind=ObservationKind.EXCHANGE_RATE,
                source_id=self.source_id,
                indicator_id=None,
                entity_code=f"{base}/{quote}",
                value=float(day_rates[quote]),
                unit="quote_per_base",
                frequency=Frequency.DAILY,
                observation_date=date.fromisoformat(day),
                publication_date=date.fromisoformat(day),  # ECB reference rates publish same-day
                retrieved_at=now,
                metadata={"base_amount": payload.get("amount", 1.0)},
            )
            for day, day_rates in sorted(rates.items())
            if quote in day_rates
        ]
        n_days = len(rates)
        warning = (
            f"frankfurter {base}/{quote}: {len(observations)} of {n_days} calendar entries in range "
            f"had a rate (weekends/holidays are genuinely absent, never filled)."
            if n_days
            else f"frankfurter {base}/{quote}: no data in range."
        )
        return FetchResult(
            observations=observations,
            raw_records=[RawRecordInfo(url=url, payload=payload, retrieved_at=now)],
            warnings=[warning],
        )

    def fetch(self, base: str, quote: str, start: Any, end: Any) -> FetchResult:
        """Generic entry point demanded by the adapter contract."""
        start_d, end_d = _as_date(start), _as_date(end)
        return self.fetch_series(base, quote, start_d, end_d)

    def known_currencies(self) -> list[CurrencyInfo]:
        """Currency list from the Frankfurter /currencies endpoint."""
        payload = get_json(self.client, f"{FRANKFURTER_BASE_URL}/currencies")
        return sorted(
            CurrencyInfo(code=code, name=name) for code, name in payload.items()  # type: ignore[union-attr]
        )


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
