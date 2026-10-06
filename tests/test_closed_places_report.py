import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from closed_places_report import (
    build_report,
    group_by_location,
    locations_of,
    render_markdown,
)


def make_place(i=1, lat=48.8566, lng=2.3522, **overrides):
    base = {
        "id": f"cid:{i}",
        "name": f"Place {i}",
        "resolved_name": None,
        "lat": lat,
        "lng": lng,
        "address": "1 Rue Test, Paris, France",
        "tier": "visited",
        "category": 1,
    }
    base.update(overrides)
    return base


def entry(status="ok", business_status="OPERATIONAL", **overrides):
    out = {"status": status, "rating": 4.5, "user_rating_count": 100}
    if business_status is not None:
        out["business_status"] = business_status
    out.update(overrides)
    return out


def test_locations_of_paris():
    assert "Paris" in locations_of(48.8566, 2.3522)


def test_closed_places_are_collected():
    places = [make_place(1), make_place(2), make_place(3)]
    cache = {
        "cid:1": entry(business_status="CLOSED_PERMANENTLY"),
        "cid:2": entry(business_status="CLOSED_TEMPORARILY"),
        "cid:3": entry(business_status="OPERATIONAL"),
    }
    report = build_report(places, cache)
    assert [p["name"] for p in report["closed"]] == ["Place 1", "Place 2"]
    assert report["counts"]["closed"] == 2
    assert report["counts"]["open"] == 1


def test_legacy_entries_counted_as_unchecked_not_open():
    places = [make_place(1)]
    cache = {"cid:1": entry(business_status=None)}  # pre-businessStatus entry
    report = build_report(places, cache)
    assert report["counts"]["unchecked"] == 1
    assert report["counts"]["open"] == 0
    assert report["closed"] == []


def test_unknown_status_is_its_own_bucket():
    places = [make_place(1)]
    cache = {"cid:1": entry(business_status="UNKNOWN")}
    report = build_report(places, cache)
    assert report["counts"]["unknown"] == 1
    assert report["counts"]["open"] == 0


def test_unenriched_and_no_match_places_are_skipped():
    places = [make_place(1), make_place(2), make_place(3)]
    cache = {
        "cid:1": {"status": "no_match"},
        "cid:2": {"status": "resolved", "place_id": "x"},
        # cid:3 absent from cache entirely
    }
    report = build_report(places, cache)
    assert report["counts"]["enriched"] == 0


def test_no_rating_entries_still_report_closure():
    places = [make_place(1)]
    cache = {"cid:1": {"status": "no_rating", "business_status": "CLOSED_PERMANENTLY"}}
    report = build_report(places, cache)
    assert report["counts"]["closed"] == 1


def test_location_filter():
    paris = make_place(1)
    tokyo = make_place(2, lat=35.68, lng=139.76)
    cache = {
        "cid:1": entry(business_status="CLOSED_PERMANENTLY"),
        "cid:2": entry(business_status="CLOSED_PERMANENTLY"),
    }
    report = build_report([paris, tokyo], cache, location="Paris")
    assert [p["name"] for p in report["closed"]] == ["Place 1"]


def test_group_by_location_and_markdown():
    places = [make_place(1)]
    cache = {"cid:1": entry(business_status="CLOSED_PERMANENTLY")}
    report = build_report(places, cache)
    grouped = group_by_location(report["closed"])
    assert "Paris" in grouped

    md = render_markdown(report)
    assert "# Closed Places" in md
    assert "## Paris" in md
    assert "**Place 1** (Permanently closed)" in md


def test_markdown_when_nothing_closed():
    report = build_report([make_place(1)], {"cid:1": entry()})
    md = render_markdown(report)
    assert "No closed places found yet." in md


def test_resolved_name_preferred():
    places = [make_place(1, resolved_name="Real Name")]
    cache = {"cid:1": entry(business_status="CLOSED_PERMANENTLY")}
    report = build_report(places, cache)
    assert report["closed"][0]["name"] == "Real Name"
