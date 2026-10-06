import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backfill_dates import backfill, build_date_index, coord_key


def place(pid="cid:1", name="Cafe", lat=37.77, lng=-122.42, date=""):
    return {"id": pid, "name": name, "lat": lat, "lng": lng, "date": date}


def test_coord_key_requires_name_and_coords():
    assert coord_key(place()) == ("cafe", 37.77, -122.42)
    assert coord_key(place(name="")) is None
    assert coord_key(place(lat=None)) is None


def test_backfill_matches_by_id():
    raw = [place(date="2022-05-01T10:00:00Z")]
    classified = [place()]
    by_id, by_coord = build_date_index(raw)
    stats = backfill(classified, by_id, by_coord)
    assert classified[0]["date"] == "2022-05-01T10:00:00Z"
    assert stats["matched_by_id"] == 1


def test_backfill_falls_back_to_coords_when_id_changed():
    raw = [place(pid="cid:OLD", date="2019-03-03T00:00:00Z")]
    classified = [place(pid="cid:NEW")]
    by_id, by_coord = build_date_index(raw)
    stats = backfill(classified, by_id, by_coord)
    assert classified[0]["date"] == "2019-03-03T00:00:00Z"
    assert stats["matched_by_coords"] == 1


def test_degenerate_id_never_matches_by_id():
    """~472 nameless pins share the id 'name:'; it must not join them."""
    raw = [place(pid="name:", name="", lat=0, lng=0, date="2020-01-01T00:00:00Z")]
    classified = [place(pid="name:", name="", lat=0, lng=0)]
    by_id, by_coord = build_date_index(raw)
    assert "name:" not in by_id
    stats = backfill(classified, by_id, by_coord)
    assert classified[0]["date"] == ""
    assert stats["no_timestamp_available"] == 1


def test_existing_dates_are_never_overwritten():
    raw = [place(date="2022-05-01T10:00:00Z")]
    classified = [place(date="1999-01-01T00:00:00Z")]
    by_id, by_coord = build_date_index(raw)
    stats = backfill(classified, by_id, by_coord)
    assert classified[0]["date"] == "1999-01-01T00:00:00Z"
    assert stats["already_had_date"] == 1


def test_scraped_places_stay_empty():
    by_id, by_coord = build_date_index([])
    classified = [place(pid="cid:99")]
    stats = backfill(classified, by_id, by_coord)
    assert classified[0]["date"] == ""
    assert stats["filled"] == 0


def test_backfill_is_idempotent():
    raw = [place(date="2022-05-01T10:00:00Z")]
    classified = [place()]
    by_id, by_coord = build_date_index(raw)
    backfill(classified, by_id, by_coord)
    stats = backfill(classified, by_id, by_coord)
    assert stats["already_had_date"] == 1
    assert stats["filled"] == 0
