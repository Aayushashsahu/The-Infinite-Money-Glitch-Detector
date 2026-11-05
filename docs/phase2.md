# Phase 2 — Economic Data Infrastructure

Objective: **retrieval, normalization, validation and persistence of
historical economic observations while preserving their original
publication and observation dates.**

Phase 2 adds data plumbing only. It does not change Phase 1 formulas and
introduces no ML, LLM, dashboard, trading or portfolio code.

## What exists

```
src/data/
├── schemas.py        # DataObservation, FetchResult, IndicatorInfo, QualityFlag, ...
├── http.py           # one hardened httpx client: timeouts, UA, bounded retries
├── quality.py        # pure batch validator (flags, never deletes)
├── coverage.py       # per-series coverage / sufficiency report
├── ingest.py         # orchestration: catalog → fetch → validate → archive → insert
├── repository.py     # catalog maintenance, idempotent inserts, point-in-time reads
├── adapters/         # world_bank, frankfurter, imf, policy_rates (ECB, FRED)
└── db/               # engine, ORM models (9 tables)
alembic/              # migration d87fb89eff94 — canonical data model
scripts/example_ingestion.py
```

### Storage model (9 tables)

`data_source`, `economic_indicator`, `country`, `currency`,
`currency_pair`, `data_observation`, `ingestion_run`, `raw_record`,
plus the Alembic version table.

Guarantees encoded in the schema:

- **Natural key** `(source_id, kind, entity_code, indicator_id,
  frequency, observation_date, revision)` is unique, so re-ingestion is
  idempotent and every revision is preserved as its own row.
- `data_observation(source_id, indicator_id)` has a composite foreign key
  into `economic_indicator`, so an unregistered indicator fails **that
  row** (counted, reported) and never the batch.
- `raw_record` keeps the untouched provider payload with a SHA-256
  content hash, unique per `(source_id, run_id, payload_sha256)`.
- `is_synthetic` is a non-null column on every observation; synthetic
  rows are permanently distinguishable and excluded from analytical
  reads by default (`load_observations(include_synthetic=False)`).
- SQLite runs with `PRAGMA foreign_keys=ON`; PostgreSQL is the intended
  production target via `DATABASE_URL`.

## Behavioral contracts

| Concern | Contract |
|---|---|
| Idempotency | same key + same value + same publication date ⇒ skipped, counted as duplicate |
| Revisions | same key, different value or newer revision ⇒ new row with `revision+1` and a `revision_change` flag |
| Stale replay | incoming revision older than stored ⇒ skipped |
| Missing values | providers' null values are skipped and reported in warnings — never forward-filled |
| Point-in-time | `point_in_time(as_of=...)` keeps only rows whose `publication_date <= as_of`; unknown publication dates are excluded unless `allow_unknown_publication=True` |
| Quality | flags only (`future_date`, `negative_rate`, `invalid_currency`, `unit_mismatch`, `frequency_inconsistent`, `duplicate_in_batch`, `order_inconsistent`, `suspicious_jump`, `outlier_suspect`, `missing_value`); nothing is silently dropped |
| Run accounting | every run is an `ingestion_run` row with status `ok` / `partial` / `failed`, counts, and notes |

An in-batch duplicate is counted in `duplicates_skipped` and does not
degrade the run (`ok`); every other quality flag marks the run `partial`.

## Providers

| source_id | Endpoint | Key | Publication dates |
|---|---|---|---|
| `world_bank` | api.worldbank.org/v2 | none | **not provided by the API** ⇒ stored as `NULL` (documented, not invented) |
| `frankfurter` | api.frankfurter.app | none | not provided ⇒ `NULL` |
| `imf` | IFS dataset | none (SDMX) | dataset-dependent |
| `ecb` | data.ecb.europa.eu | none | series-dependent |
| `fred` | api.stlouisfed.org | **required** (`FRED_API_KEY`) | alert date not modelled; stored `NULL` |

Adapters normalise to a chronological, ascending series and declare
their indicator catalog (unit + frequency) so the quality engine can
cross-check what arrives.

## Real run recorded on 2026-11-05

`python scripts/example_ingestion.py` against live endpoints:

| Series | Rows | Range | Status |
|---|---|---|---|
| World Bank `FP.CPI.TOTL.ZG` USA | 65 | 1960–2024 | ok (1 null year skipped) |
| World Bank `FP.CPI.TOTL.ZG` JPN | 66 | 1960–2025 | partial — 1 `outlier_suspect` (1974 oil-shock inflation spike), stored with its flag |
| World Bank `FP.CPI.TOTL.ZG` BRA | 45 | 1981–2025 | partial — 21 null years skipped; 15 `outlier_suspect` (hyperinflation era) |
| Frankfurter USD/BRL (30 d) | 23 | 2026-10-02 → 2026-11-03 | partial — 30.3 % of calendar days had no quote (weekends/holidays, not filled) |

Coverage: USA, JPN and BRA pass the 5-year sufficiency threshold;
the 30-day FX window intentionally does not. The point-in-time view at
2026-05-07 returned **0** rows: World Bank carries no publication dates,
and the FX window starts after that date. That is the honest result, not
a bug.

## Limitations (Phase 2)

1. World Bank and Frankfurter publish no publication/release dates, so
   their observations are **not** point-in-time safe; the strict default
   excludes them from `point_in_time` reads.
2. IMF and ECB adapters are implemented but not exercised against live
   endpoints in this run; FRED requires an explicit API key and refuses
   to run without one.
3. Revisions are detected by value change; providers that do not expose
   revision identifiers cannot report a true vintage history.
4. SQLite is the test/demo store; PostgreSQL is the production target and
   is not part of the automated suite.
5. No scheduling, retry queue or backfill orchestration yet — ingestion is
   explicit and synchronous.

## Verification

```
pytest -q        # 98 passed (62 Phase 1 + 36 Phase 2)
python scripts/example_ingestion.py
```
