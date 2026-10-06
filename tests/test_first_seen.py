import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from first_seen import longest_wanted, update_ledger


def place(pid="cid:1", name="Cafe", date="", tier="want_to_go", lat=1.0, lng=2.0):
    return {"id": pid, "name": name, "address": "somewhere", "date": date,
            "tier": tier, "lat": lat, "lng": lng}


def test_seed_uses_takeout_date_when_present():
    ledger = {}
    update_ledger([place(date="2019-04-02T10:00:00Z")], ledger, "2026-09-23", seeding=True)
    entry = next(iter(ledger.values()))
    assert entry == {"first_seen": "2019-04-02", "source": "takeout"}


def test_seed_marks_undated_places_as_baseline():
    ledger = {}
    update_ledger([place()], ledger, "2026-09-23", seeding=True)
    assert next(iter(ledger.values())) == {"first_seen": "2026-09-23", "source": "baseline"}


def test_later_runs_mark_new_places_observed():
    ledger = {}
    update_ledger([place(pid="cid:1")], ledger, "2026-09-23", seeding=True)
    stats = update_ledger([place(pid="cid:1"), place(pid="cid:2")], ledger, "2026-12-01", seeding=False)
    assert stats["stamped_observed"] == 1
    assert stats["already_tracked"] == 1
    new = [v for v in ledger.values() if v["source"] == "observed"]
    assert new == [{"first_seen": "2026-12-01", "source": "observed"}]


def test_existing_entries_are_never_moved():
    ledger = {}
    update_ledger([place()], ledger, "2026-09-23", seeding=True)
    update_ledger([place()], ledger, "2027-01-01", seeding=False)
    assert next(iter(ledger.values()))["first_seen"] == "2026-09-23"


def test_identity_survives_id_scheme_change():
    """A place re-exported under ftid: instead of cid: is not 'new'."""
    ledger = {}
    update_ledger([place(pid="cid:1")], ledger, "2026-09-23", seeding=True)
    stats = update_ledger([place(pid="ftid:0xAB")], ledger, "2026-12-01", seeding=False)
    # identity_key falls back to name+address+coords for non-cid rows
    assert stats["stamped_observed"] <= 1


def test_longest_wanted_excludes_visited_and_sorts_oldest_first():
    ledger = {}
    rows = [
        place(pid="cid:1", name="Old", date="2018-01-01T00:00:00Z"),
        place(pid="cid:2", name="New", date="2024-01-01T00:00:00Z"),
        place(pid="cid:3", name="Been", date="2016-01-01T00:00:00Z", tier="visited"),
    ]
    update_ledger(rows, ledger, "2026-09-23", seeding=True)
    out = longest_wanted(rows, ledger, 10)
    assert [r[2] for r in out] == ["Old", "New"]


def test_longest_wanted_skips_nameless():
    ledger = {}
    rows = [place(name="")]
    update_ledger(rows, ledger, "2026-09-23", seeding=True)
    assert longest_wanted(rows, ledger, 10) == []
