#!/usr/bin/env python3
"""Score visited places as "hidden gems": highly rated, under-reviewed.

Reads places_classified.json + ratings_cache.json (from enrich_ratings.py)
and writes output/gem_scores.json. The score favors places whose rating is
high *for their country* and whose review count is low *for their city*:

    gem = rating_z_country - POPULARITY_WEIGHT * log10(review_count)

with guardrails:
  - places with < MIN_REVIEWS reviews are dropped (rating too noisy)
  - the top REVIEW_CUT_QUANTILE of review counts per location is dropped
    (the no-Louvre rule: famous places self-eject)

Country rating baselines are computed from our own enriched places and
shrunk toward the global mean so small countries aren't over-trusted.

Usage:
    python gem_score.py                 # write gem_scores.json
    python gem_score.py --top 15 --location "Paris"   # sanity-check a city
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from collections import defaultdict

from category_overrides import apply_overrides
from excluded_places import is_excluded
from generate_travel_guides import LOCATIONS
from settings import CLASSIFIED_JSON, OUTPUT_DIR

RATINGS_CACHE = OUTPUT_DIR / "ratings_cache.json"
GEM_SCORES = OUTPUT_DIR / "gem_scores.json"
# Written by enrich_descriptions.py; absent until that has run.
DESCRIPTIONS_CACHE = OUTPUT_DIR / "descriptions_cache.json"
# Model-written one-liners. Kept apart from Google's own blurbs so a guide
# can say which of its sentences were generated rather than sourced.
AI_DESCRIPTIONS = OUTPUT_DIR / "ai_descriptions.json"

# Enough reviews for the rating to mean something.
MIN_REVIEWS = 30
# A floor on the rating itself. The gem score is relative to a country, so
# without this a mediocre place in a harshly-rated country can out-score a
# good one elsewhere and get recommended on a 3.6.
MIN_RATING = 4.0
CLOSED_PERMANENTLY = "CLOSED_PERMANENTLY"

# A chain is never a hidden gem, however well it rates. Two signals:
#
#  1. The same name in several distant places. Applied ONLY to food and
#     retail: landmarks legitimately share generic names, and this would
#     otherwise drop "Victory Monument", "Trinity Church" and "Rodin Museum",
#     which are genuinely different places.
#  2. A seed list, for chains represented by a single outlet in the dataset
#     (one Arby's, one Subway) that repetition alone cannot catch.
CHAIN_PRONE_CATEGORIES = frozenset({1, 2, 3, 4, 5, 12})  # food, drink, shopping
CHAIN_MIN_AREAS = 2

POPULARITY_WEIGHT = 0.35
REVIEW_CUT_QUANTILE = 0.90  # drop the most-reviewed 10% per location
COUNTRY_SHRINKAGE = 30      # pseudo-count pulling small countries to global

_KNOWN_CHAINS = re.compile(
    r"\b(?:arby|mcdonald|burger king|subway|taco bell|kfc|dunkin|domino|"
    r"pizza hut|olive garden|applebee|chili's|denny|ihop|five guys|"
    r"shake shack|popeye|wingstop|costco|walmart|cvs|walgreen|7-eleven|"
    r"familymart|lawson|dairy queen|sonic drive|whataburger|panda express|"
    r"chipotle|panera|chick-fil|in-n-out|sweetgreen|jamba|starbucks|"
    r"wendy's|the home depot|target|rei|trader joe|whole foods|"
    r"pret a manger|le pain quotidien|mister donut|krispy kreme)\b",
    re.IGNORECASE,
)


def _area_key(place: dict) -> tuple:
    """Coarse location bucket for deciding whether a name repeats."""
    return (round(place["lat"], 1), round(place["lng"], 1))


def mark_chains(rated: list[dict]) -> int:
    """Flag chain outlets in place. Returns how many were flagged."""
    areas = defaultdict(set)
    for p in rated:
        if p["category"] in CHAIN_PRONE_CATEGORIES:
            areas[p["name"].strip().casefold()].add(_area_key(p))

    flagged = 0
    for p in rated:
        name = p["name"].strip()
        repeated = (
            p["category"] in CHAIN_PRONE_CATEGORIES
            and len(areas.get(name.casefold(), ())) >= CHAIN_MIN_AREAS
        )
        p["chain"] = bool(repeated or _KNOWN_CHAINS.search(name))
        flagged += p["chain"]
    return flagged


_US_STATE_ZIP = re.compile(r"^[A-Z]{2} \d{5}(-\d{4})?$")
_US_ZIP_ONLY = re.compile(r"^\d{5}(-\d{4})?$")


def country_of(place: dict) -> str:
    address = (place.get("address") or "").strip()
    if not address:
        return "Unknown"
    # Gulf addresses are dash-separated, so the comma split returns the whole
    # string and the digit guard below then rejects it as "Unknown".
    separator = "," if "," in address else (" - " if " - " in address else ",")
    tail = address.split(separator)[-1].strip()
    if not tail:
        return "Unknown"
    # US addresses often end "NY 10003" or a bare zip, not "United States".
    if _US_STATE_ZIP.match(tail) or _US_ZIP_ONLY.match(tail):
        return "United States"
    # A tail matching the place name means the "address" is no address at all.
    name = (place.get("resolved_name") or place.get("name") or "").strip()
    if tail == name or any(ch.isdigit() for ch in tail):
        return "Unknown"
    return tail


def _bbox_area(box: tuple[float, float, float, float]) -> float:
    s, w, n, e = box
    return max(n - s, 0.0) * max(e - w, 0.0)


def locations_of(lat: float, lng: float) -> list[str]:
    """The single most specific location containing this point.

    Boxes nest — a Manhattan restaurant sits inside New York, Greater New
    York and (if it existed) the whole eastern seaboard. Returning all of
    them put the same place in several guides and made the broad regions
    duplicates of the cities inside them. The smallest containing box wins,
    so each place appears in exactly one guide and a regional guide becomes
    "everything here that isn't already its own city".
    """
    matches = [
        (name, box)
        for name, box in LOCATIONS.items()
        if box[0] <= lat <= box[2] and box[1] <= lng <= box[3]
    ]
    if not matches:
        return []
    # Ties broken by name so the assignment is stable across runs.
    best = min(matches, key=lambda m: (_bbox_area(m[1]), m[0]))
    return [best[0]]


def country_baselines(rated: list[dict]) -> dict[str, tuple[float, float]]:
    """Per-country (mean, std) of ratings, shrunk toward the global mean."""
    ratings = [p["rating"] for p in rated]
    global_mean = statistics.fmean(ratings)
    global_std = statistics.pstdev(ratings) or 0.25

    by_country = defaultdict(list)
    for p in rated:
        by_country[p["country"]].append(p["rating"])

    baselines = {}
    for country, vals in by_country.items():
        n = len(vals)
        mean = (statistics.fmean(vals) * n + global_mean * COUNTRY_SHRINKAGE) / (
            n + COUNTRY_SHRINKAGE
        )
        std = statistics.pstdev(vals) if n >= COUNTRY_SHRINKAGE else global_std
        baselines[country] = (mean, max(std, 0.1))
    baselines["Unknown"] = (global_mean, global_std)
    return baselines


def score_places(classified: list[dict], cache: dict) -> list[dict]:
    rated = []
    for p in classified:
        entry = cache.get(p.get("id") or "", {})
        if entry.get("status") != "ok":
            continue
        if entry.get("user_rating_count", 0) < MIN_REVIEWS:
            continue
        if (entry.get("rating") or 0) < MIN_RATING:
            continue
        # Never recommend a business Google reports as permanently closed.
        # Entries enriched before businessStatus was captured lack the key
        # entirely; those stay eligible rather than being dropped wholesale.
        if entry.get("business_status") == CLOSED_PERMANENTLY:
            continue
        rated.append(
            {
                "id": p["id"],
                "name": (p.get("resolved_name") or p["name"]).strip(),
                "lat": p["lat"],
                "lng": p["lng"],
                "category": p.get("category"),
                "tier": p.get("tier"),
                "address": (p.get("address") or "").strip(),
                "cid": p.get("cid"),
                "country": country_of(p),
                "locations": locations_of(p["lat"], p["lng"]),
                "rating": entry["rating"],
                "review_count": entry["user_rating_count"],
            }
        )
    if not rated:
        return []

    baselines = country_baselines(rated)

    # No-Louvre rule: per location, find the review-count cutoff.
    counts_by_loc = defaultdict(list)
    for p in rated:
        for loc in p["locations"]:
            counts_by_loc[loc].append(p["review_count"])
    cutoff_by_loc = {}
    for loc, counts in counts_by_loc.items():
        counts.sort()
        idx = min(int(len(counts) * REVIEW_CUT_QUANTILE), len(counts) - 1)
        cutoff_by_loc[loc] = counts[idx]

    for p in rated:
        mean, std = baselines.get(p["country"], baselines["Unknown"])
        z = (p["rating"] - mean) / std
        p["rating_z"] = round(z, 3)
        p["gem_score"] = round(z - POPULARITY_WEIGHT * math.log10(p["review_count"]), 3)
        p["famous"] = any(
            p["review_count"] > cutoff_by_loc[loc] for loc in p["locations"]
        )

    mark_chains(rated)
    rated.sort(key=lambda p: -p["gem_score"])
    return rated


# Guide sections: category ids collapsed into reader-facing groups.
GUIDE_GROUPS: list[tuple[str, frozenset[int]]] = [
    ("Where to Eat", frozenset({1, 2})),          # restaurants, quick bites
    ("Coffee & Sweets", frozenset({3, 4})),       # cafes/bakeries, sweets
    ("Where to Drink", frozenset({5})),           # bars & nightlife
    ("See & Do", frozenset({7, 8, 9, 12, 13})),   # museums, landmarks, sacred, shopping, entertainment
    ("Outdoors", frozenset({10, 11, 17, 18, 19})),  # parks, nature, regions, scuba, ski
]


# Two saves of one venue land on the same pin or a few metres from it.
# Distinct businesses this close are rare enough that losing one from a
# top-five list costs less than printing the same place twice.
SAME_PLACE_METRES = 30.0


def _metres_apart(a: dict, b: dict) -> float:
    """Equirectangular approximation — exact enough at 30m scale."""
    dlat = math.radians(a["lat"] - b["lat"])
    dlng = math.radians(a["lng"] - b["lng"])
    mlat = math.radians((a["lat"] + b["lat"]) / 2)
    x = dlng * math.cos(mlat)
    return 6371000.0 * math.hypot(x, dlat)


def dedupe_places(rows: list[dict]) -> list[dict]:
    """Drop repeat saves of the same venue, keeping the best-scoring one.

    The same place gets saved twice under different names — "OZONE" and
    "OZONE | The Ritz-Carlton, Hong Kong" are one bar, with review counts
    15 apart. Name matching alone misses those, so proximity decides too.
    Distance rather than a rounded grid, because two pins 9m apart can
    still straddle a bucket edge. Input is sorted best-first, so the first
    of a pair wins.
    """
    seen_names: set[str] = set()
    kept: list[dict] = []
    for p in rows:
        name_key = p["name"].strip().casefold()
        if name_key in seen_names:
            continue
        if p.get("lat") is not None and any(
            k.get("lat") is not None and _metres_apart(p, k) <= SAME_PLACE_METRES
            for k in kept
        ):
            continue
        seen_names.add(name_key)
        kept.append(p)
    return kept


def _load_blurbs(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def attach_descriptions(scored: list[dict]) -> dict[str, int]:
    """Fold in one-line descriptions, Google's in preference to the model's.

    Google's editorial blurbs are sourced; the model's are inferred from a
    name and a category. Both carry `description_source` so a guide can
    disclose which it is showing rather than blur them together.
    """
    google = _load_blurbs(DESCRIPTIONS_CACHE)
    ai = _load_blurbs(AI_DESCRIPTIONS)
    counts = {"google": 0, "ai": 0}
    for p in scored:
        pid = p.get("id") or ""
        for source, blurbs in (("google", google), ("ai", ai)):
            entry = blurbs.get(pid, {})
            if entry.get("status") == "ok" and entry.get("description"):
                p["description"] = entry["description"]
                p["description_source"] = source
                counts[source] += 1
                break
    return counts


def guide_sections(scored: list[dict], location: str, per_group: int = 5) -> list[tuple[str, list[dict]]]:
    """Top gems per category group for one location.

    Excludes the famous (top-decile review count) and chain outlets.
    """
    rows = [
        p for p in scored
        if location in p["locations"]
        and not p["famous"]
        and not p.get("chain")
        and not is_excluded(p)
    ]
    rows = dedupe_places(rows)

    sections = []
    for title, cats in GUIDE_GROUPS:
        hits = [p for p in rows if p["category"] in cats][:per_group]
        if hits:
            sections.append((title, hits))
    return sections


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=0, help="print top N gems")
    parser.add_argument("--location", default=None, help="restrict printout to one location")
    parser.add_argument(
        "--tier", choices=["visited", "want_to_go"], default=None,
        help="restrict printout to one tier; want_to_go = gems you haven't been to yet",
    )
    parser.add_argument("--guide", action="store_true", help="print grouped guide sections for --location")
    parser.add_argument("--per-group", type=int, default=5, help="places per section in --guide mode")
    args = parser.parse_args()

    classified = json.loads(CLASSIFIED_JSON.read_text(encoding="utf-8"))
    apply_overrides(classified)
    cache = json.loads(RATINGS_CACHE.read_text(encoding="utf-8"))
    scored = score_places(classified, cache)
    blurbs = attach_descriptions(scored)

    with open(GEM_SCORES, "w", encoding="utf-8", newline="") as f:
        json.dump(scored, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"Scored {len(scored)} places -> {GEM_SCORES}")
    if any(blurbs.values()):
        print(f"  descriptions: {blurbs['google']} from Google, {blurbs['ai']} model-written")

    shown = [p for p in scored if args.tier is None or p.get("tier") == args.tier]

    if args.guide:
        if not args.location:
            parser.error("--guide requires --location")
        for title, hits in guide_sections(shown, args.location, args.per_group):
            print(f"\n## {title}")
            for p in hits:
                print(f"  {p['gem_score']:6.2f}  {p['rating']:.1f}★ ({p['review_count']:>6})  {p['name']}")
        return

    if args.top:
        rows = [
            p for p in shown
            if not p["famous"]
            and (args.location is None or args.location in p["locations"])
        ]
        for p in rows[: args.top]:
            print(
                f"{p['gem_score']:6.2f}  {p['rating']:.1f}★ ({p['review_count']:>6})  "
                f"{p['name']}  [{p['country']}]"
            )


if __name__ == "__main__":
    main()
