#!/usr/bin/env python3
"""Report starred places that have closed, per Google's businessStatus.

Reads output/ratings_cache.json (written by enrich_ratings.py) joined to
output/places_classified.json, and lists places Google marks as
permanently or temporarily closed, grouped by location.

Entries enriched before businessStatus was captured have no
"business_status" key at all; they are counted separately as "not yet
checked" rather than assumed open, and are never re-fetched just to
backfill the field (that would spend paid Enterprise-SKU quota).

Usage:
    python closed_places_report.py                    # full report
    python closed_places_report.py --location Paris   # one location
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict

from enrich_ratings import RATINGS_CACHE, UNKNOWN_BUSINESS_STATUS
from generate_travel_guides import LOCATIONS
from settings import CLASSIFIED_JSON, OUTPUT_DIR

CLOSED_REPORT = OUTPUT_DIR / "closed_places.md"

PERMANENTLY_CLOSED = "CLOSED_PERMANENTLY"
TEMPORARILY_CLOSED = "CLOSED_TEMPORARILY"
OPERATIONAL = "OPERATIONAL"

CLOSED_STATUSES = (PERMANENTLY_CLOSED, TEMPORARILY_CLOSED)

STATUS_LABELS = {
    PERMANENTLY_CLOSED: "Permanently closed",
    TEMPORARILY_CLOSED: "Temporarily closed",
}


def locations_of(lat: float, lng: float) -> list[str]:
    return [
        name
        for name, (s, w, n, e) in LOCATIONS.items()
        if s <= lat <= n and w <= lng <= e
    ]


def build_report(classified: list[dict], cache: dict, location: str | None = None) -> dict:
    """Split enriched places into closed / open / unchecked buckets."""
    closed: list[dict] = []
    counts = {"closed": 0, "open": 0, "unchecked": 0, "unknown": 0, "enriched": 0}

    for place in classified:
        entry = cache.get(place.get("id") or "")
        if not entry or entry.get("status") not in ("ok", "no_rating"):
            continue

        lat, lng = place.get("lat"), place.get("lng")
        locs = locations_of(lat, lng) if lat is not None and lng is not None else []
        if location is not None and location not in locs:
            continue

        counts["enriched"] += 1

        if "business_status" not in entry:
            counts["unchecked"] += 1
            continue

        status = entry["business_status"]
        if status in CLOSED_STATUSES:
            counts["closed"] += 1
            closed.append(
                {
                    "name": (place.get("resolved_name") or place.get("name") or "").strip(),
                    "business_status": status,
                    "locations": locs,
                    "address": (place.get("address") or "").strip(),
                }
            )
        elif status == UNKNOWN_BUSINESS_STATUS:
            counts["unknown"] += 1
        else:
            counts["open"] += 1

    closed.sort(key=lambda p: (p["business_status"], p["name"].casefold()))
    return {"closed": closed, "counts": counts}


def group_by_location(closed: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for place in closed:
        for loc in place["locations"] or ["(no location)"]:
            grouped[loc].append(place)
    return dict(sorted(grouped.items()))


def render_markdown(report: dict) -> str:
    counts = report["counts"]
    lines = [
        "# Closed Places",
        "",
        f"- Enriched places checked: {counts['enriched']}",
        f"- Closed: {counts['closed']}",
        f"- Open: {counts['open']}",
        f"- Status unknown (API returned none): {counts['unknown']}",
        (f"- Not yet checked (enriched before businessStatus was captured): "
            f"{counts['unchecked']}"),
        "",
    ]
    if not report["closed"]:
        lines += ["No closed places found yet.", ""]
        return "\n".join(lines)

    for loc, places in group_by_location(report["closed"]).items():
        lines.append(f"## {loc}")
        lines.append("")
        for p in places:
            label = STATUS_LABELS.get(p["business_status"], p["business_status"])
            suffix = f" — {p['address']}" if p["address"] else ""
            lines.append(f"- **{p['name']}** ({label}){suffix}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--location", default=None, help="restrict to one location")
    args = parser.parse_args()

    if args.location is not None and args.location not in LOCATIONS:
        parser.error(f"unknown location; valid names: {', '.join(sorted(LOCATIONS))}")

    classified = json.loads(CLASSIFIED_JSON.read_text(encoding="utf-8"))
    cache = json.loads(RATINGS_CACHE.read_text(encoding="utf-8"))
    report = build_report(classified, cache, args.location)

    markdown = render_markdown(report)
    CLOSED_REPORT.parent.mkdir(parents=True, exist_ok=True)
    with open(CLOSED_REPORT, "w", encoding="utf-8", newline="") as f:
        f.write(markdown)

    print(markdown)
    print(f"Wrote {CLOSED_REPORT}")


if __name__ == "__main__":
    main()
