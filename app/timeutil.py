"""Timezone helpers.

Everything is stored naive-UTC (SQLite drops tzinfo); these convert at the
boundary between a user's local calendar day and the stored UTC instant.
"""

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def tz_or_utc(name: str | None) -> ZoneInfo:
    """The named IANA timezone, falling back to UTC for missing/invalid names."""
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def start_of_day_utc(d: date, tz_name: str | None) -> datetime:
    """Naive-UTC instant of 00:00 on local date ``d`` in timezone ``tz_name``."""
    local_dt = datetime.combine(d, time(0, 0), tzinfo=tz_or_utc(tz_name))
    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)
