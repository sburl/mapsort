#!/usr/bin/env python3
"""Tests for coordinate parsing and validation helpers."""

from __future__ import annotations

import math
import unittest

from coord_utils import (
    _coerce_float,
    coord_distance_km,
    has_coordinates,
    parse_coordinate_pair,
)


class CoerceFloatTests(unittest.TestCase):

    def test_none(self) -> None:
        self.assertIsNone(_coerce_float(None))

    def test_bool_true(self) -> None:
        self.assertIsNone(_coerce_float(True))

    def test_bool_false(self) -> None:
        self.assertIsNone(_coerce_float(False))

    def test_int(self) -> None:
        self.assertEqual(_coerce_float(42), 42.0)

    def test_float(self) -> None:
        self.assertEqual(_coerce_float(3.14), 3.14)

    def test_string_number(self) -> None:
        self.assertEqual(_coerce_float("  51.5  "), 51.5)

    def test_nan(self) -> None:
        self.assertIsNone(_coerce_float(float("nan")))

    def test_inf(self) -> None:
        self.assertIsNone(_coerce_float(float("inf")))

    def test_negative_inf(self) -> None:
        self.assertIsNone(_coerce_float(float("-inf")))

    def test_empty_string(self) -> None:
        self.assertIsNone(_coerce_float(""))

    def test_whitespace_string(self) -> None:
        self.assertIsNone(_coerce_float("   "))

    def test_garbage_string(self) -> None:
        self.assertIsNone(_coerce_float("not-a-number"))


class HasCoordinatesTests(unittest.TestCase):

    def test_valid_pair(self) -> None:
        self.assertTrue(has_coordinates(51.5, -0.12))

    def test_none_lat(self) -> None:
        self.assertFalse(has_coordinates(None, -0.12))

    def test_none_lng(self) -> None:
        self.assertFalse(has_coordinates(51.5, None))

    def test_origin_disallowed_by_default(self) -> None:
        self.assertFalse(has_coordinates(0.0, 0.0))

    def test_origin_allowed(self) -> None:
        self.assertTrue(has_coordinates(0.0, 0.0, disallow_origin=False))

    def test_string_coords(self) -> None:
        self.assertTrue(has_coordinates("48.8566", "2.3522"))


class ParseCoordinatePairTests(unittest.TestCase):

    def test_valid_pair(self) -> None:
        self.assertEqual(parse_coordinate_pair(48.8566, 2.3522), (48.8566, 2.3522))

    def test_none_returns_none(self) -> None:
        self.assertIsNone(parse_coordinate_pair(None, 2.3522))

    def test_origin_disallowed(self) -> None:
        self.assertIsNone(parse_coordinate_pair(0, 0))

    def test_origin_allowed(self) -> None:
        self.assertEqual(parse_coordinate_pair(0, 0, disallow_origin=False), (0.0, 0.0))

    def test_string_coords(self) -> None:
        self.assertEqual(parse_coordinate_pair("51.5", "-0.12"), (51.5, -0.12))

    def test_garbage_returns_none(self) -> None:
        self.assertIsNone(parse_coordinate_pair("abc", "def"))


class CoordDistanceKmTests(unittest.TestCase):

    def test_london_to_paris(self) -> None:
        london = (51.5074, -0.1278)
        paris = (48.8566, 2.3522)
        dist = coord_distance_km(london, paris)
        self.assertAlmostEqual(dist, 343.0, delta=5.0)

    def test_same_point(self) -> None:
        point = (40.7128, -74.0060)
        self.assertAlmostEqual(coord_distance_km(point, point), 0.0, places=5)

    def test_antipodal(self) -> None:
        dist = coord_distance_km((0, 0), (0, 180))
        expected = math.pi * 6371.0
        self.assertAlmostEqual(dist, expected, delta=1.0)


if __name__ == "__main__":
    unittest.main()
