#!/usr/bin/env python3
"""Parse Google Takeout "Saved Places" exports into the raw place schema.

Rebuilds the ingest stage of the pipeline (the original sort.py/enrich.py
were never committed and no longer exist on disk). Takeout gives us only a
maps URL, a timestamp, and often a null coordinate — names and addresses
come from resolution later, EXCEPT for `?q=<address>` URLs which carry the
address inline.

The useful trick for refreshes: most places in a new export are already in
places_classified.json from last time. Those carry their resolved name,
address, category and tier straight across, so only genuinely new saves
need resolving — roughly 100/year for a heavy saver, not 6,000.

Usage:
    python ingest_takeout.py --takeout-dir ~/Downloads/Takeout
    python ingest_takeout.py --takeout-dir ~/Downloads/Takeout --out output/places_raw_2026.json
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from settings import CLASSIFIED_JSON, OUTPUT_DIR

SAVED_PLACES = "Saved Places.json"
NO_LOCATION = "No location information is available for this saved place"


def parse_maps_url(url: str) -> dict:
    """Extract cid / ftid / inline address from a Google Maps URL."""
    qs = parse_qs(urlparse(url).query)
    cid = (qs.get("cid") or [None])[0]
    ftid = (qs.get("ftid") or [None])[0]
    q = (qs.get("q") or [None])[0]
    address = None
    if q and not q.replace(".", "").replace("-", "").replace(",", "").replace(" ", "").isdigit():
        address = unquote(q).replace("+", " ").strip() or None
    if cid:
        url_type, pid = "cid", f"cid:{cid}"
    elif ftid and q:
        url_type, pid = "q_with_ftid", f"ftid:{ftid}"
    elif ftid:
        url_type, pid = "ftid_only", f"ftid:{ftid}"
    else:
        url_type, pid = "q_only", None
    return {"cid": cid, "ftid": ftid, "address": address, "url_type": url_type, "id": pid}


def feature_to_row(feature: dict, account: str) -> dict | None:
    props = feature.get("properties") or {}
    url = props.get("google_maps_url") or ""
    if not url:
        return None
    parsed = parse_maps_url(url)
    coords = (feature.get("geometry") or {}).get("coordinates") or [0, 0]
    lng, lat = (coords + [0, 0])[:2]
    # Takeout writes [0, 0] when it has no location for a saved place.
    if (lat, lng) == (0, 0) and props.get("Comment") == NO_LOCATION:
        lat = lng = None
    pid = parsed["id"] or (f"latlng:{lat},{lng}" if lat is not None else "name:")
    return {
        "id": pid,
        "source": account,
        "url_type": parsed["url_type"],
        "cid": parsed["cid"],
        "ftid": parsed["ftid"],
        "name": None,
        "address": parsed["address"],
        "lat": lat,
        "lng": lng,
        "date": props.get("date") or "",
        "google_maps_url": url,
        "status": "raw",
        "category": None,
        "confidence": None,
        "resolved_name": None,
        "sources": [account],
    }


def find_exports(takeout_dir: Path) -> list[tuple[str, Path]]:
    """Locate each account's Saved Places.json.

    Takeout names the second account's folder "Maps (your places) 2", so
    accounts are distinguished by folder depth, not by any account name in
    the file — the export does not record which account it came from.
    """
    found = sorted(takeout_dir.rglob(SAVED_PLACES))
    return [(f"account{i + 1}", p) for i, p in enumerate(found)]


def merge_rows(rows: list[dict]) -> list[dict]:
    """Collapse the same place saved in both accounts into one row."""
    merged: dict[str, dict] = {}
    for row in rows:
        key = row["id"]
        if key == "name:":  # degenerate: never merge nameless pins together
            key = f"name:{row['google_maps_url']}"
        if key in merged:
            existing = merged[key]
            for acct in row["sources"]:
                if acct not in existing["sources"]:
                    existing["sources"].append(acct)
            existing["source"] = "both" if len(existing["sources"]) > 1 else existing["source"]
            # Keep the earliest save date.
            if row["date"] and (not existing["date"] or row["date"] < existing["date"]):
                existing["date"] = row["date"]
            existing["address"] = existing["address"] or row["address"]
            if existing["lat"] is None:
                existing["lat"], existing["lng"] = row["lat"], row["lng"]
        else:
            merged[key] = dict(row)
    return list(merged.values())


def norm_address(address: str | None) -> str | None:
    """Loose address key for matching across ID schemes."""
    if not address:
        return None
    key = re.sub(r"[^a-z0-9]+", " ", address.casefold()).strip()
    return key or None


def carry_over(rows: list[dict], classified: list[dict]) -> Counter:
    """Copy resolved fields from the previous run onto matching rows.

    Matching by `id` alone badly overstates how much is new: Takeout emits
    `ftid:` ids for places the old pipeline had resolved to `cid:` by
    scraping, so the same place looks new under a different scheme. Address
    and coordinate fallbacks recover those.
    """
    known = {p["id"]: p for p in classified if p.get("id") and p["id"] != "name:"}
    by_address, by_coord = {}, {}
    for p in classified:
        ak = norm_address(p.get("address"))
        if ak:
            by_address.setdefault(ak, p)
        if p.get("lat") is not None and p.get("lng") is not None:
            by_coord.setdefault((round(p["lat"], 4), round(p["lng"], 4)), p)

    stats = Counter()
    for row in rows:
        prev = known.get(row["id"]) if row["id"] != "name:" else None
        if prev:
            stats["matched_by_id"] += 1
        else:
            prev = by_address.get(norm_address(row.get("address")))
            if prev:
                stats["matched_by_address"] += 1
            elif row.get("lat") is not None:
                prev = by_coord.get((round(row["lat"], 4), round(row["lng"], 4)))
                if prev:
                    stats["matched_by_coords"] += 1
        if not prev:
            stats["new"] += 1
            continue
        stats["known"] += 1
        for field in ("name", "address", "category", "confidence", "resolved_name", "tier"):
            if prev.get(field) not in (None, ""):
                row[field] = prev[field]
        if row["lat"] is None:
            row["lat"], row["lng"] = prev.get("lat"), prev.get("lng")
        row["status"] = "carried_over"
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--takeout-dir", type=Path, required=True)
    parser.add_argument("--classified", type=Path, default=CLASSIFIED_JSON)
    parser.add_argument("--out", type=Path, default=OUTPUT_DIR / "places_raw_refresh.json")
    args = parser.parse_args()

    exports = find_exports(args.takeout_dir)
    if not exports:
        raise SystemExit(f"no {SAVED_PLACES} under {args.takeout_dir}")

    rows = []
    for account, path in exports:
        data = json.loads(path.read_text(encoding="utf-8"))
        feats = data.get("features", [])
        parsed = [r for r in (feature_to_row(f, account) for f in feats) if r]
        print(f"{account}: {len(parsed)} places from {path.name}")
        rows.extend(parsed)

    rows = merge_rows(rows)
    classified = json.loads(args.classified.read_text(encoding="utf-8")) if args.classified.exists() else []
    stats = carry_over(rows, classified)

    rows.sort(key=lambda r: (r.get("date") or "", r["id"]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
        f.write("\n")

    print(f"\n{len(rows)} unique places after merging accounts")
    print(f"  already known (fields carried over): {stats['known']}")
    print(f"  NEW (need resolution + classification): {stats['new']}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
