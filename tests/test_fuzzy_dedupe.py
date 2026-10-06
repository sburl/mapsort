#!/usr/bin/env python3
"""Tests for fuzzy duplicate detection utilities."""

from __future__ import annotations

import unittest

from fuzzy_dedupe import (
    cosine_similarity,
    dedupe_by_local_vector_index,
    name_similarity,
    normalize_text,
    tokenize,
)


class NormalizeTextTests(unittest.TestCase):

    def test_accented_chars(self) -> None:
        self.assertEqual(normalize_text("Cafe\u0301 Re\u0301sume\u0301"), "cafe resume")

    def test_punctuation_removed(self) -> None:
        result = normalize_text("Hello, World! #2024")
        self.assertEqual(result, "hello world 2024")

    def test_empty_string(self) -> None:
        self.assertEqual(normalize_text(""), "")

    def test_single_char_tokens_dropped(self) -> None:
        result = normalize_text("A B CD")
        self.assertEqual(result, "cd")


class TokenizeTests(unittest.TestCase):

    def test_basic(self) -> None:
        self.assertEqual(tokenize("hello world"), ("hello", "world"))

    def test_short_tokens_dropped(self) -> None:
        self.assertEqual(tokenize("I am ok"), ("am", "ok"))

    def test_empty(self) -> None:
        self.assertEqual(tokenize(""), ())


class CosineSimilarityTests(unittest.TestCase):

    def test_identical(self) -> None:
        vec = {"hello": 1, "world": 1}
        self.assertAlmostEqual(cosine_similarity(vec, vec), 1.0)

    def test_disjoint(self) -> None:
        a = {"hello": 1}
        b = {"world": 1}
        self.assertAlmostEqual(cosine_similarity(a, b), 0.0)

    def test_partial_overlap(self) -> None:
        a = {"hello": 1, "world": 1}
        b = {"hello": 1, "foo": 1}
        score = cosine_similarity(a, b)
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)

    def test_empty_left(self) -> None:
        self.assertAlmostEqual(cosine_similarity({}, {"hello": 1}), 0.0)

    def test_empty_right(self) -> None:
        self.assertAlmostEqual(cosine_similarity({"hello": 1}, {}), 0.0)


class NameSimilarityTests(unittest.TestCase):

    def test_identical(self) -> None:
        self.assertAlmostEqual(name_similarity("starbucks", "starbucks"), 1.0)

    def test_similar(self) -> None:
        score = name_similarity("starbucks coffee", "starbucks cafe")
        self.assertGreater(score, 0.5)

    def test_completely_different(self) -> None:
        score = name_similarity("starbucks", "mcdonalds")
        self.assertLess(score, 0.5)

    def test_empty_a(self) -> None:
        self.assertAlmostEqual(name_similarity("", "starbucks"), 0.0)

    def test_empty_b(self) -> None:
        self.assertAlmostEqual(name_similarity("starbucks", ""), 0.0)


class DedupeByLocalVectorIndexTests(unittest.TestCase):

    def _simple_merge(self, canonical: dict, incoming: dict) -> None:
        canonical.setdefault("merged_from", []).append(incoming.get("name"))

    def test_distinct_records_kept(self) -> None:
        records = [
            {"name": "Starbucks", "address": "123 Main St", "lat": 40.7128, "lng": -74.0060},
            {"name": "McDonalds", "address": "456 Oak Ave", "lat": 41.8781, "lng": -87.6298},
        ]
        result = dedupe_by_local_vector_index(records, self._simple_merge)
        self.assertEqual(len(result), 2)

    def test_duplicates_merged(self) -> None:
        records = [
            {"name": "Starbucks Coffee", "address": "123 Main St", "lat": 40.7128, "lng": -74.0060},
            {"name": "Starbucks Coffee", "address": "123 Main St", "lat": 40.7128, "lng": -74.0060},
        ]
        result = dedupe_by_local_vector_index(records, self._simple_merge)
        self.assertEqual(len(result), 1)
        self.assertIn("merged_from", result[0])

    def test_empty_input(self) -> None:
        result = dedupe_by_local_vector_index([], self._simple_merge)
        self.assertEqual(result, [])

    def test_single_record(self) -> None:
        records = [{"name": "Place", "lat": 0, "lng": 0}]
        result = dedupe_by_local_vector_index(records, self._simple_merge)
        self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main()
