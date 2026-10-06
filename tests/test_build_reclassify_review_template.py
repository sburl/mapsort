#!/usr/bin/env python3
"""Regression tests for manual review template generation."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import build_reclassify_review_template
from auto_reclassify_rules import load_rules


class BuildReclassifyReviewTemplateTests(unittest.TestCase):

    def test_build_template_from_json_queue(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue = Path(td) / "queue.json"
            classified = Path(td) / "places_classified.json"
            out = Path(td) / "template.csv"

            classified.write_text(
                json.dumps(
                    [
                        {
                            "id": "cid:1",
                            "name": "Place One",
                            "address": "123 St",
                            "category": 3,
                            "confidence": "low",
                        },
                    ]
                ),
                encoding="utf-8",
            )
            queue.write_text(
                json.dumps(
                    [
                        {
                            "id": "cid:1",
                            "reclassify_reasons": "low_confidence",
                            "category": 3,
                            "confidence": "low",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            count = build_reclassify_review_template.build_review_template(queue, classified, out)
            self.assertEqual(count, 1)

            with out.open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["id"], "cid:1")
            self.assertEqual(rows[0]["decision_category"], "")
            self.assertEqual(rows[0]["decision_confidence"], "")
            self.assertEqual(rows[0]["reclassify_reasons"], "low_confidence")

    def test_build_template_can_write_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue = Path(td) / "queue.json"
            classified = Path(td) / "places_classified.json"
            out = Path(td) / "template.json"

            classified.write_text("[]", encoding="utf-8")
            queue.write_text(
                json.dumps(
                    [
                        {"id": "cid:1", "reclassify_reasons": "low_confidence", "name": "A", "confidence": "low"}
                    ]
                ),
                encoding="utf-8",
            )

            count = build_reclassify_review_template.build_review_template(
                queue,
                classified,
                out,
                output_format="json",
            )
            self.assertEqual(count, 1)

            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertIsInstance(payload, list)
            self.assertEqual(payload[0]["id"], "cid:1")

    def test_build_template_auto_tag_fills_category(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue = Path(td) / "queue.json"
            classified = Path(td) / "places_classified.json"
            out = Path(td) / "template.csv"

            classified.write_text("[]", encoding="utf-8")
            queue.write_text(
                json.dumps(
                    [
                        {
                            "id": "cid:1",
                            "name": "Terminal 2 Airport",
                            "confidence": "low",
                            "reclassify_reasons": "low_confidence",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            count = build_reclassify_review_template.build_review_template(
                queue,
                classified,
                out,
                auto_tag=True,
            )
            self.assertEqual(count, 1)
            with out.open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["decision_category"], "14")

    def test_build_template_auto_tag_uses_custom_rules(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue = Path(td) / "queue.json"
            classified = Path(td) / "places_classified.json"
            out = Path(td) / "template.csv"
            rules = Path(td) / "rules.json"

            classified.write_text("[]", encoding="utf-8")
            queue.write_text(
                json.dumps(
                    [
                        {
                            "id": "cid:1",
                            "name": "Blue Lantern",
                            "confidence": "low",
                            "reclassify_reasons": "low_confidence",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            rules.write_text(
                json.dumps(
                    [{"pattern": r"\bblue lantern\b", "category": 3, "reason": "custom bar name"}]
                ),
                encoding="utf-8",
            )

            custom_rules = load_rules(rules)
            count = build_reclassify_review_template.build_review_template(
                queue,
                classified,
                out,
                auto_tag=True,
                auto_rules=custom_rules,
            )
            self.assertEqual(count, 1)
            with out.open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["decision_category"], "3")
            self.assertEqual(rows[0]["notes"], "custom bar name")

    def test_build_template_auto_tag_uses_country_pack(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue = Path(td) / "queue.json"
            classified = Path(td) / "places_classified.json"
            out = Path(td) / "template.csv"

            classified.write_text("[]", encoding="utf-8")
            queue.write_text(
                json.dumps(
                    [
                        {
                            "id": "cid:1",
                            "name": "BBQ Truck",
                            "confidence": "low",
                            "reclassify_reasons": "low_confidence",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            count = build_reclassify_review_template.build_review_template(
                queue,
                classified,
                out,
                auto_tag=True,
                auto_country="US",
            )
            self.assertEqual(count, 1)
            with out.open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["decision_category"], "1")

    def test_build_template_auto_tag_prefers_custom_over_region_rules(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue = Path(td) / "queue.json"
            classified = Path(td) / "places_classified.json"
            out = Path(td) / "template.csv"
            rules = Path(td) / "rules.json"

            classified.write_text("[]", encoding="utf-8")
            queue.write_text(
                json.dumps(
                    [
                        {
                            "id": "cid:1",
                            "name": "City Market",
                            "confidence": "low",
                            "reclassify_reasons": "low_confidence",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            rules.write_text(
                json.dumps(
                    [
                        {
                            "pattern": r"\bcity market\b",
                            "category": 3,
                            "reason": "custom market",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            custom_rules = load_rules(rules)
            count = build_reclassify_review_template.build_review_template(
                queue,
                classified,
                out,
                auto_tag=True,
                auto_rules=custom_rules,
                auto_country="US",
            )
            self.assertEqual(count, 1)
            with out.open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["decision_category"], "3")
            self.assertEqual(rows[0]["notes"], "custom market")

    def test_build_template_deduplicates_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue = Path(td) / "queue.json"
            classified = Path(td) / "places_classified.json"
            out = Path(td) / "template.csv"

            classified.write_text("[]", encoding="utf-8")
            queue.write_text(
                json.dumps(
                    [
                        {"id": "cid:1", "name": "A", "reclassify_reasons": "low_confidence"},
                        {"id": "cid:1", "name": "A", "reclassify_reasons": "low_confidence"},
                        {"id": "cid:2", "name": "B", "reclassify_reasons": "low_confidence"},
                    ]
                ),
                encoding="utf-8",
            )

            count = build_reclassify_review_template.build_review_template(queue, classified, out)
            self.assertEqual(count, 2)

            with out.open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual([row["id"] for row in rows], ["cid:1", "cid:2"])

    def test_build_template_rejects_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue = Path(td) / "queue.json"
            classified = Path(td) / "places_classified.json"
            out = Path(td) / "template.csv"

            queue.write_text("{}", encoding="utf-8")
            classified.write_text("[]", encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                "queue file JSON must be a list",
            ):
                build_reclassify_review_template.build_review_template(queue, classified, out)

    def test_build_template_skips_rows_missing_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue = Path(td) / "queue.csv"
            classified = Path(td) / "places_classified.json"
            out = Path(td) / "template.csv"

            with queue.open("w", encoding="utf-8", newline="") as f:
                f.write("id,reclassify_reasons\n")
                f.write("cid:1,low_confidence\n")
                f.write(",low_confidence\n")
                f.write("cid:2,\n")
                f.write("cid:3,low_confidence\n")

            classified.write_text(
                json.dumps(
                    [
                        {"id": "cid:1", "name": "A", "address": "123", "confidence": "low"},
                        {"id": "cid:3", "name": "C", "address": "456", "confidence": "low"},
                    ]
                ),
                encoding="utf-8",
            )

            count = build_reclassify_review_template.build_review_template(queue, classified, out)
            self.assertEqual(count, 2)

            with out.open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual([row["id"] for row in rows], ["cid:1", "cid:3"])


if __name__ == "__main__":
    unittest.main()
