import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import enrich_ratings
from enrich_ratings import guide_places, haversine_m, search_place_id


def make_place(**overrides) -> dict:
    base = {
        "id": "cid:1",
        "name": "Test Place",
        "resolved_name": None,
        "lat": 48.8566,
        "lng": 2.3522,
        "tier": "visited",
        "category": 1,
    }
    base.update(overrides)
    return base


def test_guide_places_filters():
    rows = [
        make_place(),
        make_place(id="c2", tier="want_to_go"),
        make_place(id="c3", category=6),
        make_place(id="c4", category=None),
        make_place(id="c5", lat=None),
        make_place(id="c6", name="", resolved_name=None),
    ]
    assert [p["id"] for p in guide_places(rows)] == ["cid:1"]


def test_haversine_zero_and_known():
    assert haversine_m(48.85, 2.35, 48.85, 2.35) == 0
    # ~111km per degree of latitude
    d = haversine_m(48.0, 2.0, 49.0, 2.0)
    assert 110_000 < d < 112_000


def _search_result(*cands):
    return {"places": list(cands)}


def test_search_picks_nearest_within_threshold():
    place = make_place()
    far = {"id": "far", "location": {"latitude": 48.99, "longitude": 2.35}}
    near = {"id": "near", "location": {"latitude": 48.8567, "longitude": 2.3523}}
    with patch.object(enrich_ratings, "_request", return_value=_search_result(far, near)):
        out = search_place_id(place, "key")
    assert out["status"] == "resolved"
    assert out["place_id"] == "near"
    assert out["distance_m"] < 50


def test_search_no_match_when_all_far():
    place = make_place()
    far = {"id": "far", "location": {"latitude": 48.99, "longitude": 2.35}}
    with patch.object(enrich_ratings, "_request", return_value=_search_result(far)):
        assert search_place_id(place, "key") == {"status": "no_match"}


def test_search_no_match_on_empty():
    with patch.object(enrich_ratings, "_request", return_value={}):
        assert search_place_id(make_place(), "key") == {"status": "no_match"}


def test_fetch_rating_shapes():
    detail = {
        "id": "x",
        "rating": 4.7,
        "userRatingCount": 120,
        "businessStatus": "OPERATIONAL",
    }
    with patch.object(enrich_ratings, "_request", return_value=detail):
        out = enrich_ratings.fetch_rating("x", "key")
    assert out == {
        "status": "ok",
        "rating": 4.7,
        "user_rating_count": 120,
        "business_status": "OPERATIONAL",
    }
    with patch.object(enrich_ratings, "_request", return_value={"id": "x"}):
        assert enrich_ratings.fetch_rating("x", "key") == {
            "status": "no_rating",
            "business_status": enrich_ratings.UNKNOWN_BUSINESS_STATUS,
        }


def test_fetch_rating_requests_business_status_in_field_mask():
    detail = {"id": "x", "rating": 4.1, "userRatingCount": 9}
    with patch.object(enrich_ratings, "_request", return_value=detail) as req:
        enrich_ratings.fetch_rating("x", "key")
    field_mask = req.call_args[0][2]
    assert "businessStatus" in field_mask
    # Guard the SKU: no Enterprise-only extras beyond the rating fields.
    assert set(field_mask.split(",")) == {
        "id",
        "rating",
        "userRatingCount",
        "businessStatus",
    }


def test_fetch_rating_marks_closed_places():
    detail = {
        "id": "x",
        "rating": 4.2,
        "userRatingCount": 88,
        "businessStatus": "CLOSED_PERMANENTLY",
    }
    with patch.object(enrich_ratings, "_request", return_value=detail):
        out = enrich_ratings.fetch_rating("x", "key")
    assert out["business_status"] == "CLOSED_PERMANENTLY"


def test_legacy_cache_entries_are_not_refetched(tmp_path, capsys):
    """Entries cached before businessStatus existed must stay terminal.

    Re-fetching them to backfill the field would spend paid Enterprise quota.
    """
    place = make_place()
    input_file = tmp_path / "classified.json"
    input_file.write_text(json.dumps([place]), encoding="utf-8")

    cache_file = tmp_path / "ratings_cache.json"
    legacy_entry = {"status": "ok", "rating": 4.5, "user_rating_count": 200}
    cache_file.write_text(json.dumps({place["id"]: legacy_entry}), encoding="utf-8")

    argv = ["enrich_ratings.py", "--input", str(input_file), "--dry-run"]
    with patch.object(enrich_ratings, "RATINGS_CACHE", cache_file), \
         patch.object(sys, "argv", argv), \
         patch.object(enrich_ratings, "_request") as request:
        enrich_ratings.main()

    request.assert_not_called()
    assert "1 enriched/terminal | 0 remaining" in capsys.readouterr().out


def _rated(pid, cat, lat, lng):
    """A place already in the cache, so it counts toward a bucket."""
    return make_place(id=pid, category=cat, lat=lat, lng=lng)


def test_leverage_prefers_unlocking_a_section_over_deepening_one():
    counts = {("Paris", "Where to Eat"): 5, ("Paris", "See & Do"): 0}
    full = make_place(category=1, lat=48.8566, lng=2.3522)      # Eat, bucket full
    empty = make_place(category=7, lat=48.8566, lng=2.3522)     # See & Do, empty
    assert enrich_ratings.leverage_of(empty, counts) > enrich_ratings.leverage_of(full, counts)
    assert enrich_ratings.leverage_of(full, counts) == 0.0


def test_leverage_zero_without_category_or_coords():
    assert enrich_ratings.leverage_of(make_place(category=None), {}) == 0.0
    assert enrich_ratings.leverage_of(make_place(lat=None), {}) == 0.0


def test_ordering_puts_section_unlockers_first():
    # Paris already has a full Eat section; its See & Do section is empty.
    classified = [_rated(f"cid:e{i}", 1, 48.8566, 2.3522) for i in range(5)]
    cache = {p["id"]: {"status": "ok"} for p in classified}
    deepen = make_place(id="cid:more-eat", category=1, lat=48.8566, lng=2.3522)
    unlock = make_place(id="cid:museum", category=7, lat=48.8566, lng=2.3522)
    todo = [deepen, unlock]
    out = enrich_ratings.order_by_leverage(todo, classified + todo, cache)
    assert [p["id"] for p in out] == ["cid:museum", "cid:more-eat"]


def test_ordering_spreads_across_buckets_rather_than_flooding_one():
    """Six places in one empty bucket: only the first few should rank high."""
    todo = [make_place(id=f"cid:{i}", category=7, lat=48.8566, lng=2.3522) for i in range(6)]
    out = enrich_ratings.order_by_leverage(todo, todo, {})
    assert len(out) == 6
    # Stable within equal scores, and the tail has decayed to no value.
    assert out[0]["id"] == "cid:0"


def test_ordering_is_deterministic():
    todo = [make_place(id=f"cid:{i}", category=(1 if i % 2 else 7)) for i in range(8)]
    first = [p["id"] for p in enrich_ratings.order_by_leverage(todo, todo, {})]
    second = [p["id"] for p in enrich_ratings.order_by_leverage(todo, todo, {})]
    assert first == second


def test_recheck_targets_only_entries_missing_business_status():
    from enrich_ratings import needs_closure_recheck
    cache = {
        "cid:1": {"status": "ok", "rating": 4.5},                            # stale
        "cid:2": {"status": "ok", "rating": 4.5, "business_status": "OPERATIONAL"},
        "cid:3": {"status": "no_match"},                                     # never rated
    }
    assert needs_closure_recheck(cache) == ["cid:1"]


def test_recheck_can_be_scoped_to_places_a_guide_prints():
    """A closure nobody can see is not worth paid quota."""
    from enrich_ratings import needs_closure_recheck
    cache = {
        "cid:shown": {"status": "ok", "rating": 4.5},
        "cid:hidden": {"status": "ok", "rating": 4.5},
    }
    assert needs_closure_recheck(cache, {"cid:shown"}) == ["cid:shown"]
    assert len(needs_closure_recheck(cache, None)) == 2
