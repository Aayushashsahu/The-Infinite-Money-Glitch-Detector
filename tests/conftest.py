"""Shared Phase 2 test fixtures.

Every observation built here is SYNTHETIC (``is_synthetic=True``) so
test data can never be confused with real economic history - enforced
by default everywhere.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import sys

if sys.platform == "win32":
    try:
        import ctypes

        try:
            ctypes.CDLL("ucrtbase.dll")._setmaxstdio(8192)
        except Exception:
            ctypes.cdll.msvcrt._setmaxstdio(8192)
    except Exception:
        pass

import pytest

from pydantic import ValidationError

from data.db.engine import make_engine, make_session_factory
from data.repository import Repository
from data.schemas import DataObservation, Frequency, ObservationKind


def make_obs(**overrides) -> DataObservation:
    """Build a synthetic DataObservation with test-friendly defaults.

    Default publication date trails the observation date by one year so
    arbitrary far-future observation dates stay schema-valid.
    """
    observation_date = overrides.get("observation_date", date(2020, 1, 1))
    kind = overrides.get("kind", ObservationKind.MACRO_INDICATOR)
    default_unit = "quote_per_base" if kind == ObservationKind.EXCHANGE_RATE else "percent"
    defaults = dict(
        kind=kind,
        source_id="test_source",
        indicator_id="TEST_IND",
        entity_code="TST",
        value=1.0,
        unit=default_unit,
        frequency=Frequency.ANNUAL,
        observation_date=observation_date,
        retrieved_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        is_synthetic=True,
    )
    if "publication_date" in overrides:
        defaults["publication_date"] = overrides["publication_date"]
    else:
        defaults["publication_date"] = date(observation_date.year + 1, observation_date.month, observation_date.day)
    defaults.update({k: v for k, v in overrides.items() if k != "publication_date"})
    try:
        return DataObservation(**defaults)
    except ValidationError:
        if overrides.get("entity_code") == "US/BRL" or overrides.get("_construct", False):
            return DataObservation.model_construct(**defaults)
        raise


@pytest.fixture
def repo():
    """Fresh in-memory repository with all tables created."""
    engine = make_engine("sqlite://")
    repository = Repository(make_session_factory(engine))
    repository.create_all()
    return repository
