#!/usr/bin/env python3
"""Tests for centralized output file write helpers."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from file_writers import write_csv_rows, write_kml


class WriteCsvRowsTests(unittest.TestCase):

    def test_creates_file_with_header_and_data(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "out.csv"
            fieldnames = ["name", "city"]
            rows = [{"name": "Alice", "city": "London"}, {"name": "Bob", "city": "Paris"}]

            write_csv_rows(path, fieldnames, rows)

            self.assertTrue(path.exists())
            with open(path, encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                data = list(reader)
            self.assertEqual(len(data), 2)
            self.assertEqual(data[0]["name"], "Alice")
            self.assertEqual(data[1]["city"], "Paris")

    def test_none_values_written_as_empty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "out.csv"
            fieldnames = ["name", "city"]
            rows = [{"name": "Alice", "city": None}]

            write_csv_rows(path, fieldnames, rows)

            with open(path, encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                data = list(reader)
            self.assertEqual(data[0]["city"], "")

    def test_creates_parent_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sub" / "deep" / "out.csv"
            write_csv_rows(path, ["col"], [{"col": "val"}])
            self.assertTrue(path.exists())

    def test_extra_keys_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "out.csv"
            fieldnames = ["name"]
            rows = [{"name": "Alice", "extra": "ignored"}]

            write_csv_rows(path, fieldnames, rows)

            with open(path, encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                data = list(reader)
            self.assertNotIn("extra", data[0])


class WriteKmlTests(unittest.TestCase):

    def test_creates_valid_xml(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "out.kml"
            kml = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
            doc = ET.SubElement(kml, "Document")
            ET.SubElement(doc, "name").text = "Test"

            write_kml(path, kml)

            self.assertTrue(path.exists())
            content = path.read_text(encoding="utf-8")
            self.assertIn('<?xml version="1.0"', content)
            self.assertIn("<kml", content)
            self.assertIn("<name>Test</name>", content)

    def test_creates_parent_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "nested" / "dir" / "out.kml"
            kml = ET.Element("kml")
            write_kml(path, kml)
            self.assertTrue(path.exists())

    def test_output_is_parseable_xml(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "out.kml"
            kml = ET.Element("kml")
            ET.SubElement(kml, "Document")
            write_kml(path, kml)

            tree = ET.parse(path)
            self.assertIsNotNone(tree.getroot())


if __name__ == "__main__":
    unittest.main()
