import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import trip_list
from trip_list import enrich_budget, preview_counts, want_to_go_places

BARCELONA = (48.8566, 2.3522)  # inside the Paris bbox


# Distinct from None, which callers pass to mean "this place has no latitude".
_AUTO = object()


def make_place(i, tier="want_to_go", category=1, lat=_AUTO, lng=BARCELONA[1], **overrides):
    # Spread the pins ~440m apart: ranking drops venues within 30m of each
    # other as repeat saves of the same place.
    if lat is _AUTO:
        lat = BARCELONA[0] + i * 0.004
    base = {
        "id": f"cid:{i}",
        "name": f"Place {i}",
        "resolved_name": None,
        "lat": lat,
        "lng": lng,
        "tier": tier,
        "category": category,
        "address": f"Rue {i}, Paris, France",
    }
    base.update(overrides)
    return base


def test_want_to_go_filters_tier_category_bbox():
    rows = [
        make_place(1),
        make_place(2, tier="visited"),
        make_place(3, category=6),
        make_place(4, category=None),
        make_place(5, lat=None),
        make_place(6, lat=35.68, lng=139.76),  # Tokyo, outside Paris
        make_place(7, name="", resolved_name=None),
    ]
    got = want_to_go_places(rows, "Paris")
    assert [p["id"] for p in got] == ["cid:1"]


def test_unknown_location_exits():
    with pytest.raises(SystemExit):
        want_to_go_places([], "Atlantis")


def test_preview_counts():
    places = [make_place(i) for i in range(1, 5)]
    cache = {
        "cid:1": {"status": "ok"},
        "cid:2": {"status": "no_match"},
        "cid:3": {"status": "resolved"},  # not terminal
    }
    assert preview_counts(places, cache) == (4, 2, 2)


def test_enrich_budget_caps_and_writes_cache():
    places = [make_place(i) for i in range(1, 6)]
    cache = {"cid:1": {"status": "ok"}}  # already done, must be skipped
    with patch.object(trip_list, "search_place_id", return_value={"status": "resolved", "place_id": "x", "distance_m": 1.0}), \
         patch.object(trip_list, "fetch_rating", return_value={"status": "ok", "rating": 4.8, "user_rating_count": 100}), \
         patch.object(trip_list, "save_cache") as saved, \
         patch.object(trip_list, "time"):
        used = enrich_budget(places, cache, "key", budget=2)
    assert used == 2
    assert cache["cid:2"]["status"] == "ok"
    assert cache["cid:3"]["status"] == "ok"
    assert "cid:4" not in cache  # budget exhausted before reaching it
    assert saved.called


def test_enrich_budget_no_match_does_not_consume_budget():
    places = [make_place(i) for i in range(1, 4)]
    cache = {}
    with patch.object(trip_list, "search_place_id", return_value={"status": "no_match"}), \
         patch.object(trip_list, "fetch_rating") as fr, \
         patch.object(trip_list, "save_cache"), \
         patch.object(trip_list, "time"):
        used = enrich_budget(places, cache, "key", budget=2)
    assert used == 0
    assert not fr.called
    assert all(cache[f"cid:{i}"]["status"] == "no_match" for i in (1, 2, 3))


def test_print_ranking_outputs_sections(capsys):
    places = [make_place(i) for i in range(1, 5)]
    cache = {
        f"cid:{i}": {"status": "ok", "rating": 4.8, "user_rating_count": 100 + i}
        for i in range(1, 5)
    }
    shown = trip_list.print_ranking(places, cache, "Paris", per_group=5)
    out = capsys.readouterr().out
    assert shown == 4
    assert "## Where to Eat" in out
    assert "Place 1" in out


def test_print_ranking_empty_cache_message(capsys):
    shown = trip_list.print_ranking([make_place(1)], {}, "Paris", per_group=5)
    assert shown == 0
    assert "run with --fetch" in capsys.readouterr().out
