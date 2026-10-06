import datetime as dt
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generate_gem_guides import (
    WANT_LABEL,
    depth_label,
    eligible_sections,
    is_hand_edited,
    map_include,
    maps_url,
    place_locality,
    render_entry,
    render_guide,
    slugify,
)

_SPREAD = [0.0, 0.004, 0.008, 0.012, 0.016, 0.020]  # ~450m apart, so dedupe keeps them
_seq = iter(range(1000))


def scored_place(name, cat, score, location="Pittsburgh", lat=None, lng=-79.99):
    # Distinct coordinates per place: the generator drops venues within 30m
    # of each other, so fixtures sharing one pin would collapse to one row.
    if lat is None:
        lat = 40.44 + _SPREAD[next(_seq) % len(_SPREAD)]
    return {
        "name": name,
        "category": cat,
        "locations": [location],
        "famous": False,
        "chain": False,
        "gem_score": score,
        "rating": 4.8,
        "review_count": 1234,
        "lat": lat,
        "lng": lng,
        "address": "100 Main St, Pittsburgh, PA 15201, United States",
        "country": "United States",
        "cid": "999",
    }


def wanted_place(name, cat, score, **kw):
    p = scored_place(name, cat, score, **kw)
    p["tier"] = "want_to_go"
    return p


def test_slugify():
    assert slugify("San Francisco") == "san-francisco"
    assert slugify("Copenhagen & Malmo") == "copenhagen-and-malmo"
    assert slugify("England & Wales") == "england-and-wales"


# ── locality parsing ────────────────────────────────────────────────

def test_locality_us_city_and_state():
    addr = "678 Post St, San Francisco, CA 94109"
    assert place_locality(addr, "United States") == "San Francisco, CA"


def test_locality_strips_trailing_country():
    addr = "119 St Marks Pl, New York, NY 10009, United States"
    assert place_locality(addr, "United States") == "New York, NY"


def test_locality_postcode_before_city():
    addr = "Potsdamer Platz, 10785 Berlin, Germany"
    assert place_locality(addr, "Germany") == "Berlin"


def test_locality_region_then_postcode():
    addr = "178 Sakuramachi, Takayama, Gifu 506-0858, Japan"
    assert place_locality(addr, "Japan") == "Takayama, Gifu"


def test_locality_drops_overlong_region():
    """'Comunitat Valenciana' crowds the line; the city alone is enough."""
    addr = "9 Carrer del Doctor Lluch, València, Comunitat Valenciana 46011, España"
    assert place_locality(addr, "España") == "València"


def test_locality_uk_postcode():
    addr = "94 St Aldate's, Oxford OX1 1BT, United Kingdom"
    assert place_locality(addr, "United Kingdom") == "Oxford"


def test_locality_handles_dash_separated_gulf_address():
    addr = "Gate Village 08 - DIFC - Dubai - United Arab Emirates"
    assert place_locality(addr, "United Arab Emirates") == "Dubai"


def test_locality_empty_when_unparseable():
    assert place_locality("", "Japan") == ""
    assert place_locality("Japan", "Japan") == ""


# ── entries ─────────────────────────────────────────────────────────

def test_entry_has_locality_rating_and_map_link():
    entry = render_entry(scored_place("Waffallonia", 1, 1.0))
    head, *rest = entry.split("  \n")
    assert head.startswith("**Waffallonia**")
    assert "**Pittsburgh, PA**" in head
    assert "4.8★ (1,234 reviews)" in head
    # the link gets its own line
    assert rest == ["[Google Maps](https://maps.google.com/?cid=999)"]


def test_entry_shows_country_in_multi_country_guides():
    p = scored_place("Al Mourjan", 1, 1.0)
    p["address"] = "Hamad International, Doha, Qatar"
    p["country"] = "Qatar"
    assert "Qatar" in render_entry(p, show_country=True)
    assert "Qatar" not in render_entry(p, show_country=False)


def test_entry_puts_description_on_its_own_line():
    p = scored_place("Waffallonia", 1, 1.0)
    p["description"] = "Liege waffles from a Brussels-trained baker."
    lines = render_entry(p).split("  \n")
    assert len(lines) == 3
    assert lines[1] == "Liege waffles from a Brussels-trained baker."
    assert lines[2].startswith("[Google Maps]")


def test_entry_omits_map_link_with_nothing_to_link_to():
    p = scored_place("No Cid", 1, 1.0)
    p["cid"], p["lat"], p["lng"] = None, None, None
    line = render_entry(p)
    assert "[Google Maps]" not in line
    assert maps_url(p) == ""


# ── depth ───────────────────────────────────────────────────────────

def test_depth_label_thresholds():
    assert depth_label(93, 5) == "deep"
    assert depth_label(50, 4) == "good"
    assert depth_label(30, 3) == "solid"
    assert depth_label(15, 2) == "light"
    assert depth_label(5, 2) == "thin"
    # plenty of places but too few sections cannot reach the top tiers
    assert depth_label(90, 2) == "light"


# ── guide pages ─────────────────────────────────────────────────────

def _sections(n=3, cat=1):
    return eligible_sections([scored_place(f"R{i}", cat, 1.0 - i * 0.1) for i in range(n)], "Pittsburgh")


def test_guide_front_matter_carries_geography_and_depth():
    page = render_guide("Pittsburgh", _sections(), dt.date(2026, 10, 1), pool_size=81)
    assert 'title: "Pittsburgh"' in page
    assert 'continent: "North America"' in page
    assert 'country: "United States"' in page
    assert "place_count: 81" in page
    # one section only, so a large pool still is not "deep"
    assert "depth: thin" in page
    assert "layout: page" in page
    # it is a collection item, not a post
    assert "categories:" not in page


def test_guide_header_states_caveats():
    page = render_guide("Pittsburgh", _sections(), dt.date(2026, 10, 1), pool_size=81)
    assert "algorithmically generated" in page
    assert "penalise places for being" in page


def test_guide_invites_reports_only_with_a_contact():
    """GUIDE_CONTACT is unset by default, so there is nowhere to write to."""
    import generate_gem_guides as g
    with patch.object(g, "CONTACT", ""):
        page = g.render_guide("Pittsburgh", _sections(), dt.date(2026, 10, 1), pool_size=81)
    assert "Tell me" not in page
    with patch.object(g, "CONTACT", "mailto:you@example.com"):
        page = g.render_guide("Pittsburgh", _sections(), dt.date(2026, 10, 1), pool_size=81)
    assert "mailto:you@example.com" in page


def test_guide_summary_is_one_fact_per_row():
    page = render_guide(
        "Pittsburgh", _sections(), dt.date(2026, 10, 1),
        pool_size=81, delta_note="average 0.29 below the US baseline",
    )
    # depth and the count are one row now; the date lives on the index page
    for label in ("<dt>Depth</dt>", "<dt>Ratings</dt>"):
        assert label in page
    assert "<dt>Places</dt>" not in page
    assert "<dt>Updated</dt>" not in page


def test_guide_summary_omits_ratings_row_without_a_delta():
    page = render_guide("Pittsburgh", _sections(), dt.date(2026, 10, 1), pool_size=81)
    assert "<dt>Ratings</dt>" not in page


def test_guide_header_describes_its_own_depth():
    thin = render_guide("Pittsburgh", _sections(), dt.date(2026, 10, 1), pool_size=8)
    assert "places-depth-thin" in thin
    assert "3/8" in thin


def test_guide_is_fully_algorithmic():
    """No prose placeholders: nothing in a guide asks to be written."""
    page = render_guide("Pittsburgh", _sections(), dt.date(2026, 10, 1), pool_size=40)
    assert "Personal note" not in page
    assert "[Intro:" not in page
    assert "*[" not in page


def test_guide_states_its_own_provenance():
    page = render_guide("Pittsburgh", _sections(), dt.date(2026, 10, 1), pool_size=81)
    assert "places I&rsquo;ve visited here" in page
    assert "3/81" in page
    assert "/places/" in page


def test_guide_appends_want_to_go_section():
    visited = _sections()
    wanted = eligible_sections([wanted_place(f"W{i}", 1, 0.5) for i in range(3)], "Pittsburgh")
    page = render_guide("Pittsburgh", visited, dt.date(2026, 10, 1), wanted, pool_size=40)
    assert "## Still on my list" in page
    assert page.index("## Where to Eat") < page.index("## Still on my list")


def test_guide_without_wanted_has_no_still_on_my_list():
    page = render_guide("Pittsburgh", _sections(), dt.date(2026, 10, 1), pool_size=40)
    assert "Still on my list" not in page


# ── map include ─────────────────────────────────────────────────────

def test_map_include_escapes_apostrophes():
    sections = eligible_sections(
        [scored_place("Joe's Place", 1, 1.0)] + [scored_place(f"R{i}", 1, 0.5) for i in range(2)],
        "Pittsburgh",
    )
    embed = map_include(sections)
    assert "Joe&#39;s Place" in embed
    assert "Joe's Place" not in embed


def test_map_tags_want_to_go_pins_distinctly():
    visited = _sections()
    wanted = eligible_sections([wanted_place(f"W{i}", 1, 0.5) for i in range(3)], "Pittsburgh")
    embed = map_include(visited, wanted)
    assert '"Where to Eat"' in embed
    assert f'"{WANT_LABEL}"' in embed


def test_map_include_skips_placeless_rows():
    scored = [scored_place(f"R{i}", 1, 1.0) for i in range(3)]
    for p in scored:
        p["lat"] = None
    assert map_include(eligible_sections(scored, "Pittsburgh")) == ""


# ── protection ──────────────────────────────────────────────────────

def test_nested_locations_lists_cities_inside_a_region():
    from generate_gem_guides import nested_locations
    inside = nested_locations("Germany", {"Berlin", "Munich", "Paris"})
    assert inside == ["Berlin", "Munich"]


def test_nested_locations_skips_other_countries():
    """Zurich falls inside Germany's rectangle but is not in Germany."""
    from generate_gem_guides import nested_locations
    assert "Zurich" not in nested_locations("Germany", {"Zurich", "Berlin"})


def test_hand_edited_guide_is_detected(tmp_path):
    protected = tmp_path / "a.md"
    protected.write_text("---\nlayout: page\nhand_edited: true\n---\nmine\n", encoding="utf-8")
    plain = tmp_path / "b.md"
    plain.write_text("---\nlayout: page\n---\ngenerated\n", encoding="utf-8")
    assert is_hand_edited(protected) is True
    assert is_hand_edited(plain) is False
    assert is_hand_edited(tmp_path / "missing.md") is False


def test_maps_url_falls_back_to_coordinates_without_a_cid():
    """Dropped pins have no business listing but do have a position."""
    p = scored_place("Amphitheatre", 10, 1.0, lat=45.51, lng=-73.53)
    p["cid"] = None
    assert maps_url(p) == "https://maps.google.com/?q=45.51,-73.53"
    assert "[Google Maps]" in render_entry(p)


def test_maps_url_empty_without_cid_or_coordinates():
    p = scored_place("Nowhere", 10, 1.0)
    p["cid"], p["lat"], p["lng"] = None, None, None
    assert maps_url(p) == ""


def test_locality_handles_country_first_japanese_address():
    """Japan lists largest-first, so reading from the end gives a floor number."""
    addr = "Japan, \u3012150-0001 Tokyo, Shibuya City, Jingumae, 3 Chome\u221223\u22122 \u5730\u4e0b\uff11\u968e"
    assert place_locality(addr, "Japan") == "Shibuya City, Tokyo"


def test_locality_still_reads_western_japanese_addresses_from_the_end():
    addr = "2 Chome-17-13 Kitazawa, Setagaya City, Tokyo 155-0031, Japan"
    assert place_locality(addr, "Japan") == "Setagaya City, Tokyo"


def test_single_country_guide_does_not_repeat_the_country():
    """Tokyo addresses say both "Japan" and native script; it is one country."""
    jp = scored_place("Gyoza", 1, 1.0)
    jp["country"], jp["address"] = "Japan", "3 Chome, Shinjuku City, Tokyo 160-0022, Japan"
    native = scored_place("Seryna", 1, 0.9)
    native["country"], native["address"] = "日本", "港区, 日本"
    page = render_guide("Tokyo", [("Where to Eat", [jp, native])], dt.date(2026, 10, 4), pool_size=40)
    assert "Shinjuku City, Tokyo**" in page
    assert "Tokyo, Japan**" not in page


def test_hawaii_entries_name_the_island_not_the_state():
    """Honolulu and Lahaina are both "HI" but a ferry apart."""
    from generate_gem_guides import hawaiian_island
    assert hawaiian_island(21.276, -157.825) == "Oahu"
    assert hawaiian_island(20.886, -156.684) == "Maui"
    assert hawaiian_island(19.420, -155.288) == "Big Island"
    assert hawaiian_island(48.0, 2.0) == ""

    p = scored_place("Furusato Sushi", 1, 1.0, lat=21.276, lng=-157.825)
    p["address"] = "2424 Kalakaua Ave, Honolulu, HI 96815, United States"
    assert "**Honolulu, Oahu**" in render_entry(p)


def test_slugify_folds_accents_rather_than_hyphenating_them():
    """Montreal with an acute must not become 'montr-al'."""
    assert slugify("Montréal") == "montreal"
    assert slugify("Québec") == "quebec"
    assert slugify("Zürich") == "zurich"
    assert slugify("Copenhagen & Malmö") == "copenhagen-and-malmo"


def test_japanese_address_gives_city_and_prefecture():
    assert place_locality(
        "Mouriya, 2 Chome-1-17 Shimoyamatedori, Chuo Ward, Kobe, Hyogo 650-0011, Japan",
        "Japan",
    ) == "Kobe, Hyogo"
    assert place_locality(
        "1-chome-20-16 Ritsurincho, Takamatsu, Kagawa 760-0073, Japan", "Japan"
    ) == "Takamatsu, Kagawa"


def test_designated_city_stands_in_for_its_prefecture():
    """Google drops the prefecture when it shares the city's name."""
    assert place_locality(
        "1 Chome-10-2 Otemachi, Naka Ward, Hiroshima, 730-0811, Japan", "Japan"
    ) == "Hiroshima"
    assert place_locality(
        "Nakatanidou, 29 Hashimotocho, Nara, 630-8217, Japan", "Japan"
    ) == "Nara"


def test_japanese_city_field_drops_a_leading_block_number():
    assert place_locality("1 Narita, Chiba 286-0023, Japan", "Japan") == "Narita, Chiba"


def test_japanese_script_address_looks_up_its_prefecture():
    assert place_locality("トキワ新町, 高松市, 日本", "日本") == "Takamatsu, Kagawa"
    assert place_locality("高山市, 日本", "日本") == "Takayama, Gifu"
