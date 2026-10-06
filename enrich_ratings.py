#!/usr/bin/env python3
"""Enrich visited places with Google ratings via the Places API (New).

Two-phase, cache-resumable, free-tier-aware:

  Phase 1 (Text Search, Essentials SKU — 10k free/month):
      resolve each place's name + coordinates to a Places API place_id.
  Phase 2 (Place Details with rating fields, Enterprise SKU — 1k free/month):
      fetch rating + userRatingCount + businessStatus for resolved places.
      businessStatus is a Pro-SKU field, but a request is billed once at the
      highest SKU it touches, so riding along with the Enterprise rating
      fields costs nothing extra.

Every result (including failures) is cached in output/ratings_cache.json,
so re-running skips completed places. The --limit flag caps NEW Place
Details calls per run (default 950) to stay inside the monthly free tier;
run it once a month until the "remaining" count hits zero.

Usage:
    GOOGLE_MAPS_API_KEY=... python enrich_ratings.py            # one batch
    python enrich_ratings.py --dry-run                          # progress only
    GOOGLE_MAPS_API_KEY=... python enrich_ratings.py --limit 50 # small test
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.request
from pathlib import Path

from category_overrides import apply_overrides
from settings import BASE_DIR, CLASSIFIED_JSON, OUTPUT_DIR

RATINGS_CACHE = OUTPUT_DIR / "ratings_cache.json"


def load_dotenv_key() -> str:
    """Read GOOGLE_MAPS_API_KEY from the environment, falling back to .env."""
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if key:
        return key
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, _, value = line.strip().partition("=")
            if name == "GOOGLE_MAPS_API_KEY":
                return value.strip().strip('"').strip("'")
    return ""

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"

# Categories excluded from guides (hotels/practical/airports/transit).
PRIVATE_CATEGORIES = frozenset({6, 14, 15, 16})

# A text-search hit further than this from our coordinates is a mismatch.
MAX_MATCH_DISTANCE_M = 300.0

# Recorded when Place Details returns no businessStatus at all. Distinct from
# a missing "business_status" key, which means the entry predates this field.
UNKNOWN_BUSINESS_STATUS = "UNKNOWN"

# Guides need MIN_PER_SECTION places in a category group before that section
# appears at all, and show at most PER_GROUP. So the marginal value of rating
# a place is highest when its (location, group) bucket is still below the
# threshold — that call unlocks a whole section — and near zero once the
# bucket is full. Ordering by that beats any hand-written city list.
SECTION_MIN = 3     # mirrors generate_gem_guides.MIN_PER_SECTION
SECTION_FULL = 5    # mirrors generate_gem_guides.PER_GROUP
UNLOCK_BONUS = 10   # weight for buckets that would gain a whole section


def _bucket_counts(classified: list[dict], cache: dict) -> dict:
    """How many already-rated places sit in each (location, group) bucket."""
    from gem_score import GUIDE_GROUPS, locations_of

    counts: dict[tuple[str, str], int] = {}
    for p in classified:
        if cache.get(p.get("id") or "", {}).get("status") != "ok":
            continue
        cat = p.get("category")
        group = next((t for t, cats in GUIDE_GROUPS if cat in cats), None)
        if group is None or not p.get("lat"):
            continue
        for loc in locations_of(p["lat"], p["lng"]):
            counts[(loc, group)] = counts.get((loc, group), 0) + 1
    return counts


def leverage_of(place: dict, counts: dict) -> float:
    """Marginal guide value of rating this place. Higher sorts earlier."""
    from gem_score import GUIDE_GROUPS, locations_of

    cat = place.get("category")
    group = next((t for t, cats in GUIDE_GROUPS if cat in cats), None)
    if group is None or not place.get("lat"):
        return 0.0
    best = 0.0
    for loc in locations_of(place["lat"], place["lng"]):
        have = counts.get((loc, group), 0)
        if have >= SECTION_FULL:
            score = 0.0                      # section already full
        elif have < SECTION_MIN:
            score = UNLOCK_BONUS + (SECTION_MIN - have)   # would unlock a section
        else:
            score = SECTION_FULL - have      # deepens an existing section
        best = max(best, score)
    return best


def order_by_leverage(todo: list[dict], classified: list[dict], cache: dict) -> list[dict]:
    """Sort pending places so the highest-leverage calls happen first.

    A bucket's value falls as it fills, so each pending place is scored at
    the position it would actually occupy: the first unrated place in an
    empty (location, group) bucket is worth far more than the sixth. That
    projection is computable in one pass, which keeps this O(n log n) —
    re-scoring greedily after every pick is O(n^2) and too slow at 1,200+.
    """
    from gem_score import GUIDE_GROUPS, locations_of

    counts = _bucket_counts(classified, cache)
    group_of = {c: t for t, cats in GUIDE_GROUPS for c in cats}

    pending: dict[tuple[str, str], int] = {}
    scored: list[tuple[float, int, dict]] = []
    for order, place in enumerate(todo):
        group = group_of.get(place.get("category"))
        if group is None or not place.get("lat"):
            scored.append((0.0, order, place))
            continue
        best = 0.0
        for loc in locations_of(place["lat"], place["lng"]):
            key = (loc, group)
            # Where this place would land once earlier ones in the bucket run.
            projected = counts.get(key, 0) + pending.get(key, 0)
            if projected >= SECTION_FULL:
                score = 0.0
            elif projected < SECTION_MIN:
                score = UNLOCK_BONUS + (SECTION_MIN - projected)
            else:
                score = SECTION_FULL - projected
            best = max(best, score)
            pending[key] = pending.get(key, 0) + 1
        scored.append((best, order, place))

    scored.sort(key=lambda row: (-row[0], row[1]))
    return [place for _, _, place in scored]


REQUEST_DELAY = 0.15  # seconds between API calls
HTTP_TIMEOUT = 20.0


def guide_places(classified: list[dict]) -> list[dict]:
    """Visited, guide-relevant places (mirrors export_site_data filters)."""
    out = []
    for p in classified:
        if p.get("tier") != "visited":
            continue
        cat = p.get("category")
        if cat is None or cat in PRIVATE_CATEGORIES:
            continue
        if not p.get("lat") or not p.get("lng"):
            continue
        if not (p.get("resolved_name") or p.get("name") or "").strip():
            continue
        out.append(p)
    return out


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _request(url: str, api_key: str, field_mask: str, body: dict | None = None) -> dict:
    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": field_mask,
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def search_place_id(place: dict, api_key: str) -> dict:
    """Phase 1: resolve place_id via Text Search (Essentials fields only)."""
    name = (place.get("resolved_name") or place["name"]).strip()
    body = {
        "textQuery": name,
        "locationBias": {
            "circle": {
                "center": {"latitude": place["lat"], "longitude": place["lng"]},
                "radius": 500.0,
            }
        },
        "pageSize": 3,
    }
    result = _request(SEARCH_URL, api_key, "places.id,places.location", body)
    best = None
    for cand in result.get("places", []):
        loc = cand.get("location") or {}
        if "latitude" not in loc:
            continue
        dist = haversine_m(place["lat"], place["lng"], loc["latitude"], loc["longitude"])
        if dist <= MAX_MATCH_DISTANCE_M and (best is None or dist < best["distance_m"]):
            best = {"place_id": cand["id"], "distance_m": round(dist, 1)}
    if best is None:
        return {"status": "no_match"}
    return {"status": "resolved", **best}


def fetch_rating(place_id: str, api_key: str) -> dict:
    """Phase 2: rating + userRatingCount + businessStatus (the scarce call).

    businessStatus is Pro-tier and the rating fields are Enterprise-tier;
    since billing takes the highest SKU in the mask, adding it is free.
    Entries cached before this field existed simply lack "business_status"
    — they are still terminal and must never be re-fetched to backfill it.
    """
    result = _request(
        DETAILS_URL.format(place_id=place_id),
        api_key,
        "id,rating,userRatingCount,businessStatus",
    )
    status = result.get("businessStatus") or UNKNOWN_BUSINESS_STATUS
    if "rating" not in result:
        return {"status": "no_rating", "business_status": status}
    return {
        "status": "ok",
        "rating": result["rating"],
        "user_rating_count": result.get("userRatingCount", 0),
        "business_status": status,
    }


def needs_closure_recheck(cache: dict, shown_ids: set[str] | None = None) -> list[str]:
    """Rated places whose closure status we have never asked about.

    Entries cached before businessStatus joined the field mask are terminal
    for rating purposes, so the normal resume logic will never revisit them
    and a place that shut in the meantime stays in the guides. Scoped to
    places a guide actually prints, since a closure nobody can see costs a
    reader nothing and the quota is finite.
    """
    stale = [
        pid for pid, entry in cache.items()
        if entry.get("status") == "ok" and "business_status" not in entry
    ]
    if shown_ids is not None:
        stale = [pid for pid in stale if pid in shown_ids]
    return sorted(stale)


def shown_in_guides() -> set[str]:
    """Ids printed in at least one guide."""
    from gem_score import GEM_SCORES, guide_sections
    from generate_travel_guides import LOCATIONS

    scored = json.loads(GEM_SCORES.read_text(encoding="utf-8"))
    ids = set()
    for location in LOCATIONS:
        for _, hits in guide_sections(scored, location, 5):
            ids.update(p["id"] for p in hits)
    return ids


def load_cache() -> dict:
    if RATINGS_CACHE.exists():
        return json.loads(RATINGS_CACHE.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict) -> None:
    RATINGS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(RATINGS_CACHE, "w", encoding="utf-8", newline="") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=CLASSIFIED_JSON)
    parser.add_argument(
        "--limit", type=int, default=950,
        help="max NEW Place Details (Enterprise SKU) calls this run",
    )
    parser.add_argument("--dry-run", action="store_true", help="report progress, no API calls")
    parser.add_argument(
        "--recheck-closures", action="store_true",
        help="re-fetch places rated before businessStatus was captured",
    )
    parser.add_argument(
        "--all-places", action="store_true",
        help="with --recheck-closures, include places no guide prints",
    )
    args = parser.parse_args()

    classified = json.loads(args.input.read_text(encoding="utf-8"))
    apply_overrides(classified)
    places = guide_places(classified)
    cache = load_cache()

    if args.recheck_closures:
        shown = None if args.all_places else shown_in_guides()
        stale = needs_closure_recheck(cache, shown)
        scope = "all rated places" if args.all_places else "places shown in guides"
        print(f"{len(stale)} {scope} have never been closure-checked")
        if args.dry_run or not stale:
            return
        api_key = load_dotenv_key()
        if not api_key:
            sys.exit("GOOGLE_MAPS_API_KEY is not set (env var or .env file)")
        used = 0
        try:
            for pid in stale:
                if used >= args.limit:
                    break
                place_id = cache[pid].get("place_id")
                if not place_id:
                    cache[pid]["business_status"] = UNKNOWN_BUSINESS_STATUS
                    continue
                time.sleep(REQUEST_DELAY)
                cache[pid].update(fetch_rating(place_id, api_key))
                used += 1
                if used % 50 == 0:
                    save_cache(cache)
                    print(f"  ...{used} re-checks used")
        finally:
            save_cache(cache)
        closed = sum(
            1 for pid in stale
            if cache[pid].get("business_status") == "CLOSED_PERMANENTLY"
        )
        print(f"Re-checked {used}; {closed} turned out to be permanently closed.")
        print(f"~{max(len(stale) - used, 0)} still stale.")
        return

    terminal = {"ok", "no_rating", "no_match"}
    done_ids = {p["id"] for p in places if cache.get(p["id"], {}).get("status") in terminal}
    todo = [p for p in places if p["id"] not in done_ids]
    todo = order_by_leverage(todo, places, cache)
    print(f"{len(places)} guide places | {len(done_ids)} enriched/terminal | {len(todo)} remaining")

    if args.dry_run or not todo:
        return

    api_key = load_dotenv_key()
    if not api_key:
        sys.exit("GOOGLE_MAPS_API_KEY is not set (env var or .env file)")

    details_used = 0
    try:
        for p in todo:
            if details_used >= args.limit:
                break
            entry = cache.get(p["id"], {})
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
            if details_used % 50 == 0:
                save_cache(cache)
                print(f"  ...{details_used} detail calls used")
    finally:
        save_cache(cache)

    remaining = len(todo) - details_used
    print(f"Used {details_used} Place Details calls; ~{max(remaining, 0)} places remain.")
    if remaining > 0:
        print("Run again next month to stay within the free tier (or raise --limit).")


if __name__ == "__main__":
    main()
