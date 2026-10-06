#!/usr/bin/env python3
"""Reverse-geocode coordinate-only entries using Nominatim.

Resolves bare lat/lng pins into addresses and place names so they can
be classified downstream. Respects Nominatim's rate limit (1 req/sec).

Usage:
    python reverse_geocode.py                          # process places_raw.json in-place
    python reverse_geocode.py --input in.json --output out.json
    python reverse_geocode.py --dry-run                # preview without writing
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from coord_utils import _coerce_float
from settings import DELAY, NOMINATIM_URL, RAW_JSON, USER_AGENT


def reverse_geocode(
    lat: float,
    lng: float,
    *,
    url: str = NOMINATIM_URL,
    user_agent: str = USER_AGENT,
    timeout: float = 10.0,
) -> dict[str, Any] | None:
    """Call Nominatim reverse API and return the response dict, or None on failure."""
    params = f"?lat={lat}&lon={lng}&format=jsonv2&addressdetails=1"
    req = urllib.request.Request(
        url + params,
        headers={"User-Agent": user_agent, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def extract_place_info(result: dict[str, Any]) -> tuple[str, str]:
    """Extract a useful (name, address) pair from a Nominatim response.

    Returns (name, display_name). Name may be empty if the result is
    just a street/house number.
    """
    name = result.get("name", "") or ""
    display_name = result.get("display_name", "") or ""
    category = result.get("category", "")
    place_type = result.get("type", "")

    # Nominatim "name" is often the road name for highway/residential types.
    # For those, return empty name so downstream treats it as a bare address.
    if category == "highway" and place_type in ("residential", "service", "tertiary",
                                                 "secondary", "primary", "unclassified",
                                                 "trunk", "motorway"):
        return "", display_name

    # For actual POIs, use the name
    if name and category not in ("highway", "boundary", "place"):
        return name, display_name

    # For places (city, town, village, etc.), use the name
    if category == "place" and name:
        return name, display_name

    return "", display_name


def _needs_resolve(record: dict) -> bool:
    """Check if a record needs reverse-geocoding."""
    name = (record.get("name") or "").strip()
    address = (record.get("address") or "").strip()
    lat = _coerce_float(record.get("lat")) or 0.0
    lng = _coerce_float(record.get("lng")) or 0.0
    status = record.get("status", "")
    return (
        (not name and not address and (lat != 0 or lng != 0))
        or (status == "q_coords_only")
    )


def resolve_coords_only(
    records: list[dict],
    *,
    delay: float = DELAY,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Reverse-geocode all coordinate-only records.

    Returns dict with:
        "records"   — updated records list
        "resolved"  — count of successfully resolved entries
        "failed"    — count of failed lookups
        "skipped"   — count of entries that weren't coords-only
    """
    resolved = 0
    failed = 0
    skipped = 0

    for i, record in enumerate(records):
        if not _needs_resolve(record):
            skipped += 1
            continue

        if dry_run:
            resolved += 1
            continue

        name = (record.get("name") or "").strip()
        lat = _coerce_float(record.get("lat")) or 0.0
        lng = _coerce_float(record.get("lng")) or 0.0

        result = reverse_geocode(lat, lng)
        if result and "display_name" in result:
            place_name, display_address = extract_place_info(result)
            if place_name:
                record["name"] = place_name
                record["_resolved_from"] = "reverse_geocode"
            if display_address:
                record["address"] = display_address
            if not name and place_name:
                record["status"] = "named"
            elif display_address:
                record["status"] = "q_with_address"
            resolved += 1
        else:
            failed += 1
            record["_geocode_failed"] = True

        # Rate limit
        if i < len(records) - 1:
            time.sleep(delay)

    return {
        "records": records,
        "resolved": resolved,
        "failed": failed,
        "skipped": skipped,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reverse-geocode coordinate-only entries using Nominatim."
    )
    parser.add_argument(
        "--input", default=str(RAW_JSON),
        help="Input JSON path (default: output/places_raw.json).",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output JSON path (default: overwrite input).",
    )
    parser.add_argument(
        "--delay", type=float, default=DELAY,
        help=f"Seconds between requests (default: {DELAY}).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Count entries to resolve without making API calls.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    input_path = Path(args.input)

    if not input_path.exists():
        print(f"ERROR: input file not found: {input_path}")
        return 2

    with open(input_path, encoding="utf-8") as f:
        records = json.load(f)

    if not isinstance(records, list):
        print("ERROR: input JSON must be a list")
        return 2

    coords_count = sum(1 for r in records if _needs_resolve(r))
    print(f"Found {coords_count} coordinate-only entries to resolve")

    if args.dry_run:
        print(f"Estimated time: ~{int(coords_count * args.delay / 60)} minutes")
        print("(dry run — no API calls made)")
        return 0

    print(f"Resolving via Nominatim (~{int(coords_count * args.delay / 60)} min at {args.delay}s/req)...")
    result = resolve_coords_only(records, delay=args.delay)

    print(f"Resolved:  {result['resolved']}")
    print(f"Failed:    {result['failed']}")
    print(f"Skipped:   {result['skipped']}")

    output_path = Path(args.output) if args.output else input_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result["records"], f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(result['records'])} records -> {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
