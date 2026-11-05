"""Adapter tests against mocked HTTP responses (httpx.MockTransport).

Tests NEVER depend on external API availability. Mock payloads mirror
each source's documented response shape so parsing logic is exercised
for real.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import httpx
import pytest

from data.adapters import (
    EcbPolicyRateAdapter,
    FrankfurterAdapter,
    FredAdapter,
    ImfAdapter,
    WorldBankAdapter,
)
from data.http import HttpFetchError, make_client


def _client(handler) -> httpx.Client:
    return make_client(transport=httpx.MockTransport(handler))


def _wb_row(iso3: str, year: str, value) -> dict:
    return {
        "indicator": {"id": "FP.CPI.TOTL.ZG", "value": "Inflation, consumer prices (annual %)"},
        "country": {"id": "United States", "value": "United States"},
        "countryiso3code": iso3,
        "date": year,
        "value": value,
    }


# ----------------------------------------------------------------- World Bank


def test_world_bank_parses_indicator_and_reports_missing() -> None:
    payload = [
        {"page": 1, "per_page": 3, "total": 3},
        [
            _wb_row("USA", "2022", 8.002),
            _wb_row("USA", "2021", None),  # genuinely missing year
            _wb_row("USA", "2020", 1.234),
        ],
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.worldbank.org"
        assert request.url.params["format"] == "json"
        assert request.url.params["per_page"] == "20000"
        assert "/country/USA/indicator/FP.CPI.TOTL.ZG" in str(request.url)
        return httpx.Response(200, json=payload)

    adapter = WorldBankAdapter(client=_client(handler))
    result = adapter.fetch_indicator("FP.CPI.TOTL.ZG", ["USA"])

    assert len(result.observations) == 2  # the null year is skipped, never fabricated
    # The adapter normalises the API's newest-first order to chronological.
    first, second = result.observations
    assert first.observation_date == date(2020, 1, 1)
    assert first.value == pytest.approx(1.234)
    assert first.publication_date is None  # WB does not publish it (documented)
    assert first.unit == "percent"
    assert first.frequency.value == "annual"
    assert second.observation_date == date(2022, 1, 1)
    assert second.value == pytest.approx(8.002)
    assert any("had no value" in w for w in result.warnings)
    assert len(result.raw_records) == 1  # original payload archived


def test_world_bank_rejects_undeclared_indicator() -> None:
    adapter = WorldBankAdapter(client=_client(lambda request: httpx.Response(200, json=[])))
    with pytest.raises(ValueError, match="not in the declared World Bank catalog"):
        adapter.fetch_indicator("NOT_A_SERIES", ["USA"])


def test_world_bank_country_metadata_uses_iso3_and_warns_on_missing_currency() -> None:
    payload = [{"total": 2}, [{"id": "USA", "name": "United States"}, {"id": "ZZZ", "name": "Unknown Land"}]]

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/country/USA;ZZZ" in str(request.url)
        return httpx.Response(200, json=payload)

    adapter = WorldBankAdapter(client=_client(handler))
    infos, result = adapter.fetch_country_metadata(["USA", "ZZZ"])
    assert infos[0].iso3 == "USA" and infos[0].currency_code == "USD"
    assert infos[1].currency_code is None
    assert any("currency" in w for w in result.warnings)  # nothing guessed silently


# ---------------------------------------------------------------- Frankfurter


def test_frankfurter_parses_daily_rates_with_convention() -> None:
    payload = {
        "amount": 1.0,
        "base": "USD",
        "start_date": "2024-01-01",
        "end_date": "2024-01-05",
        "rates": {
            "2024-01-02": {"BRL": 4.9},
            "2024-01-03": {"BRL": 4.88},
            "2024-01-04": {},  # calendar entry without a quote
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.frankfurter.app"
        assert request.url.params["from"] == "USD"
        assert request.url.params["to"] == "BRL"
        return httpx.Response(200, json=payload)

    adapter = FrankfurterAdapter(client=_client(handler))
    result = adapter.fetch_series("usd", "brl", date(2024, 1, 1), date(2024, 1, 5))

    assert len(result.observations) == 2
    obs = result.observations[0]
    assert obs.entity_code == "USD/BRL"
    assert obs.value == pytest.approx(4.9)  # units of BRL per 1 USD (quote per base)
    assert obs.publication_date == obs.observation_date  # ECB publishes same-day
    assert obs.frequency.value == "daily"
    assert any("of 3" in w for w in result.warnings)
    assert result.raw_records[0].url.startswith("https://api.frankfurter.app/2024-01-01..")


def test_frankfurter_rejects_same_currency_pair() -> None:
    adapter = FrankfurterAdapter(client=_client(lambda request: httpx.Response(200, json={})))
    with pytest.raises(ValueError, match="must differ"):
        adapter.fetch_series("USD", "USD", date(2024, 1, 1), date(2024, 1, 2))


# ------------------------------------------------------------------------ IMF


def test_imf_parses_compact_sdmx() -> None:
    payload = {
        "CompactData": {
            "DataSet": {
                "Series": [
                    {
                        "@FREQ": "M",
                        "@INDICATOR": "PCPI_IX",
                        "@REF_AREA": "US",
                        "@ISOCountry": "United States",
                        "Obs": [
                            {"@TIME_PERIOD": "2022-01", "@OBS_VALUE": "296.4"},
                            {"@TIME_PERIOD": "2022-02", "@OBS_VALUE": None},  # missing
                        ],
                    }
                ]
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "dataservices.imf.org" in str(request.url)
        assert "/CompactData/IFS/M.US.PCPI_IX" in str(request.url)
        return httpx.Response(200, json=payload)

    adapter = ImfAdapter(client=_client(handler))
    result = adapter.fetch_series("M.US.PCPI_IX")

    assert len(result.observations) == 1
    obs = result.observations[0]
    assert obs.entity_code == "US"
    assert obs.indicator_id == "PCPI_IX"
    assert obs.value == pytest.approx(296.4)
    assert obs.observation_date == date(2022, 1, 1)
    assert obs.frequency.value == "monthly"
    assert obs.publication_date is None  # endpoint does not expose it
    assert any("legacy endpoint" in w for w in result.warnings)
    assert result.raw_records  # full SDMX payload archived


def test_imf_rejects_bad_series_key_and_undeclared_indicator() -> None:
    adapter = ImfAdapter(client=_client(lambda request: httpx.Response(200, json={})))
    with pytest.raises(ValueError, match="series key"):
        adapter.fetch_series("M.US")
    with pytest.raises(ValueError, match="not in the declared catalog"):
        adapter.fetch_series("M.US.NOT_A_CODE")


def test_imf_period_parsing_quarters_and_years() -> None:
    from data.adapters.imf import _period_to_date

    assert _period_to_date("2003") == date(2003, 1, 1)
    assert _period_to_date("2003Q2") == date(2003, 4, 1)
    assert _period_to_date("2003-07") == date(2003, 7, 1)
    with pytest.raises(ValueError):
        _period_to_date("junk")


# ------------------------------------------------------------------ ECB / FRED


_ECB_CSV = "TIME_PERIOD,OBS_VALUE\n1999-01-01,3.0\n1999-01-04,\n1999-01-05,2.50\n"


def test_ecb_policy_rate_from_csv_skips_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "data-api.ecb.europa.eu" in str(request.url)
        assert "FM/B.U2.EUR.4F.KR.DF.LEV" in str(request.url)
        assert request.url.params["format"] == "csvdata"
        assert request.url.params["startPeriod"] == "2022-01-01"
        return httpx.Response(200, text=_ECB_CSV)

    adapter = EcbPolicyRateAdapter(client=_client(handler))
    result = adapter.fetch_policy_rate("KR.DF.LEV", start=date(2022, 1, 1))

    assert len(result.observations) == 2  # blank OBS_VALUE skipped
    obs = result.observations[0]
    assert obs.kind.value == "interest_rate"
    assert obs.entity_code == "ECB_EA"
    assert obs.value == pytest.approx(3.0)
    assert obs.unit == "percent"
    assert obs.publication_date == obs.observation_date
    assert result.raw_records[0].payload == _ECB_CSV  # raw CSV archived verbatim


def test_ecb_rejects_undeclared_series() -> None:
    adapter = EcbPolicyRateAdapter(client=_client(lambda request: httpx.Response(200, text="")))
    with pytest.raises(ValueError, match="not in the declared policy-rate catalog"):
        adapter.fetch_policy_rate("KR.NOPE.LEV")


_FRED_JSON = {
    "observations": [
        {"date": "2022-01-31", "value": "0.08"},
        {"date": "2022-02-01", "value": "."},  # FRED missing-marker
    ]
}


def test_fred_parses_observations_with_explicit_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["api_key"] == "TEST_KEY"
        assert request.url.params["series_id"] == "DFEDTARU"
        assert request.url.params["file_type"] == "json"
        assert request.url.host == "api.stlouisfed.org"
        return httpx.Response(200, json=_FRED_JSON)

    adapter = FredAdapter(api_key="TEST_KEY", client=_client(handler))
    result = adapter.fetch_policy_rate("DFEDTARU", start=date(2022, 1, 1))

    assert len(result.observations) == 1  # '.'-marked missing skipped
    obs = result.observations[0]
    assert obs.entity_code == "FED_USA"
    assert obs.value == pytest.approx(0.08)
    assert obs.kind.value == "interest_rate"


def test_fred_requires_explicit_api_key() -> None:
    with pytest.raises(ValueError, match="FRED API key"):
        FredAdapter(api_key="")


def test_unimplemented_central_banks_are_documents_not_guesses() -> None:
    from data.adapters import UNIMPLEMENTED_CENTRAL_BANKS

    assert "BoE" in UNIMPLEMENTED_CENTRAL_BANKS  # honest registry, no scraping


# ------------------------------------------------------------------ HTTP layer


def test_http_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("data.http.time.sleep", lambda _s: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] == 1 else httpx.Response(200, json={"ok": True})

    client = _client(handler)
    from data.http import get_json

    assert get_json(client, "https://example.com/data") == {"ok": True}
    assert calls["n"] == 2


def test_http_fails_loudly_on_client_error() -> None:
    client = _client(lambda request: httpx.Response(403))
    from data.http import get_json

    with pytest.raises(HttpFetchError, match="403"):
        get_json(client, "https://example.com/data")


def test_http_fails_loudly_on_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    client = _client(handler)
    from data.http import get_json

    with pytest.raises(HttpFetchError, match="no route to host"):
        get_json(client, "https://example.com/data")
