#!/usr/bin/env python3
"""Taste self-portrait: what a decade of saved places reveals.

Reads places_classified.json and reports, with no ratings needed:
  a) visited-to-saved conversion rate per location (>= 30 places)
  b) category mix, and which categories get visited vs hoarded
  c) save-date recency (skipped gracefully when dates are absent)
  d) shared-list stats as counts only — list names are never printed
     (they contain friends' names)

Writes output/taste_report.json and prints a readable report.

Usage:
    python taste_report.py
"""

from __future__ import annotations

import json
from collections import Counter

from generate_travel_guides import LOCATIONS
from settings import CLASSIFIED_JSON, OUTPUT_DIR

TASTE_REPORT = OUTPUT_DIR / "taste_report.json"

MIN_PLACES_PER_LOCATION = 30

CATEGORY_NAMES = {
    1: "Restaurants", 2: "Quick Bites", 3: "Cafes & Bakeries",
    4: "Sweets & Snacks", 5: "Bars & Nightlife", 6: "Hotels & Stays",
    7: "Museums & Culture", 8: "Landmarks & History", 9: "Sacred Sites",
    10: "Parks & Gardens", 11: "Nature & Outdoors", 12: "Shopping",
    13: "Entertainment", 14: "Airports", 15: "Train & Transit",
    16: "Practical", 17: "Regions & Destinations", 18: "Scuba & Diving",
    19: "Ski Resorts",
}

FOOD_CATEGORIES = {1, 2, 3, 4, 5}


def locations_of(lat: float, lng: float) -> list[str]:
    return [
        name for name, (s, w, n, e) in LOCATIONS.items()
        if s <= lat <= n and w <= lng <= e
    ]


def conversion_by_location(places: list[dict]) -> list[dict]:
    visited = Counter()
    total = Counter()
    for p in places:
        if not p.get("lat") or not p.get("lng"):
            continue
        for loc in locations_of(p["lat"], p["lng"]):
            total[loc] += 1
            if p.get("tier") == "visited":
                visited[loc] += 1
    rows = [
        {
            "location": loc,
            "visited": visited[loc],
            "saved": total[loc],
            "conversion": round(visited[loc] / total[loc], 3),
        }
        for loc in total
        if total[loc] >= MIN_PLACES_PER_LOCATION
    ]
    rows.sort(key=lambda r: -r["conversion"])
    return rows


def category_mix(places: list[dict]) -> dict:
    overall = Counter()
    visited = Counter()
    for p in places:
        cat = p.get("category")
        if cat is None:
            continue
        overall[cat] += 1
        if p.get("tier") == "visited":
            visited[cat] += 1

    total = sum(overall.values())
    food = sum(v for c, v in overall.items() if c in FOOD_CATEGORIES)
    rows = []
    for cat, count in overall.most_common():
        rows.append(
            {
                "category": CATEGORY_NAMES.get(cat, str(cat)),
                "saved": count,
                "visited": visited[cat],
                "share": round(count / total, 3),
                "conversion": round(visited[cat] / count, 3),
            }
        )
    return {
        "total_classified": total,
        "food_share": round(food / total, 3),
        "categories": rows,
    }


def date_stats(places: list[dict]) -> dict:
    usable = [p for p in places if (p.get("date") or "").strip()]
    return {"places_with_dates": len(usable), "total": len(places)}


def shared_list_stats(places: list[dict]) -> dict:
    """Counts only. List names contain friends' names and are never emitted."""
    named = 0
    distinct: set[str] = set()
    for p in places:
        lists = (p.get("source_lists") or "").strip()
        if not lists:
            continue
        if "(" in lists:  # shared lists carry an owner tag in parentheses
            named += 1
        distinct.add(lists)
    return {
        "places_from_shared_lists": named,
        "distinct_source_list_combos": len(distinct),
    }


def build_report(places: list[dict]) -> dict:
    return {
        "total_places": len(places),
        "tiers": dict(Counter(p.get("tier") for p in places)),
        "conversion_by_location": conversion_by_location(places),
        "category_mix": category_mix(places),
        "date_stats": date_stats(places),
        "shared_lists": shared_list_stats(places),
    }


def print_report(report: dict) -> None:
    tiers = report["tiers"]
    print(f"{report['total_places']} places | {tiers.get('visited', 0)} visited, "
          f"{tiers.get('want_to_go', 0)} want-to-go")

    print("\n== Conversion by location (visited/saved) ==")
    rows = report["conversion_by_location"]
    for r in rows[:10]:
        print(f"  {r['conversion']:5.0%}  {r['location']:22} {r['visited']:4}/{r['saved']}")
    print("  ...")
    for r in rows[-10:]:
        print(f"  {r['conversion']:5.0%}  {r['location']:22} {r['visited']:4}/{r['saved']}")

    mix = report["category_mix"]
    print(f"\n== Category mix (food share {mix['food_share']:.0%}) ==")
    for r in mix["categories"][:8]:
        print(f"  {r['share']:5.1%}  {r['category']:22} conv {r['conversion']:.0%}")

    ds = report["date_stats"]
    print(f"\nDates usable on {ds['places_with_dates']}/{ds['total']} places")
    sl = report["shared_lists"]
    print(f"Shared-list places: {sl['places_from_shared_lists']} "
          f"({sl['distinct_source_list_combos']} distinct list combos)")


def main() -> None:
    places = json.loads(CLASSIFIED_JSON.read_text(encoding="utf-8"))
    report = build_report(places)
    with open(TASTE_REPORT, "w", encoding="utf-8", newline="") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print_report(report)
    print(f"\nwrote {TASTE_REPORT}")


if __name__ == "__main__":
    main()
