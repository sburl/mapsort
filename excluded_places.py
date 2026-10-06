"""Places to keep out of the guides regardless of what they score.

The algorithm has no concept of "this is my old university" or "a shop
nobody reviews because nobody needs to". Rather than contort the scoring,
name them here. Matching is on the exact place name, case-insensitively,
so a chain-style name drops every branch — which is usually the intent.

Add a line, re-run gem_score.py and generate_gem_guides.py.

Kinds of thing that end up here, from a real run of ~2,700 scored places:

  - A high-rated local service business. A tuxedo rental shop ranked
    first in England: 4.8 stars from 216 reviews is exactly the shape the
    scoring rewards, because "nobody reviews it" and "nobody should visit
    it" look identical from outside. This is the scoring's blind spot.
  - Institutions rather than destinations — your own university, a church
    you went to once.
  - Somewhere that closed before businessStatus was being captured, so
    the closure filter has nothing to go on.
  - One venue pinned twice more than SAME_PLACE_METRES apart. A museum
    inside a sports club sat 100m from the club's own pin.
  - A misclassification the category filters cannot catch, such as a
    transit station filed as a neighbourhood.
"""

from __future__ import annotations

EXCLUDED_NAMES: frozenset[str] = frozenset(
    name.casefold()
    for name in (
        # "Some Place That Should Not Appear",
    )
)


def is_excluded(place: dict) -> bool:
    return (place.get("name") or "").strip().casefold() in EXCLUDED_NAMES
