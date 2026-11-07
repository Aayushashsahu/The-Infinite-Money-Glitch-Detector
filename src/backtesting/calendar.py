"""Currency Market Calendar and Joint Settlement Calendar Utilities.

Distinguishes:
- Trading days (business days when interbank FX markets operate)
- Weekends (Saturday and Sunday, market closure)
- Standard global currency market holidays (e.g. New Year's Day, Christmas)
- Jurisdiction-specific central bank settlement calendars (TARGET2 for EUR, US Fed for USD)
- Joint settlement days for cross-currency pairs (requiring both jurisdictions to be open)
- Weekend observance shifts (Saturday -> Friday, Sunday -> Monday)
- Missing trading-day data vs stale prices

Prevents non-settlement or holiday days from being falsely counted as staleness
or data-quality failures.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Container
import zoneinfo

EASTERN_TZ = zoneinfo.ZoneInfo("America/New_York")


def _easter_date(year: int) -> date:
    """Meeus/Butcher algorithm to calculate Gregorian Easter Sunday."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l_val = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_val) // 451
    month = (h + l_val - 7 * m + 114) // 31
    day = ((h + l_val - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """Find the nth occurrence (1-indexed) of a weekday (0=Mon, ..., 6=Sun) in year/month."""
    first_day = date(year, month, 1)
    day_of_week = first_day.weekday()
    days_to_add = (weekday - day_of_week) % 7
    first_target = first_day + timedelta(days=days_to_add)
    return first_target + timedelta(weeks=n - 1)


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    """Find the last occurrence of a weekday in year/month."""
    if month == 12:
        last_day = date(year, 12, 31)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)
    day_of_week = last_day.weekday()
    days_to_sub = (day_of_week - weekday) % 7
    return last_day - timedelta(days=days_to_sub)


def _us_observed(d: date) -> date:
    """Standard US federal holiday weekend observance rule."""
    if d.weekday() == 5:  # Saturday -> Friday
        return d - timedelta(days=1)
    if d.weekday() == 6:  # Sunday -> Monday
        return d + timedelta(days=1)
    return d


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


def _target_holidays(year: int) -> set[date]:
    """Eurosystem TARGET2 / TARGET settlement holidays."""
    easter = _easter_date(year)
    holidays = {
        date(year, 1, 1),                        # New Year's Day
        easter - timedelta(days=2),              # Good Friday
        easter + timedelta(days=1),              # Easter Monday
        date(year, 5, 1),                        # Labour Day
        date(year, 12, 25),                      # Christmas Day
        date(year, 12, 26),                      # Boxing Day
    }
    return holidays


def _us_fed_holidays(year: int) -> set[date]:
    """US Federal Reserve / US Banking holidays with weekend observance shifts."""
    holidays: set[date] = set()

    # Jan 1 - New Year's Day (observed)
    # If Jan 1 falls on Saturday, Friday Dec 31 of prior year is observed
    jan1 = date(year, 1, 1)
    holidays.add(_us_observed(jan1))
    # Check if next year's Jan 1 falls on Saturday (so Dec 31 of this year is observed holiday)
    next_jan1 = date(year + 1, 1, 1)
    if next_jan1.weekday() == 5:
        holidays.add(date(year, 12, 31))

    # Martin Luther King Jr. Day (3rd Monday in January)
    holidays.add(_nth_weekday_of_month(year, 1, 0, 3))

    # Washington's Birthday / Presidents Day (3rd Monday in February)
    holidays.add(_nth_weekday_of_month(year, 2, 0, 3))

    # Memorial Day (Last Monday in May)
    holidays.add(_last_weekday_of_month(year, 5, 0))

    # Juneteenth National Independence Day (June 19, federal holiday starting 2021)
    if year >= 2021:
        holidays.add(_us_observed(date(year, 6, 19)))

    # Independence Day (July 4)
    holidays.add(_us_observed(date(year, 7, 4)))

    # Labor Day (1st Monday in September)
    holidays.add(_nth_weekday_of_month(year, 9, 0, 1))

    # Columbus Day (2nd Monday in October)
    holidays.add(_nth_weekday_of_month(year, 10, 0, 2))

    # Veterans Day (November 11)
    holidays.add(_us_observed(date(year, 11, 11)))

    # Thanksgiving Day (4th Thursday in November)
    holidays.add(_nth_weekday_of_month(year, 11, 3, 4))

    # Christmas Day (December 25)
    holidays.add(_us_observed(date(year, 12, 25)))

    return holidays


class JointCurrencySettlementCalendar:
    """Joint settlement calendar for cross-currency spot settlements (e.g. EUR/USD).

    Spot FX transactions typically settle on T+2 joint business days.
    Both currency payment and settlement systems (e.g. TARGET for EUR, Fedwire for USD)
    must be open for settlement to occur.
    """

    def __init__(self, base_currency: str, quote_currency: str):
        self.base_currency = base_currency.strip().upper()
        self.quote_currency = quote_currency.strip().upper()
        self._currencies = {self.base_currency, self.quote_currency}

        known_supported = {"EUR", "USD"}
        if self._currencies.issubset(known_supported):
            self.is_approximate = False
            self.calendar_name = f"{self.base_currency}/{self.quote_currency} Joint Settlement Calendar"
        else:
            self.is_approximate = True
            self.calendar_name = f"{self.base_currency}/{self.quote_currency} Global Settlement Calendar (Approximate)"

        self._holiday_cache: dict[int, set[date]] = {}

    def is_weekend(self, d: date) -> bool:
        """Saturday (5) and Sunday (6) are FX market closure days."""
        return d.weekday() >= 5

    def _get_holidays_for_year(self, year: int) -> set[date]:
        if year not in self._holiday_cache:
            holidays: set[date] = set()
            if not self.is_approximate:
                if "EUR" in self._currencies:
                    holidays.update(_target_holidays(year))
                if "USD" in self._currencies:
                    holidays.update(_us_fed_holidays(year))
            else:
                holidays.update(_default_fx_holidays(year))
            self._holiday_cache[year] = holidays
        return self._holiday_cache[year]

    def is_holiday(self, d: date) -> bool:
        """Check if date is a scheduled settlement holiday for either currency."""
        return d in self._get_holidays_for_year(d.year)

    def is_settlement_day(self, d: date) -> bool:
        """True if the date is an active joint settlement day (not weekend, not holiday)."""
        return not self.is_weekend(d) and not self.is_holiday(d)

    def is_trading_day(self, d: date) -> bool:
        """Alias for compatibility with trading day conventions."""
        return self.is_settlement_day(d)

    def classify_date(self, d: date) -> str:
        """Categorize a calendar date."""
        if self.is_weekend(d):
            return "weekend"
        if self.is_holiday(d):
            return "holiday"
        return "settlement_day"

    def next_settlement_day(self, d: date) -> date:
        """Earliest joint settlement day strictly after date d."""
        curr = d + timedelta(days=1)
        while not self.is_settlement_day(curr):
            curr += timedelta(days=1)
        return curr

    def previous_settlement_day(self, d: date) -> date:
        """Latest joint settlement day strictly before date d."""
        curr = d - timedelta(days=1)
        while not self.is_settlement_day(curr):
            curr -= timedelta(days=1)
        return curr

    def next_trading_day(self, d: date) -> date:
        return self.next_settlement_day(d)

    def previous_trading_day(self, d: date) -> date:
        return self.previous_settlement_day(d)

    def add_settlement_days(self, d: date, n: int) -> date:
        """Advance (or regress if n < 0) date d by n active joint settlement days."""
        if n == 0:
            return d
        step = 1 if n > 0 else -1
        remaining = abs(n)
        curr = d
        while remaining > 0:
            curr += timedelta(days=step)
            if self.is_settlement_day(curr):
                remaining -= 1
        return curr

    def add_trading_days(self, d: date, n: int) -> date:
        return self.add_settlement_days(d, n)

    def settlement_days_between(self, start_date: date, end_date: date) -> list[date]:
        """All active joint settlement days in [start_date, end_date] inclusive."""
        if start_date > end_date:
            return []
        days: list[date] = []
        curr = start_date
        while curr <= end_date:
            if self.is_settlement_day(curr):
                days.append(curr)
            curr += timedelta(days=1)
        return days

    def trading_days_between(self, start_date: date, end_date: date) -> list[date]:
        return self.settlement_days_between(start_date, end_date)

    def count_settlement_days(self, start_date: date, end_date: date) -> int:
        """Count the number of active joint settlement days in [start_date, end_date]."""
        return len(self.settlement_days_between(start_date, end_date))

    def count_trading_days(self, start_date: date, end_date: date) -> int:
        return self.count_settlement_days(start_date, end_date)

    def trading_days_lag(self, from_date: date, to_date: date) -> int:
        """Calculate lag between two dates strictly in settlement days."""
        if to_date < from_date:
            raise ValueError(f"to_date ({to_date}) cannot be before from_date ({from_date})")
        if from_date == to_date:
            return 0
        count = 0
        curr = from_date + timedelta(days=1)
        while curr <= to_date:
            if self.is_settlement_day(curr):
                count += 1
            curr += timedelta(days=1)
        return count


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
        """Calculate lag between two dates strictly in trading days."""
        if to_date < from_date:
            raise ValueError(f"to_date ({to_date}) cannot be before from_date ({from_date})")
        if from_date == to_date:
            return 0
        count = 0
        curr = from_date + timedelta(days=1)
        while curr <= to_date:
            if self.is_trading_day(curr):
                count += 1
            curr += timedelta(days=1)
        return count

    def add_trading_days(self, d: date, n: int) -> date:
        """Advance (or regress if n < 0) date d by n active trading days."""
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


def get_settlement_calendar(curr_a: str, curr_b: str) -> JointCurrencySettlementCalendar:
    """Return a JointCurrencySettlementCalendar for a given currency pair."""
    return JointCurrencySettlementCalendar(curr_a, curr_b)


# Global default instance
DEFAULT_FX_CALENDAR = MarketCalendar()


class FederalReserveH15Calendar:
    """Federal Reserve Statistical Release H.15 Availability Calendar.

    Publication rules for daily Selected Interest Rates (H.15):
    - Rates for business day T are published at approximately 4:15 PM Eastern Time
      (America/New_York) on the next Federal Reserve business day (T_next).
    - Federal Reserve business days are Monday through Friday, excluding Federal Reserve holidays:
      New Year's Day, Martin Luther King Jr. Day, Washington's Birthday/Presidents Day,
      Memorial Day, Juneteenth National Independence Day, Independence Day, Labor Day,
      Columbus Day, Veterans Day, Thanksgiving Day, and Christmas Day.
    - Weekend observance shifts: Sunday holidays are observed on Monday; Saturday holidays
      are observed on Friday.
    - Timezone conversion evaluates Eastern Standard Time (UTC-5, 21:15 UTC) and Eastern
      Daylight Time (UTC-4, 20:15 UTC) accurately via zoneinfo.ZoneInfo("America/New_York").
    """

    def __init__(self) -> None:
        self._holiday_cache: dict[int, set[date]] = {}

    def is_weekend(self, d: date) -> bool:
        """Saturday (5) and Sunday (6) are weekend closures."""
        return d.weekday() >= 5

    def get_fed_holidays(self, year: int) -> set[date]:
        """Return scheduled Federal Reserve holidays for a given year."""
        if year not in self._holiday_cache:
            self._holiday_cache[year] = _us_fed_holidays(year)
        return self._holiday_cache[year]

    def is_fed_holiday(self, d: date) -> bool:
        """Check whether date is an official Federal Reserve holiday."""
        return d in self.get_fed_holidays(d.year)

    def is_fed_business_day(self, d: date) -> bool:
        """Check whether date is an active Federal Reserve business day."""
        return not self.is_weekend(d) and not self.is_fed_holiday(d)

    def next_fed_business_day(self, d: date) -> date:
        """Earliest Federal Reserve business day strictly after date d."""
        curr = d + timedelta(days=1)
        while not self.is_fed_business_day(curr):
            curr += timedelta(days=1)
        return curr

    def get_next_business_day(self, d: date) -> date:
        """Alias for next_fed_business_day."""
        return self.next_fed_business_day(d)

    def previous_fed_business_day(self, d: date) -> date:
        """Latest Federal Reserve business day strictly before date d."""
        curr = d - timedelta(days=1)
        while not self.is_fed_business_day(curr):
            curr -= timedelta(days=1)
        return curr

    def get_h15_release_timestamp(self, obs_date: date) -> datetime:
        """Compute the point-in-time H.15 availability timestamp in UTC for an observation date.

        The rate for obs_date is released at 16:15 Eastern Time on the next Federal Reserve business day.
        """
        release_date = self.next_fed_business_day(obs_date)
        et_dt = datetime(release_date.year, release_date.month, release_date.day, 16, 15, 0, tzinfo=EASTERN_TZ)
        return et_dt.astimezone(timezone.utc)


FED_H15_CALENDAR = FederalReserveH15Calendar()
