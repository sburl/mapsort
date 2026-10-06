"""Hand-corrected categories for places the classifier got wrong.

The classifier works from the name, so anything whose name does not say
what it is lands in 16 (Practical) with low confidence — and 16 is one of
the PRIVATE_CATEGORIES that enrichment never sends to the Places API. A
place can therefore fall out of the guides before it is ever rated, which
is invisible from the guides themselves. A thermal bath whose name was a
coined word went missing this way for a whole run.

Keyed on place id so a correction survives a re-ingest, unlike editing
output/places_classified.json. After adding a line, re-run
enrich_ratings.py (the place needs a rating it has never been given),
then gem_score.py and generate_gem_guides.py.
"""

from __future__ import annotations

# id -> (category, name for readability, why)
CATEGORY_OVERRIDES: dict[str, tuple[int, str, str]] = {
    # "cid:1234567890": (13, "Some Baths", "thermal baths, not a utility"),
}


def apply_overrides(places: list[dict]) -> int:
    """Rewrite categories in place. Returns the number changed."""
    changed = 0
    for p in places:
        entry = CATEGORY_OVERRIDES.get(p.get("id") or "")
        if entry and p.get("category") != entry[0]:
            p["category"] = entry[0]
            p["category_override"] = True
            changed += 1
    return changed
