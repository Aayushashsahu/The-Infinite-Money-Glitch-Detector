"""Shared Phase 2 test fixtures.

Every observation built here is SYNTHETIC (``is_synthetic=True``) so
test data can never be confused with real economic history - enforced
by default everywhere.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from data.db.engine import make_engine, make_session_factory
from data.repository import Repository
from data.schemas import DataObservation, Frequency, ObservationKind


def make_obs(**overrides) -> DataObservation:
    """Build a synthetic DataObservation with test-friendly defaults.

    Default publication date trails the observation date by one year so
    arbitrary far-future observation dates stay schema-valid.
    """
    observation_date = overrides.get("observation_date", date(2020, 1, 1))
    defaults = dict(
        kind=ObservationKind.MACRO_INDICATOR,
        source_id="test_source",
        indicator_id="TEST_IND",
        entity_code="TST",
        value=1.0,
        unit="percent",
        frequency=Frequency.ANNUAL,
        observation_date=observation_date,
        retrieved_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        is_synthetic=True,
    )
    if "publication_date" in overrides:
        defaults["publication_date"] = overrides["publication_date"]
    else:
        defaults["publication_date"] = date(
            observation_date.year + 1, observation_date.month, observation_date.day
        )
    defaults.update({k: v for k, v in overrides.items() if k != "publication_date"})
    return DataObservation(**defaults)


@pytest.fixture
def repo():
    """Fresh in-memory repository with all tables created."""
    engine = make_engine("sqlite://")
    repository = Repository(make_session_factory(engine))
    repository.create_all()
    return repository
