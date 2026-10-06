#!/usr/bin/env python3
"""Tests for heuristic auto-tag rule inference."""

from __future__ import annotations

import unittest

from auto_reclassify_rules import infer_category_hint, load_region_rules, load_rules


class AutoReclassifyRuleTests(unittest.TestCase):

    def test_airport_rule(self) -> None:
        cat, reason = infer_category_hint("Terminal 2 Airport", "")
        self.assertEqual(cat, 14)
        self.assertEqual(reason, "airport/aviation")

    def test_transit_rule(self) -> None:
        cat, reason = infer_category_hint("Downtown Metro", "")
        self.assertEqual(cat, 15)
        self.assertEqual(reason, "train/transit")

    def test_no_match(self) -> None:
        cat, reason = infer_category_hint("Just a random place", "")
        self.assertIsNone(cat)
        self.assertIsNone(reason)


class AutoReclassifyRulesLoadTests(unittest.TestCase):

    def test_load_rules_rejects_invalid_content(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            rules_file = Path(td) / "rules.json"
            rules_file.write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "rules file JSON must be a list"):
                load_rules(rules_file)

    def test_load_rules_rejects_no_valid_entries(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            rules_file = Path(td) / "rules.json"
            rules_file.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "rules file has no valid entries"):
                load_rules(rules_file)

    def test_load_region_rules_returns_matching_pack_rules(self) -> None:
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            pack_dir = Path(td)
            pack_dir.joinpath("country-us.json").write_text(
                json.dumps(
                    [{"pattern": r"\bbbq\b", "category": 1, "reason": "us bbq"}],
                ),
                encoding="utf-8",
            )

            rules = load_region_rules(country="US", rule_pack_dir=pack_dir)
            cat, reason = infer_category_hint("BBQ Truck", "", rules=rules)
            self.assertEqual(cat, 1)
            self.assertEqual(reason, "us bbq")

    def test_load_rules_normalizes_double_escaped_patterns(self) -> None:
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            rules_file = Path(td) / "rules.json"
            rules_file.write_text(
                json.dumps(
                    [{"pattern": r"\\bblue lantern\\b", "category": 3, "reason": "double-escaped"}]
                ),
                encoding="utf-8",
            )

            rules = load_rules(rules_file)
            cat, reason = infer_category_hint(
                "Blue Lantern",
                "",
                rules=rules,
                include_default_rules=False,
            )
            self.assertEqual(cat, 3)
            self.assertEqual(reason, "double-escaped")

    def test_load_region_rules_ignores_missing_pack_files(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            pack_dir = Path(td)
            rules = load_region_rules(country="MISSING", travel_plan="nope", rule_pack_dir=pack_dir)
            self.assertEqual(rules, ())

    def test_load_region_rules_ignores_invalid_pack_file(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            pack_dir = Path(td)
            pack_dir.joinpath("country-br.json").write_text("{", encoding="utf-8")
            rules = load_region_rules(country="BR", rule_pack_dir=pack_dir)
            self.assertEqual(rules, ())


if __name__ == "__main__":
    unittest.main()
