"""Ingestion orchestration: adapter -> quality engine -> repository.

Every run is recorded in ``ingestion_run`` with counts and full error
transparency: a source failure marks the run ``failed``, a row-level
integrity issue or flagged observation marks it ``partial``, and nothing
ever changes silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from data.adapters.base import SourceAdapter
from data.quality import summarize, validate_batch
from data.repository import Repository
from data.schemas import FetchResult, IndicatorInfo, QualityFlag

SOURCE_DISPLAY_NAMES: dict[str, str] = {
    "world_bank": "World Bank Open Data (API v2)",
    "imf": "IMF International Financial Statistics",
    "frankfurter": "Frankfurter (ECB daily reference rates)",
    "ecb": "ECB Data Portal",
    "fred": "FRED (Federal Reserve Economic Data)",
    "us_treasury": "U.S. Department of the Treasury (Daily Par Yield Curve Rates)",
}

SOURCE_LICENSES: dict[str, str] = {
    "world_bank": "CC BY-4.0 (World Bank terms of use for datasets)",
    "imf": "IMF data terms of use (attribution; check per-dataset terms)",
    "frankfurter": "Derived from ECB statistical data; Frankfurter app code MIT",
    "ecb": "ECB statistical data terms (free reuse with attribution)",
    "fred": "FRED terms of use (attribution; free API key required)",
    "us_treasury": "Public domain (US Government Work; free reuse without restriction)",
}


@dataclass
class IngestResult:
    """Outcome of one orchestrated ingestion run."""

    run_id: str
    status: str  # ok | partial | failed
    observations_in: int = 0
    inserted: int = 0
    duplicates_skipped: int = 0
    revisions_added: int = 0
    errors: int = 0
    warnings: list[str] | None = None
    quality: dict | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "observations_in": self.observations_in,
            "inserted": self.inserted,
            "duplicates_skipped": self.duplicates_skipped,
            "revisions_added": self.revisions_added,
            "errors": self.errors,
            "warnings": self.warnings or [],
            "quality": self.quality or {},
        }


def run_ingestion(
    adapter: SourceAdapter,
    repository: Repository,
    fetch_kwargs: dict[str, Any],
    indicators: list[IndicatorInfo] | None = None,
) -> IngestResult:
    """Execute one full ingestion cycle for one adapter call.

    Steps: register source/catalog -> create run row -> fetch ->
    quality-validate -> archive raw payloads -> insert -> record stats.
    Fetch failures mark the run ``failed`` and return a result (callers
    inspect it; errors are data, not crashes).
    """
    display_name = SOURCE_DISPLAY_NAMES.get(adapter.source_id, adapter.source_id)
    repository.ensure_source(
        adapter.source_id,
        display_name,
        license=SOURCE_LICENSES.get(adapter.source_id),
    )
    indicator_meta: dict[tuple[str, str], IndicatorInfo] = {}
    for ind in indicators or []:
        repository.ensure_indicator(ind.source_id, ind.indicator_id, ind.name, ind.unit, ind.frequency.value)
        indicator_meta[(ind.source_id, ind.indicator_id)] = ind

    run_id = repository.create_run(adapter.source_id)
    try:
        result: FetchResult = adapter.fetch(**fetch_kwargs)
    except Exception as exc:  # noqa: BLE001 - a source failure is recorded, not hidden
        repository.finish_run(
            run_id,
            status="failed",
            notes=f"fetch failed: {type(exc).__name__}: {exc}",
        )
        return IngestResult(run_id=run_id, status="failed", errors=1, warnings=[str(exc)])

    observations = result.observations
    observations, quality_report = validate_batch(observations, indicator_meta or None)
    repository.archive_raw_records(run_id, adapter.source_id, result.raw_records)
    stats = repository.insert_observations(observations)
    repository.record_run_stats(run_id, stats, warnings=result.warnings)

    # A duplicate inside one batch is already accounted for as a skipped
    # duplicate (it is dropped, not stored), so it does not degrade the run;
    # every other quality flag does.
    duplicate_flags = quality_report.counts.get(QualityFlag.DUPLICATE_IN_BATCH.value, 0)
    review_flags = quality_report.flagged - duplicate_flags
    status = "ok"
    if stats.error_count or review_flags:
        has_rows = stats.inserted + stats.revisions_added + stats.duplicates_skipped > 0
        status = "partial" if has_rows else "failed"
    repository.finish_run(run_id, status=status)

    return IngestResult(
        run_id=run_id,
        status=status,
        observations_in=stats.inserted + stats.duplicates_skipped + stats.revisions_added,
        inserted=stats.inserted,
        duplicates_skipped=stats.duplicates_skipped,
        revisions_added=stats.revisions_added,
        errors=stats.error_count,
        warnings=result.warnings,
        quality=summarize(quality_report),
    )
