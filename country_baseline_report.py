#!/usr/bin/env python3
"""Per-country Google rating baselines from enriched visited places.

Joins places_classified.json with ratings_cache.json and reports, per
country, how ratings distribute (n, mean, median, std) — the raw material
for the rating-inflation-by-country essay and the gem-score normalization.

Usage:
    python country_baseline_report.py               # table + CSV
    python country_baseline_report.py --min-n 30    # stricter cutoff
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

from file_writers import write_csv_rows
from gem_score import RATINGS_CACHE, country_of
from settings import CLASSIFIED_JSON, OUTPUT_DIR

COUNTRY_BASELINES_CSV = OUTPUT_DIR / "country_baselines.csv"

DEFAULT_MIN_N = 15


def country_stats(classified: list[dict], cache: dict, min_n: int = DEFAULT_MIN_N) -> list[dict]:
    """Rows of per-country rating stats, sorted by mean descending."""
    by_country = defaultdict(list)
    for p in classified:
        entry = cache.get(p.get("id") or "", {})
        if entry.get("status") != "ok":
            continue
        by_country[country_of(p)].append(entry["rating"])

    rows = []
    for country, ratings in by_country.items():
        if country == "Unknown" or len(ratings) < min_n:
            continue
        rows.append(
            {
                "country": country,
                "n": len(ratings),
                "mean": round(statistics.fmean(ratings), 3),
                "median": round(statistics.median(ratings), 2),
                "std": round(statistics.pstdev(ratings), 3),
            }
        )
    rows.sort(key=lambda r: (-r["mean"], r["country"]))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=CLASSIFIED_JSON)
    parser.add_argument("--cache", type=Path, default=RATINGS_CACHE)
    parser.add_argument("--min-n", type=int, default=DEFAULT_MIN_N)
    parser.add_argument("--output", type=Path, default=COUNTRY_BASELINES_CSV)
    args = parser.parse_args()

    classified = json.loads(args.input.read_text(encoding="utf-8"))
    cache = json.loads(args.cache.read_text(encoding="utf-8"))
    rows = country_stats(classified, cache, args.min_n)

    total = sum(r["n"] for r in rows)
    print(f"{'country':<16}{'n':>6}{'mean':>8}{'median':>8}{'std':>7}")
    for r in rows:
        print(f"{r['country']:<16}{r['n']:>6}{r['mean']:>8.3f}{r['median']:>8.2f}{r['std']:>7.3f}")
    print(f"\n{len(rows)} countries with n >= {args.min_n}; {total} rated places")

    write_csv_rows(args.output, ["country", "n", "mean", "median", "std"], rows)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
