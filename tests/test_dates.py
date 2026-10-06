#!/usr/bin/env python3
"""Tests for shared datetime helpers."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from dates import as_utc, days_since, format_utc_iso, parse_iso_datetime, utc_now


class UtcNowTests(unittest.TestCase):

    def test_returns_aware_datetime(self) -> None:
        now = utc_now()
        self.assertIsNotNone(now.tzinfo)
        self.assertEqual(now.tzinfo, timezone.utc)


class AsUtcTests(unittest.TestCase):

    def test_none(self) -> None:
        self.assertIsNone(as_utc(None))

    def test_naive_datetime(self) -> None:
        naive = datetime(2024, 1, 15, 12, 0, 0)  # noqa: DTZ001 - naive input is the point
        result = as_utc(naive)
        self.assertIsNotNone(result)
        self.assertEqual(result.tzinfo, timezone.utc)
        self.assertEqual(result.hour, 12)

    def test_aware_datetime_different_tz(self) -> None:
        eastern = timezone(timedelta(hours=-5))
        aware = datetime(2024, 1, 15, 12, 0, 0, tzinfo=eastern)
        result = as_utc(aware)
        self.assertIsNotNone(result)
        self.assertEqual(result.tzinfo, timezone.utc)
        self.assertEqual(result.hour, 17)


class FormatUtcIsoTests(unittest.TestCase):

    def test_produces_z_suffix(self) -> None:
        dt = datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        result = format_utc_iso(dt)
        self.assertTrue(result.endswith("Z"))
        self.assertNotIn("+00:00", result)

    def test_specific_value(self) -> None:
        dt = datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        self.assertEqual(format_utc_iso(dt), "2024-06-15T10:30:00Z")

    def test_none_returns_current_time_string(self) -> None:
        result = format_utc_iso(None)
        self.assertTrue(result.endswith("Z"))
        self.assertGreater(len(result), 10)


class ParseIsoDatetimeTests(unittest.TestCase):

    def test_z_suffix(self) -> None:
        dt = parse_iso_datetime("2024-06-15T10:30:00Z")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2024)
        self.assertEqual(dt.month, 6)
        self.assertEqual(dt.hour, 10)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_offset_format(self) -> None:
        dt = parse_iso_datetime("2024-06-15T10:30:00+00:00")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.hour, 10)

    def test_date_only(self) -> None:
        dt = parse_iso_datetime("2024-06-15")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2024)
        self.assertEqual(dt.month, 6)
        self.assertEqual(dt.day, 15)

    def test_space_separated(self) -> None:
        dt = parse_iso_datetime("2024-06-15 10:30:00")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.hour, 10)

    def test_with_microseconds(self) -> None:
        dt = parse_iso_datetime("2024-06-15T10:30:00.123456+00:00")
        self.assertIsNotNone(dt)

    def test_none(self) -> None:
        self.assertIsNone(parse_iso_datetime(None))

    def test_empty_string(self) -> None:
        self.assertIsNone(parse_iso_datetime(""))

    def test_garbage(self) -> None:
        self.assertIsNone(parse_iso_datetime("not-a-date"))


class DaysSinceTests(unittest.TestCase):

    def test_known_date(self) -> None:
        reference = datetime(2024, 6, 20, 12, 0, 0, tzinfo=timezone.utc)
        result = days_since("2024-06-15", now=reference)
        self.assertEqual(result, 5)

    def test_none_input(self) -> None:
        self.assertIsNone(days_since(None))

    def test_future_date_returns_zero(self) -> None:
        reference = datetime(2024, 6, 10, 12, 0, 0, tzinfo=timezone.utc)
        result = days_since("2024-06-15", now=reference)
        self.assertEqual(result, 0)

    def test_garbage_returns_none(self) -> None:
        self.assertIsNone(days_since("not-a-date"))


if __name__ == "__main__":
    unittest.main()
