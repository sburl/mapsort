"""Shared datetime helpers for UTC parsing and formatting."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_DATETIME_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
)


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    """Return `dt` in UTC, or `None` when no input is given."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def format_utc_iso(dt: datetime | None = None, *, timespec: str = "seconds") -> str:
    """Format a datetime as UTC Z-suffixed ISO-8601."""
    normalized = as_utc(dt or utc_now())
    if normalized is None:
        normalized = utc_now()
    return normalized.isoformat(timespec=timespec).replace("+00:00", "Z")


def parse_iso_datetime(raw: Any) -> datetime | None:
    """Parse ISO-like timestamps into a timezone-aware datetime."""
    if raw is None:
        return None

    text = str(raw).strip()
    if not text:
        return None

    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    for fmt in _DATETIME_FORMATS:
        try:
            dt = datetime.strptime(candidate, fmt)  # noqa: DTZ007 - UTC attached below
        except ValueError:
            continue
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None

    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def days_since(date_value: Any, now: datetime | None = None) -> int | None:
    """Return non-negative day delta since `date_value`."""
    parsed = parse_iso_datetime(date_value)
    if parsed is None:
        return None

    reference = as_utc(now or utc_now())
    if reference is None:
        reference = utc_now()

    delta_days = int((reference - parsed).total_seconds() // 86400)
    return max(0, delta_days)
