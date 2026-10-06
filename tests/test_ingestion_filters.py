#!/usr/bin/env python3
"""Tests for ingestion_filters.py."""

import unittest

from ingestion_filters import (
    classify_bare_address,
    is_bare_address,
    is_coords_only,
    is_residential_address,
    run_filters,
    triage_record,
)


class TestIsResidentialAddress(unittest.TestCase):
    def test_us_street_address(self):
        self.assertTrue(is_residential_address("360 Lily St, San Francisco, CA 94102"))

    def test_us_with_unit(self):
        self.assertTrue(is_residential_address("1475 Mecaslin St NW #7307, Atlanta, GA 30309"))

    def test_apartment(self):
        self.assertTrue(is_residential_address("27 W 16th St #3e, New York, NY 10011"))

    def test_suite(self):
        self.assertTrue(is_residential_address("5555 Oakbrook Pkwy Suite 200, Norcross, GA 30093"))

    def test_named_place_not_residential(self):
        self.assertFalse(is_residential_address("Carmel Beach, California, United States"))

    def test_city_not_residential(self):
        self.assertFalse(is_residential_address("Singapore"))

    def test_mountain_not_residential(self):
        self.assertFalse(is_residential_address("Mount Fuji, Shizuoka, Japan"))

    def test_empty(self):
        self.assertFalse(is_residential_address(""))

    def test_place_keyword_overrides_intl_pattern(self):
        self.assertFalse(is_residential_address("4 Fort Mason, San Francisco, CA 94123"))


class TestIsBareAddress(unittest.TestCase):
    def test_named_not_bare(self):
        self.assertFalse(is_bare_address("Starbucks", "123 Main St"))

    def test_empty_name_is_bare(self):
        self.assertTrue(is_bare_address("", "123 Main St"))

    def test_whitespace_name_is_bare(self):
        self.assertTrue(is_bare_address("   ", "123 Main St"))

    def test_no_address_not_bare(self):
        self.assertFalse(is_bare_address("", ""))


class TestIsCoordsOnly(unittest.TestCase):
    def test_coords_only(self):
        self.assertTrue(is_coords_only("", "", 35.749, 139.850))

    def test_has_name_not_coords_only(self):
        self.assertFalse(is_coords_only("Place", "", 35.749, 139.850))

    def test_zero_coords_with_no_info(self):
        self.assertFalse(is_coords_only("", "", 0, 0))


class TestClassifyBareAddress(unittest.TestCase):
    def test_beach(self):
        cat, reason = classify_bare_address("Carmel Beach, California")
        self.assertEqual(cat, 8)
        self.assertIn("nature", reason)

    def test_mountain(self):
        cat, _reason = classify_bare_address("Mount Washington, NH")
        self.assertEqual(cat, 8)

    def test_falls(self):
        cat, _reason = classify_bare_address("Alamere Falls, CA")
        self.assertEqual(cat, 8)

    def test_airport(self):
        cat, _reason = classify_bare_address("NAIA Terminal 3, Manila")
        self.assertEqual(cat, 14)

    def test_market(self):
        cat, _reason = classify_bare_address("Carmel Market, Tel Aviv")
        self.assertEqual(cat, 11)

    def test_square(self):
        cat, _reason = classify_bare_address("Queen Square, Bath, UK")
        self.assertEqual(cat, 4)

    def test_church(self):
        cat, _reason = classify_bare_address("Grace Cathedral, San Francisco")
        self.assertEqual(cat, 9)

    def test_no_match(self):
        cat, _reason = classify_bare_address("Singapore")
        self.assertIsNone(cat)

    def test_park(self):
        cat, _reason = classify_bare_address("Central Park, New York")
        self.assertEqual(cat, 10)

    def test_volcano(self):
        cat, _reason = classify_bare_address("Taal Volcano, Philippines")
        self.assertEqual(cat, 8)


class TestTriageRecord(unittest.TestCase):
    def _make(self, name="", address="", lat=0, lng=0, status="named"):
        return {"name": name, "address": address, "lat": lat, "lng": lng, "status": status}

    def test_named_place_kept(self):
        self.assertEqual(triage_record(self._make(name="Starbucks")), "keep")

    def test_coords_only(self):
        self.assertEqual(triage_record(self._make(lat=35.0, lng=139.0)), "coords")

    def test_residential_skipped(self):
        self.assertEqual(
            triage_record(self._make(address="360 Lily St, San Francisco, CA 94102")),
            "skip",
        )

    def test_classifiable_address(self):
        self.assertEqual(
            triage_record(self._make(address="Carmel Beach, California")),
            "classify",
        )

    def test_ambiguous_address_review(self):
        self.assertEqual(
            triage_record(self._make(address="Singapore")),
            "review",
        )


class TestRunFilters(unittest.TestCase):
    def test_nothing_dropped(self):
        records = [
            {"name": "Starbucks", "address": "123 Main St", "lat": 0, "lng": 0, "sources": ["a"]},
            {"name": "", "address": "360 Lily St, San Francisco, CA 94102", "lat": 0, "lng": 0, "sources": ["a"]},
            {"name": "", "address": "Carmel Beach, CA", "lat": 0, "lng": 0, "sources": ["a"]},
            {"name": "", "address": "", "lat": 35.0, "lng": 139.0, "sources": ["a"]},
        ]
        result = run_filters(records)
        self.assertEqual(result["stats"]["input"], 4)
        # All 4 kept — nothing is dropped, only flagged
        self.assertEqual(result["stats"]["output"], 4)

    def test_residential_flagged_not_dropped(self):
        records = [
            {"name": "", "address": "360 Lily St, San Francisco, CA 94102", "lat": 0, "lng": 0, "sources": ["a"]},
        ]
        result = run_filters(records)
        self.assertEqual(result["stats"]["output"], 1)
        self.assertEqual(result["filtered"][0]["_triage"], "skip")
        self.assertEqual(result["filtered"][0]["_flag"], "residential_address")

    def test_coords_flagged_not_dropped(self):
        records = [
            {"name": "", "address": "", "lat": 35.0, "lng": 139.0, "sources": ["a"]},
        ]
        result = run_filters(records)
        self.assertEqual(result["stats"]["output"], 1)
        self.assertEqual(result["filtered"][0]["_triage"], "coords")
        self.assertEqual(result["filtered"][0]["_flag"], "needs_reverse_geocode")

    def test_dedup(self):
        records = [
            {"name": "Pike Place Market", "address": "Seattle, WA", "lat": 47.6, "lng": -122.3, "sources": ["a"]},
            {"name": "Pike Place Market", "address": "Seattle, WA", "lat": 47.6, "lng": -122.3, "sources": ["b"]},
        ]
        result = run_filters(records)
        self.assertEqual(result["stats"]["output"], 1)
        self.assertEqual(result["stats"]["deduped"], 1)
        # Sources should be merged
        self.assertIn("a", result["filtered"][0]["sources"])
        self.assertIn("b", result["filtered"][0]["sources"])

    def test_auto_classify(self):
        records = [
            {"name": "", "address": "Mount Washington, NH 03846", "lat": 0, "lng": 0, "sources": ["a"]},
        ]
        result = run_filters(records)
        filtered = result["filtered"]
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["category"], 8)
        self.assertEqual(filtered[0]["confidence"], "low")


if __name__ == "__main__":
    unittest.main()
