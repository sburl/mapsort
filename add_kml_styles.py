#!/usr/bin/env python3
"""Add <Style> elements with category-specific icons to all KML files.

Injects Google Maps built-in icon URLs so that Google My Maps displays
distinct pin shapes per category instead of default pins.

Usage:
    python add_kml_styles.py                   # process all KMLs in output/
    python add_kml_styles.py --dry-run          # preview without writing
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from xml.etree import ElementTree as ET

from settings import OUTPUT_DIR

KML_NS = "http://www.opengis.net/kml/2.2"
ET.register_namespace("", KML_NS)

ICON_BASE = "https://maps.google.com/mapfiles/kml/shapes"

# Maps category slug (from KML filename) to Google Maps icon filename.
# All URLs verified via HTTP 200.
SLUG_TO_ICON: dict[str, str] = {
    "airports": "airports.png",
    "bars_nightlife": "bars.png",
    "cafes_bakeries": "coffee.png",
    "entertainment": "play.png",
    "hotels_stays": "lodging.png",
    "landmarks_history": "camera.png",
    "museums_culture": "museum.png",
    "nature_outdoors": "trail.png",
    "parks_gardens": "parks.png",
    "practical": "mechanic.png",
    "quick_bites": "snack_bar.png",
    "regions_destinations": "flag.png",
    "restaurants": "dining.png",
    "sacred_sites": "church.png",
    "scuba_diving": "water.png",
    "shopping": "shopping.png",
    "ski_resorts": "snowflake_simple.png",
    "sweets_snacks": "grocery.png",
    "train_transit": "rail.png",
}

# Regex to extract category slug from filename like "blue_airports.kml"
# or "green_restaurants_part2.kml"
_FILENAME_RE = re.compile(
    r"^(?:blue|green)_(.+?)(?:_part\d+)?\.kml$"
)


def extract_slug(filename: str) -> str | None:
    """Extract category slug from a KML filename."""
    m = _FILENAME_RE.match(filename)
    return m.group(1) if m else None


def add_style_to_kml(path: Path, icon_url: str) -> int:
    """Add a <Style> element and <styleUrl> to each Placemark.

    Returns the number of Placemarks updated.
    """
    tree = ET.parse(path)
    root = tree.getroot()

    doc = root.find(f"{{{KML_NS}}}Document")
    if doc is None:
        return 0

    # Add Style element if not already present
    existing = doc.find(f"{{{KML_NS}}}Style[@id='categoryIcon']")
    if existing is None:
        style = ET.SubElement(doc, "Style")
        style.set("id", "categoryIcon")
        icon_style = ET.SubElement(style, "IconStyle")
        icon = ET.SubElement(icon_style, "Icon")
        href = ET.SubElement(icon, "href")
        href.text = icon_url

        # Insert Style after <name> (first child) for clean ordering
        doc.remove(style)
        doc.insert(1, style)

    # Add styleUrl to each Placemark that lacks one
    count = 0
    for pm in doc.findall(f"{{{KML_NS}}}Placemark"):
        existing_url = pm.find(f"{{{KML_NS}}}styleUrl")
        if existing_url is None:
            style_url = ET.SubElement(pm, "styleUrl")
            style_url.text = "#categoryIcon"
            count += 1

    # Only write if we made changes
    if count == 0 and existing is not None:
        return 0

    ET.indent(tree, space="  ")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(f, encoding="unicode", xml_declaration=False)

    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Add category-specific icon styles to KML files."
    )
    parser.add_argument(
        "--dir", default=str(OUTPUT_DIR),
        help=f"Directory containing KML files (default: {OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview changes without writing files.",
    )
    args = parser.parse_args(argv)

    kml_dir = Path(args.dir)
    kml_files = sorted(kml_dir.glob("*.kml"))

    if not kml_files:
        print(f"No KML files found in {kml_dir}")
        return 1

    total_files = 0
    total_placemarks = 0
    skipped = 0
    no_icon = 0

    for path in kml_files:
        slug = extract_slug(path.name)
        if slug is None:
            print(f"  SKIP (no slug): {path.name}")
            skipped += 1
            continue

        icon_file = SLUG_TO_ICON.get(slug)
        if icon_file is None:
            print(f"  SKIP (no icon mapping): {path.name} -> slug '{slug}'")
            no_icon += 1
            continue

        icon_url = f"{ICON_BASE}/{icon_file}"

        if args.dry_run:
            print(f"  WOULD style: {path.name} -> {icon_file}")
            total_files += 1
            continue

        count = add_style_to_kml(path, icon_url)
        if count > 0:
            print(f"  Styled: {path.name} -> {icon_file} ({count} placemarks)")
            total_files += 1
            total_placemarks += count
        else:
            print(f"  Already styled: {path.name}")

    print(f"\nFiles styled:     {total_files}")
    if not args.dry_run:
        print(f"Placemarks styled: {total_placemarks}")
    if skipped:
        print(f"Skipped:          {skipped}")
    if no_icon:
        print(f"No icon mapping:  {no_icon}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
