#!/usr/bin/env python3
"""Export a slim, public-safe places dataset for a personal site.

Reads places_classified.json and writes a compact JSON of VISITED places
only, excluding private-ish categories (hotels, practical, airports,
transit) and stripping all provenance fields (source lists, tiers, ids).

Usage:
    python export_site_data.py                      # writes to output/
    python export_site_data.py --output /path/to/site/public/data/travel-places.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from settings import CLASSIFIED_JSON, OUTPUT_DIR

DEFAULT_OUTPUT = OUTPUT_DIR / "travel-places.json"

# Numeric category id -> public slug. Derived from the KML output cross-tab.
CATEGORY_SLUGS: dict[int, str] = {
    1: "restaurants",
    2: "quick_bites",
    3: "cafes_bakeries",
    4: "sweets_snacks",
    5: "bars_nightlife",
    6: "hotels_stays",
    7: "museums_culture",
    8: "landmarks_history",
    9: "sacred_sites",
    10: "parks_gardens",
    11: "nature_outdoors",
    12: "shopping",
    13: "entertainment",
    14: "airports",
    15: "train_transit",
    16: "practical",
    17: "regions_destinations",
    18: "scuba_diving",
    19: "ski_resorts",
}

# Categories that never ship publicly: lodging and logistics reveal
# patterns of travel rather than taste.
PRIVATE_CATEGORIES: frozenset[int] = frozenset({6, 14, 15, 16})

PUBLIC_TIER = "visited"

# Human-readable labels, in display order for the site's filter UI.
CATEGORY_LABELS: dict[str, str] = {
    "restaurants": "Restaurants",
    "cafes_bakeries": "Cafes & Bakeries",
    "quick_bites": "Quick Bites",
    "bars_nightlife": "Bars & Nightlife",
    "sweets_snacks": "Sweets & Snacks",
    "landmarks_history": "Landmarks & History",
    "museums_culture": "Museums & Culture",
    "sacred_sites": "Sacred Sites",
    "entertainment": "Entertainment",
    "shopping": "Shopping",
    "nature_outdoors": "Nature & Outdoors",
    "parks_gardens": "Parks & Gardens",
    "regions_destinations": "Regions & Destinations",
    "scuba_diving": "Scuba & Diving",
    "ski_resorts": "Ski Resorts",
}


def build_export(places: list[dict]) -> dict:
    """Filter and slim classified places into the public payload.

    Output shape (compact, array-of-arrays to keep the file small):
        {
          "categories": [{"slug": ..., "label": ...}, ...],
          "places": [[name, lat, lng, category_index, cid_or_null], ...]
        }
    """
    category_order = list(CATEGORY_LABELS)
    slug_to_index = {slug: i for i, slug in enumerate(category_order)}

    rows: list[tuple] = []
    for p in places:
        if p.get("tier") != PUBLIC_TIER:
            continue
        cat = p.get("category")
        if cat is None or cat in PRIVATE_CATEGORIES:
            continue
        slug = CATEGORY_SLUGS.get(cat)
        if slug is None or slug not in slug_to_index:
            continue
        lat, lng = p.get("lat"), p.get("lng")
        if lat is None or lng is None:
            continue
        name = (p.get("resolved_name") or p.get("name") or "").strip()
        if not name:
            continue
        cid = p.get("cid") or None
        rows.append((name, round(lat, 5), round(lng, 5), slug_to_index[slug], cid))

    # Deterministic output: sort by category, then name, then coords.
    rows.sort(key=lambda r: (r[3], r[0].casefold(), r[1], r[2]))

    return {
        "categories": [
            {"slug": slug, "label": CATEGORY_LABELS[slug]} for slug in category_order
        ],
        "places": [list(r) for r in rows],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=CLASSIFIED_JSON, help="classified places JSON"
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT, help="destination JSON path"
    )
    args = parser.parse_args()

    places = json.loads(args.input.read_text(encoding="utf-8"))
    payload = build_export(places)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8", newline="") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")

    print(f"Wrote {len(payload['places'])} places to {args.output}")


if __name__ == "__main__":
    main()
