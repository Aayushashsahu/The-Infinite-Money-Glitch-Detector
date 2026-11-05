"""End-to-end orchestrator tests on the in-memory DB, using a fake
adapter; plus the network-failure path (fetch exceptions mark the run
failed and persist zero fabricated rows)."""

from __future__ import annotations

from datetime import date

import pytest

from conftest import make_obs
from data.ingest import IngestResult, run_ingestion
from data.schemas import FetchResult, Frequency, IndicatorInfo, ObservationKind, RawRecordInfo

_FAKE_INDICATORS = [
    IndicatorInfo(
        source_id="fake_source",
        indicator_id="TEST_IND",
        name="Fake indicator",
        unit="percent",
        frequency=Frequency.ANNUAL,
    )
]


class FakeAdapter:
    """Test double standing in for a real SourceAdapter."""

    source_id = "fake_source"
    display_name = "Fake adapter (tests only)"

    def __init__(self, result: FetchResult | None = None, error: Exception | None = None):
        self.result = result
        self.error = error

    def fetch(self, **_kwargs) -> FetchResult:
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def _fake_fetch(n: int = 3) -> FetchResult:
    return FetchResult(
        observations=[
            make_obs(source_id="fake_source", observation_date=date(2020 + i, 1, 1), is_synthetic=True)
            for i in range(n)
        ],
        raw_records=[RawRecordInfo(url="synthetic://test", payload={"batches": 1})],
        warnings=["FAKE DATA: tests only."],
    )


def test_first_run_inserts_second_run_is_idempotent(repo) -> None:
    adapter = FakeAdapter(result=_fake_fetch())
    result1 = run_ingestion(adapter, repo, {}, indicators=_FAKE_INDICATORS)
    assert isinstance(result1, IngestResult)
    assert result1.status == "ok"
    assert (result1.inserted, result1.duplicates_skipped, result1.revisions_added) == (3, 0, 0)
    assert result1.quality["flagged"] == 0

    result2 = run_ingestion(adapter, repo, {}, indicators=_FAKE_INDICATORS)
    assert result2.status == "ok"
    assert (result2.inserted, result2.duplicates_skipped) == (0, 3)
    assert result2.observations_in == 3

    run = repo.get_run(result2.run_id)
    assert run.observations_in == 3 and run.observations_new == 0


def test_fetch_failure_marks_run_failed_and_inserts_nothing(repo) -> None:
    boom = RuntimeError("grid at data center reached capacity")
    adapter = FakeAdapter(error=boom)

    result = run_ingestion(adapter, repo, {}, indicators=None)
    assert result.status == "failed"
    assert result.inserted == 0
    assert any("grid at data center" in w for w in (result.warnings or []))

    run = repo.get_run(result.run_id)
    assert run.status == "failed"
    assert "RuntimeError" in (run.notes or "")
    assert run.observations_in == 0

    # Nothing fake was fabricated: the failing source contributed ZERO rows.
    assert repo.load_observations(include_synthetic=True).empty


def test_flagged_rows_mark_run_partial_but_persist_with_flags(repo) -> None:
    fetch = FetchResult(
        observations=[
            make_obs(source_id="fake_source", kind="exchange_rate", entity_code="USD/BRL", value=-1.0,
                     frequency="daily", indicator_id=None, is_synthetic=True),
            make_obs(source_id="fake_source", is_synthetic=True),
        ],
        raw_records=[RawRecordInfo(url="synthetic://test", payload={"n": 2})],
    )
    result = run_ingestion(FakeAdapter(result=fetch), repo, {}, indicators=_FAKE_INDICATORS)

    assert result.status == "partial"
    assert result.errors == 0
    assert result.quality["flags"].get("negative_rate") == 1

    stored = repo.load_observations(include_synthetic=True, kind=ObservationKind.EXCHANGE_RATE)
    assert len(stored) == 1  # flagged row persisted, original value preserved
    assert stored.iloc[0]["value"] == pytest.approx(-1.0)
    assert "negative_rate" in stored.iloc[0]["quality_flags"]


def test_duplicate_within_batch_land_in_stats_not_storage(repo) -> None:
    obs = make_obs(source_id="fake_source", is_synthetic=True)
    fetch = FetchResult(
        observations=[obs, make_obs(source_id="fake_source", is_synthetic=True)],  # identical twice in one batch
        raw_records=[],
    )
    result = run_ingestion(FakeAdapter(result=fetch), repo, {}, indicators=_FAKE_INDICATORS)
    assert result.status == "ok"
    assert (result.inserted, result.duplicates_skipped) == (1, 1)
    frame = repo.load_observations(include_synthetic=True)
    assert len(frame) == 1
