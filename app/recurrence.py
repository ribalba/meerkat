"""Date math for recurring tasks.

The cadence fires at the start of the chosen day in the owner's timezone; we
return that instant as a naive-UTC datetime (matching how everything is stored).
"""

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

from .models import RepeatFreq
from .timeutil import start_of_day_utc, tz_or_utc


def _first_on_or_after(
    freq: str, dow: int, dom: int, moy: int, start: date
) -> date:
    """First date >= ``start`` matching the cadence."""
    if freq == RepeatFreq.daily.value:
        return start
    if freq == RepeatFreq.weekly.value:
        # date.weekday(): Monday=0 .. Sunday=6, matching our day_of_week encoding.
        return start + timedelta(days=(dow - start.weekday()) % 7)
    if freq == RepeatFreq.monthly.value:
        y, m = start.year, start.month
        for _ in range(13):
            cand = date(y, m, min(dom, monthrange(y, m)[1]))
            if cand >= start:
                return cand
            m += 1
            if m > 12:
                m, y = 1, y + 1
        return start
    if freq == RepeatFreq.yearly.value:
        y = start.year
        for _ in range(2):
            cand = date(y, moy, min(dom, monthrange(y, moy)[1]))
            if cand >= start:
                return cand
            y += 1
        return start
    return start


def compute_next_run(
    freq: str,
    day_of_week: int | None,
    day_of_month: int | None,
    month_of_year: int | None,
    tz_name: str | None,
    after_utc: datetime,
) -> datetime:
    """Naive-UTC instant of the first cadence fire strictly after ``after_utc``.

    Fires at 00:00 on the matching local date in the owner's timezone.
    """
    tz = tz_or_utc(tz_name)
    dow = day_of_week if day_of_week is not None else 0
    dom = day_of_month if day_of_month is not None else 1
    moy = month_of_year if month_of_year is not None else 1

    start = after_utc.replace(tzinfo=timezone.utc).astimezone(tz).date()
    for _ in range(450):  # bounded; at most a couple of iterations in practice
        cand_date = _first_on_or_after(freq, dow, dom, moy, start)
        cand_utc = start_of_day_utc(cand_date, tz_name)
        if cand_utc > after_utc:
            return cand_utc
        start = cand_date + timedelta(days=1)
    # Should be unreachable for valid cadences; fall back to a day later.
    return after_utc + timedelta(days=1)
