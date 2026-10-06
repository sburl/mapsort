#!/usr/bin/env python3
"""Annual refresh orchestrator: diff a new Takeout export against the current
dataset, then drive the downstream steps that are safe to automate.

This is a thin wrapper. It does not reimplement ingestion, classification, or
scoring — it calls the existing scripts (or, where an entry point is missing
from the repo, prints the manual step instead of pretending to automate it).

Modes:
    --plan              ordered annual-refresh checklist + real budget math
    --diff NEW.json     compare a new classified dataset to the current one
    --run-downstream    re-score and regenerate guides (no API calls, no cost)

Usage:
    python refresh_pipeline.py --plan
    python refresh_pipeline.py --diff output/places_classified_2027.json
    python refresh_pipeline.py --run-downstream

The metered step (enrich_ratings.py) is deliberately NOT run from here: it
spends the monthly Places API free-tier budget and should be invoked
consciously. --plan prints the exact command and the remaining budget.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

from settings import BASE_DIR, CLASSIFIED_JSON, DATA_DIR, OUTPUT_DIR

YEAR_DIFF_MD = OUTPUT_DIR / "year_diff.md"

# Free-tier ceilings for the Places API (New), per Google's per-SKU model.
ENTERPRISE_FREE_PER_MONTH = 1_000   # rating / userRatingCount fields
ESSENTIALS_FREE_PER_MONTH = 10_000  # text search (place_id resolution)
MONTHLY_BATCH_LIMIT = 950           # enrich_ratings.py default --limit

# Upstream entry points referenced by settings.py that are not in this repo.
# These stages are manual; the checklist says so rather than shelling out to
# a script that does not exist.
MISSING_UPSTREAM = {
    "scrape.py": "scrape shared/starred Google Maps lists into output/scraped/",
    "sort.py": "classify filtered places into categories (LLM classifier)",
    "enrich.py": "address/name enrichment pass",
}


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

def identity_key(place: dict) -> str:
    """Stable identity for a place row across exports.

    Prefers the Takeout id ("cid:123...", "ftid:0x..."). Roughly 470 rows in
    the current dataset carry the degenerate id "name:" (nameless,
    address-only pins at 0,0), so those fall back to a composite of the
    fields that actually identify them.
    """
    raw = (place.get("id") or "").strip()
    _, _, suffix = raw.partition(":")
    if raw and suffix.strip():
        return raw
    name = (place.get("resolved_name") or place.get("name") or "").strip().casefold()
    addr = (place.get("address") or "").strip().casefold()
    lat = float(place.get("lat") or 0.0)
    lng = float(place.get("lng") or 0.0)
    return f"composite:{name}|{addr}|{round(lat, 5)},{round(lng, 5)}"


def display_name(place: dict) -> str:
    name = (place.get("resolved_name") or place.get("name") or "").strip()
    if name:
        return name
    addr = (place.get("address") or "").strip()
    return addr or "(unnamed)"


def category_label(category: int | None) -> str:
    """Human label for a category id, tolerating unknown/missing ids."""
    from export_site_data import CATEGORY_LABELS, CATEGORY_SLUGS

    if category is None:
        return "unclassified"
    slug = CATEGORY_SLUGS.get(category)
    if slug is None:
        return f"category {category}"
    return CATEGORY_LABELS.get(slug, slug)


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

def index_places(places: list[dict]) -> tuple[dict[str, dict], Counter]:
    """Map identity -> representative row, plus a multiset of identities.

    A handful of rows are exact duplicates (same address, no name, no
    coordinates). The Counter preserves their multiplicity so added/removed
    counts stay honest; the dict keeps one representative for reporting.
    """
    representative: dict[str, dict] = {}
    counts: Counter = Counter()
    for p in places:
        key = identity_key(p)
        counts[key] += 1
        representative.setdefault(key, p)
    return representative, counts


def diff_datasets(old: list[dict], new: list[dict]) -> dict:
    """Compare two classified datasets.

    Returns added / removed / tier_changes / category_changes, where
    tier_changes highlights want_to_go -> visited ("places you finally went").
    """
    old_rep, old_counts = index_places(old)
    new_rep, new_counts = index_places(new)

    added_counts = new_counts - old_counts
    removed_counts = old_counts - new_counts

    added = [
        {"key": k, "name": display_name(new_rep[k]),
         "tier": new_rep[k].get("tier"),
         "category": category_label(new_rep[k].get("category")),
         "count": n}
        for k, n in sorted(added_counts.items())
    ]
    removed = [
        {"key": k, "name": display_name(old_rep[k]),
         "tier": old_rep[k].get("tier"),
         "category": category_label(old_rep[k].get("category")),
         "count": n}
        for k, n in sorted(removed_counts.items())
    ]

    tier_changes, category_changes = [], []
    for key in sorted(set(old_rep) & set(new_rep)):
        before, after = old_rep[key], new_rep[key]
        if before.get("tier") != after.get("tier"):
            tier_changes.append({
                "key": key,
                "name": display_name(after),
                "from": before.get("tier"),
                "to": after.get("tier"),
                "finally_went": before.get("tier") == "want_to_go"
                                and after.get("tier") == "visited",
            })
        if before.get("category") != after.get("category"):
            category_changes.append({
                "key": key,
                "name": display_name(after),
                "from": category_label(before.get("category")),
                "to": category_label(after.get("category")),
            })

    return {
        "old_total": len(old),
        "new_total": len(new),
        "added": added,
        "removed": removed,
        "tier_changes": tier_changes,
        "category_changes": category_changes,
    }


def _cell(value: object) -> str:
    """Escape a value for a markdown table cell.

    Place names really do contain pipes ("Señor Piña | Poke Bowl"), which
    would otherwise split into a phantom column.
    """
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def _table(rows: list[dict], columns: list[tuple[str, str]], limit: int) -> list[str]:
    """Render a markdown table for up to `limit` rows."""
    if not rows:
        return ["_None._", ""]
    headers = [title for title, _ in columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows[:limit]:
        cells = [_cell(row.get(field)) for _, field in columns]
        lines.append("| " + " | ".join(cells) + " |")
    if len(rows) > limit:
        filler = " | ".join([f"_...and {len(rows) - limit} more_"] + [""] * (len(headers) - 1))
        lines.append("| " + filler + " |")
    lines.append("")
    return lines


def render_diff_md(diff: dict, limit: int = 50) -> str:
    finally_went = [t for t in diff["tier_changes"] if t["finally_went"]]
    lines = [
        "# Year Diff",
        "",
        f"- Previous dataset: **{diff['old_total']:,}** places",
        f"- New dataset: **{diff['new_total']:,}** places",
        f"- Added: **{sum(a['count'] for a in diff['added']):,}**",
        f"- Removed: **{sum(r['count'] for r in diff['removed']):,}**",
        (f"- Tier changes: **{len(diff['tier_changes']):,}** "
            f"(of which {len(finally_went):,} are places you finally went)"),
        f"- Category changes: **{len(diff['category_changes']):,}**",
        "",
        "## Places you finally went",
        "",
        "Saved on a previous export, visited since.",
        "",
    ]
    lines += _table(finally_went, [("Place", "name")], limit)

    lines += ["## Added", ""]
    lines += _table(
        diff["added"],
        [("Place", "name"), ("Tier", "tier"), ("Category", "category")],
        limit,
    )

    lines += ["## Removed", ""]
    lines += _table(
        diff["removed"],
        [("Place", "name"), ("Tier", "tier"), ("Category", "category")],
        limit,
    )

    other_tier = [t for t in diff["tier_changes"] if not t["finally_went"]]
    lines += ["## Other tier changes", ""]
    lines += _table(
        other_tier, [("Place", "name"), ("From", "from"), ("To", "to")], limit
    )

    lines += ["## Category changes", ""]
    lines += _table(
        diff["category_changes"],
        [("Place", "name"), ("From", "from"), ("To", "to")],
        limit,
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

def enrichment_budget(classified: list[dict]) -> dict:
    """Real remaining-enrichment math against the monthly free tier."""
    from enrich_ratings import guide_places, load_cache

    places = guide_places(classified)
    cache = load_cache()
    terminal = {"ok", "no_rating", "no_match"}
    done = sum(1 for p in places if cache.get(p["id"], {}).get("status") in terminal)
    remaining = len(places) - done
    months = -(-remaining // MONTHLY_BATCH_LIMIT)  # ceiling division
    return {
        "guide_places": len(places),
        "enriched": done,
        "remaining": remaining,
        "months_to_finish": months,
        "cost_if_bought_now": remaining * 35 / 1000,
    }


def print_plan(classified: list[dict]) -> None:
    budget = enrichment_budget(classified)
    print("Annual refresh — ordered checklist\n")
    print("  1. MANUAL: export Google Takeout (Maps > Saved Places), unzip into")
    print(f"     {DATA_DIR} (or set TAKEOUT_DIR).")
    print("  2. MANUAL: build places_raw.json from the Takeout JSON.")
    for name, what in MISSING_UPSTREAM.items():
        print(f"     - {name} is NOT in this repo ({what}); run your local copy.")
    print("  3. python3 reverse_geocode.py            # resolve coordinate-only pins")
    print("  4. python3 ingestion_filters.py          # triage + dedupe -> places_filtered.json")
    print("  5. MANUAL: classify (sort.py) -> a new places_classified JSON.")
    print("     Write it to a NEW path; do not overwrite the current one yet.")
    print("  6. python3 refresh_pipeline.py --diff <new_classified.json>")
    print(f"     -> writes {YEAR_DIFF_MD.relative_to(BASE_DIR)} (the 'year in places' summary)")
    print("  7. Promote the new dataset over output/places_classified.json once the diff looks right.")
    print(f"  8. python3 enrich_ratings.py --limit {MONTHLY_BATCH_LIMIT}   # metered; see budget below")
    print("  9. python3 refresh_pipeline.py --run-downstream   # gem_score + guide drafts")
    print()
    print("Enrichment budget (real, from the current dataset + cache):")
    print(f"  guide-relevant visited places : {budget['guide_places']:,}")
    print(f"  already enriched              : {budget['enriched']:,}")
    print(f"  remaining                     : {budget['remaining']:,}")
    print(f"  months at {MONTHLY_BATCH_LIMIT}/month free      : {budget['months_to_finish']}")
    print(f"  cost if bought outright       : ${budget['cost_if_bought_now']:,.2f}")
    print()
    print(f"Free tier: Enterprise (rating fields) {ENTERPRISE_FREE_PER_MONTH:,}/month; "
          f"Essentials (search) {ESSENTIALS_FREE_PER_MONTH:,}/month.")
    print("New places added by a refresh need enrichment too — re-run --plan after the diff.")


# ---------------------------------------------------------------------------
# Downstream
# ---------------------------------------------------------------------------

def run_downstream() -> int:
    """Re-score and regenerate guide drafts. No API calls, no cost."""
    steps = [
        [sys.executable, "gem_score.py"],
        [sys.executable, "generate_gem_guides.py"],
    ]
    for cmd in steps:
        print(f"\n$ {' '.join(cmd)}")
        result = subprocess.run(  # noqa: PLW1510 - return code inspected below
        cmd, cwd=BASE_DIR)
        if result.returncode != 0:
            print(f"step failed: {' '.join(cmd)}", file=sys.stderr)
            return result.returncode
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true", help="print the refresh checklist")
    parser.add_argument("--diff", type=Path, metavar="NEW_JSON",
                        help="compare a new classified dataset to the current one")
    parser.add_argument("--current", type=Path, default=CLASSIFIED_JSON,
                        help="baseline dataset for --diff")
    parser.add_argument("--output", type=Path, default=YEAR_DIFF_MD,
                        help="where --diff writes its markdown summary")
    parser.add_argument("--limit", type=int, default=50,
                        help="max rows per table in the diff markdown")
    parser.add_argument("--run-downstream", action="store_true",
                        help="run gem_score.py then generate_gem_guides.py")
    args = parser.parse_args()

    if not (args.plan or args.diff or args.run_downstream):
        parser.error("choose one of --plan, --diff, or --run-downstream")

    if args.diff:
        old = json.loads(args.current.read_text(encoding="utf-8"))
        new = json.loads(args.diff.read_text(encoding="utf-8"))
        diff = diff_datasets(old, new)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(render_diff_md(diff, args.limit), encoding="utf-8")
        finally_went = sum(1 for t in diff["tier_changes"] if t["finally_went"])
        print(
            f"{diff['old_total']:,} -> {diff['new_total']:,} places | "
            f"+{sum(a['count'] for a in diff['added']):,} added, "
            f"-{sum(r['count'] for r in diff['removed']):,} removed | "
            f"{len(diff['tier_changes']):,} tier changes ({finally_went:,} finally went) | "
            f"{len(diff['category_changes']):,} category changes"
        )
        print(f"wrote {args.output}")

    if args.plan:
        print_plan(json.loads(args.current.read_text(encoding="utf-8")))

    if args.run_downstream:
        sys.exit(run_downstream())


if __name__ == "__main__":
    main()
