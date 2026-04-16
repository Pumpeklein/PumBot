from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9 fallback
    ZoneInfo = None  # type: ignore[assignment]


DATETIME_DISPLAY_FORMAT = "%d.%m.%Y %H:%M Uhr"
DATE_DISPLAY_FORMAT = "%d.%m.%Y"


def _last_sunday(year: int, month: int) -> date:
    day = date(year, month + 1, 1) - timedelta(days=1)
    return day - timedelta(days=(day.weekday() + 1) % 7)


class _BerlinFallbackTZ(tzinfo):
    """Small Europe/Berlin fallback for Windows installs without tzdata."""

    def _is_dst_utc(self, dt: datetime) -> bool:
        start = datetime.combine(_last_sunday(dt.year, 3), time(1), tzinfo=timezone.utc)
        end = datetime.combine(_last_sunday(dt.year, 10), time(1), tzinfo=timezone.utc)
        return start <= dt.astimezone(timezone.utc) < end

    def _is_dst_local(self, dt: datetime | None) -> bool:
        if dt is None:
            return False
        naive = dt.replace(tzinfo=None)
        start = datetime.combine(_last_sunday(naive.year, 3), time(2))
        end = datetime.combine(_last_sunday(naive.year, 10), time(3))
        return start <= naive < end

    def utcoffset(self, dt: datetime | None) -> timedelta:
        return timedelta(hours=2 if self._is_dst_local(dt) else 1)

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(hours=1 if self._is_dst_local(dt) else 0)

    def tzname(self, dt: datetime | None) -> str:
        return "CEST" if self._is_dst_local(dt) else "CET"

    def fromutc(self, dt: datetime) -> datetime:
        if self._is_dst_utc(dt.replace(tzinfo=timezone.utc)):
            return (dt + timedelta(hours=2)).replace(tzinfo=self)
        return (dt + timedelta(hours=1)).replace(tzinfo=self)


def _berlin_tz() -> tzinfo:
    if ZoneInfo is not None:
        try:
            return ZoneInfo("Europe/Berlin")
        except Exception:
            pass
    return _BerlinFallbackTZ()


BERLIN_TZ = _berlin_tz()


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    return None


def _as_berlin_datetime(value: Any) -> datetime | None:
    dt = _parse_datetime(value)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BERLIN_TZ)


def format_berlin_datetime(value: Any, fallback: str = "-") -> str:
    dt = _as_berlin_datetime(value)
    if dt is None:
        return fallback
    return dt.strftime(DATETIME_DISPLAY_FORMAT)


def format_berlin_date(value: Any, fallback: str = "-") -> str:
    dt = _as_berlin_datetime(value)
    if dt is None:
        return fallback
    return dt.strftime(DATE_DISPLAY_FORMAT)


def berlin_today() -> date:
    return datetime.now(BERLIN_TZ).date()
