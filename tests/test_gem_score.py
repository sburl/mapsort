import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gem_score import country_baselines, country_of, locations_of, score_places


def make_place(i, lat=48.8566, lng=2.3522, country="France", **overrides):
    base = {
        "id": f"cid:{i}",
        "name": f"Place {i}",
        "resolved_name": None,
        "lat": lat,
        "lng": lng,
        "category": 1,
        "address": f"1 Rue Test, Paris, {country}",
        "tier": "visited",
    }
    base.update(overrides)
    return base


def cache_entry(rating, count, status="ok"):
    return {"status": status, "rating": rating, "user_rating_count": count}


def test_country_of_dash_separated_address():
    place = {"address": "Gate Village 08 - DIFC - Dubai - United Arab Emirates"}
    assert country_of(place) == "United Arab Emirates"


def test_country_of():
    assert country_of({"address": "1 Main St, Springfield, United States"}) == "United States"
    assert country_of({"address": ""}) == "Unknown"
    assert country_of({}) == "Unknown"


def test_locations_of_returns_only_the_most_specific():
    """Tokyo sits inside the Japan box; the place belongs to Tokyo alone."""
    assert locations_of(35.68, 139.76) == ["Tokyo"]


def test_locations_of_falls_back_to_the_region():
    """Somewhere in Japan but in no city box still lands in Japan."""
    assert locations_of(36.90, 137.50) == ["Japan"]


def test_locations_of_empty_when_nowhere_matches():
    assert locations_of(-70.0, 0.0) == []


def test_min_reviews_and_status_filters():
    places = [make_place(1), make_place(2), make_place(3)]
    cache = {
        "cid:1": cache_entry(4.8, 100),
        "cid:2": cache_entry(4.9, 5),          # too few reviews
        "cid:3": {"status": "no_match"},
    }
    scored = score_places(places, cache)
    assert [p["id"] for p in scored] == ["cid:1"]


def test_gem_prefers_low_review_count_at_same_rating():
    places = [make_place(i) for i in range(1, 13)]
    cache = {f"cid:{i}": cache_entry(4.0, 500) for i in range(1, 11)}
    cache["cid:11"] = cache_entry(4.8, 120)     # the gem
    cache["cid:12"] = cache_entry(4.8, 60000)   # the Louvre
    scored = score_places(places, cache)
    assert scored[0]["id"] == "cid:11"
    louvre = next(p for p in scored if p["id"] == "cid:12")
    assert louvre["famous"] is True
    assert scored[0]["famous"] is False


def test_country_normalization():
    # Japan rates harshly (mean ~3.9), US inflates (~4.5): same 4.4 rating
    # should z-score higher in Japan.
    rated = []
    for i in range(40):
        rated.append({"country": "Japan", "rating": 3.9})
        rated.append({"country": "United States", "rating": 4.5})
    baselines = country_baselines(rated)
    jp_mean, _ = baselines["Japan"]
    us_mean, _ = baselines["United States"]
    assert jp_mean < us_mean


def test_dedupe_drops_same_venue_under_different_names():
    """'OZONE' and 'OZONE | The Ritz-Carlton' share a pin and are one bar."""
    from gem_score import dedupe_places
    rows = [
        {"name": "OZONE | The Ritz-Carlton, Hong Kong", "lat": 22.30340, "lng": 114.16019},
        {"name": "OZONE", "lat": 22.30340, "lng": 114.16019},
    ]
    kept = dedupe_places(rows)
    assert [p["name"] for p in kept] == ["OZONE | The Ritz-Carlton, Hong Kong"]


def test_dedupe_tolerates_slightly_drifted_pins():
    """9m apart, and on opposite sides of a rounding boundary."""
    from gem_score import dedupe_places
    rows = [
        {"name": "Labad's Mediterranean", "lat": 40.4502662, "lng": -79.9854012},
        {"name": "Labad's Mediterranean Cafe And Grocery", "lat": 40.4503463, "lng": -79.9854992},
    ]
    assert len(dedupe_places(rows)) == 1


def test_dedupe_keeps_genuinely_different_neighbours():
    from gem_score import dedupe_places
    rows = [
        {"name": "Cafe A", "lat": 40.4502, "lng": -79.9854},
        {"name": "Bar B", "lat": 40.4530, "lng": -79.9890},
    ]
    assert len(dedupe_places(rows)) == 2


def test_empty_cache_scores_nothing():
    assert score_places([make_place(1)], {}) == []


def test_guide_sections_groups_and_excludes_famous():
    from gem_score import guide_sections
    scored = [
        {"name": "A", "category": 1, "locations": ["Barcelona"], "famous": False, "gem_score": 1.0},
        {"name": "B", "category": 3, "locations": ["Barcelona"], "famous": False, "gem_score": 0.5},
        {"name": "C", "category": 1, "locations": ["Barcelona"], "famous": True, "gem_score": 2.0},
        {"name": "D", "category": 1, "locations": ["Tokyo"], "famous": False, "gem_score": 0.9},
    ]
    sections = guide_sections(scored, "Barcelona")
    titles = [t for t, _ in sections]
    assert titles == ["Where to Eat", "Coffee & Sweets"]
    eat = dict(sections)["Where to Eat"]
    assert [p["name"] for p in eat] == ["A"]


def test_permanently_closed_places_are_excluded():
    places = [make_place(1), make_place(2)]
    cache = {
        "cid:1": {**cache_entry(4.9, 100), "business_status": "OPERATIONAL"},
        "cid:2": {**cache_entry(4.9, 100), "business_status": "CLOSED_PERMANENTLY"},
    }
    scored = score_places(places, cache)
    assert [p["id"] for p in scored] == ["cid:1"]


def test_legacy_entries_without_business_status_still_score():
    places = [make_place(1)]
    cache = {"cid:1": cache_entry(4.9, 100)}  # no business_status key at all
    assert len(score_places(places, cache)) == 1


def test_tier_is_carried_into_scored_rows():
    """want_to_go places score identically — only enrichment has lagged."""
    visited = make_place(1)
    wanted = make_place(2)
    wanted["tier"] = "want_to_go"
    cache = {"cid:1": cache_entry(4.8, 120), "cid:2": cache_entry(4.9, 140)}
    scored = score_places([visited, wanted], cache)
    tiers = {p["id"]: p["tier"] for p in scored}
    assert tiers == {"cid:1": "visited", "cid:2": "want_to_go"}
    assert len([p for p in scored if p["tier"] == "want_to_go"]) == 1
