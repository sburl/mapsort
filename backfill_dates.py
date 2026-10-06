#!/usr/bin/env python3
"""Restore save timestamps that the pipeline drops.

Google Takeout stamps every saved place with the time it was added, and
those timestamps survive into places_raw.json. They do not survive into
places_classified.json, whose `date` field arrives empty for all 10,463
rows. This joins them back.

Places sourced from list scraping (places_scraped.json) have no timestamp
at any stage and stay empty — that is a limit of the source, not a bug.

Matching is by `id`, skipping the degenerate `name:` id shared by ~472
nameless pins, with a coordinate+name fallback for rows whose id changed
between stages.

Usage:
    python backfill_dates.py --dry-run     # report coverage, write nothing
    python backfill_dates.py               # backfill in place
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from settings import CLASSIFIED_JSON, OUTPUT_DIR

RAW_JSON = OUTPUT_DIR / "places_raw.json"

# Shared by every nameless, address-only pin; useless as an identity.
DEGENERATE_ID = "name:"


def coord_key(place: dict) -> tuple | None:
    lat, lng = place.get("lat"), place.get("lng")
    name = (place.get("name") or "").strip().casefold()
    if lat is None or lng is None or not name:
        return None
    return (name, round(lat, 5), round(lng, 5))


def build_date_index(raw: list[dict]) -> tuple[dict, dict]:
    """Map id -> date and coord_key -> date for rows carrying a timestamp."""
    by_id, by_coord = {}, {}
    for p in raw:
        date = (p.get("date") or "").strip()
        if not date:
            continue
        pid = p.get("id")
        if pid and pid != DEGENERATE_ID:
            by_id.setdefault(pid, date)
        ck = coord_key(p)
        if ck:
            by_coord.setdefault(ck, date)
    return by_id, by_coord


def backfill(classified: list[dict], by_id: dict, by_coord: dict) -> Counter:
    """Fill empty `date` fields in place. Returns a stats counter."""
    stats = Counter()
    for p in classified:
        if (p.get("date") or "").strip():
            stats["already_had_date"] += 1
            continue
        pid = p.get("id")
        date = by_id.get(pid) if pid and pid != DEGENERATE_ID else None
        if date:
            stats["matched_by_id"] += 1
        else:
            date = by_coord.get(coord_key(p))
            if date:
                stats["matched_by_coords"] += 1
        if date:
            p["date"] = date
            stats["filled"] += 1
        else:
            stats["no_timestamp_available"] += 1
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", default=RAW_JSON)
    parser.add_argument("--classified", default=CLASSIFIED_JSON)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    raw = json.loads(Path(args.raw).read_text(encoding="utf-8"))
    classified = json.loads(Path(args.classified).read_text(encoding="utf-8"))

    by_id, by_coord = build_date_index(raw)
    stats = backfill(classified, by_id, by_coord)

    total = len(classified)
    dated = stats["filled"] + stats["already_had_date"]
    print(f"{total} places | {dated} now dated ({100 * dated / total:.0f}%)")
    for key in ("matched_by_id", "matched_by_coords", "no_timestamp_available"):
        print(f"  {key}: {stats[key]}")

    if args.dry_run:
        print("dry run — nothing written")
        return

    with open(args.classified, "w", encoding="utf-8", newline="") as f:
        json.dump(classified, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"wrote {args.classified}")


if __name__ == "__main__":
    main()
