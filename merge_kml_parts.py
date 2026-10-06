#!/usr/bin/env python3
"""Merge split KML part files into single files for Google My Maps import.

Combines files like blue_restaurants_part1.kml through part4 into a single
blue_restaurants.kml in the output/import/ directory.

Usage:
    python merge_kml_parts.py              # merge all
    python merge_kml_parts.py --dry-run    # preview without writing
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

from settings import OUTPUT_DIR

KML_NS = "http://www.opengis.net/kml/2.2"
ET.register_namespace("", KML_NS)

IMPORT_DIR = OUTPUT_DIR / "import"

# Maps category slugs to Google My Maps map folders.
MAP_GROUPS: dict[str, list[str]] = {
    "food": [
        "restaurants",
        "cafes_bakeries",
        "quick_bites",
        "bars_nightlife",
        "sweets_snacks",
    ],
    "culture": [
        "landmarks_history",
        "museums_culture",
        "entertainment",
        "sacred_sites",
        "shopping",
    ],
    "outdoors": [
        "nature_outdoors",
        "parks_gardens",
        "regions_destinations",
        "ski_resorts",
        "scuba_diving",
    ],
    "logistics": [
        "hotels_stays",
        "practical",
        "airports",
        "train_transit",
    ],
}

# Reverse lookup: slug -> map folder name
SLUG_TO_MAP: dict[str, str] = {
    slug: map_name
    for map_name, slugs in MAP_GROUPS.items()
    for slug in slugs
}

# Match blue_restaurants.kml or blue_restaurants_part2.kml
_FILE_RE = re.compile(r"^((?:blue|green)_[a-z_]+?)(?:_part\d+)?\.kml$")
_SLUG_RE = re.compile(r"^(?:blue|green)_(.+)$")


def group_files(kml_dir: Path) -> dict[str, list[Path]]:
    """Group KML files by their base name (without _partN suffix)."""
    groups: dict[str, list[Path]] = defaultdict(list)
    for path in sorted(kml_dir.glob("*.kml")):
        if " 2" in path.name:
            continue
        m = _FILE_RE.match(path.name)
        if m:
            groups[m.group(1)].append(path)
    return dict(groups)


def merge_group(files: list[Path], output_path: Path) -> int:
    """Merge multiple KML files into one. Returns total placemark count."""
    # Use the first file as the base
    tree = ET.parse(files[0])
    root = tree.getroot()
    doc = root.find(f"{{{KML_NS}}}Document")
    if doc is None:
        return 0

    # Collect placemarks from additional part files
    for extra in files[1:]:
        extra_tree = ET.parse(extra)
        extra_doc = extra_tree.getroot().find(f"{{{KML_NS}}}Document")
        if extra_doc is None:
            continue
        for pm in extra_doc.findall(f"{{{KML_NS}}}Placemark"):
            doc.append(pm)

    # Relabel Document name: replace color dot with (Visited)/(Want to Go)
    name_el = doc.find(f"{{{KML_NS}}}name")
    if name_el is not None and name_el.text:
        label = name_el.text
        if label.startswith("\U0001f535 "):  # blue circle
            name_el.text = label.replace("\U0001f535 ", "") + " (Want to Go)"
        elif label.startswith("\U0001f7e2 "):  # green circle
            name_el.text = label.replace("\U0001f7e2 ", "") + " (Visited)"

    count = len(doc.findall(f"{{{KML_NS}}}Placemark"))

    ET.indent(tree, space="  ")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(f, encoding="unicode", xml_declaration=False)

    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Merge split KML part files for Google My Maps import."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview merges without writing files.",
    )
    args = parser.parse_args(argv)

    groups = group_files(OUTPUT_DIR)
    if not groups:
        print(f"No KML files found in {OUTPUT_DIR}")
        return 1

    total_files = 0
    total_placemarks = 0

    map_counts: dict[str, int] = defaultdict(int)

    for base_name, files in sorted(groups.items()):
        slug_m = _SLUG_RE.match(base_name)
        slug = slug_m.group(1) if slug_m else base_name
        map_folder = SLUG_TO_MAP.get(slug, "other")
        output_path = IMPORT_DIR / map_folder / f"{base_name}.kml"
        count_str = " + ".join(str(len(ET.parse(f).findall(f".//{{{KML_NS}}}Placemark"))) for f in files)

        if args.dry_run:
            print(f"  {map_folder}/{base_name}.kml <- {len(files)} file(s) ({count_str})")
            total_files += 1
            continue

        count = merge_group(files, output_path)
        if count > 0:
            print(f"  {map_folder}/{base_name}.kml ({count} placemarks from {len(files)} file(s))")
            total_files += 1
            total_placemarks += count
            map_counts[map_folder] += count
        else:
            print(f"  SKIP (empty): {base_name}")

    print(f"\nFiles created: {total_files}")
    if not args.dry_run:
        print(f"Total placemarks: {total_placemarks}")
        print("\nBy map:")
        for name in ("food", "culture", "outdoors", "logistics"):
            if name in map_counts:
                print(f"  {name}/: {map_counts[name]} placemarks")
        print(f"\nOutput directory: {IMPORT_DIR}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
