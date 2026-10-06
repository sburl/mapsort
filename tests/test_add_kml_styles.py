#!/usr/bin/env python3
"""Tests for add_kml_styles.py."""

import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from add_kml_styles import add_style_to_kml, extract_slug


class TestExtractSlug(unittest.TestCase):
    def test_blue_airports(self):
        self.assertEqual(extract_slug("blue_airports.kml"), "airports")

    def test_green_restaurants(self):
        self.assertEqual(extract_slug("green_restaurants.kml"), "restaurants")

    def test_part_file(self):
        self.assertEqual(extract_slug("blue_restaurants_part3.kml"), "restaurants")

    def test_multi_word_slug(self):
        self.assertEqual(extract_slug("green_nature_outdoors.kml"), "nature_outdoors")

    def test_multi_word_with_part(self):
        self.assertEqual(extract_slug("blue_cafes_bakeries_part1.kml"), "cafes_bakeries")

    def test_no_match(self):
        self.assertIsNone(extract_slug("unresolved.kml"))

    def test_random_file(self):
        self.assertIsNone(extract_slug("README.md"))


class TestAddStyleToKml(unittest.TestCase):
    def _make_kml(self, name="Test", placemarks=2):
        kml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
            f"  <Document>\n    <name>{name}</name>\n"
        )
        for i in range(placemarks):
            kml += (
                f"    <Placemark>\n"
                f"      <name>Place {i}</name>\n"
                f"      <Point><coordinates>0,0,0</coordinates></Point>\n"
                f"    </Placemark>\n"
            )
        kml += "  </Document>\n</kml>"
        return kml

    def test_adds_style_and_urls(self):
        with tempfile.NamedTemporaryFile(suffix=".kml", mode="w", delete=False) as f:
            f.write(self._make_kml(placemarks=3))
            path = Path(f.name)

        count = add_style_to_kml(path, "https://maps.google.com/mapfiles/kml/shapes/dining.png")
        self.assertEqual(count, 3)

        tree = ET.parse(path)
        ns = {"k": "http://www.opengis.net/kml/2.2"}
        style = tree.find(".//k:Style[@id='categoryIcon']", ns)
        self.assertIsNotNone(style)

        href = style.find(".//k:href", ns)
        self.assertEqual(href.text, "https://maps.google.com/mapfiles/kml/shapes/dining.png")

        for pm in tree.findall(".//k:Placemark", ns):
            url = pm.find("k:styleUrl", ns)
            self.assertIsNotNone(url)
            self.assertEqual(url.text, "#categoryIcon")

        path.unlink()

    def test_idempotent(self):
        with tempfile.NamedTemporaryFile(suffix=".kml", mode="w", delete=False) as f:
            f.write(self._make_kml(placemarks=2))
            path = Path(f.name)

        add_style_to_kml(path, "https://maps.google.com/mapfiles/kml/shapes/dining.png")
        count = add_style_to_kml(path, "https://maps.google.com/mapfiles/kml/shapes/dining.png")
        self.assertEqual(count, 0)  # Already styled, no changes

        path.unlink()

    def test_styles_new_placemarks_in_already_styled_doc(self):
        """Placemarks added after initial styling should get styleUrl on re-run."""
        with tempfile.NamedTemporaryFile(suffix=".kml", mode="w", delete=False) as f:
            f.write(self._make_kml(placemarks=2))
            path = Path(f.name)

        url = "https://maps.google.com/mapfiles/kml/shapes/dining.png"
        add_style_to_kml(path, url)

        # Simulate adding a new unstyled placemark after initial styling
        ns = {"k": "http://www.opengis.net/kml/2.2"}
        tree = ET.parse(path)
        doc = tree.find(".//k:Document", ns)
        pm = ET.SubElement(doc, "{http://www.opengis.net/kml/2.2}Placemark")
        name = ET.SubElement(pm, "{http://www.opengis.net/kml/2.2}name")
        name.text = "New Place"
        tree.write(path, encoding="unicode", xml_declaration=True)

        count = add_style_to_kml(path, url)
        self.assertEqual(count, 1)  # Only the new placemark

        # Verify all 3 placemarks now have styleUrl
        tree = ET.parse(path)
        for pm in tree.findall(f".//{{{ns['k']}}}Placemark"):
            style_url = pm.find(f"{{{ns['k']}}}styleUrl")
            self.assertIsNotNone(style_url)

        path.unlink()


if __name__ == "__main__":
    unittest.main()
