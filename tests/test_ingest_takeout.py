import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest_takeout import (
    NO_LOCATION,
    carry_over,
    feature_to_row,
    find_exports,
    merge_rows,
    norm_address,
    parse_maps_url,
)


def feature(url, date="2026-01-01T00:00:00Z", coords=(2.35, 48.85), comment=None):
    props = {"date": date, "google_maps_url": url}
    if comment:
        props["Comment"] = comment
    return {"geometry": {"coordinates": list(coords), "type": "Point"}, "properties": props, "type": "Feature"}


def test_parse_cid_url():
    out = parse_maps_url("http://maps.google.com/?cid=123")
    assert out["cid"] == "123" and out["id"] == "cid:123" and out["url_type"] == "cid"


def test_parse_q_with_ftid_extracts_address():
    url = "http://maps.google.com/?q=19+Joy+St,+San+Francisco&ftid=0x808f:0x7a"
    out = parse_maps_url(url)
    assert out["ftid"] == "0x808f:0x7a"
    assert out["address"] == "19 Joy St, San Francisco"
    assert out["url_type"] == "q_with_ftid"


def test_parse_q_only_has_no_id():
    out = parse_maps_url("http://maps.google.com/?q=Somewhere")
    assert out["id"] is None and out["url_type"] == "q_only"


def test_zero_coords_with_no_location_comment_become_null():
    row = feature_to_row(feature("http://maps.google.com/?cid=1", coords=(0, 0), comment=NO_LOCATION), "a")
    assert row["lat"] is None and row["lng"] is None


def test_real_coordinates_survive():
    row = feature_to_row(feature("http://maps.google.com/?cid=1"), "a")
    assert (row["lat"], row["lng"]) == (48.85, 2.35)  # GeoJSON is lng,lat


def test_feature_without_url_is_skipped():
    assert feature_to_row({"geometry": {}, "properties": {}}, "a") is None


def test_merge_keeps_earliest_date_and_both_sources():
    a = feature_to_row(feature("http://maps.google.com/?cid=9", date="2022-01-01T00:00:00Z"), "account1")
    b = feature_to_row(feature("http://maps.google.com/?cid=9", date="2019-01-01T00:00:00Z"), "account2")
    merged = merge_rows([a, b])
    assert len(merged) == 1
    assert merged[0]["date"].startswith("2019")
    assert merged[0]["source"] == "both"


def test_nameless_pins_never_merge_together():
    a = feature_to_row(feature("http://maps.google.com/?q=A", coords=(0, 0), comment=NO_LOCATION), "account1")
    b = feature_to_row(feature("http://maps.google.com/?q=B", coords=(0, 0), comment=NO_LOCATION), "account1")
    assert a["id"] == b["id"] == "name:"
    assert len(merge_rows([a, b])) == 2


def test_norm_address():
    assert norm_address("19 Joy St., SF") == norm_address("19 joy st sf")
    assert norm_address("") is None and norm_address(None) is None


def test_carry_over_matches_by_id_then_address():
    rows = [
        feature_to_row(feature("http://maps.google.com/?cid=1"), "a"),
        feature_to_row(feature("http://maps.google.com/?q=19+Joy+St&ftid=0xAB:0xCD"), "a"),
        feature_to_row(feature("http://maps.google.com/?cid=999"), "a"),
    ]
    classified = [
        {"id": "cid:1", "name": "Known", "address": "somewhere", "category": 3, "tier": "visited"},
        {"id": "cid:2", "name": "ByAddress", "address": "19 Joy St", "category": 1, "tier": "visited"},
    ]
    stats = carry_over(rows, classified)
    assert rows[0]["name"] == "Known" and rows[0]["category"] == 3
    assert rows[1]["name"] == "ByAddress"          # ftid matched via address
    assert stats["matched_by_id"] == 1
    assert stats["matched_by_address"] == 1
    assert stats["new"] == 1


def test_find_exports_discovers_both_accounts(tmp_path):
    nested = tmp_path / "Maps (your places)" / "Maps (your places) 2"
    nested.mkdir(parents=True)
    (tmp_path / "Maps (your places)" / "Saved Places.json").write_text("{}", encoding="utf-8")
    (nested / "Saved Places.json").write_text("{}", encoding="utf-8")
    found = find_exports(tmp_path)
    assert len(found) == 2
    assert [a for a, _ in found] == ["account1", "account2"]
