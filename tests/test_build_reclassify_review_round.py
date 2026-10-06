#!/usr/bin/env python3
"""Regression tests for full reclassify review round generation."""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import build_reclassify_review_round as build_reclassify_review_round_module
from auto_reclassify_rules import load_rules
from build_reclassify_review_round import build_reclassify_review_round
from reclassify_queue import RECLASSIFY_FIELDNAMES


class BuildReclassifyReviewRoundTests(unittest.TestCase):

    def test_build_review_round_writes_queue_and_template(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            classified = Path(td) / "places_classified.json"
            low_conf = Path(td) / "low_confidence_review.json"
            queue = Path(td) / "reclassification_queue.json"
            template = Path(td) / "template.csv"
            review_ui = Path(td) / "review-ui.html"

            classified.write_text(
                json.dumps(
                    [
                        {
                            "id": "cid:1",
                            "name": "Cafe Blue",
                            "address": "100 Main",
                            "category": 1,
                            "confidence": "low",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            low_conf.write_text(
                json.dumps([{"id": "cid:1"}]),
                encoding="utf-8",
            )

            queue_count, template_count = build_reclassify_review_round(
                classified_path=classified,
                low_confidence_path=low_conf,
                queue_output=queue,
                template_output=template,
                build_ui=True,
                ui_output=review_ui,
                ui_title="Round Review",
            )

            self.assertEqual(queue_count, 1)
            self.assertEqual(template_count, 1)
            self.assertTrue(queue.exists())
            self.assertTrue(template.exists())
            self.assertTrue(review_ui.exists())

            with template.open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["id"], "cid:1")
            self.assertEqual(rows[0]["decision_category"], "")

            html = review_ui.read_text(encoding="utf-8")
            self.assertIn("Round Review", html)

    def test_build_review_round_with_auto_tag_and_custom_rules(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            classified = Path(td) / "places_classified.json"
            low_conf = Path(td) / "low_confidence_review.json"
            queue = Path(td) / "reclassification_queue.csv"
            template = Path(td) / "template.csv"
            rules = Path(td) / "rules.json"

            classified.write_text(
                json.dumps(
                    [
                        {
                            "id": "cid:2",
                            "name": "Blue Lantern",
                            "confidence": "low",
                            "reclassify_reasons": "low_confidence",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            low_conf.write_text(
                json.dumps(
                    [
                        {
                            "id": "cid:2",
                            "name": "Blue Lantern",
                            "confidence": "low",
                            "reclassify_reasons": "low_confidence",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            rules.write_text(
                json.dumps([{"pattern": r"\bblue lantern\b", "category": 3, "reason": "bars"}]),
                encoding="utf-8",
            )

            custom_rules = load_rules(rules)
            queue_count, template_count = build_reclassify_review_round(
                classified_path=classified,
                low_confidence_path=low_conf,
                queue_output=queue,
                template_output=template,
                queue_output_format="csv",
                auto_tag=True,
                auto_rules=custom_rules,
                include_stale=False,
            )

            self.assertEqual(queue_count, 1)
            self.assertEqual(template_count, 1)
            self.assertTrue(queue.suffix == ".csv")

            with template.open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["decision_category"], "3")
            self.assertEqual(rows[0]["notes"], "bars")

    def test_build_review_round_auto_tag_combines_custom_and_region_rules(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            classified = Path(td) / "places_classified.json"
            low_conf = Path(td) / "low_confidence_review.json"
            queue = Path(td) / "reclassification_queue.csv"
            template = Path(td) / "template.csv"
            rules = Path(td) / "rules.json"

            classified.write_text(
                json.dumps(
                    [
                        {
                            "id": "cid:5",
                            "name": "City Market",
                            "confidence": "low",
                            "reclassify_reasons": "low_confidence",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            low_conf.write_text(
                json.dumps(
                    [
                        {
                            "id": "cid:5",
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
                    [{"pattern": r"\bcity market\b", "category": 3, "reason": "custom market"}]
                ),
                encoding="utf-8",
            )

            custom_rules = load_rules(rules)
            queue_count, template_count = build_reclassify_review_round(
                classified_path=classified,
                low_confidence_path=low_conf,
                queue_output=queue,
                template_output=template,
                queue_output_format="csv",
                auto_tag=True,
                auto_rules=custom_rules,
                auto_country="US",
                include_stale=False,
            )

            self.assertEqual(queue_count, 1)
            self.assertEqual(template_count, 1)
            with template.open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["decision_category"], "3")
            self.assertEqual(rows[0]["notes"], "custom market")

    def test_build_review_round_with_region_auto_tag_pack(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            classified = Path(td) / "places_classified.json"
            low_conf = Path(td) / "low_confidence_review.json"
            queue = Path(td) / "reclassification_queue.csv"
            template = Path(td) / "template.csv"

            classified.write_text(
                json.dumps(
                    [
                        {
                            "id": "cid:4",
                            "name": "Craft Market",
                            "confidence": "low",
                            "reclassify_reasons": "low_confidence",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            low_conf.write_text(
                json.dumps(
                    [
                        {
                            "id": "cid:4",
                            "name": "Craft Market",
                            "confidence": "low",
                            "reclassify_reasons": "low_confidence",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            queue_count, template_count = build_reclassify_review_round(
                classified_path=classified,
                low_confidence_path=low_conf,
                queue_output=queue,
                template_output=template,
                queue_output_format="csv",
                auto_tag=True,
                auto_travel_plan="city break",
                include_stale=False,
            )

            self.assertEqual(queue_count, 1)
            self.assertEqual(template_count, 1)

            with template.open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["decision_category"], "9")

    def test_build_review_round_supports_template_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            classified = Path(td) / "places_classified.json"
            low_conf = Path(td) / "low_confidence_review.json"
            queue = Path(td) / "reclassification_queue.csv"
            template = Path(td) / "template.json"

            low_conf.write_text(
                json.dumps(
                    [
                        {"id": "cid:3", "name": "Blue Note", "confidence": "low", "reclassify_reasons": "low_confidence"}
                    ]
                ),
                encoding="utf-8",
            )

            classified.write_text(
                json.dumps(
                    [
                        {
                            "id": "cid:3",
                            "name": "Blue Note",
                            "confidence": "low",
                            "reclassify_reasons": "low_confidence",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            queue_count, template_count = build_reclassify_review_round(
                classified_path=classified,
                low_confidence_path=low_conf,
                queue_output=queue,
                template_output=template,
                queue_output_format="csv",
                template_output_format="json",
                include_stale=False,
            )

            self.assertEqual(queue_count, 1)
            self.assertEqual(template_count, 1)
            with queue.open(encoding="utf-8", newline="") as f:
                rows = list(csv.reader(f))
            self.assertEqual(rows[0], list(RECLASSIFY_FIELDNAMES))
            self.assertEqual(len(rows), 2)

            payload = json.loads(template.read_text(encoding="utf-8"))
            self.assertIsInstance(payload, list)
            self.assertEqual(payload[0]["id"], "cid:3")

    def test_build_review_round_main_invalid_rule_file_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            from build_reclassify_review_round import main

            classified = Path(td) / "places_classified.json"
            low_conf = Path(td) / "low_confidence_review.json"
            queue = Path(td) / "queue.json"
            template = Path(td) / "template.csv"
            rules = Path(td) / "rules.json"

            classified.write_text("[]", encoding="utf-8")
            low_conf.write_text("[]", encoding="utf-8")
            rules.write_text("{}", encoding="utf-8")

            self.assertEqual(
                main(
                    [
                        "--classified",
                        str(classified),
                        "--low-confidence",
                        str(low_conf),
                        "--queue",
                        str(queue),
                        "--template",
                        str(template),
                        "--auto-tag",
                        "--rule-file",
                        str(rules),
                    ]
                ),
                2,
            )

    def test_build_review_round_json_template_with_build_ui_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            classified = Path(td) / "places_classified.json"
            low_conf = Path(td) / "low_confidence_review.json"
            queue = Path(td) / "queue.csv"
            template = Path(td) / "template.json"
            ui = Path(td) / "review.html"

            classified.write_text(
                json.dumps([{"id": "cid:1", "name": "A", "confidence": "low"}]),
                encoding="utf-8",
            )
            low_conf.write_text(
                json.dumps([{"id": "cid:1", "name": "A", "confidence": "low", "reclassify_reasons": "low_confidence"}]),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "build_ui requires template output in CSV format"):
                build_reclassify_review_round(
                    classified_path=classified,
                    low_confidence_path=low_conf,
                    queue_output=queue,
                    template_output=template,
                    queue_output_format="csv",
                    template_output_format="json",
                    build_ui=True,
                    ui_output=ui,
                )

    def test_build_review_round_main_supports_queue_priority(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            classified = Path(td) / "places_classified.json"
            low_conf = Path(td) / "low_confidence_review.json"
            queue = Path(td) / "queue.csv"
            template = Path(td) / "template.csv"

            classified.write_text(
                json.dumps(
                    [
                        {"id": "cid:new", "name": "New", "confidence": "high", "date": "2026-03-03"},
                        {"id": "cid:old", "name": "Old", "confidence": "high", "date": "2024-01-01"},
                    ]
                ),
                encoding="utf-8",
            )
            low_conf.write_text("[]", encoding="utf-8")

            fixed_now = datetime.fromisoformat("2026-03-04T00:00:00+00:00")
            with patch("reclassify_queue.utc_now", return_value=fixed_now):
                self.assertEqual(
                    build_reclassify_review_round_module.main([
                        "--classified", str(classified),
                        "--low-confidence", str(low_conf),
                        "--queue", str(queue),
                        "--template", str(template),
                        "--queue-format", "csv",
                        "--no-low-confidence",
                        "--include-stale",
                        "--stale-days", "1",
                        "--priority", "oldest",
                    ]),
                    0,
                )

            with queue.open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual([row["id"] for row in rows], ["cid:old", "cid:new"])

    def test_build_review_round_main_triggers_low_confidence_notification(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            classified = Path(td) / "places_classified.json"
            low_conf = Path(td) / "low_confidence_review.json"
            queue = Path(td) / "queue.json"
            template = Path(td) / "template.csv"
            hook_output = Path(td) / "hook.json"
            hook = Path(td) / "notify_hook.py"

            hook.write_text(
                """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

payload = json.load(sys.stdin)
Path(sys.argv[1]).write_text(json.dumps(payload), encoding=\"utf-8\")
""",
                encoding="utf-8",
            )
            os.chmod(hook, 0o755)

            classified.write_text(
                json.dumps(
                    [
                        {"id": "cid:1", "name": "A", "confidence": "low", "date": "2026-01-01"},
                        {"id": "cid:2", "name": "B", "confidence": "low", "date": "2026-01-01"},
                    ]
                ),
                encoding="utf-8",
            )
            low_conf.write_text(
                json.dumps(
                    [
                        {"id": "cid:1", "name": "A", "confidence": "low"},
                        {"id": "cid:2", "name": "B", "confidence": "low"},
                    ]
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                build_reclassify_review_round_module.main([
                    "--classified", str(classified),
                    "--low-confidence", str(low_conf),
                    "--queue", str(queue),
                    "--template", str(template),
                    "--notify-threshold", "1",
                    "--notify-command", f"{sys.executable} {hook} {hook_output}",
                ]),
                0,
            )

            payload = json.loads(hook_output.read_text(encoding="utf-8"))
            self.assertEqual(payload["low_confidence_backlog"], 2)


if __name__ == "__main__":
    unittest.main()
