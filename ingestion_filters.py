#!/usr/bin/env python3
"""Ingestion-time filters: triage, dedupe, and address classification.

Run this on places_raw.json (or places_resolved.json) BEFORE classification
to remove noise, deduplicate, and pre-classify bare addresses.

Pipeline position:
    Takeout → places_raw.json → **ingestion_filters.py** → places_filtered.json → classifier
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from coord_utils import _coerce_float
from fuzzy_dedupe import dedupe_by_local_vector_index
from settings import FILTERED_JSON, RAW_JSON

# ---------------------------------------------------------------------------
# 1. Residential / personal address detection
# ---------------------------------------------------------------------------

# US residential: "123 Main St, City, ST 12345"
_US_RESIDENTIAL = re.compile(
    r"^\d+\s+[\w\s]+(St|Ave|Dr|Rd|Ln|Ct|Blvd|Way|Pl|Cir|Pkwy|Ter)\b"
    r".*,\s*[A-Z]{2}\s+\d{5}",
    re.IGNORECASE,
)

# Apartment/unit indicators
_UNIT_PATTERN = re.compile(
    r"\b(apt|unit|suite|ste|#|floor|flr|piso|departamento)\b",
    re.IGNORECASE,
)

# International residential: number + street name + postal code
_INTL_RESIDENTIAL = re.compile(
    r"^\d+[\s,-]+[\w\s\-'àáâãäåæçèéêëìíîïñòóôõöùúûüýÿ]+"
    r",\s*\d{4,6}\b",
    re.IGNORECASE,
)

# Japanese chome/banchi addresses
_JP_ADDRESS = re.compile(r"(chōme|丁目|番地|\d+-\d+-\d+)", re.IGNORECASE)

# Korean addresses
_KR_ADDRESS = re.compile(r"(dong\b|gu,|gil\b|ro\b.*gu|특별시|광역시)", re.IGNORECASE)

# Bare postal code + city
_POSTAL_CITY = re.compile(r"^\d{4,6}[-\s]?\d{0,3}\s+\w+.*,\s*\w+")


def is_residential_address(address: str) -> bool:
    """Heuristic: does this look like a home/personal address?"""
    if not address:
        return False
    if _UNIT_PATTERN.search(address):
        return True
    if _US_RESIDENTIAL.match(address):
        return True
    if _INTL_RESIDENTIAL.match(address):
        # But not if it looks like a known place type
        return not _has_place_keywords(address)
    return False


def is_bare_address(name: str, address: str) -> bool:
    """Entry has no business name — just a raw address or coordinates."""
    return not name.strip() and bool(address.strip())


def is_coords_only(name: str, address: str, lat: float, lng: float) -> bool:
    """Entry is a dropped pin with no name or address."""
    return not name.strip() and not address.strip() and (lat != 0 or lng != 0)


# ---------------------------------------------------------------------------
# 2. Address-based place classification (for bare addresses)
# ---------------------------------------------------------------------------

_PLACE_PATTERNS: list[tuple[re.Pattern[str], str, int]] = [
    # Nature & outdoors
    (re.compile(r"\b(beach|playa|praia|bay\b|cove|shore|coast)\b", re.IGNORECASE), "nature", 8),
    (re.compile(r"\b(mountain|mount\b|mt\b|peak|summit|ridge|volcano)\b", re.IGNORECASE), "nature", 8),
    (re.compile(r"\b(falls|waterfall|cascade|gorge|canyon|cliff)\b", re.IGNORECASE), "nature", 8),
    (re.compile(r"\b(island|isle\b|archipelago|atoll)\b", re.IGNORECASE), "nature", 8),
    (re.compile(r"\b(lake\b|river\b|pond\b|creek\b|swamp|reservoir)\b", re.IGNORECASE), "nature", 8),
    (re.compile(r"\b(trail|hike|hiking)\b", re.IGNORECASE), "nature", 8),
    # Parks & gardens
    (re.compile(r"\b(park\b|garden|botanical|reserve|forest)\b", re.IGNORECASE), "parks", 10),
    # Landmarks
    (re.compile(r"\b(square|piazza|plaza|platz|tér\b|campo\b)\b", re.IGNORECASE), "landmarks", 4),
    (re.compile(r"\b(tower|castle|palace|fort\b|fortress|bridge|monument|memorial|statue)\b", re.IGNORECASE), "landmarks", 4),
    (re.compile(r"\b(promenade|boardwalk|esplanade)\b", re.IGNORECASE), "landmarks", 4),
    # Markets
    (re.compile(r"\b(market|bazaar|souk|souq|mercado)\b", re.IGNORECASE), "shopping", 11),
    # Airports
    (re.compile(r"\b(airport|terminal|aeropuerto|flughafen)\b", re.IGNORECASE), "airports", 14),
    # Religious
    (re.compile(r"\b(church|cathedral|mosque|temple|shrine|synagogue|chapel|basilica|monastery)\b", re.IGNORECASE), "sacred", 9),
    # Transit
    (re.compile(r"\b(station|metro|subway|ferry|funicular)\b", re.IGNORECASE), "transit", 15),
    # Ski
    (re.compile(r"\b(ski|skiing|snowboard)\b", re.IGNORECASE), "ski", 16),
]


def _has_place_keywords(text: str) -> bool:
    """Check if text contains any known place-type keyword."""
    for pattern, _, _ in _PLACE_PATTERNS:
        if pattern.search(text):
            return True
    return False


def classify_bare_address(address: str) -> tuple[int | None, str | None]:
    """Try to classify a bare address by keyword matching.

    Returns (category_id, reason) or (None, None).
    """
    text = address.lower()
    for pattern, reason, category_id in _PLACE_PATTERNS:
        if pattern.search(text):
            return category_id, f"address-keyword: {reason}"
    return None, None


# ---------------------------------------------------------------------------
# 3. Deduplication merge function
# ---------------------------------------------------------------------------

def _merge_places(canonical: dict, incoming: dict) -> None:
    """Merge incoming duplicate into canonical record."""
    # Prefer the record with a name
    if not canonical.get("name") and incoming.get("name"):
        canonical["name"] = incoming["name"]

    # Prefer non-zero coordinates
    if (canonical.get("lat", 0) == 0 and canonical.get("lng", 0) == 0) and (
        incoming.get("lat", 0) != 0 or incoming.get("lng", 0) != 0
    ):
        canonical["lat"] = incoming["lat"]
        canonical["lng"] = incoming["lng"]

    # Merge sources
    existing_sources = set(canonical.get("sources", []))
    incoming_sources = set(incoming.get("sources", []))
    canonical["sources"] = sorted(existing_sources | incoming_sources)

    # Keep earliest date
    if incoming.get("date") and (
        not canonical.get("date") or incoming["date"] < canonical["date"]
    ):
        canonical["date"] = incoming["date"]


# ---------------------------------------------------------------------------
# 4. Triage pipeline
# ---------------------------------------------------------------------------

def triage_record(record: dict) -> str:
    """Assign a triage tier to a record.

    Returns one of:
        "keep"      — named place, pass to classifier
        "skip"      — personal/residential address, flag but keep
        "coords"    — bare coordinates, flag for reverse-geocoding
        "classify"  — bare address with place keywords, attempt auto-classify
        "review"    — bare address, no keywords, needs manual review
    """
    name = (record.get("name") or "").strip()
    address = (record.get("address") or "").strip()
    lat = _coerce_float(record.get("lat")) or 0.0
    lng = _coerce_float(record.get("lng")) or 0.0

    # Named places always pass through
    if name:
        return "keep"

    # Coordinates only — no name, no address
    if is_coords_only(name, address, lat, lng):
        return "coords"

    # Bare address — check if residential
    if is_residential_address(address):
        return "skip"

    # Bare address with place keywords
    cat_id, _ = classify_bare_address(address)
    if cat_id is not None:
        return "classify"

    # Everything else needs review
    return "review"


def run_filters(
    records: list[dict],
    *,
    dedupe: bool = True,
    auto_classify_addresses: bool = True,
) -> dict[str, Any]:
    """Run all ingestion filters and return results.

    Nothing is dropped — every record is kept and tagged with a triage tier.

    Returns dict with:
        "filtered"  — all records, tagged with _triage tier
        "stats"     — summary counters
    """
    stats: Counter = Counter()
    filtered = []

    for record in records:
        tier = triage_record(record)
        stats[f"triage_{tier}"] += 1
        record = {**record, "_triage": tier}

        if tier == "skip":
            record["_flag"] = "residential_address"

        if tier == "coords":
            record["_flag"] = "needs_reverse_geocode"

        if tier == "classify" and auto_classify_addresses:
            address = (record.get("address") or "").strip()
            cat_id, reason = classify_bare_address(address)
            if cat_id is not None:
                record = {**record, "category": cat_id, "confidence": "low",
                          "_auto_classified": True, "_classify_reason": reason}
                stats["auto_classified"] += 1

        filtered.append(record)

    # Deduplicate
    if dedupe:
        before = len(filtered)
        filtered = dedupe_by_local_vector_index(filtered, _merge_places)
        stats["deduped"] = before - len(filtered)

    stats["input"] = len(records)
    stats["output"] = len(filtered)

    return {
        "filtered": filtered,
        "stats": dict(stats),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Triage, dedupe, and pre-classify raw places data. Nothing is dropped."
    )
    parser.add_argument(
        "--input", default=str(RAW_JSON),
        help="Input JSON path (default: output/places_raw.json).",
    )
    parser.add_argument(
        "--output", default=str(FILTERED_JSON),
        help="Output filtered JSON path.",
    )
    parser.add_argument(
        "--no-dedupe", action="store_true",
        help="Skip deduplication.",
    )
    parser.add_argument(
        "--no-auto-classify", action="store_true",
        help="Skip auto-classification of bare addresses.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print stats only, don't write files.",
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

    result = run_filters(
        records,
        dedupe=not args.no_dedupe,
        auto_classify_addresses=not args.no_auto_classify,
    )

    stats = result["stats"]
    print(f"Input:            {stats['input']}")
    print(f"Triage keep:      {stats.get('triage_keep', 0)}")
    print(f"Triage classify:  {stats.get('triage_classify', 0)}")
    print(f"Triage review:    {stats.get('triage_review', 0)}")
    print(f"Triage skip:      {stats.get('triage_skip', 0)} (flagged residential)")
    print(f"Triage coords:    {stats.get('triage_coords', 0)} (flagged for reverse-geocode)")
    print(f"Auto-classified:  {stats.get('auto_classified', 0)}")
    print(f"Deduped:          {stats.get('deduped', 0)}")
    print(f"Output:           {stats['output']}")

    if args.dry_run:
        print("\n(dry run — no files written)")
        return 0

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result["filtered"], f, indent=2, ensure_ascii=False)
    print(f"\nWrote {len(result['filtered'])} records -> {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
