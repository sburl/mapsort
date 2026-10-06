#!/usr/bin/env python3
"""Regression tests for reclassification queue builder."""

from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import reclassify_queue


class ReclassifyQueueTests(unittest.TestCase):

    def test_build_queue_uses_low_confidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            classified = Path(td) / "places_classified.json"
            low_conf = Path(td) / "low_confidence_review.json"

            classified.write_text(
                json.dumps(
                    [
                        {"id": "cid:1", "name": "A", "confidence": "high", "date": "2026-01-01"},
                        {"id": "cid:2", "name": "B", "confidence": "high", "date": "2026-01-01"},
                        {"id": "cid:3", "name": "C", "confidence": "low", "date": "2026-01-01"},
                    ]
                ),
                encoding="utf-8",
            )
            low_conf.write_text(
                json.dumps([{"id": "cid:1"}]),
                encoding="utf-8",
            )

            queue = reclassify_queue.build_reclassify_queue(
                classified,
                low_conf,
                include_low_confidence=True,
                include_stale=False,
            )

            self.assertEqual(len(queue), 2)
            queue_ids = {row["id"] for row in queue}
            self.assertEqual(queue_ids, {"cid:1", "cid:3"})
            self.assertTrue(all("low_confidence" in row["reclassify_reasons"] for row in queue))
            self.assertEqual({row["date"] for row in queue}, {"2026-01-01"})

    def test_build_queue_explain_fields_show_similarity_match(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            classified = Path(td) / "places_classified.json"
            low_conf = Path(td) / "low_confidence_review.json"

            classified.write_text(
                json.dumps(
                    [
                        {
                            "id": "cid:1",
                            "name": "Bluebird Cafe",
                            "address": "100 Main Street",
                            "confidence": "low",
                            "lat": "37.7749",
                            "lng": "-122.4194",
                        },
                        {
                            "id": "cid:2",
                            "name": "Blue Bird Café",
                            "address": "100 Main St.",
                            "confidence": "high",
                            "lat": "37.7750",
                            "lng": "-122.4195",
                        },
                        {
                            "id": "cid:3",
                            "name": "Distant Place",
                            "address": "789 Faraway Ave",
                            "confidence": "low",
                            "lat": "47.6062",
                            "lng": "-122.3321",
                        },
                    ]
                ),
                encoding="utf-8",
            )
            low_conf.write_text("[]", encoding="utf-8")

            queue = reclassify_queue.build_reclassify_queue(
                classified,
                low_conf,
                include_low_confidence=True,
                include_stale=False,
            )

            rows_by_id = {row["id"]: row for row in queue}
            self.assertIn("cid:1", rows_by_id)
            self.assertIn("cid:3", rows_by_id)
            row = rows_by_id["cid:1"]
            self.assertEqual(row["explain_best_match_id"], "cid:2")
            self.assertGreater(float(row["explain_similarity"]), 0.60)
            self.assertGreater(float(row["explain_name_score"]), 0.60)
            self.assertGreater(float(row["explain_distance_km"]), 0.0)

    def test_build_queue_explain_fields_empty_when_no_neighbors(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            classified = Path(td) / "places_classified.json"
            low_conf = Path(td) / "low_confidence_review.json"
            classified.write_text(
                json.dumps(
                    [
                        {
                            "id": "solo",
                            "name": "Lonely Place",
                            "address": "123 Main St",
                            "confidence": "low",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            low_conf.write_text("[]", encoding="utf-8")

            queue = reclassify_queue.build_reclassify_queue(
                classified,
                low_conf,
                include_low_confidence=True,
                include_stale=False,
            )

            self.assertEqual(len(queue), 1)
            row = queue[0]
            self.assertEqual(row["explain_best_match_id"], "")
            self.assertEqual(row["explain_name_score"], "")
            self.assertEqual(row["explain_address_score"], "")
            self.assertEqual(row["explain_distance_km"], "")
            self.assertEqual(row["explain_similarity"], "")

    def test_build_queue_flags_stale_places(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            classified = Path(td) / "places_classified.json"
            low_conf = Path(td) / "low_confidence_review.json"

            classified.write_text(
                json.dumps(
                    [
                        {"id": "cid:1", "name": "Old", "confidence": "high", "date": "2024-01-01"},
                        {"id": "cid:2", "name": "New", "confidence": "high", "date": "2026-03-02"},
                    ]
                ),
                encoding="utf-8",
            )
            low_conf.write_text("[]", encoding="utf-8")

            fixed_now = datetime(2026, 3, 3, tzinfo=timezone.utc)
            with patch("reclassify_queue.utc_now", return_value=fixed_now):
                queue = reclassify_queue.build_reclassify_queue(
                    classified,
                    low_conf,
                    include_low_confidence=False,
                    include_stale=True,
                    stale_days=365,
                )

            self.assertEqual(len(queue), 1)
            self.assertEqual(queue[0]["id"], "cid:1")
            self.assertEqual(queue[0]["reclassify_reasons"], "stale")
            self.assertEqual(queue[0]["days_since_saved"], 792)

    def test_oldest_priority_orders_by_days_since_saved(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            classified = Path(td) / "places_classified.json"
            low_conf = Path(td) / "low_confidence_review.json"

            classified.write_text(
                json.dumps(
                    [
                        {"id": "cid:new", "name": "New", "confidence": "high", "date": "2026-03-02"},
                        {"id": "cid:old", "name": "Old", "confidence": "high", "date": "2024-01-01"},
                    ]
                ),
                encoding="utf-8",
            )
            low_conf.write_text("[]", encoding="utf-8")

            fixed_now = datetime(2026, 3, 4, tzinfo=timezone.utc)
            with patch("reclassify_queue.utc_now", return_value=fixed_now):
                queue = reclassify_queue.build_reclassify_queue(
                    classified,
                    low_conf,
                    include_low_confidence=False,
                    include_stale=True,
                    stale_days=1,
                    priority="oldest",
                )

            self.assertEqual([row["id"] for row in queue], ["cid:old", "cid:new"])

    def test_lowest_confidence_priority_orders_by_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            classified = Path(td) / "places_classified.json"
            low_conf = Path(td) / "low_confidence_review.json"

            classified.write_text(
                json.dumps(
                    [
                        {"id": "cid:high", "name": "High", "confidence": "high"},
                        {"id": "cid:low", "name": "Low", "confidence": "low"},
                        {"id": "cid:med", "name": "Med", "confidence": "medium"},
                    ]
                ),
                encoding="utf-8",
            )
            low_conf.write_text(
                json.dumps(
                    [
                        {"id": "cid:high"},
                        {"id": "cid:low"},
                        {"id": "cid:med"},
                    ]
                ),
                encoding="utf-8",
            )

            queue = reclassify_queue.build_reclassify_queue(
                classified,
                low_conf,
                include_stale=False,
                priority="lowest-confidence",
            )

            self.assertEqual([row["id"] for row in queue], ["cid:low", "cid:med", "cid:high"])

    def test_most_recently_reviewed_priority_orders_by_history_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            classified = Path(td) / "places_classified.json"
            low_conf = Path(td) / "low_confidence_review.json"
            history = Path(td) / "history.json"

            classified.write_text(
                json.dumps(
                    [
                        {"id": "cid:one", "name": "One", "confidence": "low"},
                        {"id": "cid:two", "name": "Two", "confidence": "low"},
                        {"id": "cid:three", "name": "Three", "confidence": "low"},
                    ]
                ),
                encoding="utf-8",
            )
            low_conf.write_text("[]", encoding="utf-8")
            history.write_text(
                json.dumps(
                    [
                        {"id": "cid:one", "reviewed_at": "2026-03-02T00:00:00Z"},
                        {"id": "cid:two", "reviewed_at": "2026-03-01T00:00:00Z"},
                    ]
                ),
                encoding="utf-8",
            )

            queue = reclassify_queue.build_reclassify_queue(
                classified,
                low_conf,
                history_path=history,
                priority="most-recently-reviewed",
            )

            self.assertEqual([row["id"] for row in queue], ["cid:one", "cid:two", "cid:three"])

    def test_retry_days_zero_does_not_suppress_history_records(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            classified = Path(td) / "places_classified.json"
            low_conf = Path(td) / "low_confidence_review.json"
            history = Path(td) / "history.json"

            classified.write_text(
                json.dumps(
                    [
                        {"id": "cid:one", "name": "One", "confidence": "low"},
                        {"id": "cid:two", "name": "Two", "confidence": "low"},
                    ]
                ),
                encoding="utf-8",
            )
            low_conf.write_text("[]", encoding="utf-8")
            history.write_text(
                json.dumps([{"id": "cid:one", "reviewed_at": "2026-01-01T00:00:00Z"}]),
                encoding="utf-8",
            )

            queue = reclassify_queue.build_reclassify_queue(
                classified,
                low_conf,
                history_path=history,
                retry_days=0,
            )
            self.assertEqual(len(queue), 2)

    def test_stale_reference_prefers_classified_at_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            classified = Path(td) / "places_classified.json"
            low_conf = Path(td) / "low_confidence_review.json"

            classified.write_text(
                json.dumps(
                    [
                        {
                            "id": "cid:1",
                            "name": "Old source date",
                            "confidence": "high",
                            "date": "2024-01-01",
                            "classified_at": "2026-03-01T00:00:00Z",
                        },
                    ]
                ),
                encoding="utf-8",
            )
            low_conf.write_text("[]", encoding="utf-8")

            fixed_now = datetime(2026, 3, 3, tzinfo=timezone.utc)
            queue = reclassify_queue.build_reclassify_queue(
                classified,
                low_conf,
                include_low_confidence=False,
                include_stale=True,
                stale_days=1,
                now=fixed_now,
            )

            self.assertEqual(len(queue), 1)
            self.assertEqual(queue[0]["id"], "cid:1")
            self.assertEqual(queue[0]["days_since_saved"], 2)
            self.assertEqual(queue[0]["date"], "2026-03-01T00:00:00Z")

    def test_outputs_csv(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            classified = Path(td) / "places_classified.json"
            low_conf = Path(td) / "low_confidence_review.json"
            out = Path(td) / "queue.csv"

            classified.write_text(
                json.dumps([{"id": "cid:1", "name": "A", "confidence": "low", "date": "2026-01-01"}]),
                encoding="utf-8",
            )
            low_conf.write_text("[]", encoding="utf-8")

            self.assertEqual(
                reclassify_queue.main([
                    "--classified", str(classified),
                    "--low-confidence", str(low_conf),
                    "--output", str(out),
                    "--output-format", "csv",
                    "--max-items", "1",
                ]),
                0,
            )

            self.assertTrue(out.exists())
            with out.open(encoding="utf-8", newline="") as f:
                rows = list(csv.reader(f))
            self.assertEqual(rows[0], list(reclassify_queue.RECLASSIFY_FIELDNAMES))
            self.assertEqual(len(rows), 2)

    def test_main_non_verbose_outputs_json_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            classified = Path(td) / "places_classified.json"
            low_conf = Path(td) / "low_confidence_review.json"
            out = Path(td) / "queue.json"

            classified.write_text(
                json.dumps([{"id": "cid:1", "name": "A", "confidence": "low", "date": "2026-01-01"}]),
                encoding="utf-8",
            )
            low_conf.write_text("[]", encoding="utf-8")

            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                self.assertEqual(
                    reclassify_queue.main([
                        "--classified", str(classified),
                        "--low-confidence", str(low_conf),
                        "--output", str(out),
                    ]),
                    0,
                )

            payload = json.loads(stdout.getvalue().strip())
            self.assertEqual(payload["rows"], 1)
            self.assertEqual(payload["format"], "json")

    def test_main_triggers_low_confidence_backlog_notification(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            classified = Path(td) / "places_classified.json"
            low_conf = Path(td) / "low_confidence_review.json"
            out = Path(td) / "queue.json"
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
                        {
                            "id": "cid:1",
                            "name": "A",
                            "confidence": "low",
                            "date": "2026-01-01",
                        },
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
                reclassify_queue.main([
                    "--classified", str(classified),
                    "--low-confidence", str(low_conf),
                    "--output", str(out),
                    "--notify-threshold", "1",
                    "--notify-command", f"{sys.executable} {hook} {hook_output}",
                ]),
                0,
            )

            payload = json.loads(hook_output.read_text(encoding="utf-8"))
            self.assertEqual(payload["low_confidence_backlog"], 2)
            self.assertEqual(payload["threshold"], 1)

    def test_notify_hook_timeout_does_not_crash(self) -> None:
        """A slow hook should time out gracefully, not hang the pipeline."""
        from reclassify_queue import run_low_confidence_backlog_hook

        queue = [
            {"reclassify_reasons": "low_confidence"},
            {"reclassify_reasons": "low_confidence"},
        ]
        # Use a command that sleeps longer than the 30s timeout.
        # We mock timeout to 0.1s so the test doesn't actually wait 30s.
        with patch("reclassify_queue.subprocess.run", side_effect=subprocess.TimeoutExpired("sleep", 0.1)):
            # Should not raise — just prints a warning
            run_low_confidence_backlog_hook(queue, threshold=1, command="sleep 60")

    def test_history_suppresses_recently_reviewed_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            classified = Path(td) / "places_classified.json"
            low_conf = Path(td) / "low_confidence_review.json"
            history = Path(td) / "history.json"
            fixed_now = datetime(2026, 3, 3, tzinfo=timezone.utc)

            classified.write_text(
                json.dumps([
                    {"id": "cid:1", "name": "A", "confidence": "low", "date": "2026-01-01"},
                    {"id": "cid:2", "name": "B", "confidence": "low", "date": "2026-01-01"},
                ]),
                encoding="utf-8",
            )
            low_conf.write_text("[]", encoding="utf-8")
            history.write_text(
                json.dumps([
                    {"id": "cid:1", "reviewed_at": "2026-02-20T00:00:00Z"},
                ]),
                encoding="utf-8",
            )

            queue = reclassify_queue.build_reclassify_queue(
                classified,
                low_conf,
                include_low_confidence=True,
                include_stale=False,
                history_path=history,
                retry_days=14,
                now=fixed_now,
            )

            self.assertEqual(len(queue), 1)
            self.assertEqual(queue[0]["id"], "cid:2")

    def test_history_older_than_retry_reappears_in_queue(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            classified = Path(td) / "places_classified.json"
            low_conf = Path(td) / "low_confidence_review.json"
            history = Path(td) / "history.json"
            fixed_now = datetime(2026, 3, 3, tzinfo=timezone.utc)

            classified.write_text(
                json.dumps([
                    {"id": "cid:1", "name": "A", "confidence": "low", "date": "2026-01-01"},
                ]),
                encoding="utf-8",
            )
            low_conf.write_text("[]", encoding="utf-8")
            history.write_text(
                json.dumps([
                    {"id": "cid:1", "reviewed_at": "2025-12-30T00:00:00Z"},
                ]),
                encoding="utf-8",
            )

            queue = reclassify_queue.build_reclassify_queue(
                classified,
                low_conf,
                include_low_confidence=True,
                include_stale=False,
                history_path=history,
                retry_days=14,
                now=fixed_now,
            )

            self.assertEqual(len(queue), 1)


if __name__ == "__main__":
    unittest.main()
