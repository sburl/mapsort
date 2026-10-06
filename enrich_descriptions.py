#!/usr/bin/env python3
"""Fetch Google's own one-line description for places shown in guides.

Uses `editorialSummary` — Google's editorial blurb — rather than asking a
model to write one. For ~800 mostly-obscure venues an LLM has nothing real
to draw on and will produce confident fiction about actual small
businesses, which a "may be hallucinated" disclaimer does not make safe.
Google either has a blurb or it does not, and "not" is a fine answer.

COST: editorialSummary sits in the Place Details Enterprise + Atmosphere
SKU, which is metered separately from the rating fields. Only places that
actually appear in a guide are fetched (~800, not the full 3,243), and
--limit caps each run. Results cache separately from ratings_cache.json so
a failure here can never cost us the rating data.

Usage:
    python enrich_descriptions.py --dry-run      # how many, no API calls
    python enrich_descriptions.py --limit 900    # one batch
"""

from __future__ import annotations

import argparse
import json
import time

from enrich_ratings import (
    DETAILS_URL,
    REQUEST_DELAY,
    _request,
    load_dotenv_key,
)
from gem_score import GEM_SCORES
from settings import OUTPUT_DIR

DESCRIPTIONS_CACHE = OUTPUT_DIR / "descriptions_cache.json"
RATINGS_CACHE = OUTPUT_DIR / "ratings_cache.json"

# Enterprise + Atmosphere. Keep the mask minimal: every extra field risks
# pushing the request into a dearer SKU for no gain.
FIELD_MASK = "id,editorialSummary"


def shown_place_ids(scored: list[dict], per_group: int = 5) -> list[str]:
    """Ids of places that actually appear in a guide.

    Scoring covers every rated place, but only the top few per section are
    ever printed. Fetching the rest would be paying for text nobody reads.
    """
    from gem_score import guide_sections
    from generate_travel_guides import LOCATIONS

    ids: list[str] = []
    seen: set[str] = set()
    for location in LOCATIONS:
        for _, hits in guide_sections(scored, location, per_group):
            for p in hits:
                pid = p.get("id")
                if pid and pid not in seen:
                    seen.add(pid)
                    ids.append(pid)
    return ids


def fetch_description(place_id: str, api_key: str) -> dict:
    """One blurb. Absence is recorded so we never ask for it twice."""
    result = _request(DETAILS_URL.format(place_id=place_id), api_key, FIELD_MASK)
    summary = (result.get("editorialSummary") or {}).get("text", "").strip()
    if not summary:
        return {"status": "none"}
    return {"status": "ok", "description": summary}


def load_cache(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_cache(cache: dict) -> None:
    DESCRIPTIONS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(DESCRIPTIONS_CACHE, "w", encoding="utf-8", newline="") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=900)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    scored = json.loads(GEM_SCORES.read_text(encoding="utf-8"))
    ratings = load_cache(RATINGS_CACHE)
    cache = load_cache(DESCRIPTIONS_CACHE)

    wanted = shown_place_ids(scored)
    todo = [pid for pid in wanted if pid not in cache]
    have = sum(1 for v in cache.values() if v.get("status") == "ok")
    print(f"{len(wanted)} places shown in guides | {len(cache)} checked "
          f"({have} with a blurb) | {len(todo)} remaining")

    if args.dry_run or not todo:
        return

    api_key = load_dotenv_key()
    if not api_key:
        raise SystemExit("GOOGLE_MAPS_API_KEY is not set (env var or .env file)")

    used = 0
    try:
        for pid in todo:
            if used >= args.limit:
                break
            # The ratings pass already resolved every id to a Places id.
            entry = ratings.get(pid) or {}
            place_id = entry.get("place_id")
            if not place_id:
                cache[pid] = {"status": "unresolved"}
                continue
            time.sleep(REQUEST_DELAY)
            cache[pid] = fetch_description(place_id, api_key)
            used += 1
            if used % 50 == 0:
                save_cache(cache)
                print(f"  ...{used} calls used")
    finally:
        save_cache(cache)

    got = sum(1 for v in cache.values() if v.get("status") == "ok")
    print(f"Used {used} calls; {got} places now have a description.")
    print(f"~{max(len(todo) - used, 0)} remaining.")


if __name__ == "__main__":
    main()
