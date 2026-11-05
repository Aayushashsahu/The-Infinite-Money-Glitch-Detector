"""Persistence tests on an in-memory SQLite engine (same ORM code that
targets PostgreSQL in production): insertion, duplicate detection and
idempotent ingestion, revision preservation, publication-date-aware
queries, and the synthetic-data separation guarantee.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from conftest import make_obs
from data.db.models import Currency
from data.schemas import Frequency, ObservationKind

_NOW = datetime(2024, 6, 1, tzinfo=timezone.utc)


def _catalog_populated(repo):
    repo.ensure_source("test_source", "Test source")
    repo.ensure_indicator("test_source", "TEST_IND", "Test indicator", "percent", "annual")
    repo.ensure_currency("TSD")
    repo.ensure_currency("USD")
    return repo


def test_catalog_registration_is_idempotent(repo) -> None:
    _catalog_populated(repo)
    _catalog_populated(repo)  # rerun must not explode
    with repo._session_factory() as session:
        currencies = session.query(Currency).all()
    assert len({c.code for c in currencies}) == 2  # no duplicate currency rows


def test_unregistered_indicator_fails_the_row_not_the_batch(repo) -> None:
    """FK integrity is enforced per-row: the bad row is counted, the rest persist."""
    repo.ensure_source("test_source", "Test source")
    repo.ensure_indicator("test_source", "TEST_IND", "Test indicator", "percent", "annual")
    good = [
        make_obs(observation_date=date(2020, 1, 1)),
        make_obs(observation_date=date(2021, 1, 1), is_synthetic=False),
        make_obs(  # indicator (test_source, UNKNOWN) was never registered
            observation_date=date(2022, 1, 1),
            indicator_id="UNKNOWN",
        ),
    ]
    stats = repo.insert_observations(good)
    assert stats.inserted == 2
    assert stats.error_count == 1
    assert "UNKNOWN" in stats.errors[0]


def test_insert_and_idempotent_reingestion(repo) -> None:
    _catalog_populated(repo)
    batch = [make_obs(observation_date=date(2020 + i, 1, 1), is_synthetic=False) for i in range(3)]

    first = repo.insert_observations(batch)
    assert (first.inserted, first.duplicates_skipped, first.revisions_added) == (3, 0, 0)

    second = repo.insert_observations(batch)  # identical replay: no-op
    assert (second.inserted, second.duplicates_skipped, second.revisions_added) == (0, 3, 0)

    frame = repo.load_observations(include_synthetic=True)
    assert len(frame) == 3  # nothing duplicated in storage


def test_different_value_creates_new_revision_preserving_history(repo) -> None:
    _catalog_populated(repo)
    original = make_obs(observation_date=date(2020, 1, 1), value=1.0, is_synthetic=False)
    revised = make_obs(observation_date=date(2020, 1, 1), value=2.5, is_synthetic=False)

    first = repo.insert_observations([original])
    assert first.inserted == 1
    second = repo.insert_observations([revised])
    assert (second.inserted, second.revisions_added, second.duplicates_skipped) == (0, 1, 0)

    frame = repo.load_observations(include_synthetic=True, entity_code="TST", indicator_id="TEST_IND")
    assert len(frame) == 2  # BOTH revisions stored; nothing overwritten
    revisions = dict(
        zip(frame["observation_date"].astype(str) + "#" + frame["revision"].astype(str), frame["value"])
    )
    assert revisions["2020-01-01#0"] == pytest.approx(1.0)
    assert revisions["2020-01-01#1"] == pytest.approx(2.5)

    new_row = frame[frame["revision"] == 1]
    assert new_row.iloc[0]["quality_flags"] == ["revision_change"]
    # A third replay of the SAME revised value is again a plain duplicate.
    replay = repo.insert_observations([revised])
    assert (replay.inserted, replay.revisions_added, replay.duplicates_skipped) == (0, 0, 1)


def test_stale_older_revision_replay_is_skipped_not_resurrected(repo) -> None:
    _catalog_populated(repo)
    v1 = make_obs(observation_date=date(2020, 1, 1), value=1.0, is_synthetic=False)
    v2 = make_obs(observation_date=date(2020, 1, 1), value=2.0, is_synthetic=False)
    repo.insert_observations([v1])
    repo.insert_observations([v2])  # revision 1 exists now
    # Replay of revision-0 content while revision 1 is the top revision:
    # stale, skipped - old history must never be silently re-applied.
    stale = repo.insert_observations([v1])
    assert stale.duplicates_skipped == 1 and stale.revisions_added == 0
    frame = repo.load_observations(include_synthetic=True)
    assert set(frame["value"]) == {1.0, 2.0}


def test_point_in_time_excludes_unknown_publication_by_default(repo) -> None:
    _catalog_populated(repo)
    with_pub = make_obs(  # published 2020-05-01 for year 2019
        observation_date=date(2019, 1, 1), publication_date=date(2020, 5, 1), is_synthetic=False
    )
    no_pub = make_obs(  # unknown publication date
        observation_date=date(2020, 2, 15), publication_date=None, is_synthetic=False
    )
    repo.insert_observations([with_pub, no_pub])

    # as_of must be after the KNOWN publication (2020-05-01) to see the row.
    df_strict = repo.point_in_time(as_of=date(2020, 6, 1))
    assert len(df_strict) == 1 and df_strict.iloc[0]["observation_date"] == date(2019, 1, 1)

    df_relaxed = repo.point_in_time(as_of=date(2020, 6, 1), allow_unknown_publication=True)
    assert len(df_relaxed) == 2  # unknown-publication now included on request

    df_as_of_2020_03 = repo.point_in_time(as_of=date(2020, 3, 1))
    assert df_as_of_2020_03.empty  # not yet published, not yet observable

    df_before_all = repo.point_in_time(as_of=date(2018, 12, 31))
    assert df_before_all.empty


def test_point_in_time_returns_latest_published_revision_only(repo) -> None:
    _catalog_populated(repo)
    v1 = make_obs(observation_date=date(2019, 1, 1), value=1.0,
                  publication_date=date(2020, 5, 1), is_synthetic=False)
    v2 = make_obs(observation_date=date(2019, 1, 1), value=1.5,
                  publication_date=date(2021, 5, 1), is_synthetic=False)
    repo.insert_observations([v1, v2])

    df = repo.point_in_time(as_of=date(2020, 12, 31))
    assert len(df) == 1 and df.iloc[0]["value"] == pytest.approx(1.0)  # rev 1 not yet published
    df_later = repo.point_in_time(as_of=date(2022, 1, 1))
    assert len(df_later) == 1 and df_later.iloc[0]["value"] == pytest.approx(1.5)


def test_synthetic_rows_are_separate_by_default(repo) -> None:
    _catalog_populated(repo)
    synthetic = make_obs(is_synthetic=True)
    real = make_obs(is_synthetic=False, entity_code="USA")
    repo.insert_observations([synthetic, real])

    df_real = repo.load_observations()
    assert df_real["is_synthetic"].sum() == 0
    assert set(df_real["entity_code"]) == {"USA"}

    df_all = repo.load_observations(include_synthetic=True)
    assert df_all["is_synthetic"].sum() == 1


def test_raw_records_archived_with_content_dedup(repo) -> None:
    from data.schemas import RawRecordInfo

    repo.ensure_source("test_source", "Test source")  # ingestion_run FK target
    run_id = repo.create_run("test_source")
    records = [RawRecordInfo(url="u", payload={"a": 1}), RawRecordInfo(url="u", payload={"a": 1})]
    assert repo.archive_raw_records(run_id, "test_source", records) == 1  # dedup by hash
    assert repo.archive_raw_records(
        run_id, "test_source", [RawRecordInfo(url="u", payload={"a": 2})]
    ) == 1


def test_run_lifecycle_records_stats(repo) -> None:
    _catalog_populated(repo)
    run_id = repo.create_run("test_source")
    stats = repo.insert_observations([make_obs(is_synthetic=False)])
    repo.record_run_stats(run_id, stats, warnings=["some warning"])
    repo.finish_run(run_id, status="ok")

    run = repo.get_run(run_id)
    assert run.status == "ok"
    assert run.observations_in == 1 and run.observations_new == 1
    assert run.errors_seen == 0
    assert run.error_log == ["some warning"]
    assert run.finished_at is not None


def test_load_filters_by_kind_and_entity(repo) -> None:
    _catalog_populated(repo)
    macro = make_obs(is_synthetic=False)
    fx = make_obs(kind=ObservationKind.EXCHANGE_RATE, entity_code="USD/BRL",
                  indicator_id=None, frequency=Frequency.DAILY,
                  publication_date=date(2020, 1, 1), is_synthetic=False)
    repo.insert_observations([macro, fx])

    fx_frame = repo.load_observations(kind=ObservationKind.EXCHANGE_RATE)
    assert len(fx_frame) == 1 and fx_frame.iloc[0]["entity_code"] == "USD/BRL"
    assert repo.load_observations(entity_code="TST").iloc[0]["kind"] == "macro_indicator"


def test_duplicate_natural_key_violates_unique_constraint(repo) -> None:
    """Direct ORM double-insert must fail on the DB constraint, not silently merge."""
    from data.db.models import DataObservation as Row

    _catalog_populated(repo)
    with repo._session_factory() as session:
        args = dict(
            kind="macro_indicator", source_id="test_source", indicator_id="TEST_IND",
            entity_code="TST", value=1.0, unit="percent", frequency="annual",
            observation_date=date(2020, 1, 1), publication_date=date(2021, 1, 1),
            retrieved_at=_NOW, is_synthetic=False,
        )
        session.add(Row(**args))
        session.commit()
        session.add(Row(**args))
        with pytest.raises(IntegrityError):
            session.commit()
