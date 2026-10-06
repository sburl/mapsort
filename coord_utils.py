"""
Reusable coordinate parsing and validation helpers.
"""

import math
from math import isfinite


def _coerce_float(value) -> float | None:
    """Coerce a coordinate-like value to float, returning None on failure."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isfinite(value):
            return float(value)
        return None
    try:
        text = str(value).strip()
    except Exception:  # noqa: BLE001 - any __str__ may raise; the value is simply unusable
        return None
    if not text:
        return None
    try:
        value_f = float(text)
    except ValueError:
        return None
    return value_f if isfinite(value_f) else None


def coord_distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Haversine distance in km between two (lat, lng) pairs."""
    lat1, lng1 = a
    lat2, lng2 = b
    lat_delta = math.radians(lat2 - lat1)
    lng_delta = math.radians(lng2 - lng1)
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    h = (
        math.sin(lat_delta / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(lng_delta / 2) ** 2
    )
    return 2 * 6_371.0 * math.asin(min(1.0, math.sqrt(h)))


def has_coordinates(lat, lng, *, disallow_origin: bool = True) -> bool:
    """Return True when both coordinates parse to finite floats."""
    if lat is None or lng is None:
        return False
    lat_f = _coerce_float(lat)
    lng_f = _coerce_float(lng)
    if lat_f is None or lng_f is None:
        return False
    return not (disallow_origin and lat_f == 0.0 and lng_f == 0.0)


def parse_coordinate_pair(lat, lng, *, disallow_origin: bool = True) -> tuple[float, float] | None:
    """Return (lat, lng) when both values are valid, otherwise None."""
    if not has_coordinates(lat, lng, disallow_origin=disallow_origin):
        return None
    lat_f = _coerce_float(lat)
    lng_f = _coerce_float(lng)
    if lat_f is None or lng_f is None:
        return None
    return lat_f, lng_f
