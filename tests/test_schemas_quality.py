"""Schema validation + data-quality engine tests. All data is synthetic."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from conftest import make_obs
from data.quality import validate_batch
from data.schemas import (
    Frequency,
    IndicatorInfo,
    ObservationKind,
    QualityFlag,
)

TODAY = date(2024, 6, 1)


# ---------------------------------------------------------------- schema rules


def test_schema_rejects_publication_before_observation() -> None:
    with pytest.raises(ValidationError):
        make_obs(
            observation_date=date(2021, 1, 1),
            publication_date=date(2020, 12, 31),
        )


def test_schema_rejects_nonfinite_values() -> None:
    with pytest.raises(ValidationError):
        make_obs(value=float("nan"))
    with pytest.raises(ValidationError):
        make_obs(value=float("inf"))


def test_schema_rejects_extra_fields_and_bad_source_id() -> None:
    with pytest.raises(ValidationError):
        make_obs(hallucinated_field=True)
    with pytest.raises(ValidationError):
        make_obs(source_id="Not A Slug")


def test_schema_keeps_quality_flags() -> None:
    obs = make_obs(quality_flags=[QualityFlag.OUTLIER_SUSPECT])
    assert obs.quality_flags == [QualityFlag.OUTLIER_SUSPECT]


# ---------------------------------------------------------------- quality rules


def test_clean_batch_is_clean() -> None:
    obs = [
        make_obs(observation_date=date(2020 + i, 1, 1), publication_date=date(2021 + i, 1, 1))
        for i in range(3)
    ]
    _, report = validate_batch(obs, today=TODAY)
    assert report.is_clean
    assert report.total == 3


def test_future_observations_are_flagged_not_dropped() -> None:
    future = make_obs(
        observation_date=TODAY + timedelta(days=10), publication_date=None
    )
    observations, report = validate_batch([future], today=TODAY)
    assert future.quality_flags == [QualityFlag.FUTURE_DATE]
    assert report.flagged == 1
    assert observations == [future]  # preserved for the caller to decide


def test_negative_quoted_rates_flagged() -> None:
    fx = make_obs(kind=ObservationKind.EXCHANGE_RATE, entity_code="USD/BRL", value=-4.9,
                  frequency=Frequency.DAILY, indicator_id=None)
    ir = make_obs(kind=ObservationKind.INTEREST_RATE, entity_code="TST", value=0.0,
                  indicator_id=None)
    _, report = validate_batch([fx, ir], today=TODAY)
    assert fx.quality_flags == [QualityFlag.NEGATIVE_RATE]
    assert ir.quality_flags == [QualityFlag.NEGATIVE_RATE]
    assert report.counts["negative_rate"] == 2


def test_macro_indicators_may_be_negative() -> None:
    deflation = make_obs(value=-2.0)
    _, report = validate_batch([deflation], today=TODAY)
    assert report.is_clean  # negative inflation is a fact, not an error


def test_invalid_fx_pair_codes_flagged() -> None:
    bad = make_obs(kind=ObservationKind.EXCHANGE_RATE, entity_code="US/BRL", indicator_id=None)
    ok = make_obs(kind=ObservationKind.EXCHANGE_RATE, entity_code="USD/BRL", indicator_id=None)
    _, report = validate_batch([bad, ok], today=TODAY)
    assert bad.quality_flags == [QualityFlag.INVALID_CURRENCY]
    assert ok.quality_flags == []


def test_unit_and_frequency_mismatch_against_catalog() -> None:
    catalog = {
        ("test_source", "TEST_IND"): IndicatorInfo(
            source_id="test_source",
            indicator_id="TEST_IND",
            name="Inflation",
            unit="percent",
            frequency=Frequency.ANNUAL,
        )
    }
    # Cross-checks engage only for declared cataloged indicators. The two
    # observations below must NOT form one mixed-frequency series (different
    # entities), otherwise the intra-series frequency rule would flag both:
    wrong_unit = make_obs(indicator_id="TEST_IND", unit="index")
    wrong_freq = make_obs(indicator_id="TEST_IND", unit="percent", frequency=Frequency.MONTHLY,
                          entity_code="OTHER")
    _, report = validate_batch([wrong_unit, wrong_freq], indicators=catalog, today=TODAY)
    assert wrong_unit.quality_flags == [QualityFlag.UNIT_MISMATCH]
    assert wrong_freq.quality_flags == [QualityFlag.FREQUENCY_INCONSISTENT]


def test_frequency_mix_within_series_flagged() -> None:
    annual = make_obs(indicator_id=None, frequency=Frequency.ANNUAL)
    quarterly = make_obs(indicator_id=None, frequency=Frequency.QUARTERLY,
                         observation_date=date(2020, 4, 1))
    _, report = validate_batch([annual, quarterly], today=TODAY)
    # Same (entity, indicator) mixing frequencies: both flagged as inconsistent.
    assert annual.quality_flags == [QualityFlag.FREQUENCY_INCONSISTENT]
    assert quarterly.quality_flags == [QualityFlag.FREQUENCY_INCONSISTENT]


def test_batch_duplicates_flagged() -> None:
    first = make_obs()
    duplicate = make_obs()
    _, report = validate_batch([first, duplicate], today=TODAY)
    assert first.quality_flags == []
    assert duplicate.quality_flags == [QualityFlag.DUPLICATE_IN_BATCH]


def test_non_chronological_batch_flagged() -> None:
    newer = make_obs(observation_date=date(2021, 1, 1))
    older = make_obs(observation_date=date(2020, 1, 1), publication_date=date(2020, 6, 1))
    _, report = validate_batch([newer, older], today=TODAY)
    assert all(o.quality_flags == [QualityFlag.ORDER_INCONSISTENT] for o in (newer, older))


def test_suspicious_daily_fx_jump_flagged() -> None:
    calm = make_obs(kind=ObservationKind.EXCHANGE_RATE, entity_code="USD/BRL",
                    frequency=Frequency.DAILY, indicator_id=None,
                    observation_date=date(2024, 1, 1), value=5.0,
                    publication_date=date(2024, 1, 1))
    crash = make_obs(kind=ObservationKind.EXCHANGE_RATE, entity_code="USD/BRL",
                     frequency=Frequency.DAILY, indicator_id=None,
                     observation_date=date(2024, 1, 2), value=8.0,  # +60 % overnight
                     publication_date=date(2024, 1, 2))
    _, report = validate_batch([calm, crash], today=TODAY)
    assert crash.quality_flags == [QualityFlag.SUSPICIOUS_JUMP]
    assert calm.quality_flags == []  # the jump is the anomaly, not the level


def test_outliers_flagged_but_alive() -> None:
    values = [1.0, 1.05, 0.98, 1.02, 0.97, 1.03, 0.99, 1000.0]
    obs = [
        make_obs(observation_date=date(2017 + i, 1, 1), value=v,
                 publication_date=date(2018 + i, 1, 1))
        for i, v in enumerate(values)
    ]
    observations, report = validate_batch(obs, today=TODAY)
    suspected = [o for o in observations if QualityFlag.OUTLIER_SUSPECT in o.quality_flags]
    assert [o.value for o in suspected] == [1000.0]
    assert 1000.0 in [o.value for o in observations]  # NOT deleted, never auto-discarded
    assert report.counts["outlier_suspect"] == 1


def test_nan_values_rejected_upstream_never_reach_the_engine() -> None:
    """The schema layer rejects non-finite values; the engine's
    missing-value branch is a defensive last resort, not a data path."""
    with pytest.raises(ValidationError):
        make_obs(value=float("nan"))
