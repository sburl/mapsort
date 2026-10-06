#!/usr/bin/env python3
"""Report the most statistically overrated places: the inverse gem score.

Overrated = famous (top decile of review counts for its city) AND rated
below the country baseline (rating_z < 0). Sorted worst-first.

Usage:
    python overrated_report.py                 # top 20
    python overrated_report.py --top 10 --location "San Francisco"
"""

from __future__ import annotations

import argparse
import json

from gem_score import GEM_SCORES


def overrated(scored: list[dict], location: str | None = None) -> list[dict]:
    """Famous places rated below their country baseline, worst first."""
    rows = [
        p for p in scored
        if p.get("famous") and p.get("rating_z", 0) < 0
        and (location is None or location in p.get("locations", []))
    ]
    rows.sort(key=lambda p: p["rating_z"])
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=20, help="rows to print")
    parser.add_argument("--location", default=None, help="restrict to one location")
    args = parser.parse_args()

    scored = json.loads(GEM_SCORES.read_text(encoding="utf-8"))
    rows = overrated(scored, args.location)
    print(f"{len(rows)} overrated places (famous + below country baseline)\n")
    for p in rows[: args.top]:
        locs = ", ".join(p.get("locations", [])) or "-"
        print(
            f"{p['rating_z']:6.2f}  {p['rating']:.1f}★ ({p['review_count']:>6})  "
            f"{p['name']}  [{locs}]"
        )


if __name__ == "__main__":
    main()
