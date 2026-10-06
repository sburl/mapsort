#!/usr/bin/env python3
"""Pre-trip hit list: rank the WANT-TO-GO backlog for one city by gem score.

Default run is an offline cost preview — how many places are saved there,
how many already have cached ratings, and how many NEW rating lookups
(Enterprise SKU, 1,000 free/month shared with the monthly batch) a full
enrichment would take. Nothing touches the API unless --fetch is passed.

Usage:
    python trip_list.py --location Lisbon                 # preview + ranking from cache
    python trip_list.py --location Lisbon --fetch --budget 100
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from enrich_ratings import (
    PRIVATE_CATEGORIES,
    REQUEST_DELAY,
    fetch_rating,
    load_cache,
    load_dotenv_key,
    save_cache,
    search_place_id,
)
from gem_score import guide_sections, score_places
from generate_travel_guides import LOCATIONS
from settings import CLASSIFIED_JSON

TERMINAL_STATUSES = {"ok", "no_rating", "no_match"}
SUGGESTED_MAX_BUDGET = 200


def want_to_go_places(classified: list[dict], location: str) -> list[dict]:
    """Want-to-go places inside the location's bounding box."""
    if location not in LOCATIONS:
        sys.exit(f"Unknown location {location!r}. Known: {', '.join(sorted(LOCATIONS))}")
    s, w, n, e = LOCATIONS[location]
    out = []
    for p in classified:
        if p.get("tier") != "want_to_go":
            continue
        cat = p.get("category")
        if cat is None or cat in PRIVATE_CATEGORIES:
            continue
        if not p.get("lat") or not p.get("lng"):
            continue
        if not (p.get("resolved_name") or p.get("name") or "").strip():
            continue
        if s <= p["lat"] <= n and w <= p["lng"] <= e:
            out.append(p)
    return out


def preview_counts(places: list[dict], cache: dict) -> tuple[int, int, int]:
    """(backlog_total, already_cached_terminal, new_lookups_needed)."""
    total = len(places)
    cached = sum(
        1 for p in places if cache.get(p["id"], {}).get("status") in TERMINAL_STATUSES
    )
    return total, cached, total - cached


def enrich_budget(places: list[dict], cache: dict, api_key: str, budget: int) -> int:
    """Enrich up to `budget` places (rating lookups); returns detail calls used."""
    details_used = 0
    try:
        for p in places:
            if details_used >= budget:
                break
            entry = cache.get(p["id"], {})
            if entry.get("status") in TERMINAL_STATUSES:
                continue
            if entry.get("status") != "resolved":
                time.sleep(REQUEST_DELAY)
                entry = search_place_id(p, api_key)
                cache[p["id"]] = entry
                if entry["status"] == "no_match":
                    continue
            time.sleep(REQUEST_DELAY)
            entry.update(fetch_rating(entry["place_id"], api_key))
            cache[p["id"]] = entry
            details_used += 1
    finally:
        save_cache(cache)
    return details_used


def print_ranking(places: list[dict], cache: dict, location: str, per_group: int) -> int:
    """Score cached want-to-go places and print grouped sections; returns rows shown."""
    scored = score_places(places, cache)
    shown = 0
    for title, hits in guide_sections(scored, location, per_group):
        print(f"\n## {title}")
        for p in hits:
            print(
                f"  {p['gem_score']:6.2f}  {p['rating']:.1f}★ ({p['review_count']:>6})  {p['name']}"
            )
            shown += 1
    if shown == 0:
        print("\nNo rated places yet for this location — run with --fetch --budget N first.")
    return shown


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--location", required=True, help="a LOCATIONS name, e.g. Lisbon")
    parser.add_argument("--fetch", action="store_true", help="actually call the API (costs quota)")
    parser.add_argument("--budget", type=int, default=None, help="max NEW rating lookups (required with --fetch)")
    parser.add_argument("--per-group", type=int, default=5, help="places per section in the ranking")
    args = parser.parse_args()

    classified = json.loads(CLASSIFIED_JSON.read_text(encoding="utf-8"))
    places = want_to_go_places(classified, args.location)
    cache = load_cache()

    total, cached, remaining = preview_counts(places, cache)
    print(f"{args.location}: {total} want-to-go places | {cached} already rated | {remaining} new lookups needed")

    if not args.fetch:
        if remaining:
            print("(preview only — pass --fetch --budget N to enrich; Enterprise free tier is 1,000/month, shared with the monthly batch)")
        print_ranking(places, cache, args.location, args.per_group)
        return

    if args.budget is None:
        sys.exit("--fetch requires an explicit --budget N")
    if args.budget > SUGGESTED_MAX_BUDGET:
        print(f"warning: --budget {args.budget} exceeds the suggested per-trip cap of {SUGGESTED_MAX_BUDGET}")
    api_key = load_dotenv_key()
    if not api_key:
        sys.exit("GOOGLE_MAPS_API_KEY is not set (env var or .env file)")

    used = enrich_budget(places, cache, api_key, args.budget)
    print(f"Used {used} rating lookups (Enterprise free tier: 1,000/month, shared with the monthly batch).")
    print_ranking(places, cache, args.location, args.per_group)


if __name__ == "__main__":
    main()
