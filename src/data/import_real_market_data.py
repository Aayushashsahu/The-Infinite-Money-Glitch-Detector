"""Reproducible Historical Data Ingestion Workflow for Phase 3.2.

Fetches, validates, and persists genuine historical financial market data for:
1. FX Reference Rates: USD/EUR daily rates from Frankfurter (ECB daily reference rates).
2. US Interest Rates: 3-Month and 1-Month Treasury Yield Curve Rates from US Treasury.
3. Euro Interest Rates: Deposit Facility Rate (DFR) and Main Refinancing Rate from ECB.

Covers two distinct macroeconomic regimes:
- Regime 1 (2020-01-01 to 2022-03-31): Zero/negative interest rates (NIRP/ZIRP).
- Regime 2 (2022-04-01 to 2024-12-31): Rapid monetary tightening and high rate volatility.

Enforces:
- Idempotency (re-running does not create duplicate rows).
- Provenance tracking (source_id, URL, raw record hash, publication date).
- Genuine data classification (REAL_VERIFIED).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

# Prevent src/data from shadowing standard library 'http'
if sys.path and Path(sys.path[0]).resolve() == Path(__file__).resolve().parent:
    sys.path.pop(0)

# Ensure src/ is on sys.path
src_dir = Path(__file__).resolve().parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from data.adapters.frankfurter import FrankfurterAdapter
from data.adapters.policy_rates import EcbPolicyRateAdapter
from data.adapters.us_treasury import UsTreasuryAdapter
from data.db.engine import make_engine, make_session_factory
from data.quality import validate_batch
from data.repository import Repository
from data.schemas import (
    DataClassification,
    Frequency,
    IndicatorInfo,
    ObservationKind,
)


def run_import(
    start_date: date = date(2020, 1, 1),
    end_date: date = date(2024, 12, 31),
    db_url: str | None = None,
    raw_archive_dir: Path | None = None,
) -> dict[str, int]:
    """Execute complete reproducible real market data import."""
    engine = make_engine(db_url)
    session_factory = make_session_factory(engine)
    repo = Repository(session_factory)
    repo.create_all()

    archive_dir = raw_archive_dir or Path(__file__).resolve().parent.parent.parent / "data" / "raw"
    archive_dir.mkdir(parents=True, exist_ok=True)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting Real Market Data Import ({start_date} to {end_date})...")

    # 1. Register sources & catalog
    repo.ensure_source(
        "frankfurter",
        "Frankfurter (ECB daily reference rates)",
        license="Derived from ECB statistical data; MIT app code",
        base_url="https://api.frankfurter.app",
    )
    repo.ensure_source(
        "us_treasury",
        "U.S. Department of the Treasury",
        license="Public domain (US Government Work; free reuse)",
        base_url="https://home.treasury.gov",
    )
    repo.ensure_source(
        "ecb",
        "ECB Data Portal",
        license="ECB statistical data terms (free reuse with attribution)",
        base_url="https://data-api.ecb.europa.eu",
    )

    repo.ensure_currency("USD", "United States Dollar")
    repo.ensure_currency("EUR", "Euro")
    repo.ensure_pair("USD", "EUR")

    indicators = [
        IndicatorInfo(
            source_id="us_treasury",
            indicator_id="DGS3MO",
            name="3-Month Treasury Constant Maturity Rate",
            unit="percent",
            frequency=Frequency.DAILY,
            category="interest_rate",
        ),
        IndicatorInfo(
            source_id="us_treasury",
            indicator_id="DGS1MO",
            name="1-Month Treasury Constant Maturity Rate",
            unit="percent",
            frequency=Frequency.DAILY,
            category="interest_rate",
        ),
        IndicatorInfo(
            source_id="ecb",
            indicator_id="KR.DFR.LEV",
            name="Euro area deposit facility rate, level",
            unit="percent",
            frequency=Frequency.DAILY,
            category="interest_rate",
        ),
        IndicatorInfo(
            source_id="ecb",
            indicator_id="KR.MRR_FR.LEV",
            name="Euro area main refinancing operations rate",
            unit="percent",
            frequency=Frequency.DAILY,
            category="interest_rate",
        ),
    ]
    for ind in indicators:
        repo.ensure_indicator(ind.source_id, ind.indicator_id, ind.name, ind.unit, ind.frequency.value)

    stats: dict[str, int] = {}

    # -------------------------------------------------------------------------
    # A. Fetch & Ingest USD/EUR FX Reference Rates (Frankfurter)
    # -------------------------------------------------------------------------
    # A. Fetch & Ingest Genuine FX Reference Rates (Frankfurter / ECB)
    # Convention in core.currency: rate is units of borrowing A per unit of investment B
    # For USD/EUR (borrow USD, invest EUR): rate is USD per EUR (~1.12, base EUR, quote USD)
    # For EUR/USD (borrow EUR, invest USD): rate is EUR per USD (~0.89, base USD, quote EUR)
    # -------------------------------------------------------------------------
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Fetching genuine FX reference rates from Frankfurter...")
    fx_adapter = FrankfurterAdapter()

    # 1. USD/EUR (USD per 1 EUR: ECB reference rate with base EUR, quote USD)
    fx_usd_eur_res = fx_adapter.fetch_series("EUR", "USD", start_date, end_date)
    for obs in fx_usd_eur_res.observations:
        obs.entity_code = "USD/EUR"
        obs.unit = "USD_per_EUR"
        obs.classification = DataClassification.REAL_VERIFIED
    
    # 2. EUR/USD (EUR per 1 USD: ECB reference rate with base USD, quote EUR)
    fx_eur_usd_res = fx_adapter.fetch_series("USD", "EUR", start_date, end_date)
    for obs in fx_eur_usd_res.observations:
        obs.entity_code = "EUR/USD"
        obs.unit = "EUR_per_USD"
        obs.classification = DataClassification.REAL_VERIFIED

    # Save raw records to disk
    for raw in fx_usd_eur_res.raw_records:
        with open(archive_dir / f"frankfurter_EUR_base_USD_quote_{start_date}_{end_date}.json", "w", encoding="utf-8") as f:
            json.dump(raw.payload, f)
    for raw in fx_eur_usd_res.raw_records:
        with open(archive_dir / f"frankfurter_USD_base_EUR_quote_{start_date}_{end_date}.json", "w", encoding="utf-8") as f:
            json.dump(raw.payload, f)

    fx_all_obs = fx_usd_eur_res.observations + fx_eur_usd_res.observations
    fx_valid, _ = validate_batch(fx_all_obs)
    fx_stats = repo.insert_observations(fx_valid)
    stats["fx_inserted"] = fx_stats.inserted
    stats["fx_skipped"] = fx_stats.duplicates_skipped
    print(f"   -> FX Rates: {len(fx_valid)} valid observations (new: {fx_stats.inserted}, skipped: {fx_stats.duplicates_skipped})")

    # -------------------------------------------------------------------------
    # B. Fetch & Ingest US Treasury Yield Curve Rates (3-Month & 1-Month)
    # -------------------------------------------------------------------------
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Fetching US Treasury 3M and 1M rates from home.treasury.gov...")
    ust_adapter = UsTreasuryAdapter()
    ust_3m_res = ust_adapter.fetch_series(tenor="3 Mo", start_year=start_date.year, end_year=end_date.year)
    ust_1m_res = ust_adapter.fetch_series(tenor="1 Mo", start_year=start_date.year, end_year=end_date.year)

    # Filter to exact date window
    ust_3m_obs = [o for o in ust_3m_res.observations if start_date <= o.observation_date <= end_date]
    ust_1m_obs = [o for o in ust_1m_res.observations if start_date <= o.observation_date <= end_date]

    # Save raw CSV payloads
    for raw in ust_3m_res.raw_records:
        year_str = raw.url.split("/")[-2]
        with open(archive_dir / f"us_treasury_{year_str}.csv", "w", encoding="utf-8") as f:
            f.write(str(raw.payload))

    ust_3m_valid, _ = validate_batch(ust_3m_obs)
    ust_3m_stats = repo.insert_observations(ust_3m_valid)
    stats["us_treasury_3m_inserted"] = ust_3m_stats.inserted
    stats["us_treasury_3m_skipped"] = ust_3m_stats.duplicates_skipped
    print(f"   -> US Treasury 3M: {len(ust_3m_valid)} valid observations (new: {ust_3m_stats.inserted}, skipped: {ust_3m_stats.duplicates_skipped})")

    ust_1m_valid, _ = validate_batch(ust_1m_obs)
    ust_1m_stats = repo.insert_observations(ust_1m_valid)
    stats["us_treasury_1m_inserted"] = ust_1m_stats.inserted
    stats["us_treasury_1m_skipped"] = ust_1m_stats.duplicates_skipped
    print(f"   -> US Treasury 1M: {len(ust_1m_valid)} valid observations (new: {ust_1m_stats.inserted}, skipped: {ust_1m_stats.duplicates_skipped})")

    # -------------------------------------------------------------------------
    # C. Fetch & Ingest ECB Policy Rates (DFR & Main Refinancing Operations)
    # -------------------------------------------------------------------------
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Fetching ECB deposit facility and main refinancing rates...")
    ecb_adapter = EcbPolicyRateAdapter()
    ecb_dfr_res = ecb_adapter.fetch_policy_rate("KR.DFR.LEV", start=start_date)
    ecb_mro_res = ecb_adapter.fetch_policy_rate("KR.MRR_FR.LEV", start=start_date)

    ecb_dfr_obs = [o for o in ecb_dfr_res.observations if start_date <= o.observation_date <= end_date]
    ecb_mro_obs = [o for o in ecb_mro_res.observations if start_date <= o.observation_date <= end_date]

    for raw in ecb_dfr_res.raw_records:
        with open(archive_dir / f"ecb_dfr_{start_date}_{end_date}.csv", "w", encoding="utf-8") as f:
            f.write(str(raw.payload))

    for raw in ecb_mro_res.raw_records:
        with open(archive_dir / f"ecb_mro_{start_date}_{end_date}.csv", "w", encoding="utf-8") as f:
            f.write(str(raw.payload))

    ecb_dfr_valid, _ = validate_batch(ecb_dfr_obs)
    ecb_dfr_stats = repo.insert_observations(ecb_dfr_valid)
    stats["ecb_dfr_inserted"] = ecb_dfr_stats.inserted
    stats["ecb_dfr_skipped"] = ecb_dfr_stats.duplicates_skipped
    print(f"   -> ECB Deposit Facility: {len(ecb_dfr_valid)} valid observations (new: {ecb_dfr_stats.inserted}, skipped: {ecb_dfr_stats.duplicates_skipped})")

    ecb_mro_valid, _ = validate_batch(ecb_mro_obs)
    ecb_mro_stats = repo.insert_observations(ecb_mro_valid)
    stats["ecb_mro_inserted"] = ecb_mro_stats.inserted
    stats["ecb_mro_skipped"] = ecb_mro_stats.duplicates_skipped
    print(f"   -> ECB Main Refinancing: {len(ecb_mro_valid)} valid observations (new: {ecb_mro_stats.inserted}, skipped: {ecb_mro_stats.duplicates_skipped})")

    manifest_path = archive_dir.parent / "manifest.json"
    generate_manifest(archive_dir, manifest_path)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Manifest generated at {manifest_path}")

    total_new = sum(v for k, v in stats.items() if k.endswith("_inserted"))
    total_skipped = sum(v for k, v in stats.items() if k.endswith("_skipped"))
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Import complete. Total new rows: {total_new}, Total skipped duplicates: {total_skipped}.\n")
    return stats


def generate_manifest(archive_dir: Path, manifest_path: Path) -> dict[str, Any]:
    """Generate SHA-256 manifest of raw archived files."""
    manifest_entries: list[dict[str, Any]] = []
    if archive_dir.exists():
        for file_path in sorted(archive_dir.glob("*")):
            if file_path.is_file() and file_path.name != ".gitkeep":
                content = file_path.read_bytes()
                digest = hashlib.sha256(content).hexdigest()
                size_bytes = len(content)
                manifest_entries.append({
                    "file_name": file_path.name,
                    "sha256": digest,
                    "file_size_bytes": size_bytes,
                })
    manifest_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files_count": len(manifest_entries),
        "files": manifest_entries,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)
    return manifest_data


if __name__ == "__main__":
    run_import()
