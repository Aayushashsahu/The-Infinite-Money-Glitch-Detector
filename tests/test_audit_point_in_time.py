"""Adversarial Point-in-Time and Look-Ahead Bias Audit Tests.

Phase 3.1 Validation:
- Multi-revision tracking: Ensures signals as of intermediate date T see only
  the latest revision published BY T, never future revisions.
- Delayed publication: Verifies observations with delayed publications are
  completely invisible to strategy signals until their official publication date.
- Look-ahead leakage prevention: Adversarial test ensuring future data cannot
  infiltrate signals under any query pattern.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import pytest

from backtesting.point_in_time import PointInTimeDataStore, PointInTimeFirewall
from data.schemas import DataObservation, Frequency, ObservationKind
from schemas.backtest import AvailabilityPolicy, DataAvailabilityConfig


def make_obs(
    obs_date: date,
    pub_date: date | None,
    val: float,
    kind: ObservationKind = ObservationKind.MACRO_INDICATOR,
    entity: str = "USA",
    indicator: str = "CPI_ANNUAL",
    revision: int = 0,
) -> DataObservation:
    return DataObservation(
        kind=kind,
        source_id="test_source",
        indicator_id=indicator,
        entity_code=entity,
        value=val,
        unit="percent",
        frequency=Frequency.MONTHLY,
        observation_date=obs_date,
        publication_date=pub_date,
        retrieved_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        revision=revision,
        is_synthetic=True,
    )


def test_adversarial_economic_revisions():
    """Signals evaluated on intermediate dates must see only pre-revision data.

    Scenario:
    - January CPI observed 2024-01-31.
    - Initial release (Revision 0): 3.2% published on 2024-02-15.
    - Revised release (Revision 1): 2.8% published on 2024-04-15 (restatement).
    - As of 2024-03-01: signal MUST see Revision 0 (3.2%), NOT Revision 1 (2.8%).
    - As of 2024-05-01: signal MUST see Revision 1 (2.8%).
    """
    rev0 = make_obs(
        obs_date=date(2024, 1, 31),
        pub_date=date(2024, 2, 15),
        val=3.2,
        revision=0,
    )
    rev1 = make_obs(
        obs_date=date(2024, 1, 31),
        pub_date=date(2024, 4, 15),
        val=2.8,
        revision=1,
    )
    observations = [rev0, rev1]

    config = DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=True)
    firewall = PointInTimeFirewall(config)
    store = PointInTimeDataStore(observations, firewall)

    # 1. As of 2024-03-01: Revision 1 has not been published yet
    rec_march = store.get_record(
        kind=ObservationKind.MACRO_INDICATOR,
        entity_code="USA",
        indicator_id="CPI_ANNUAL",
        as_of=date(2024, 3, 1),
    )
    assert rec_march is not None
    assert rec_march.observation.revision == 0
    assert rec_march.observation.value == 3.2

    # 2. As of 2024-05-01: Revision 1 is now officially published
    rec_may = store.get_record(
        kind=ObservationKind.MACRO_INDICATOR,
        entity_code="USA",
        indicator_id="CPI_ANNUAL",
        as_of=date(2024, 5, 1),
    )
    assert rec_may is not None
    assert rec_may.observation.revision == 1
    assert rec_may.observation.value == 2.8


def test_adversarial_delayed_publication_invisible_until_release():
    """Observations with delayed publications must be completely invisible to trading signals."""
    # Q1 GDP observed 2024-03-31, but official release is 2024-05-15
    gdp_obs = make_obs(
        obs_date=date(2024, 3, 31),
        pub_date=date(2024, 5, 15),
        val=2.5,
        indicator="GDP_GROWTH",
    )

    config = DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=True)
    firewall = PointInTimeFirewall(config)
    store = PointInTimeDataStore([gdp_obs], firewall)

    # Signal evaluations throughout April must return None
    assert store.get_record(ObservationKind.MACRO_INDICATOR, "USA", date(2024, 4, 1), indicator_id="GDP_GROWTH") is None
    assert store.get_record(ObservationKind.MACRO_INDICATOR, "USA", date(2024, 4, 15), indicator_id="GDP_GROWTH") is None
    assert store.get_record(ObservationKind.MACRO_INDICATOR, "USA", date(2024, 5, 14), indicator_id="GDP_GROWTH") is None

    # On May 15 (release date), it becomes available
    rec = store.get_record(ObservationKind.MACRO_INDICATOR, "USA", date(2024, 5, 15), indicator_id="GDP_GROWTH")
    assert rec is not None
    assert rec.observation.value == 2.5


def test_adversarial_future_observation_date_leakage():
    """Future observation dates cannot be retrieved under any policy."""
    obs_today = make_obs(date(2024, 1, 1), date(2024, 1, 1), 1.0)
    obs_future = make_obs(date(2024, 2, 1), date(2024, 2, 1), 5.0)

    for pol in [AvailabilityPolicy.STRICT, AvailabilityPolicy.ESTIMATED_LAG, AvailabilityPolicy.RESEARCH_ONLY]:
        cfg = DataAvailabilityConfig(policy=pol, allow_synthetic=True)
        store = PointInTimeDataStore([obs_today, obs_future], PointInTimeFirewall(cfg))

        # Query as of 2024-01-15: MUST NOT see obs_future
        rec = store.get_record(ObservationKind.MACRO_INDICATOR, "USA", as_of=date(2024, 1, 15), indicator_id="CPI_ANNUAL")
        assert rec is not None
        assert rec.observation.observation_date == date(2024, 1, 1)
        assert rec.observation.value == 1.0
