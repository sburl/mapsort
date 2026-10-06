#!/usr/bin/env python3
"""Export a single "greatest hits" KML of top gems for Google My Maps.

Reads gem_scores.json and writes one KML layer holding the best places
worldwide — the personal counterpart to the per-category import files:
something to carry on a phone and consult while standing in a city.

Selection takes the top N per location before capping globally, so one
densely-scored city cannot crowd out everywhere else. Places that fall
outside every known bounding box are pooled into their own bucket and
get the same per-bucket allowance rather than being dropped.

Usage:
    python export_gems_kml.py
    python export_gems_kml.py --per-location 10 --max-total 200
    python export_gems_kml.py --min-score 0.0 --output /tmp/gems.kml
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

from add_kml_styles import ICON_BASE, KML_NS, SLUG_TO_ICON
from export_site_data import CATEGORY_SLUGS
from file_writers import write_kml
from settings import CLASSIFIED_JSON, OUTPUT_DIR

GEM_SCORES = OUTPUT_DIR / "gem_scores.json"
DEFAULT_OUTPUT = OUTPUT_DIR / "gems_greatest_hits.kml"

# Bucket for places outside every known bounding box. Kept in the running
# so a high-scoring rural gem is not silently discarded, but capped like
# any single location so it cannot flood the layer.
UNMATCHED = "(unmatched)"

DEFAULT_PER_LOCATION = 15
DEFAULT_MAX_TOTAL = 300


def select_gems(
    scored: list[dict],
    *,
    per_location: int = DEFAULT_PER_LOCATION,
    max_total: int = DEFAULT_MAX_TOTAL,
    min_score: float | None = None,
) -> list[dict]:
    """Top gems per location, unioned and capped at max_total."""
    pool = [p for p in scored if not p.get("famous")]
    if min_score is not None:
        pool = [p for p in pool if p.get("gem_score", 0) >= min_score]

    by_location: dict[str, list[dict]] = defaultdict(list)
    for place in pool:
        for loc in place.get("locations") or [UNMATCHED]:
            by_location[loc].append(place)

    chosen: dict[str, dict] = {}
    for loc in sorted(by_location):
        ranked = sorted(by_location[loc], key=lambda p: -p.get("gem_score", 0))
        for place in ranked[:per_location]:
            chosen[place["id"]] = place

    winners = sorted(chosen.values(), key=lambda p: (-p.get("gem_score", 0), p["name"]))
    return winners[:max_total]


def load_cids(path: Path) -> dict[str, str]:
    """Map place id -> Google CID, from the authoritative classified file."""
    if not path.exists():
        return {}
    classified = json.loads(path.read_text(encoding="utf-8"))
    return {p["id"]: p["cid"] for p in classified if p.get("id") and p.get("cid")}


def describe(place: dict, cid: str | None) -> str:
    """Human-readable placemark description; link only when a CID exists."""
    rating = place.get("rating")
    reviews = place.get("review_count")
    parts = []
    if rating is not None:
        parts.append(f"{rating}★")
    if reviews is not None:
        parts.append(f"{reviews:,} reviews")
    parts.append(f"gem score {place.get('gem_score')}")
    text = " · ".join(parts)
    if cid:
        text += f"\nhttps://maps.google.com/?cid={cid}"
    return text


def build_kml(places: list[dict], cids: dict[str, str], *, title: str = "Greatest Hits") -> ET.Element:
    """Build a styled, single-layer KML document from selected places."""
    kml = ET.Element(f"{{{KML_NS}}}kml")
    doc = ET.SubElement(kml, "Document")
    ET.SubElement(doc, "name").text = title

    # One Style per category actually present, mirroring the icon
    # conventions of the per-category KML pipeline.
    slugs = []
    for place in places:
        slug = CATEGORY_SLUGS.get(place.get("category"))
        if slug and slug in SLUG_TO_ICON and slug not in slugs:
            slugs.append(slug)
    for slug in slugs:
        style = ET.SubElement(doc, "Style")
        style.set("id", f"cat_{slug}")
        icon_style = ET.SubElement(style, "IconStyle")
        icon = ET.SubElement(icon_style, "Icon")
        ET.SubElement(icon, "href").text = f"{ICON_BASE}/{SLUG_TO_ICON[slug]}"

    for place in places:
        pm = ET.SubElement(doc, "Placemark")
        ET.SubElement(pm, "name").text = place["name"]
        ET.SubElement(pm, "description").text = describe(place, cids.get(place["id"]))
        slug = CATEGORY_SLUGS.get(place.get("category"))
        if slug and slug in SLUG_TO_ICON:
            ET.SubElement(pm, "styleUrl").text = f"#cat_{slug}"
        point = ET.SubElement(pm, "Point")
        ET.SubElement(point, "coordinates").text = f"{place['lng']},{place['lat']}"

    return kml


def summarize(places: list[dict]) -> list[tuple[str, int]]:
    counts: dict[str, int] = defaultdict(int)
    for place in places:
        for loc in place.get("locations") or [UNMATCHED]:
            counts[loc] += 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=GEM_SCORES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--per-location", type=int, default=DEFAULT_PER_LOCATION)
    parser.add_argument("--max-total", type=int, default=DEFAULT_MAX_TOTAL)
    parser.add_argument("--min-score", type=float, default=None)
    args = parser.parse_args()

    scored = json.loads(args.input.read_text(encoding="utf-8"))
    places = select_gems(
        scored,
        per_location=args.per_location,
        max_total=args.max_total,
        min_score=args.min_score,
    )
    cids = load_cids(CLASSIFIED_JSON)
    write_kml(args.output, build_kml(places, cids))

    linked = sum(1 for p in places if p["id"] in cids)
    print(f"Wrote {len(places)} places to {args.output}")
    print(f"  {linked} with Google Maps links, {len(places) - linked} without")
    print("  locations represented:")
    for loc, count in summarize(places)[:15]:
        print(f"    {loc:24} {count}")


if __name__ == "__main__":
    main()
