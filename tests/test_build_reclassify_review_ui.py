#!/usr/bin/env python3
"""Regression tests for review UI generation."""

from __future__ import annotations

import csv
import json
import re
import tempfile
import unittest
from pathlib import Path

from build_reclassify_review_ui import build_review_ui


class BuildReclassifyReviewUiTests(unittest.TestCase):

    def test_build_review_ui_writes_html_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            template = Path(td) / "template.csv"
            out = Path(td) / "review.html"

            with template.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=(
                        "id",
                        "name",
                        "address",
                        "category",
                        "confidence",
                        "reclassify_reasons",
                        "decision_category",
                        "decision_confidence",
                        "notes",
                    ),
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "id": "cid:1",
                        "name": "Cafe's Blue\nMain",
                        "address": "100 Main",
                        "category": "3",
                        "confidence": "low",
                        "reclassify_reasons": "low_confidence",
                    }
                )

            count = build_review_ui(template, out, title="Review UI")
            self.assertEqual(count, 1)
            self.assertTrue(out.exists())

            html = out.read_text(encoding="utf-8")
            self.assertIn("Review UI", html)
            self.assertIn("Export decisions CSV", html)

            script_match = re.search(r"const REVIEW_ROWS = (.*?);", html)
            self.assertIsNotNone(script_match)
            payload = script_match.group(1)
            rows = json.loads(payload)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["name"], "Cafe's Blue\nMain")

    def test_build_review_ui_escapes_script_closing_tag(self) -> None:
        """Verify that </script> in data cannot break out of the script block."""
        with tempfile.TemporaryDirectory() as td:
            template = Path(td) / "template.csv"
            out = Path(td) / "review.html"

            with template.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=(
                        "id", "name", "address", "category", "confidence",
                        "reclassify_reasons", "decision_category",
                        "decision_confidence", "notes",
                    ),
                )
                writer.writeheader()
                writer.writerow({
                    "id": "cid:xss",
                    "name": '</script><img src=x onerror=alert(1)>',
                    "address": "123 Main",
                    "category": "1",
                    "confidence": "low",
                    "reclassify_reasons": "low_confidence",
                })

            build_review_ui(template, out)
            html = out.read_text(encoding="utf-8")

            # The literal </script> must NOT appear inside the JSON payload
            script_start = html.index("const REVIEW_ROWS = ")
            script_end = html.index("</script>", script_start)
            inline_block = html[script_start:script_end]
            self.assertNotIn("</script>", inline_block)

            # The escaped version should still parse back to the original value
            match = re.search(r"const REVIEW_ROWS = (.*?);", html)
            self.assertIsNotNone(match)
            # Undo the escape so json.loads works
            raw = match.group(1).replace(r"<\/", "</")
            rows = json.loads(raw)
            self.assertEqual(rows[0]["name"], '</script><img src=x onerror=alert(1)>')

    def test_build_review_ui_main_template_missing_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            from build_reclassify_review_ui import main

            out = Path(td) / "review.html"

            self.assertEqual(
                main(["--template", str(Path(td) / "missing.csv"), "--output", str(out)]),
                2,
            )


if __name__ == "__main__":
    unittest.main()
