import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taste_report import (
    build_report,
    category_mix,
    conversion_by_location,
    shared_list_stats,
)


def make_place(i, tier="visited", cat=1, lat=48.8566, lng=2.3522, lists=""):
    return {
        "id": f"cid:{i}",
        "name": f"P{i}",
        "lat": lat,
        "lng": lng,
        "tier": tier,
        "category": cat,
        "source_lists": lists,
        "date": "",
    }


def test_conversion_requires_min_places():
    places = [make_place(i) for i in range(5)]  # Paris, only 5
    assert conversion_by_location(places) == []


def test_conversion_math():
    places = [make_place(i, tier="visited") for i in range(20)]
    places += [make_place(100 + i, tier="want_to_go") for i in range(20)]
    rows = conversion_by_location(places)
    paris = next(r for r in rows if r["location"] == "Paris")
    assert paris["saved"] == 40
    assert paris["conversion"] == 0.5


def test_category_mix_and_food_share():
    places = [make_place(1, cat=1), make_place(2, cat=1, tier="want_to_go"),
              make_place(3, cat=7, tier="want_to_go"), make_place(4, cat=None)]
    mix = category_mix(places)
    assert mix["total_classified"] == 3
    assert mix["food_share"] == round(2 / 3, 3)
    top = mix["categories"][0]
    assert top["category"] == "Restaurants" and top["conversion"] == 0.5


def test_shared_lists_counts_only_no_names():
    places = [
        make_place(1, lists="Best of Testville (Secret Friend)"),
        make_place(2, lists="Want to go"),
        make_place(3, lists=""),
    ]
    out = shared_list_stats(places)
    assert out == {"places_from_shared_lists": 1, "distinct_source_list_combos": 2}
    assert "Secret Friend" not in json.dumps(out)


def test_build_report_no_list_names_leak():
    places = [make_place(1, lists="Best of Testville (Secret Friend)")]
    payload = json.dumps(build_report(places))
    assert "Secret Friend" not in payload
    assert "Testville" not in payload
