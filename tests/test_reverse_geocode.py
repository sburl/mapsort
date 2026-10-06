#!/usr/bin/env python3
"""Tests for reverse_geocode.py."""

import unittest
from unittest.mock import patch

from reverse_geocode import extract_place_info, resolve_coords_only


class TestExtractPlaceInfo(unittest.TestCase):
    def test_poi_returns_name(self):
        result = {
            "name": "Eiffel Tower",
            "display_name": "Eiffel Tower, Champ de Mars, Paris, France",
            "category": "tourism",
            "type": "attraction",
        }
        name, address = extract_place_info(result)
        self.assertEqual(name, "Eiffel Tower")
        self.assertIn("Paris", address)

    def test_residential_road_no_name(self):
        result = {
            "name": "Lily Street",
            "display_name": "360 Lily St, San Francisco, CA 94102, USA",
            "category": "highway",
            "type": "residential",
        }
        name, address = extract_place_info(result)
        self.assertEqual(name, "")
        self.assertIn("360 Lily St", address)

    def test_city_returns_name(self):
        result = {
            "name": "Paris",
            "display_name": "Paris, Île-de-France, France",
            "category": "place",
            "type": "city",
        }
        name, _address = extract_place_info(result)
        self.assertEqual(name, "Paris")

    def test_empty_name(self):
        result = {
            "name": "",
            "display_name": "Some Street, Some City",
            "category": "highway",
            "type": "tertiary",
        }
        name, address = extract_place_info(result)
        self.assertEqual(name, "")
        self.assertEqual(address, "Some Street, Some City")


class TestResolveCoordsOnly(unittest.TestCase):
    def test_dry_run_counts_only(self):
        records = [
            {"name": "", "address": "", "lat": 48.8584, "lng": 2.2945, "status": "q_coords_only"},
            {"name": "Starbucks", "address": "123 Main St", "lat": 0, "lng": 0, "status": "named"},
        ]
        result = resolve_coords_only(records, dry_run=True)
        self.assertEqual(result["resolved"], 1)
        self.assertEqual(result["skipped"], 1)

    @patch("reverse_geocode.reverse_geocode")
    def test_successful_resolution(self, mock_geocode):
        mock_geocode.return_value = {
            "name": "Eiffel Tower",
            "display_name": "Eiffel Tower, Champ de Mars, Paris, France",
            "category": "tourism",
            "type": "attraction",
        }
        records = [
            {"name": "", "address": "", "lat": 48.8584, "lng": 2.2945, "status": "q_coords_only"},
        ]
        result = resolve_coords_only(records, delay=0)
        self.assertEqual(result["resolved"], 1)
        self.assertEqual(records[0]["name"], "Eiffel Tower")
        self.assertEqual(records[0]["status"], "named")

    @patch("reverse_geocode.reverse_geocode")
    def test_failed_resolution_flags_record(self, mock_geocode):
        mock_geocode.return_value = None
        records = [
            {"name": "", "address": "", "lat": 48.8584, "lng": 2.2945, "status": "q_coords_only"},
        ]
        result = resolve_coords_only(records, delay=0)
        self.assertEqual(result["failed"], 1)
        self.assertTrue(records[0].get("_geocode_failed"))

    @patch("reverse_geocode.reverse_geocode")
    def test_road_resolution_sets_address_only(self, mock_geocode):
        mock_geocode.return_value = {
            "name": "Some Road",
            "display_name": "123 Some Road, City, Country",
            "category": "highway",
            "type": "residential",
        }
        records = [
            {"name": "", "address": "", "lat": 40.0, "lng": -74.0, "status": "q_coords_only"},
        ]
        result = resolve_coords_only(records, delay=0)
        self.assertEqual(result["resolved"], 1)
        self.assertEqual(records[0]["name"], "")
        self.assertEqual(records[0]["status"], "q_with_address")
        self.assertIn("123 Some Road", records[0]["address"])

    def test_skips_named_records(self):
        records = [
            {"name": "Starbucks", "address": "123 Main St", "lat": 47.6, "lng": -122.3, "status": "named"},
        ]
        result = resolve_coords_only(records, dry_run=True)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["resolved"], 0)


if __name__ == "__main__":
    unittest.main()
