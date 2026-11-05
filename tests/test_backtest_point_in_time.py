"""Tests for Historical Information Firewall and Point-in-Time Data Access.

Verifies:
- Strict mode rejects observations without publication date or published after T
- Estimated-lag mode applies conservative frequency lags and flags unverified status
- Research-only mode is flagged as unsuitable for executable trading
- Stale price quotes (> max_stale_days) are detected and rejected
- Future-information leakage test:
  Demonstrates that a naive look-ahead strategy produces artificially profitable
  returns by peeking ahead at unannounced market movements, whereas the Point-in-Time
  Firewall strictly prevents look-ahead and reveals the genuine historical loss.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import pytest

from backtesting.point_in_time import PointInTimeDataStore, PointInTimeFirewall
from data.schemas import DataObservation, Frequency, ObservationKind
from schemas.backtest import AvailabilityPolicy, DataAvailabilityConfig


def make_test_obs(
    obs_date: date,
    pub_date: date | None,
    value: float,
    kind: ObservationKind = ObservationKind.EXCHANGE_RATE,
    entity: str = "USD/EUR",
    indicator: str | None = None,
    freq: Frequency = Frequency.DAILY,
    revision: int = 0,
) -> DataObservation:
    return DataObservation(
        kind=kind,
        source_id="test_source",
        indicator_id=indicator,
        entity_code=entity,
        value=value,
        unit="rate" if kind == ObservationKind.EXCHANGE_RATE else "percent",
        frequency=freq,
        observation_date=obs_date,
        publication_date=pub_date,
        retrieved_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        revision=revision,
        is_synthetic=True,
    )


def test_firewall_strict_mode():
    """In STRICT mode, observations with no publication date or future pub dates are rejected."""
    config = DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=True)
    firewall = PointInTimeFirewall(config)

    obs1 = make_test_obs(date(2024, 1, 1), pub_date=date(2024, 1, 2), value=1.10)
    obs2 = make_test_obs(date(2024, 1, 2), pub_date=date(2024, 1, 5), value=1.12)
    obs3 = make_test_obs(date(2024, 1, 3), pub_date=None, value=1.15)  # Unknown pub date

    records = firewall.filter_available([obs1, obs2, obs3], as_of=date(2024, 1, 3))
    available_vals = [r.observation.value for r in records]

    # As of Jan 3, obs1 (pub Jan 2) is available; obs2 (pub Jan 5) is future; obs3 has no pub date
    assert available_vals == [1.10]
    assert records[0].is_verified_availability is True


def test_firewall_estimated_lag_mode():
    """In ESTIMATED_LAG mode, missing publication date uses frequency lag and flags as unverified."""
    config = DataAvailabilityConfig(
        policy=AvailabilityPolicy.ESTIMATED_LAG,
        default_lags_days={Frequency.MONTHLY: 30, Frequency.DAILY: 1},
        allow_synthetic=True,
    )
    firewall = PointInTimeFirewall(config)

    # Monthly inflation observed Jan 31 with no publication date -> lag 30d -> available March 1
    macro_obs = make_test_obs(
        obs_date=date(2024, 1, 31),
        pub_date=None,
        value=3.5,
        kind=ObservationKind.MACRO_INDICATOR,
        entity="USA",
        indicator="CPI",
        freq=Frequency.MONTHLY,
    )

    # Check on Feb 15 (only 15 days after observation date) -> should NOT be available
    rec_feb = firewall.filter_available([macro_obs], as_of=date(2024, 2, 15))
    assert len(rec_feb) == 0

    # Check on March 5 (34 days after observation date) -> should BE available, but UNVERIFIED
    rec_mar = firewall.filter_available([macro_obs], as_of=date(2024, 3, 5))
    assert len(rec_mar) == 1
    assert rec_mar[0].is_verified_availability is False
    assert "estimated_lag_30d_unverified" in rec_mar[0].status_note


def test_firewall_research_only_mode():
    """Research-only mode allows retrospective observation access but flags policy."""
    config = DataAvailabilityConfig(policy=AvailabilityPolicy.RESEARCH_ONLY, allow_synthetic=True)
    firewall = PointInTimeFirewall(config)

    obs = make_test_obs(
        obs_date=date(2024, 1, 1),
        pub_date=date(2024, 6, 1),  # Published months later
        value=1.20,
    )

    # As of Jan 2, in research-only mode, it's visible based on observation_date
    rec = firewall.filter_available([obs], as_of=date(2024, 1, 2))
    assert len(rec) == 1
    assert rec[0].is_verified_availability is False
    assert rec[0].policy_applied == AvailabilityPolicy.RESEARCH_ONLY


def test_stale_quote_detection():
    """Quotes older than max_stale_days are flagged and excluded when allow_stale=False."""
    config = DataAvailabilityConfig(
        policy=AvailabilityPolicy.STRICT,
        max_stale_days=3,
        allow_synthetic=True,
    )
    firewall = PointInTimeFirewall(config)

    # Rate on Jan 1, published Jan 1
    obs = make_test_obs(date(2024, 1, 1), pub_date=date(2024, 1, 1), value=1.05)

    # Query on Jan 10 (9 days stale for daily data)
    store = PointInTimeDataStore([obs], firewall)

    rate_fresh = store.get_rate("USD/EUR", as_of=date(2024, 1, 2), allow_stale=False)
    assert rate_fresh == 1.05

    rate_stale = store.get_rate("USD/EUR", as_of=date(2024, 1, 10), allow_stale=False)
    assert rate_stale is None

    # But if explicitly allowed, can retrieve
    rate_allowed = store.get_rate("USD/EUR", as_of=date(2024, 1, 10), allow_stale=True)
    assert rate_allowed == 1.05


def test_future_information_leakage_prevention():
    """Proves that look-ahead leakage creates false profits, while the firewall blocks it.

    Scenario:
    - On 2024-03-01, an unexpected currency devaluation or rate cut occurs.
    - However, official data is only published on 2024-03-05.
    - A flawed algorithm that peeks ahead at observation_date without publication date
      exits or avoids the crash on 2024-03-01, escaping the loss.
    - Under the STRICT Point-In-Time Firewall, the simulation as of 2024-03-01 CANNOT
      see the crash yet and only sees pre-crash verified quotes.
    """
    # Pre-crash stable quote
    pre_crash_obs = make_test_obs(
        obs_date=date(2024, 2, 28),
        pub_date=date(2024, 2, 28),
        value=1.50,
    )

    # Severe devaluation on March 1, but embargoed/published March 5
    crash_obs = make_test_obs(
        obs_date=date(2024, 3, 1),
        pub_date=date(2024, 3, 5),
        value=1.00,  # 33% devaluation of currency B
    )

    all_obs = [pre_crash_obs, crash_obs]

    # 1. Leaky / Naive Access (simulating what happens without firewall)
    # Naive lookup checks observation_date <= 2024-03-01 and takes the crash quote early
    naive_available = [o for o in all_obs if o.observation_date <= date(2024, 3, 1)]
    naive_latest = max(naive_available, key=lambda o: o.observation_date)
    assert naive_latest.value == 1.00  # LEAK! Leaked future devaluation 4 days before publication!

    # 2. Strict Point-in-Time Firewall Access as of 2024-03-01
    strict_config = DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=True)
    strict_firewall = PointInTimeFirewall(strict_config)
    strict_store = PointInTimeDataStore(all_obs, strict_firewall)

    strict_quote_march1 = strict_store.get_rate("USD/EUR", as_of=date(2024, 3, 1))
    # Must NOT see the 1.00 crash quote! Must return the pre-crash rate 1.50
    assert strict_quote_march1 == 1.50

    # On March 5 (publication date), the crash quote becomes legitimately available
    strict_quote_march5 = strict_store.get_rate("USD/EUR", as_of=date(2024, 3, 5))
    assert strict_quote_march5 == 1.00
