"""Centralized helpers for deterministic output file writes."""

import csv
from collections.abc import Sequence
from pathlib import Path
from xml.etree import ElementTree as ET


def write_kml(path: Path, kml_root: ET.Element, *, encoding: str = "utf-8") -> None:
    """Write a KML tree with consistent encoding and indentation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(kml_root)
    ET.indent(tree, space="  ")

    with open(path, "w", encoding=encoding, newline="") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(f, encoding="unicode", xml_declaration=False)


def write_csv_rows(
    path: Path,
    fieldnames: Sequence[str],
    rows: list[dict],
) -> None:
    """Write CSV rows with a deterministic field order and stable newline handling."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            normalized = {
                key: ("" if row.get(key) is None else row.get(key))
                for key in fieldnames
            }
            writer.writerow(normalized)
