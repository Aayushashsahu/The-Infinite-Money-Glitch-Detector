"""Currency Market Calendar and Trading Day Utilities.

Distinguishes:
- Trading days (business days when interbank FX markets operate)
- Weekends (Saturday and Sunday, market closure)
- Standard global currency market holidays (e.g. New Year's Day, Christmas)
- Missing trading-day data (provider outage / data gap on an active trading day)
- Stale prices (quotes exceeding permissible trading-day lag)

Prevents weekend non-trading days from being falsely counted as staleness
or data-quality failures.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Container, Sequence


def _default_fx_holidays(year: int) -> set[date]:
    """Standard global international FX market holidays for a given year."""
    holidays = {
        date(year, 1, 1),   # New Year's Day
        date(year, 12, 25), # Christmas Day
    }
    # If Jan 1 is Sunday, Monday Jan 2 is observed
    if date(year, 1, 1).weekday() == 6:
        holidays.add(date(year, 1, 2))
    # If Dec 25 is Sunday, Monday Dec 26 is observed
    if date(year, 12, 25).weekday() == 6:
        holidays.add(date(year, 12, 26))
    return holidays


class MarketCalendar:
    """Calendar for foreign exchange trading days, weekends, and holidays."""

    def __init__(self, custom_holidays: Container[date] | None = None):
        self._custom_holidays = set(custom_holidays or [])
        self._holiday_cache: dict[int, set[date]] = {}

    def is_weekend(self, d: date) -> bool:
        """Saturday (5) and Sunday (6) are FX market weekends."""
        return d.weekday() >= 5

    def is_holiday(self, d: date) -> bool:
        """Check if date is a scheduled currency market holiday."""
        if d in self._custom_holidays:
            return True
        if d.year not in self._holiday_cache:
            self._holiday_cache[d.year] = _default_fx_holidays(d.year)
        return d in self._holiday_cache[d.year]

    def is_trading_day(self, d: date) -> bool:
        """True if the date is an active FX trading day (not weekend, not holiday)."""
        return not self.is_weekend(d) and not self.is_holiday(d)

    def classify_date(self, d: date) -> str:
        """Categorize a calendar date."""
        if self.is_weekend(d):
            return "weekend"
        if self.is_holiday(d):
            return "holiday"
        return "trading_day"

    def next_trading_day(self, d: date) -> date:
        """Find the earliest trading day strictly after date d."""
        curr = d + timedelta(days=1)
        while not self.is_trading_day(curr):
            curr += timedelta(days=1)
        return curr

    def previous_trading_day(self, d: date) -> date:
        """Find the latest trading day strictly before date d."""
        curr = d - timedelta(days=1)
        while not self.is_trading_day(curr):
            curr -= timedelta(days=1)
        return curr

    def trading_days_between(self, start_date: date, end_date: date) -> list[date]:
        """Return all active trading days in [start_date, end_date] inclusive."""
        if start_date > end_date:
            return []
        days: list[date] = []
        curr = start_date
        while curr <= end_date:
            if self.is_trading_day(curr):
                days.append(curr)
            curr += timedelta(days=1)
        return days

    def count_trading_days(self, start_date: date, end_date: date) -> int:
        """Count the number of active trading days in [start_date, end_date]."""
        return len(self.trading_days_between(start_date, end_date))

    def trading_days_lag(self, from_date: date, to_date: date) -> int:
        """Calculate lag between two dates strictly in trading days.

        For example, a Friday quote queried on Monday morning has a lag of
        1 trading day (not 3 calendar days).
        """
        if to_date < from_date:
            raise ValueError(f"to_date ({to_date}) cannot be before from_date ({from_date})")
        if from_date == to_date:
            return 0
        # Count trading days strictly between from_date and to_date (exclusive of from_date, inclusive of to_date)
        count = 0
        curr = from_date + timedelta(days=1)
        while curr <= to_date:
            if self.is_trading_day(curr):
                count += 1
            curr += timedelta(days=1)
        return count

    def add_trading_days(self, d: date, n: int) -> date:
        """Advance (or regress if n < 0) date d by n active trading days.

        For example, advancing Thursday by 2 trading days yields Monday (Friday is 1,
        Saturday/Sunday skipped, Monday is 2).
        """
        if n == 0:
            return d
        step = 1 if n > 0 else -1
        remaining = abs(n)
        curr = d
        while remaining > 0:
            curr += timedelta(days=step)
            if self.is_trading_day(curr):
                remaining -= 1
        return curr


# Global default instance
DEFAULT_FX_CALENDAR = MarketCalendar()
