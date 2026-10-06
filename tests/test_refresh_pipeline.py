import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from refresh_pipeline import (
    diff_datasets,
    display_name,
    identity_key,
    index_places,
    render_diff_md,
)


def make_place(**overrides) -> dict:
    base = {
        "id": "cid:1",
        "name": "Test Place",
        "resolved_name": None,
        "address": "1 Test St, Springfield, United States",
        "lat": 37.77,
        "lng": -122.42,
        "tier": "want_to_go",
        "category": 1,
    }
    base.update(overrides)
    return base


# --- identity -------------------------------------------------------------

def test_identity_key_prefers_real_id():
    assert identity_key(make_place(id="cid:999")) == "cid:999"


def test_identity_key_falls_back_on_degenerate_id():
    # "name:" is the real degenerate id in the dataset (nameless, 0,0 pins).
    a = make_place(id="name:", name="", address="110 Sage Dr, Sedona, AZ", lat=0.0, lng=0.0)
    b = make_place(id="name:", name="", address="Lofoten, Norway", lat=0.0, lng=0.0)
    assert identity_key(a) != identity_key(b)
    assert identity_key(a).startswith("composite:")


def test_identity_key_stable_across_equivalent_rows():
    a = make_place(id="name:", name="Cafe", address="1 A St", lat=1.0, lng=2.0)
    b = make_place(id="name:", name="CAFE", address="1 a st", lat=1.0, lng=2.0)
    assert identity_key(a) == identity_key(b)


def test_display_name_falls_back_to_address():
    assert display_name(make_place(name="", resolved_name=None)) == \
        "1 Test St, Springfield, United States"
    assert display_name(make_place(resolved_name="Real")) == "Real"


def test_index_places_counts_exact_duplicates():
    dup = make_place(id="name:", name="", address="Same St", lat=0.0, lng=0.0)
    rep, counts = index_places([dup, dict(dup)])
    assert len(rep) == 1
    assert list(counts.values()) == [2]


# --- diff -----------------------------------------------------------------

def test_diff_detects_added_and_removed():
    old = [make_place(id="cid:1"), make_place(id="cid:2")]
    new = [make_place(id="cid:2"), make_place(id="cid:3")]
    diff = diff_datasets(old, new)
    assert [a["key"] for a in diff["added"]] == ["cid:3"]
    assert [r["key"] for r in diff["removed"]] == ["cid:1"]
    assert diff["old_total"] == 2 and diff["new_total"] == 2


def test_diff_flags_finally_went():
    old = [make_place(id="cid:1", tier="want_to_go")]
    new = [make_place(id="cid:1", tier="visited")]
    diff = diff_datasets(old, new)
    assert len(diff["tier_changes"]) == 1
    change = diff["tier_changes"][0]
    assert change["from"] == "want_to_go" and change["to"] == "visited"
    assert change["finally_went"] is True


def test_diff_tier_change_backwards_is_not_finally_went():
    old = [make_place(id="cid:1", tier="visited")]
    new = [make_place(id="cid:1", tier="want_to_go")]
    diff = diff_datasets(old, new)
    assert diff["tier_changes"][0]["finally_went"] is False


def test_diff_detects_category_change_with_labels():
    old = [make_place(id="cid:1", category=1)]   # restaurants
    new = [make_place(id="cid:1", category=7)]   # museums & culture
    diff = diff_datasets(old, new)
    assert len(diff["category_changes"]) == 1
    change = diff["category_changes"][0]
    assert change["from"] == "Restaurants"
    assert change["to"] == "Museums & Culture"


def test_diff_handles_unclassified_category():
    old = [make_place(id="cid:1", category=None)]
    new = [make_place(id="cid:1", category=1)]
    diff = diff_datasets(old, new)
    assert diff["category_changes"][0]["from"] == "unclassified"


def test_diff_counts_duplicate_multiplicity():
    dup = make_place(id="name:", name="", address="Same St", lat=0.0, lng=0.0)
    old = [dict(dup)]
    new = [dict(dup), dict(dup), dict(dup)]
    diff = diff_datasets(old, new)
    assert sum(a["count"] for a in diff["added"]) == 2


def test_diff_identical_datasets_is_empty():
    rows = [make_place(id="cid:1"), make_place(id="cid:2", tier="visited")]
    diff = diff_datasets(rows, [dict(r) for r in rows])
    assert diff["added"] == [] and diff["removed"] == []
    assert diff["tier_changes"] == [] and diff["category_changes"] == []


# --- rendering ------------------------------------------------------------

def test_render_diff_md_sections_and_counts():
    old = [make_place(id="cid:1", tier="want_to_go"), make_place(id="cid:2")]
    new = [make_place(id="cid:1", tier="visited"), make_place(id="cid:3")]
    md = render_diff_md(diff_datasets(old, new))
    assert "# Year Diff" in md
    assert "## Places you finally went" in md
    assert "## Added" in md and "## Removed" in md
    assert "1 are places you finally went" in md


def test_render_diff_md_empty_sections_say_none():
    rows = [make_place(id="cid:1")]
    md = render_diff_md(diff_datasets(rows, [dict(rows[0])]))
    assert "_None._" in md


def test_render_diff_md_truncates_to_limit():
    old = []
    new = [make_place(id=f"cid:{i}") for i in range(10)]
    md = render_diff_md(diff_datasets(old, new), limit=3)
    assert "and 7 more" in md


def test_render_diff_md_escapes_pipes_in_names():
    # Real dataset names contain pipes, e.g. "Señor Piña | Poke Bowl".
    old = [make_place(id="cid:1", name="Bar | Grill", tier="want_to_go")]
    new = [make_place(id="cid:1", name="Bar | Grill", tier="visited")]
    md = render_diff_md(diff_datasets(old, new))
    row = next(l for l in md.splitlines() if "Bar" in l and l.startswith("|"))
    assert "\\|" in row
    assert row.count("|") - row.count("\\|") == 2  # only the two column delimiters


# --- downstream orchestration --------------------------------------------

def test_run_downstream_invokes_both_steps_in_order():
    from unittest.mock import MagicMock, patch

    import refresh_pipeline

    calls = []

    def fake_run(cmd, cwd=None):
        calls.append(cmd[1])
        return MagicMock(returncode=0)

    with patch.object(refresh_pipeline.subprocess, "run", side_effect=fake_run):
        assert refresh_pipeline.run_downstream() == 0
    assert calls == ["gem_score.py", "generate_gem_guides.py"]


def test_run_downstream_stops_on_failure():
    from unittest.mock import MagicMock, patch

    import refresh_pipeline

    calls = []

    def fake_run(cmd, cwd=None):
        calls.append(cmd[1])
        return MagicMock(returncode=1)

    with patch.object(refresh_pipeline.subprocess, "run", side_effect=fake_run):
        assert refresh_pipeline.run_downstream() == 1
    assert calls == ["gem_score.py"]  # did not continue past the failure
