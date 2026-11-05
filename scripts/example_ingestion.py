"""Example Phase 2 ingestion workflow (offline first, network optional).

Runs, in order:
1. a `alembic upgrade head`-equivalent (create_all) on DATABASE_URL
   (default: local SQLite demo file),
2. a clearly-labeled SYNTHETIC ingestion (quality flags visible; stored
   permanently as synthetic),
3. REAL, keyless ingests - World Bank inflation (USA, JPN, BRA) and
   Frankfurter daily FX (USD/BRL) - and reports honestly what happened,
   including failures (network errors are expected to be possible).
4. a coverage report + point-in-time slice demonstration.

Run from the project root:  python scripts/example_ingestion.py
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data.adapters import FrankfurterAdapter, WorldBankAdapter, WORLD_BANK_INDICATORS
from data.coverage import country_indicator_coverage, insufficient_data, series_coverage
from data.ingest import IngestResult, run_ingestion
from data.repository import Repository
from data.schemas import DataObservation, Frequency, IndicatorInfo, ObservationKind
from data.db.engine import make_engine, make_session_factory


def _synthetic_batch() -> tuple[list, list]:
    """A tiny hand-built dataset, PERMANENTLY marked is_synthetic=True."""
    now = datetime.now()
    base = date(2020, 1, 1)
    indicators = [
        IndicatorInfo(
            source_id="synthetic_demo",
            indicator_id="CPI_YOY",
            name="Synthetic annual inflation (test data)",
            unit="percent",
            frequency=Frequency.ANNUAL,
        )
    ]
    values = {"AAA": [1.5, 2.0, 2.5, 3.0], "BBB": [6.0, 0.0, -1.0, 2.0]}
    observations = [
        DataObservation(
            kind=ObservationKind.MACRO_INDICATOR,
            source_id="synthetic_demo",
            indicator_id="CPI_YOY",
            entity_code=iso3,
            value=v,
            unit="percent",
            frequency=Frequency.ANNUAL,
            observation_date=date(base.year + i, 1, 1),
            publication_date=date(base.year + i, 4, 30),  # typical annual publication lag
            retrieved_at=now,
            is_synthetic=True,
        )
        for iso3, series in values.items()
        for i, v in enumerate(series)
    ]
    return observations, indicators


def _report(label: str, result: IngestResult) -> None:
    print(f"  {label}: status={result.status} in={result.observations_in} "
          f"new={result.inserted} dup={result.duplicates_skipped} "
          f"rev={result.revisions_added} errors={result.errors}")
    for w in result.warnings or []:
        print(f"    - {w}")


def main() -> None:
    engine = make_engine()  # DATABASE_URL if set, else sqlite demo file
    repo = Repository(make_session_factory(engine))
    repo.create_all()
    print(f"Storage ready at: {engine.url}")

    # 1) Synthetic ingestion (twice: proves idempotency)
    observations, indicators = _synthetic_batch()
    for i, batch in enumerate([observations, observations], start=1):
        from data.schemas import FetchResult, RawRecordInfo

        class SyntheticAdapter:
            source_id = "synthetic_demo"
            display_name = "Synthetic demo source (TEST DATA)"

            def fetch(self, **_):
                return FetchResult(
                    observations=batch,
                    raw_records=[RawRecordInfo(url="synthetic://demo", payload={"note": "test data"})],
                    warnings=["SYNTHETIC DATA: not real economics, for tests/demos only."],
                )

            def __getattr__(self, item):  # interface permissiveness for the orchestrator
                raise AttributeError(item)

        result = run_ingestion(
            SyntheticAdapter(), repo, {}, indicators=indicators  # type: ignore[arg-type]
        )
        _report(f"synthetic pass {i}", result)

    # 2) Real keyless sources (network permitting; failures reported, not hidden)
    end = date.today() - timedelta(days=2)  # FX published with ~1 day lag
    start = end - timedelta(days=30)

    wb = WorldBankAdapter()
    wb_indicator = "FP.CPI.TOTL.ZG"
    wb_spec = WORLD_BANK_INDICATORS[wb_indicator]
    wb_catalog = [
        IndicatorInfo(
            source_id="world_bank",
            indicator_id=wb_indicator,
            name=wb_spec["name"],
            unit=wb_spec["unit"],
            frequency=wb_spec["frequency"],
        )
    ]
    for country in ["USA", "JPN", "BRA"]:
        try:
            _report(f"world_bank inflation {country}",
                    run_ingestion(wb, repo, {"indicator_id": wb_indicator, "countries": [country]},
                                  indicators=wb_catalog))
        except Exception as exc:  # noqa: BLE001
            print(f"  world_bank {country}: FAILED - {type(exc).__name__}: {exc}")

    fx = FrankfurterAdapter()
    try:
        _report("frankfurter USD/BRL 30d",
                run_ingestion(fx, repo, {"base": "USD", "quote": "BRL", "start": start, "end": end}))
    except Exception as exc:  # noqa: BLE001
        print(f"  frankfurter USD/BRL: FAILED - {type(exc).__name__}: {exc}")

    # 3) Coverage report (synthetic rows excluded from real-data analytics by
    #    default; shown separately below so the split stays visible)
    real = repo.load_observations()
    print("\nCoverage (real sources only):")
    print(series_coverage(real).to_string(index=False))
    print("\nInsufficient-data series:")
    print(insufficient_data(series_coverage(real)).to_string(index=False))

    print("\nCountry x indicator matrix:")
    print(country_indicator_coverage(real).to_string(index=False))

    # 4) Point-in-time query (look-ahead bias defense)
    as_of = date.today() - timedelta(days=365 * 50 // 100)  # arbitrary demo date
    punt = repo.point_in_time(as_of=as_of, kind=ObservationKind.MACRO_INDICATOR)
    print(f"\nPoint-in-time view at {as_of}: {len(punt)} observations published by then.")
    synthetic = repo.load_observations(include_synthetic=True)
    print(f"Synthetic rows still stored separately and flagged: "
          f"{int(synthetic['is_synthetic'].sum())} of {len(synthetic)}.")


if __name__ == "__main__":
    main()
