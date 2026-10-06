#!/usr/bin/env python3
"""Generate hidden-gems blog post drafts from gem scores.

Emits one Jekyll draft per sufficiently-covered location, in the format of
the hand-tuned San Francisco post: personal-note placeholders in the body,
ratings kept in an HTML comment for reference while editing, and a single
methodology link in the footer. Existing files are never overwritten unless
--force is passed, so hand-edited drafts survive regeneration.

Usage:
    python generate_gem_guides.py                     # write eligible drafts
    python generate_gem_guides.py --list              # show eligibility only
    python generate_gem_guides.py --force --location Paris
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import statistics
import unicodedata
from pathlib import Path

from gem_score import GEM_SCORES, guide_sections
from generate_travel_guides import (
    LOCATION_REGION,
    LOCATIONS,
    SUBREGION_ORDER,
    US_SUBREGION,
)
from settings import OUTPUT_DIR

# "CA 94109" / "NY 10009-1234" — a US state code followed by a ZIP.
_US_STATE_ZIP = re.compile(r"^(?P<state>[A-Z]{2})\s+\d{5}(?:-\d{4})?$")
# "10785 Berlin" — postcode before the city, common across Europe.
_ZIP_THEN_CITY = re.compile(r"^\d{4,6}\s+(?P<city>.+)$")
# "Gifu 506-0858" / "Comunitat Valenciana 46011" — region then postcode.
_REGION_ZIP = re.compile(r"^(?P<region>.+?)\s+[\d-]{4,10}$")
# "Oxford OX1 1BT" — a UK postcode trailing the city in one field.
_UK_POSTCODE = re.compile(r"\s+[A-Z]{1,2}\d{1,2}[A-Z]?\s+\d[A-Z]{2}$")
# Japanese postal marker, e.g. "\u3012150-0001".
_JP_POSTCODE = re.compile(r"\u3012\s*\d{3}-?\d{4}")
# "Gifu 506-0858" or a bare "730-0811": the field that ends a Japanese
# address, optionally prefixed by the prefecture.
_JP_CITY_ZIP = re.compile(r"^(?:(?P<prefecture>\D.*?)\s+)?\d{3}-\d{4}$")
# Block numbers lead the city field in some records ("1 Narita, Chiba"),
# and "N Chome-N-N" runs ahead of the district name.
_JP_BLOCK = re.compile(
    r"^(?:[\d\uff10-\uff19][\d\uff10-\uff19\-\u2212\s]*"
    r"(?:Chome(?:-[\d\uff10-\uff19\-]+)?)?\s+)"
)

# Addresses written only in Japanese give a city or ward and nothing else,
# so the prefecture has to be looked up. Only the ones in the data.
_JP_WARDS_AND_CITIES: dict[str, tuple[str, str]] = {
    "\u9ad8\u677e\u5e02": ("Takamatsu", "Kagawa"),
    "\u9ad8\u5c71\u5e02": ("Takayama", "Gifu"),
    "\u5e83\u5cf6\u5e02": ("Hiroshima", "Hiroshima"),
    "\u9e7f\u5150\u5cf6\u5e02": ("Kagoshima", "Kagoshima"),
    "\u5343\u4ee3\u7530\u533a": ("Chiyoda City", "Tokyo"),
    "\u53f0\u6771\u533a": ("Taito City", "Tokyo"),
    "\u6e2f\u533a": ("Minato City", "Tokyo"),
}

# Regions short enough to read as a qualifier ("CA", "Gifu"); longer ones
# like "Comunitat Valenciana" just crowd the line, so the city stands alone.
MAX_REGION_LEN = 14


def japanese_locality(parts: list[str], country: str) -> str:
    """"City, Prefecture" from a romanised, country-last Japanese address.

    Google writes these smallest-first with the prefecture folded into the
    postcode field: "<block>, <ward>, Kobe, Hyogo 650-0011, Japan". For a
    designated city the prefecture shares the city's name and Google drops
    it, so "Naka Ward, Hiroshima, 730-0811" carries no prefecture field at
    all and the city name doubles as one.
    """
    fields = [p for p in parts if p.casefold() not in {country.casefold(), "japan", "\u65e5\u672c"}]
    if not fields:
        return ""

    for i, field in enumerate(fields):
        m = _JP_CITY_ZIP.match(field)
        if not m:
            continue
        prefecture = (m.group("prefecture") or "").strip()
        city = _JP_BLOCK.sub("", fields[i - 1]).strip() if i else ""
        if not prefecture:
            # No prefecture field: the preceding name is a designated city,
            # which shares its prefecture's name.
            return city
        if city and city.casefold() != prefecture.casefold():
            return f"{city}, {prefecture}"
        return prefecture

    # Japanese-script addresses stop at the ward or city.
    for field in reversed(fields):
        looked_up = _JP_WARDS_AND_CITIES.get(field.strip())
        if looked_up:
            city, prefecture = looked_up
            return city if city == prefecture else f"{city}, {prefecture}"
    return ""


def place_locality(address: str, country: str) -> str:
    """Best-effort "City, Region" from a free-form Google address.

    Address formats vary wildly by country, so this aims for a useful label
    rather than correctness everywhere, and returns "" when it cannot find
    something it trusts.
    """
    address = (address or "").strip()
    parts = [p.strip() for p in address.split(",") if p.strip()]

    # Japanese addresses run largest-first: "Japan, <postcode> <prefecture>,
    # <ward>, <district>, <street detail>". Reading from the end, as Western
    # formats require, returns the building and floor instead of the city.
    if parts and (parts[0] == country or parts[0] == "Japan") and _JP_POSTCODE.search(address):
        prefecture = _JP_POSTCODE.sub("", parts[1]).strip() if len(parts) > 1 else ""
        ward = parts[2].strip() if len(parts) > 2 else ""
        if ward and prefecture and ward.casefold() != prefecture.casefold():
            return f"{ward}, {prefecture}"
        return ward or prefecture
    if country in {"Japan", "\u65e5\u672c"} or address.endswith(("Japan", "\u65e5\u672c")):
        jp = japanese_locality(parts, country)
        if jp:
            return jp
    # Gulf addresses come dash-separated ("Gate Village 08 - DIFC - Dubai -
    # United Arab Emirates"), which the comma split leaves as one blob.
    if len(parts) <= 1 and " - " in address:
        parts = [p.strip() for p in address.split(" - ") if p.strip()]
    if not parts:
        return ""
    # Drop a trailing country field.
    if parts[-1].casefold() in {country.casefold(), "united states", "usa", "uk"}:
        parts.pop()
    if not parts:
        return ""

    tail = parts[-1]
    city, region = "", ""

    m = _US_STATE_ZIP.match(tail)
    if m and len(parts) >= 2:
        city, region = parts[-2], m.group("state")
    else:
        m = _ZIP_THEN_CITY.match(tail)
        if m:
            city = m.group("city")
        else:
            m = _REGION_ZIP.match(tail)
            if m and len(parts) >= 2:
                city, region = parts[-2], m.group("region")
            else:
                city = _UK_POSTCODE.sub("", tail)

    city = city.strip()
    if not city or city.isdigit():
        return ""
    if region and len(region) <= MAX_REGION_LEN and region.casefold() != city.casefold():
        return f"{city}, {region}"
    return city


# Hawaii's islands, which matter far more to a reader than the state code
# they all share: "Honolulu, HI" and "Lahaina, HI" are a ferry apart.
# (south, west, north, east)
HAWAIIAN_ISLANDS: list[tuple[str, tuple[float, float, float, float]]] = [
    ("Kauai", (21.80, -159.85, 22.30, -159.25)),
    ("Oahu", (21.20, -158.35, 21.75, -157.60)),
    ("Molokai", (21.02, -157.35, 21.25, -156.70)),
    ("Lanai", (20.70, -157.10, 20.95, -156.78)),
    ("Maui", (20.50, -156.75, 21.05, -155.95)),
    ("Big Island", (18.85, -156.10, 20.30, -154.75)),
]


def hawaiian_island(lat: float | None, lng: float | None) -> str:
    """Which island a Hawaiian coordinate sits on, or '' if not Hawaii."""
    if lat is None or lng is None:
        return ""
    for name, (s, w, n, e) in HAWAIIAN_ISLANDS:
        if s <= lat <= n and w <= lng <= e:
            return name
    return ""


def maps_url(place: dict) -> str:
    """A Google Maps link for a place.

    A CID points at the business listing, which is what you want. Dropped
    pins never had one, so fall back to coordinates rather than printing an
    entry with no way to find it.
    """
    cid = place.get("cid")
    if cid:
        return f"https://maps.google.com/?cid={cid}"
    lat, lng = place.get("lat"), place.get("lng")
    if lat is not None and lng is not None:
        return f"https://maps.google.com/?q={lat},{lng}"
    return ""

# Guides are a Jekyll collection, not posts: 60+ generated pages would drown
# the blog feed, and they are reference material rather than writing.
DEFAULT_OUTPUT_DIR = OUTPUT_DIR / "guides"

WANT_LABEL = "Want to Go"

MIN_SECTIONS = 2         # sections needed for a location to be eligible
MIN_PER_SECTION = 3      # places needed for a section to count
PER_GROUP = 5


def is_hand_edited(path: Path) -> bool:
    """True if a draft opts out of regeneration via front matter.

    Adding `hand_edited: true` to a guide's front matter protects it even
    from --force, so prose written into a draft is never silently replaced
    by placeholders on the next data refresh.
    """
    if not path.exists():
        return False
    for line in path.read_text(encoding="utf-8").splitlines()[:15]:
        if line.strip().replace(" ", "") == "hand_edited:true":
            return True
    return False


def slugify(name: str) -> str:
    """URL slug. Accents are folded, not replaced.

    Without the fold, "Montreal" with an acute becomes "montr-al" and
    "Zurich" with an umlaut "z-rich", because the non-ASCII byte is
    swapped for a hyphen like any other separator.
    """
    folded = unicodedata.normalize("NFKD", name)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    s = folded.lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def eligible_sections(scored: list[dict], location: str) -> list[tuple[str, list[dict]]]:
    sections = guide_sections(scored, location, PER_GROUP)
    return [(t, hits) for t, hits in sections if len(hits) >= MIN_PER_SECTION]


def map_include(*section_groups: list[tuple[str, list[dict]]]) -> str:
    """Jekyll include rendering this guide's places as a mini-map.

    Places are [name, lat, lng, section] tuples; the JSON is single-quoted
    into the include argument, so any apostrophe in a name is escaped.
    Want-to-go pins carry a "Want to Go" section label so the map colours
    them apart from places already visited.
    """
    rows = [
        [p["name"], p["lat"], p["lng"], WANT_LABEL if p.get("tier") == "want_to_go" else title]
        for sections in section_groups
        for title, hits in sections
        for p in hits
        if p.get("lat") is not None and p.get("lng") is not None
    ]
    if not rows:
        return ""
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("'", "&#39;")
    return "{% include gem-map.html places='" + payload + "' %}"


# (label, min places, min sections), richest first.
DEPTH_TIERS = [
    ("deep", 80, 4),
    ("good", 45, 4),
    ("solid", 25, 3),
    ("light", 12, 2),
    ("thin", 0, 0),
]


# A guide's bounding box doubles as its scale: a city box is a fraction of a
# degree, a country spans tens. Sorting the index by this puts Tokyo above
# Hokkaido above Japan, rather than alphabetically interleaving them.
SCALE_THRESHOLDS = [("city", 1.5), ("region", 60.0), ("country", float("inf"))]
SCALE_RANK = {"city": 0, "region": 1, "country": 2}


def outermost_guide(location: str, eligible: set[str]) -> str:
    """The widest eligible guide containing this one, or itself.

    San Francisco sits in SF Bay Area sits in Northern California. Sorting
    the index by this keeps a nesting family together, so the three appear
    as a block rather than scattered under S, R and R by their titles.
    """
    box = LOCATIONS.get(location)
    if not box:
        return location
    s, w, n, e = box
    containing = [
        name for name in eligible
        if LOCATIONS.get(name)
        and LOCATIONS[name][0] <= s and LOCATIONS[name][1] <= w
        and LOCATIONS[name][2] >= n and LOCATIONS[name][3] >= e
    ]
    if not containing:
        return location
    return max(containing, key=lambda nm: _box_area(LOCATIONS[nm]))


def _box_area(box: tuple[float, float, float, float]) -> float:
    s, w, n, e = box
    return max(n - s, 0.0) * max(e - w, 0.0)


def family_latitude(location: str, eligible: set[str]) -> float:
    """Latitude of a guide's outermost family member.

    Alphabetical order scatters a country's guides, so they are ordered
    geographically instead: north to south within whatever group they are
    shown in. Keying on the family rather than the guide keeps San
    Francisco, SF Bay Area and Northern California adjacent.
    """
    box = LOCATIONS.get(outermost_guide(location, eligible)) or LOCATIONS.get(location)
    if not box:
        return 0.0
    return (box[0] + box[2]) / 2


def location_scale(location: str) -> str:
    box = LOCATIONS.get(location)
    if not box:
        return "region"
    s, w, n, e = box
    area = max(n - s, 0.0) * max(e - w, 0.0)
    for name, limit in SCALE_THRESHOLDS:
        if area < limit:
            return name
    return "country"


def nested_locations(location: str, eligible: set[str]) -> list[str]:
    """Eligible guides whose box sits inside this one.

    Each place belongs to its smallest matching box, so a country guide is
    really "everywhere here that isn't already a city page". Saying which
    cities those are stops the Germany page looking like it forgot Berlin.
    """
    outer = LOCATIONS.get(location)
    if not outer:
        return []
    os_, ow, on, oe = outer
    outer_country = LOCATION_REGION.get(location, ("", ""))[1]
    inside = []
    for name in eligible:
        if name == location:
            continue
        box = LOCATIONS.get(name)
        if not box:
            continue
        s, w, n, e = box
        if not (s >= os_ and w >= ow and n <= on and e <= oe):
            continue
        # Germany's rectangle swallows Zurich, which is not in Germany.
        # Containment is geometric; only claim places the country shares.
        if outer_country and LOCATION_REGION.get(name, ("", ""))[1] != outer_country:
            continue
        inside.append(name)
    return sorted(inside)


def depth_label(place_count: int, section_count: int) -> str:
    """How much to trust a guide, from how much data stands behind it."""
    for label, min_places, min_sections in DEPTH_TIERS:
        if place_count >= min_places and section_count >= min_sections:
            return label
    return "thin"


# How each depth reads to someone deciding whether to trust the list.
DEPTH_BLURB = {
    "deep": "one of the best-covered places here",
    "good": "well covered",
    "solid": "a decent sample, but not exhaustive",
    "light": "a light sample, so treat it as a few leads rather than a guide",
    "thin": "a thin sample — I haven't spent much time here",
}

# Shown in each guide's disclaimer so readers can report a bad result.
CONTACT = os.environ.get("GUIDE_CONTACT", "")

# Below this the difference is noise, not a reviewing culture.
MIN_RATING_DELTA = 0.05
MIN_DELTA_SAMPLE = 12


def rating_delta_note(location: str, pool: list[dict], us_mean: float) -> str:
    """How this place's ratings sit against the American scale.

    The whole project rests on ratings not being comparable across borders,
    so each guide says where its own numbers sit relative to the US, which
    is the scale most readers have calibrated on.
    """
    ratings = [p["rating"] for p in pool if p.get("rating") is not None]
    if len(ratings) < MIN_DELTA_SAMPLE or not us_mean:
        return ""
    delta = statistics.fmean(ratings) - us_mean
    if abs(delta) < MIN_RATING_DELTA:
        return f"Reviews in {location} run about level with the US."
    return f"Reviews in {location} average {delta:+.2f} compared to the US."


def render_header(
    location: str,
    pool_size: int,
    shown: int,
    depth: str,
    today: dt.date,
    delta_note: str = "",
    excludes: list[str] | None = None,
    ai_lines: int = 0,
) -> list[str]:
    """Provenance and caveats, stated up front on every guide.

    One thought per line: how big the list is, how far to trust it, how its
    ratings compare, and when the data is from. Run together as a paragraph
    these blur into each other and none of them get read.
    """
    rows = [
        "<dl class=\"place-summary\">",
        ("  <div><dt>Depth</dt><dd>"
            f"<span class=\"places-depth places-depth-{depth}\">{depth}</span> "
            f"<strong>{shown}/{pool_size}</strong> places I&rsquo;ve visited here"
            "</dd></div>"),
    ]
    if delta_note:
        rows.append(f"  <div><dt>Ratings</dt><dd>{delta_note}</dd></div>")
    if excludes:
        links = ", ".join(
            f"<a href=\"/places/{slugify(n)}/\">{n}</a>" for n in excludes
        )
        rows.append(
            f"  <div><dt>Excludes</dt><dd>{links} &mdash; each has its own page</dd></div>"
        )
    rows += [
        "</dl>",
        "",
        ("<p class=\"place-disclaimer\">This list is "
            "<a href=\"/places/\">algorithmically generated</a> from places "
            "I&rsquo;ve marked visited on Google Maps.<br>"
            "I penalise places for being too popular, but some are so highly "
            "reviewed they make the list anyway.<br>"
            "I don&rsquo;t review every result, so some may be very weird!"
            # Only invite reports when there is somewhere to send them.
            + (f" <a href=\"{CONTACT}\">Tell me</a> if you spot one :)</p>"
               if CONTACT else "</p>")),
    ]
    return rows


def render_entry(place: dict, show_country: bool = False) -> str:
    """One place, as up to three lines.

    Headline (name, where, how it rates), then any description on its own
    line, then the map link on its own line — so the eye can skim names
    without the links running into the prose.
    """
    bits = [f"**{place['name']}**"]
    country = (place.get("country") or "").strip()
    locality = place_locality(place.get("address", ""), country)
    island = hawaiian_island(place.get("lat"), place.get("lng"))
    if island:
        # Swap the shared state code for the island.
        city = locality.split(",")[0].strip()
        locality = f"{city}, {island}" if city and city != "HI" else island
    # A guide spanning several countries ('Persian Gulf') needs the country
    # on each line, or "Doha" and "Dubai" sit side by side unexplained.
    if show_country and country and country != "Unknown":
        locality = f"{locality}, {country}" if locality else country
    if locality:
        bits.append(f"**{locality}**")
    bits.append(f"{place['rating']}★ ({place['review_count']:,} reviews)")

    lines = [" · ".join(bits)]
    description = (place.get("description") or "").strip()
    if description:
        lines.append(description)
    url = maps_url(place)
    if url:
        lines.append(f"[Google Maps]({url})")
    # Two trailing spaces force a line break inside one markdown paragraph.
    return "  \n".join(lines)


def render_guide(
    location: str,
    sections: list[tuple[str, list[dict]]],
    today: dt.date,
    wanted: list[tuple[str, list[dict]]] | None = None,
    pool_size: int = 0,
    delta_note: str = "",
    excludes: list[str] | None = None,
    family: str = "",
    family_lat: float = 0.0,
) -> str:
    """A guide page. Entirely generated — no placeholders to fill in.

    Every line states what the data says: where the place is, how it rates,
    how many people rated it, and a link to it. Nothing here asks for prose.
    """
    wanted = wanted or []
    continent, country = LOCATION_REGION.get(location, ("", ""))
    shown = sum(len(h) for _, h in sections) + sum(len(h) for _, h in wanted)
    depth = depth_label(pool_size, len(sections))

    # Whether to name the country on each line is a property of the guide,
    # not of its addresses. Counting distinct country strings made Tokyo
    # look multi-country because some addresses say "Japan" and others
    # "\u65e5\u672c". A region that genuinely spans countries says so in its
    # configured name, e.g. "Qatar & UAE".
    show_country = "&" in country

    # A guide that contains other guides is really the remainder: Tokyo and
    # Hokkaido have their own pages, so the Japan page is everywhere else.
    # Saying "Rest of Japan" in the title is clearer than any footnote. The
    # filename keeps the plain name, so URLs stay put.
    display = f"Rest of {location}" if excludes else location

    lines = [
        "---",
        "layout: page",
        f'title: "{display}"',
        # Same header treatment as the site's other main pages. No deck: the
        # summary list below the title already serves as the subhead.
        "editorial_header: true",
        f"location: \"{location}\"",
        f"continent: \"{continent}\"",
        f"country: \"{country}\"",
        f"place_count: {pool_size}",
        f"section_count: {len(sections)}",
        f"shown_count: {shown}",
        f"depth: {depth}",
        f"scale: {location_scale(location)}",
        f"scale_rank: {SCALE_RANK[location_scale(location)]}",
        f'family: "{family or location}"',
        # One composite sort key: longitude orders a country west to east
        # and the scale digit puts a city above its region above its
        # country. Two Liquid `sort` filters cannot do this; the second
        # discards the first ordering.
        # One composite key. 90 minus latitude orders north to south; the
        # box area then puts the most specific guide first inside a family.
        # Area rather than the scale label, because SF Bay Area is small
        # enough to count as a "city" and would tie with San Francisco.
        # Two Liquid `sort` filters cannot do this; the second discards the
        # first ordering.
        f'sort_key: "{90 - family_lat:06.2f}-{_box_area(LOCATIONS.get(location, (0, 0, 0, 0))):09.3f}"',
        f'subregion: "{US_SUBREGION.get(location, "")}"',
        f"subregion_rank: {SUBREGION_ORDER.index(US_SUBREGION[location]) if location in US_SUBREGION else 9}",
        f"generated: {today.isoformat()}",
        "---",
        "",
        *render_header(
            location, pool_size, shown, depth, today, delta_note, excludes,
            ai_lines=sum(
                1
                for _, hits in list(sections) + list(wanted)
                for p in hits
                if p.get("description") and p.get("description_source") == "ai"
            ),
        ),
    ]

    embed = map_include(sections, wanted)
    if embed:
        lines += ["", embed]

    for title, hits in sections:
        lines += ["", f"## {title}", ""]
        for p in hits:
            lines.append(render_entry(p, show_country))
            lines.append("")

    if wanted:
        lines += [
            "",
            "## Still on my list",
            "",
            ("<p class=\"place-meta\">Saved but not yet visited — same scoring, "
                "no personal verdict.</p>"),
        ]
        for title, hits in wanted:
            lines += ["", f"### {title}", ""]
            for p in hits:
                lines.append(render_entry(p, show_country))
                lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--location", default=None, help="generate only this location")
    parser.add_argument("--force", action="store_true", help="overwrite existing drafts")
    parser.add_argument("--list", action="store_true", help="show eligibility, write nothing")
    args = parser.parse_args()

    scored = json.loads(GEM_SCORES.read_text(encoding="utf-8"))
    # Aware, then converted back to local: the stamp is the local date,
    # but naive date.today() trips ruff's DTZ011.
    today = dt.datetime.now(tz=dt.timezone.utc).astimezone().date()
    targets = [args.location] if args.location else sorted(LOCATIONS)

    visited = [p for p in scored if p.get("tier") != "want_to_go"]
    wanted_pool = [p for p in scored if p.get("tier") == "want_to_go"]

    us_ratings = [
        p["rating"] for p in visited
        if p.get("country") == "United States" and p.get("rating") is not None
    ]
    us_mean = statistics.fmean(us_ratings) if us_ratings else 0.0

    # Which locations will produce a page, so nested-guide links never 404.
    eligible = {
        loc for loc in LOCATIONS
        if len(eligible_sections(visited, loc)) >= MIN_SECTIONS
    }

    written, skipped, ineligible = [], [], []
    for location in targets:
        sections = eligible_sections(visited, location)
        wanted = guide_sections(wanted_pool, location, PER_GROUP)
        if len(sections) < MIN_SECTIONS:
            ineligible.append(location)
            continue
        # The pool is every place that could have made this guide, which is
        # what tells a reader whether it rests on 200 places or on 12.
        pool = [
            p for p in visited
            if location in p["locations"] and not p["famous"] and not p.get("chain")
        ]
        pool_size = len(pool)
        if args.list:
            counts = ", ".join(f"{t}:{len(h)}" for t, h in sections)
            print(f"  {location:24} [{depth_label(pool_size, len(sections)):5}] "
                  f"pool {pool_size:4}  {counts}")
            continue
        path = args.output_dir / f"{slugify(location)}.md"
        if path.exists() and is_hand_edited(path):
            skipped.append(location)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        note = "" if LOCATION_REGION.get(location, ("", ""))[1] == "United States" else rating_delta_note(location, pool, us_mean)
        path.write_text(
            render_guide(
                location, sections, today, wanted, pool_size, note,
                nested_locations(location, eligible),
                outermost_guide(location, eligible),
                family_latitude(location, eligible),
            ),
            encoding="utf-8",
        )
        written.append(location)

    if not args.list:
        print(f"wrote {len(written)}")
        if skipped:
            print(f"skipped (hand_edited): {', '.join(skipped)}")
    print(f"not yet eligible: {len(ineligible)} locations")


if __name__ == "__main__":
    main()
