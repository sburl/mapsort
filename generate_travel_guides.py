#!/usr/bin/env python3
"""Generate travel guide drafts from KML place data.

Scans all KML files, groups places by location bounding box, and outputs:
  1. Raw data sorted by category (raw-data.md)
  2. Three draft blog post versions (draft-1.md, draft-2.md, draft-3.md)

Usage:
    python generate_travel_guides.py
    python generate_travel_guides.py --output-dir /path/to/your-site/_drafts/travel-guides
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

from settings import OUTPUT_DIR

KML_NS = "http://www.opengis.net/kml/2.2"

# ── Location definitions ────────────────────────────────────────────
# (south_lat, west_lng, north_lat, east_lng)
LOCATIONS: dict[str, tuple[float, float, float, float]] = {
    # Tier A cities
    # The five boroughs. "Greater New York" is the surrounding metro.
    "New York City": (40.49, -74.26, 40.92, -73.70),
    "San Francisco": (37.70, -122.52, 37.82, -122.35),
    # Widened to Greater LA + Orange County so Pasadena, Burbank, San Marino
    # and Anaheim land here rather than in a vague "Southern California".
    "LA": (33.55, -118.95, 34.35, -117.55),
    "Tokyo": (35.53, 139.55, 35.82, 139.92),
    "Bangkok": (13.60, 100.35, 13.90, 100.65),
    "Boston": (42.28, -71.19, 42.40, -70.99),
    # Metro Pittsburgh.
    "Pittsburgh": (40.20, -80.30, 40.65, -79.60),
    "Istanbul": (40.88, 28.63, 41.20, 29.15),
    # Widened to the DC metro: McLean, Vienna VA and Arlington parks
    # were landing in no guide at all.
    "Washington DC": (38.70, -77.40, 39.10, -76.75),
    "Hong Kong": (22.15, 113.82, 22.56, 114.35),
    "Buenos Aires": (-34.70, -58.55, -34.52, -58.33),
    # Tier A regions
    "Japan": (30.00, 128.00, 45.55, 146.00),
    "SF Bay Area": (37.20, -122.60, 37.90, -121.80),
    "New England": (41.00, -73.73, 47.46, -66.95),
    "Argentina": (-55.05, -73.60, -21.78, -53.60),
    "Hawaii": (18.90, -160.25, 22.25, -154.80),
    "Vietnam": (8.18, 102.14, 23.39, 109.46),
    # Tier B cities
    "Singapore": (1.20, 103.60, 1.47, 104.05),
    "New Orleans": (29.90, -90.14, 30.00, -89.95),
    "Berlin": (52.34, 13.08, 52.68, 13.76),
    "Lisbon": (38.69, -9.23, 38.80, -9.09),
    # Metro Atlanta: Stone Mountain, Truist Park and Sweetwater Creek.
    "Atlanta": (33.50, -84.75, 34.10, -84.00),
    "Bangalore": (12.85, 77.48, 13.08, 77.72),
    "Delhi": (28.45, 76.95, 28.80, 77.35),
    "CDMX": (19.20, -99.35, 19.55, -99.00),
    "Seoul": (37.42, 126.80, 37.70, 127.15),
    "Vienna": (48.12, 16.18, 48.32, 16.52),
    "Budapest": (47.40, 18.95, 47.58, 19.18),
    "Osaka": (34.55, 135.38, 34.75, 135.58),
    "Amsterdam": (52.33, 4.73, 52.43, 5.02),
    "Philadelphia": (39.87, -75.28, 40.07, -75.05),
    "Kyiv": (50.35, 30.35, 50.55, 30.65),
    "Warsaw": (52.13, 20.85, 52.32, 21.10),
    "Montréal": (45.41, -73.75, 45.62, -73.47),
    "Geneva": (46.15, 6.05, 46.28, 6.22),
    # Tier B regions
    # West edge reaches 46.5 to take in Kuwait, which sat outside the
    # original box despite being on the same gulf.
    "Persian Gulf": (21.00, 46.50, 30.50, 59.50),
    "Iceland": (63.30, -24.55, 66.60, -13.50),
    # Tier C cities
    # Widened past the city: the Stalin Line and the Mound of Glory are
    # 30km out and were landing in no guide at all.
    "Minsk": (53.60, 26.90, 54.30, 28.20),
    # Albania's 9 places give one qualifying section on their own; with
    # North Macedonia's 16 the pair makes a guide.
    "Albania & North Macedonia": (39.60, 19.20, 42.70, 23.03),
    "Venice": (45.40, 12.28, 45.48, 12.38),
    "Fukuoka": (33.52, 130.30, 33.65, 130.48),
    "Hiroshima": (34.30, 132.35, 34.45, 132.55),
    # East to Tervuren for the Africa Museum, south for Waterloo.
    "Brussels": (50.60, 4.15, 51.00, 4.65),
    "Prague": (50.00, 14.22, 50.15, 14.55),
    "Zürich": (47.25, 8.35, 47.45, 8.70),
    "Kyoto": (34.93, 135.68, 35.08, 135.82),
    "Kagoshima": (31.50, 130.45, 31.65, 130.75),
    "Chennai": (12.95, 80.15, 13.15, 80.30),
    "Nova Scotia": (43.38, -66.42, 47.03, -59.73),
    # Added 2026-08 from uncovered-cluster analysis
    "Paris": (48.70, 2.10, 49.05, 2.60),
    "London": (51.25, -0.55, 51.72, 0.30),
    "Rome": (41.75, 12.30, 42.05, 12.70),
    "Chicago": (41.60, -88.05, 42.10, -87.50),
    "Copenhagen & Malmö": (55.50, 12.30, 55.75, 13.15),
    "Kuala Lumpur": (2.95, 101.50, 3.35, 101.85),
    "Sydney": (-34.15, 150.85, -33.60, 151.35),
    "Melbourne": (-38.15, 144.70, -37.55, 145.30),
    "Israel": (29.45, 34.20, 33.35, 35.90),
    "Las Vegas": (35.95, -115.35, 36.35, -114.95),
    "Vancouver": (49.00, -123.30, 49.40, -122.90),
    "Munich": (48.00, 11.30, 48.30, 11.80),
    # Widened to San Diego County (Julian, Palomar Mountain).
    "San Diego": (32.50, -117.40, 33.45, -116.30),
    # Added 2026-09 — broad regional buckets. Cities above stay the precise
    # layer; these catch everything between them, which was previously
    # invisible to the guides (3,085 places matched no box at all).
    "Northern California": (36.00, -124.50, 40.50, -119.50),
    "Greater New York": (40.40, -74.70, 41.60, -71.80),
    "Germany": (47.20, 5.80, 55.10, 15.10),
    "France": (42.30, -5.20, 51.10, 8.25),
    # Both sit inside the France rectangle and are far smaller, so they
    # reclaim their own places. Without these the Africa Museum and the
    # Waterloo battlefield were filed under France.
    "Belgium": (49.45, 2.50, 51.55, 6.45),
    "Switzerland": (45.80, 5.95, 47.82, 10.50),
    "Italy": (36.60, 6.60, 47.10, 18.60),
    # West edge is -7.0, not -9.4: the wider box swallowed Portugal whole and
    # the "Spain" guide came out 38 Portuguese places to 28 Spanish ones.
    "Spain": (36.00, -7.00, 43.80, 3.40),
    "Portugal": (36.90, -9.60, 42.20, -6.20),
    # Contains London, which keeps its own page, so this renders as
    # "Rest of England & Wales".
    "England & Wales": (50.00, -6.50, 55.90, 1.90),
    "Florida": (24.40, -87.70, 31.10, -79.90),
    # Austin (6), Texas (3) and Tulsa (12) each fell below the bar alone;
    # as one box they make a guide. Separate boxes meant no guide at all.
    "Texas & Oklahoma": (25.80, -106.70, 37.10, -93.50),
    # Widened west-to-east to take in Denver and Boulder, which had 3
    # places of their own and no guide.
    "Utah & Colorado": (36.90, -114.10, 42.10, -104.50),
    "Mexico": (14.50, -118.40, 32.70, -86.70),
    "Cuba": (19.80, -85.00, 23.30, -74.10),
    "Brazil": (-33.80, -74.00, 5.30, -34.80),
    "Peru": (-18.40, -81.40, 0.00, -68.60),
    "Philippines": (4.60, 116.90, 19.60, 126.60),
    "Taiwan": (21.80, 119.50, 25.40, 122.10),
    # Added 2026-10. New England was carrying 97 New Hampshire places and 40
    # Maine ones under one label; Seattle and Toronto had no guide at all.
    "New Hampshire": (42.70, -72.56, 45.31, -70.70),
    # Both sit inside the New England rectangle, which reaches into Canada.
    # They are smaller, so exclusive assignment gives them their own places
    # back instead of filing Quebec City under New England. Keep them
    # smaller than New England (~30 sq deg) or that stops working.
    "Québec": (45.00, -74.50, 48.00, -69.50),
    "New Brunswick": (45.00, -68.00, 48.00, -64.00),
    "Seattle & Puget Sound": (46.85, -123.30, 48.80, -121.50),
    "Romania": (43.62, 20.26, 48.27, 29.70),
    "Hokkaido": (41.35, 139.33, 45.56, 145.83),
    "Nashville": (36.00, -87.06, 36.41, -86.51),
    "Toronto": (43.58, -79.64, 43.86, -79.12),
}

# ── Continent / country for each location ─────────────────────────
# Stated explicitly rather than inferred from each location's places: the
# modal-country heuristic mislabels bboxes that straddle a border (the Spain
# box catches more rated places in Portugal) or whose addresses omit the
# country (Kyiv came out as "United States"). Used to group the guide index.
LOCATION_REGION: dict[str, tuple[str, str]] = {
    # North America
    "Atlanta": ("North America", "United States"),
    "Boston": ("North America", "United States"),
    "CDMX": ("North America", "Mexico"),
    "Mexico": ("North America", "Mexico"),
    "Chicago": ("North America", "United States"),
    "Cuba": ("North America", "Cuba"),
    "Washington DC": ("North America", "United States"),
    "Florida": ("North America", "United States"),
    "Greater New York": ("North America", "United States"),
    "Hawaii": ("North America", "United States"),
    "LA": ("North America", "United States"),
    "Las Vegas": ("North America", "United States"),
    "Montréal": ("North America", "Canada"),
    "Québec": ("North America", "Canada"),
    "New Brunswick": ("North America", "Canada"),
    "New England": ("North America", "United States"),
    "New Orleans": ("North America", "United States"),
    "New York City": ("North America", "United States"),
    "Northern California": ("North America", "United States"),
    "Nova Scotia": ("North America", "Canada"),
    "Texas & Oklahoma": ("North America", "United States"),
    "New Hampshire": ("North America", "United States"),
    "Seattle & Puget Sound": ("North America", "United States"),
    "Nashville": ("North America", "United States"),
    "Toronto": ("North America", "Canada"),
    "Philadelphia": ("North America", "United States"),
    "Pittsburgh": ("North America", "United States"),
    "SF Bay Area": ("North America", "United States"),
    "San Diego": ("North America", "United States"),
    "San Francisco": ("North America", "United States"),
    "Texas": ("North America", "United States"),
    "Utah & Colorado": ("North America", "United States"),
    "Vancouver": ("North America", "Canada"),
    # South America
    "Argentina": ("South America", "Argentina"),
    "Brazil": ("South America", "Brazil"),
    "Buenos Aires": ("South America", "Argentina"),
    "Peru": ("South America", "Peru"),
    # Europe
    "Amsterdam": ("Europe", "Netherlands"),
    "Berlin": ("Europe", "Germany"),
    "Belgium": ("Europe", "Belgium"),
    "Switzerland": ("Europe", "Switzerland"),
    "Brussels": ("Europe", "Belgium"),
    "Romania": ("Europe", "Romania"),
    "Budapest": ("Europe", "Hungary"),
    "Copenhagen & Malmö": ("Europe", "Denmark"),
    "England & Wales": ("Europe", "United Kingdom"),
    "Geneva": ("Europe", "Switzerland"),
    "France": ("Europe", "France"),
    "Germany": ("Europe", "Germany"),
    "Zürich": ("Europe", "Switzerland"),
    "Iceland": ("Europe", "Iceland"),
    "Istanbul": ("Europe", "Türkiye"),
    "Italy": ("Europe", "Italy"),
    "Kyiv": ("Europe", "Ukraine"),
    "Lisbon": ("Europe", "Portugal"),
    "Portugal": ("Europe", "Portugal"),
    "London": ("Europe", "United Kingdom"),
    "Minsk": ("Europe", "Belarus"),
    "Albania & North Macedonia": ("Europe", "Albania & North Macedonia"),
    "Munich": ("Europe", "Germany"),
    "Paris": ("Europe", "France"),
    "Prague": ("Europe", "Czechia"),
    "Rome": ("Europe", "Italy"),
    "Spain": ("Europe", "Spain"),
    "Venice": ("Europe", "Italy"),
    "Vienna": ("Europe", "Austria"),
    "Warsaw": ("Europe", "Poland"),
    # Asia
    "Bangalore": ("Asia", "India"),
    "Bangkok": ("Asia", "Thailand"),
    "Chennai": ("Asia", "India"),
    "Delhi": ("Asia", "India"),
    "Fukuoka": ("Asia", "Japan"),
    "Hiroshima": ("Asia", "Japan"),
    "Hokkaido": ("Asia", "Japan"),
    "Hong Kong": ("Asia", "Hong Kong"),
    "Israel": ("Asia", "Israel"),
    "Japan": ("Asia", "Japan"),
    "Kagoshima": ("Asia", "Japan"),
    "Kuala Lumpur": ("Asia", "Malaysia"),
    "Kyoto": ("Asia", "Japan"),
    "Osaka": ("Asia", "Japan"),
    "Persian Gulf": ("Asia", "Qatar, UAE & Kuwait"),
    "Philippines": ("Asia", "Philippines"),
    "Seoul": ("Asia", "South Korea"),
    "Singapore": ("Asia", "Singapore"),
    "Taiwan": ("Asia", "Taiwan"),
    "Tokyo": ("Asia", "Japan"),
    "Vietnam": ("Asia", "Vietnam"),
    # Oceania
    "Melbourne": ("Oceania", "Australia"),
    "Sydney": ("Oceania", "Australia"),
}

# US guides grouped coarsely, east to west. Longitude alone cannot do this:
# it would file Washington DC with Pittsburgh and Texas with Colorado. Only
# the US has enough guides to need the extra level.
US_SUBREGION: dict[str, str] = {
    # East
    "Boston": "East",
    "New England": "East",
    "New Hampshire": "East",
    "New York City": "East",
    "Greater New York": "East",
    "Philadelphia": "East",
    "Pittsburgh": "East",
    "Washington DC": "East",
    "Atlanta": "East",
    "Florida": "East",
    # Middle
    "Chicago": "Middle",
    "Texas & Oklahoma": "Middle",
    "Nashville": "Middle",
    "New Orleans": "Middle",
    "Utah & Colorado": "Middle",
    # West
    "Las Vegas": "West",
    "San Diego": "West",
    "LA": "West",
    "Northern California": "West",
    "SF Bay Area": "West",
    "San Francisco": "West",
    "Seattle & Puget Sound": "West",
    "Hawaii": "West",
}

SUBREGION_ORDER = ["East", "Middle", "West"]


# Display order for the guide index.
CONTINENT_ORDER = [
    "North America",
    "South America",
    "Europe",
    "Asia",
    "Oceania",
    "Africa",
]


# ── Category display config ─────────────────────────────────────────
SLUG_DISPLAY: dict[str, tuple[str, str]] = {
    "restaurants": ("Where to Eat", "Restaurants"),
    "cafes_bakeries": ("Coffee & Bakeries", "Cafes & Bakeries"),
    "quick_bites": ("Quick Bites", "Quick Bites"),
    "bars_nightlife": ("Where to Drink", "Bars & Nightlife"),
    "sweets_snacks": ("Sweets & Snacks", "Sweets & Snacks"),
    "hotels_stays": ("Where to Stay", "Hotels & Stays"),
    "landmarks_history": ("Landmarks & History", "Landmarks & History"),
    "museums_culture": ("Museums & Culture", "Museums & Culture"),
    "entertainment": ("Entertainment", "Entertainment"),
    "sacred_sites": ("Sacred & Religious Sites", "Sacred Sites"),
    "shopping": ("Shopping", "Shopping"),
    "nature_outdoors": ("Nature & Outdoors", "Nature & Outdoors"),
    "parks_gardens": ("Parks & Gardens", "Parks & Gardens"),
    "regions_destinations": ("Neighborhoods & Areas", "Regions & Destinations"),
    "airports": ("Getting There", "Airports"),
    "train_transit": ("Getting Around", "Train & Transit"),
    "practical": ("Practical", "Practical"),
    "ski_resorts": ("Ski & Snow", "Ski Resorts"),
    "scuba_diving": ("Diving", "Scuba & Diving"),
}

# Section ordering for guides
GUIDE_SECTIONS = [
    "restaurants", "cafes_bakeries", "quick_bites", "bars_nightlife",
    "sweets_snacks", "hotels_stays", "landmarks_history", "museums_culture",
    "entertainment", "sacred_sites", "shopping", "nature_outdoors",
    "parks_gardens", "regions_destinations", "ski_resorts", "scuba_diving",
    "airports", "train_transit", "practical",
]


def _slug_to_folder(name: str) -> str:
    """Convert location name to folder-safe slug."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def extract_places() -> list[dict]:
    """Extract all places from KML files."""
    pat = re.compile(r"^(blue|green)_(.+?)(?:_part\d+)?\.kml$")
    places = []
    for f in sorted(OUTPUT_DIR.glob("*.kml")):
        m = pat.match(f.name)
        if not m or " 2" in f.name:
            continue
        color = m.group(1)
        slug = m.group(2)
        tree = ET.parse(f)
        for pm in tree.findall(f".//{{{KML_NS}}}Placemark"):
            name_el = pm.find(f"{{{KML_NS}}}name")
            desc_el = pm.find(f"{{{KML_NS}}}description")
            coords_el = pm.find(f".//{{{KML_NS}}}coordinates")
            name = name_el.text if name_el is not None else ""
            desc = desc_el.text if desc_el is not None else ""
            lat, lng = 0.0, 0.0
            if coords_el is not None and coords_el.text:
                parts = coords_el.text.strip().split(",")
                if len(parts) >= 2:
                    try:
                        lng, lat = float(parts[0]), float(parts[1])
                    except ValueError:
                        pass
            places.append({
                "name": name or "", "desc": desc or "",
                "lat": lat, "lng": lng,
                "color": color, "slug": slug,
            })
    return places


def match_places(
    places: list[dict], bbox: tuple[float, float, float, float],
) -> dict[str, dict[str, list[str]]]:
    """Match places to a bounding box, grouped by slug and color."""
    s_lat, w_lng, n_lat, e_lng = bbox
    matched: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: {"blue": [], "green": []}
    )
    for p in places:
        if p["lat"] == 0 and p["lng"] == 0:
            continue
        if s_lat <= p["lat"] <= n_lat and w_lng <= p["lng"] <= e_lng:
            matched[p["slug"]][p["color"]].append(p["name"])
    return dict(matched)


def tier_for(matched: dict) -> str:
    total = sum(len(v["blue"]) + len(v["green"]) for v in matched.values())
    cats = len(matched)
    if total >= 100 and cats >= 8:
        return "A"
    if total >= 30 and cats >= 5:
        return "B"
    if total >= 10 and cats >= 3:
        return "C"
    return "D"


def write_raw_data(
    path: Path, loc_name: str, matched: dict, tier: str,
) -> None:
    total = sum(len(v["blue"]) + len(v["green"]) for v in matched.values())
    want = sum(len(v["blue"]) for v in matched.values())
    visited = sum(len(v["green"]) for v in matched.values())

    lines = [
        f"# {loc_name} — Raw Place Data\n",
        (f"**Tier {tier}** | {total} places "
            f"({want} want to go, {visited} visited) | "
            f"{len(matched)} categories\n"),
        "---\n",
    ]
    for slug in GUIDE_SECTIONS:
        if slug not in matched:
            continue
        data = matched[slug]
        _, display = SLUG_DISPLAY.get(slug, (slug, slug))
        b, g = data["blue"], data["green"]
        lines.append(f"\n## {display} ({len(b) + len(g)})\n")
        if g:
            lines.append(f"\n### Visited ({len(g)})\n")
            for name in sorted(g):
                lines.append(f"- {name}\n")
        if b:
            lines.append(f"\n### Want to Go ({len(b)})\n")
            for name in sorted(b):
                lines.append(f"- {name}\n")

    path.write_text("".join(lines), encoding="utf-8")


def _section_block(
    slug: str, matched: dict, visited_only: bool = False,
) -> list[str]:
    """Build a markdown section for a category."""
    if slug not in matched:
        return []
    data = matched[slug]
    section_title, _ = SLUG_DISPLAY.get(slug, (slug, slug))
    b, g = data["blue"], data["green"]
    if not b and not g:
        return []
    lines = [f"\n## {section_title}\n\n"]
    if g:
        for name in sorted(g):
            lines.append(f"- {name} ✓\n")
    if b and not visited_only:
        for name in sorted(b):
            lines.append(f"- {name}\n")
    return lines


def write_draft_1(
    path: Path, loc_name: str, matched: dict, tier: str,
) -> None:
    """Draft 1: Comprehensive list-style guide."""
    total = sum(len(v["blue"]) + len(v["green"]) for v in matched.values())
    lines = [
        "---\n",
        "layout: post\n",
        f"title: \"A Local's Guide to {loc_name}\"\n",
        "date: 2026-03-07\n",
        "categories: [travel]\n",
        f"tags: [travel, {_slug_to_folder(loc_name)}]\n",
        "---\n\n",
        (f"*{total} places I've been to or want to visit in {loc_name}, "
            "organized by category. Places marked with ✓ are ones I've "
            "personally visited.*\n\n"),
        "<!--more-->\n",
    ]
    for slug in GUIDE_SECTIONS:
        lines.extend(_section_block(slug, matched))
    path.write_text("".join(lines), encoding="utf-8")


def write_draft_2(
    path: Path, loc_name: str, matched: dict, tier: str,
) -> None:
    """Draft 2: Curated highlights — visited places only, grouped thematically."""
    visited = sum(len(v["green"]) for v in matched.values())
    if visited == 0:
        # Fall back to want-to-go if no visited places
        write_draft_1(path, loc_name, matched, tier)
        return

    eat_slugs = ["restaurants", "cafes_bakeries", "quick_bites",
                 "bars_nightlife", "sweets_snacks"]
    see_slugs = ["landmarks_history", "museums_culture", "entertainment",
                 "sacred_sites", "shopping"]
    do_slugs = ["nature_outdoors", "parks_gardens", "regions_destinations",
                "ski_resorts", "scuba_diving"]
    stay_slugs = ["hotels_stays"]
    move_slugs = ["airports", "train_transit", "practical"]

    def _mega_section(title: str, slugs: list[str]) -> list[str]:
        all_names: list[str] = []
        for s in slugs:
            if s in matched:
                all_names.extend(matched[s]["green"])
        if not all_names:
            return []
        lines = [f"\n## {title}\n\n"]
        for name in sorted(all_names):
            lines.append(f"- {name}\n")
        return lines

    lines = [
        "---\n",
        "layout: post\n",
        f"title: \"What I Loved in {loc_name}\"\n",
        "date: 2026-03-07\n",
        "categories: [travel]\n",
        f"tags: [travel, {_slug_to_folder(loc_name)}]\n",
        "---\n\n",
        (f"*The places I actually visited and enjoyed in {loc_name}. "
            "This is the personal, tested version of the guide.*\n\n"),
        "<!--more-->\n",
    ]
    lines.extend(_mega_section("Eat & Drink", eat_slugs))
    lines.extend(_mega_section("See & Do", see_slugs + do_slugs))
    lines.extend(_mega_section("Where to Stay", stay_slugs))
    lines.extend(_mega_section("Getting Around", move_slugs))
    path.write_text("".join(lines), encoding="utf-8")


def write_draft_3(
    path: Path, loc_name: str, matched: dict, tier: str,
) -> None:
    """Draft 3: Wish list — want-to-go places only, for trip planning."""
    want = sum(len(v["blue"]) for v in matched.values())
    if want == 0:
        # Nothing on the wish list — write a note
        lines = [
            "---\n",
            "layout: post\n",
            f"title: \"{loc_name} — Been There, Done That\"\n",
            "date: 2026-03-07\n",
            "categories: [travel]\n",
            f"tags: [travel, {_slug_to_folder(loc_name)}]\n",
            "---\n\n",
            (f"*I've visited everything on my {loc_name} list. "
                "Time to find new spots.*\n\n"),
            "<!--more-->\n",
        ]
        path.write_text("".join(lines), encoding="utf-8")
        return

    lines = [
        "---\n",
        "layout: post\n",
        f"title: \"{loc_name} — My Hit List\"\n",
        "date: 2026-03-07\n",
        "categories: [travel]\n",
        f"tags: [travel, {_slug_to_folder(loc_name)}]\n",
        "---\n\n",
        (f"*{want} places I haven't been to yet in {loc_name}. "
            "This is my trip-planning cheat sheet.*\n\n"),
        "<!--more-->\n",
    ]
    for slug in GUIDE_SECTIONS:
        if slug not in matched:
            continue
        data = matched[slug]
        if not data["blue"]:
            continue
        section_title, _ = SLUG_DISPLAY.get(slug, (slug, slug))
        lines.append(f"\n## {section_title} ({len(data['blue'])})\n\n")
        for name in sorted(data["blue"]):
            lines.append(f"- {name}\n")
    path.write_text("".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate travel guide drafts from KML place data."
    )
    parser.add_argument(
        "--output-dir",
        default=str(OUTPUT_DIR / "travel-guides"),
        help="Output directory for guides.",
    )
    args = parser.parse_args(argv)
    out_root = Path(args.output_dir)

    print("Extracting places from KML files...")
    places = extract_places()
    has_coords = [p for p in places if p["lat"] != 0 or p["lng"] != 0]
    print(f"  {len(places)} total, {len(has_coords)} with coordinates\n")

    tier_counts: dict[str, int] = defaultdict(int)

    for loc_name, bbox in sorted(LOCATIONS.items()):
        matched = match_places(has_coords, bbox)
        if not matched:
            print(f"  SKIP (no matches): {loc_name}")
            continue

        tier = tier_for(matched)
        if tier == "D":
            print(f"  SKIP (Tier D): {loc_name}")
            continue

        total = sum(len(v["blue"]) + len(v["green"]) for v in matched.values())
        folder = out_root / f"{_slug_to_folder(loc_name)}"
        folder.mkdir(parents=True, exist_ok=True)

        write_raw_data(folder / "raw-data.md", loc_name, matched, tier)
        write_draft_1(folder / "draft-1-full-guide.md", loc_name, matched, tier)
        write_draft_2(folder / "draft-2-visited-highlights.md", loc_name, matched, tier)
        write_draft_3(folder / "draft-3-hit-list.md", loc_name, matched, tier)

        tier_counts[tier] += 1
        print(f"  [{tier}] {loc_name}: {total} places -> {folder.name}/")

    print("\nGenerated guides:")
    for t in ("A", "B", "C"):
        if t in tier_counts:
            print(f"  Tier {t}: {tier_counts[t]} locations")
    print(f"  Total: {sum(tier_counts.values())} locations")
    print(f"  Output: {out_root}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
