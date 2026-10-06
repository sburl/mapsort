#!/usr/bin/env python3
"""Track when each place first appeared in the dataset.

Google only timestamps places that come through Takeout — the ~5,200
want-to-go places harvested from shared lists have no date at any stage,
and no source to recover one from. But we don't need Google for this
going forward: fingerprint the dataset now, and every later run stamps
whatever is new. The ledger becomes the chronology Google never gave us.

Each place is keyed by refresh_pipeline.identity_key (cid/ftid where
available, else a name+address+coords composite), so a place keeps its
first-seen date even if its id scheme changes between exports.

Entries record where the date came from:
    takeout   — a real save timestamp, trustworthy
    baseline  — present at seeding; the true date is this or EARLIER
    observed  — first appeared in a later run, so the date is accurate

Usage:
    python first_seen.py --seed          # one-time: stamp today's dataset
    python first_seen.py                 # later runs: stamp new arrivals
    python first_seen.py --longest-wanted 20
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter
from pathlib import Path

from refresh_pipeline import identity_key
from settings import CLASSIFIED_JSON, OUTPUT_DIR

LEDGER = OUTPUT_DIR / "first_seen.json"

TAKEOUT, BASELINE, OBSERVED = "takeout", "baseline", "observed"


def load_ledger() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    return {}


def save_ledger(ledger: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER, "w", encoding="utf-8", newline="") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


def update_ledger(places: list[dict], ledger: dict, today: str, seeding: bool) -> Counter:
    """Stamp places not already in the ledger. Existing entries never move."""
    stats = Counter()
    for p in places:
        key = identity_key(p)
        if key in ledger:
            stats["already_tracked"] += 1
            continue
        date = (p.get("date") or "").strip()
        if date:
            ledger[key] = {"first_seen": date[:10], "source": TAKEOUT}
            stats["stamped_takeout"] += 1
        else:
            ledger[key] = {
                "first_seen": today,
                "source": BASELINE if seeding else OBSERVED,
            }
            stats["stamped_baseline" if seeding else "stamped_observed"] += 1
    return stats


def longest_wanted(places: list[dict], ledger: dict, limit: int) -> list[tuple]:
    """Want-to-go places, oldest first-seen first. Baseline rows are floors."""
    rows = []
    for p in places:
        if p.get("tier") != "want_to_go":
            continue
        entry = ledger.get(identity_key(p))
        if not entry:
            continue
        name = (p.get("resolved_name") or p.get("name") or "").strip()
        if not name:
            continue
        rows.append((entry["first_seen"], entry["source"], name, p.get("address") or ""))
    rows.sort(key=lambda r: (r[0], r[2].casefold()))
    return rows[:limit]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--classified", default=CLASSIFIED_JSON)
    parser.add_argument("--seed", action="store_true", help="first run: mark existing places as baseline")
    parser.add_argument("--longest-wanted", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    places = json.loads(Path(args.classified).read_text(encoding="utf-8"))
    ledger = load_ledger()
    if ledger and args.seed:
        raise SystemExit(f"{LEDGER} already exists — drop --seed for incremental runs")
    if not ledger and not args.seed:
        raise SystemExit("no ledger yet — run once with --seed to establish the baseline")

    today = dt.datetime.now(tz=dt.timezone.utc).astimezone().date().isoformat()
    stats = update_ledger(places, ledger, today, seeding=args.seed)

    print(f"{len(places)} places | ledger holds {len(ledger)}")
    for key in ("already_tracked", "stamped_takeout", "stamped_baseline", "stamped_observed"):
        if stats[key]:
            print(f"  {key}: {stats[key]}")
    if stats["stamped_observed"]:
        print(f"\n{stats['stamped_observed']} places are NEW since the last run.")

    if not args.dry_run:
        save_ledger(ledger)
        print(f"wrote {LEDGER}")

    if args.longest_wanted:
        print(f"\nLongest-wanted, still unvisited (top {args.longest_wanted}):")
        for date, source, name, addr in longest_wanted(places, ledger, args.longest_wanted):
            mark = "" if source == TAKEOUT else f" ({source})"
            print(f"  {date}{mark}  {name[:44]}")


if __name__ == "__main__":
    main()
