import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from export_site_data import CATEGORY_LABELS, build_export


def make_place(**overrides) -> dict:
    base = {
        "id": "cid:123",
        "cid": "123",
        "name": "Test Place",
        "resolved_name": None,
        "lat": 41.37916,
        "lng": 2.17311,
        "tier": "visited",
        "category": 1,
        "source_lists": "Best of Barcelona (Friend Name)",
    }
    base.update(overrides)
    return base


def test_visited_public_place_is_exported():
    out = build_export([make_place()])
    assert len(out["places"]) == 1
    name, lat, lng, cat_idx, cid = out["places"][0]
    assert name == "Test Place"
    assert (lat, lng) == (41.37916, 2.17311)
    assert out["categories"][cat_idx]["slug"] == "restaurants"
    assert cid == "123"


def test_want_to_go_is_excluded():
    out = build_export([make_place(tier="want_to_go")])
    assert out["places"] == []


@pytest.mark.parametrize("category", [6, 14, 15, 16])
def test_private_categories_are_excluded(category):
    out = build_export([make_place(category=category)])
    assert out["places"] == []


def test_unclassified_and_coordless_are_excluded():
    rows = [
        make_place(category=None),
        make_place(lat=None),
        make_place(lng=None),
        make_place(name="", resolved_name=None),
    ]
    assert build_export(rows)["places"] == []


def test_no_provenance_fields_in_output():
    payload = json.dumps(build_export([make_place()]))
    assert "source_lists" not in payload
    assert "Friend Name" not in payload
    assert "tier" not in payload


def test_resolved_name_preferred():
    out = build_export([make_place(resolved_name="Real Name")])
    assert out["places"][0][0] == "Real Name"


def test_deterministic_ordering():
    rows = [
        make_place(name="B spot", cid="2"),
        make_place(name="a spot", cid="1"),
        make_place(name="Museum", category=7, cid="3"),
    ]
    out = build_export(rows)
    names = [r[0] for r in out["places"]]
    assert names == ["a spot", "B spot", "Museum"]  # by category, then name


def test_categories_cover_all_labels():
    out = build_export([])
    assert [c["slug"] for c in out["categories"]] == list(CATEGORY_LABELS)


def test_cli_writes_output(tmp_path):
    src = tmp_path / "classified.json"
    dst = tmp_path / "out" / "travel-places.json"
    src.write_text(json.dumps([make_place()]), encoding="utf-8")
    repo = Path(__file__).resolve().parent.parent
    result = subprocess.run(  # noqa: PLW1510 - returncode asserted below
        [sys.executable, "export_site_data.py", "--input", str(src), "--output", str(dst)],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(dst.read_text(encoding="utf-8"))
    assert len(data["places"]) == 1
