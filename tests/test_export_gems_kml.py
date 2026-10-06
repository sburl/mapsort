import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from export_gems_kml import (
    UNMATCHED,
    build_kml,
    describe,
    load_cids,
    select_gems,
    summarize,
)

KML_NS = "{http://www.opengis.net/kml/2.2}"


def make_gem(i, score, *, locations=("Barcelona",), famous=False, category=1, **overrides):
    base = {
        "id": f"cid:{i}",
        "name": f"Place {i}",
        "lat": 41.37916,
        "lng": 2.17311,
        "category": category,
        "country": "Spain",
        "locations": list(locations),
        "rating": 4.8,
        "review_count": 100,
        "rating_z": 1.0,
        "gem_score": score,
        "famous": famous,
    }
    base.update(overrides)
    return base


def test_famous_places_are_excluded():
    gems = [make_gem(1, 2.0, famous=True), make_gem(2, 0.5)]
    assert [p["id"] for p in select_gems(gems)] == ["cid:2"]


def test_per_location_cap_prevents_one_city_crowding_out():
    dense = [make_gem(i, 10.0 - i, locations=("Paris",)) for i in range(20)]
    sparse = [make_gem(100, 0.1, locations=("Lisbon",))]
    picked = select_gems(dense + sparse, per_location=5, max_total=100)
    paris = [p for p in picked if "Paris" in p["locations"]]
    assert len(paris) == 5
    assert any("Lisbon" in p["locations"] for p in picked)


def test_max_total_caps_globally_keeping_best():
    gems = [make_gem(i, float(i), locations=(f"City{i}",)) for i in range(10)]
    picked = select_gems(gems, per_location=15, max_total=3)
    assert [p["gem_score"] for p in picked] == [9.0, 8.0, 7.0]


def test_min_score_filter():
    gems = [make_gem(1, 0.9), make_gem(2, -0.4)]
    assert [p["id"] for p in select_gems(gems, min_score=0.0)] == ["cid:1"]


def test_unmatched_places_survive_and_are_capped():
    """A top gem outside every bbox must not be silently dropped."""
    unmatched = [make_gem(i, 5.0 - i * 0.1, locations=()) for i in range(20)]
    picked = select_gems(unmatched, per_location=3, max_total=100)
    assert len(picked) == 3
    assert picked[0]["gem_score"] == 5.0


def test_place_in_two_locations_appears_once():
    gems = [make_gem(1, 1.0, locations=("San Francisco", "SF Bay Area"))]
    picked = select_gems(gems)
    assert len(picked) == 1


def test_kml_is_parseable_and_styled():
    gems = [make_gem(1, 1.0, category=1), make_gem(2, 0.5, category=7)]
    root = build_kml(gems, {"cid:1": "123"})
    parsed = ET.fromstring(ET.tostring(root, encoding="unicode"))
    placemarks = parsed.findall(f".//{KML_NS}Placemark")
    assert len(placemarks) == 2
    coords = placemarks[0].find(f".//{KML_NS}coordinates").text
    assert coords == "2.17311,41.37916"  # lng,lat order
    styles = {s.get("id") for s in parsed.findall(f".//{KML_NS}Style")}
    assert styles == {"cat_restaurants", "cat_museums_culture"}
    assert placemarks[0].find(f"{KML_NS}styleUrl").text == "#cat_restaurants"


def test_link_present_only_when_cid_known():
    with_cid = describe(make_gem(1, 1.0), "999")
    without = describe(make_gem(2, 1.0), None)
    assert "https://maps.google.com/?cid=999" in with_cid
    assert "maps.google.com" not in without
    assert "4.8★" in without and "100 reviews" in without


def test_kml_omits_link_for_place_without_cid():
    root = build_kml([make_gem(1, 1.0)], {})
    text = ET.tostring(root, encoding="unicode")
    assert "maps.google.com/?cid" not in text


def test_unknown_category_gets_no_style_reference():
    root = build_kml([make_gem(1, 1.0, category=None)], {})
    parsed = ET.fromstring(ET.tostring(root, encoding="unicode"))
    assert parsed.find(f".//{KML_NS}Style") is None
    assert parsed.find(f".//{KML_NS}Placemark/{KML_NS}styleUrl") is None


def test_load_cids_reads_classified(tmp_path):
    path = tmp_path / "classified.json"
    path.write_text(
        json.dumps([
            {"id": "cid:1", "cid": "1"},
            {"id": "latlng:x", "cid": None},
        ]),
        encoding="utf-8",
    )
    assert load_cids(path) == {"cid:1": "1"}


def test_load_cids_missing_file(tmp_path):
    assert load_cids(tmp_path / "nope.json") == {}


def test_summarize_counts_unmatched_bucket():
    gems = [make_gem(1, 1.0, locations=()), make_gem(2, 1.0, locations=("Paris",))]
    assert dict(summarize(gems)) == {UNMATCHED: 1, "Paris": 1}
