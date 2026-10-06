import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from overrated_report import overrated


def scored_place(name, famous=True, rating_z=-1.0, location="Barcelona"):
    return {
        "name": name,
        "famous": famous,
        "rating_z": rating_z,
        "rating": 4.2,
        "review_count": 50000,
        "locations": [location],
    }


def test_requires_famous_and_negative_z():
    rows = overrated(
        [
            scored_place("A", famous=True, rating_z=-0.5),
            scored_place("B", famous=False, rating_z=-2.0),
            scored_place("C", famous=True, rating_z=0.3),
        ]
    )
    assert [p["name"] for p in rows] == ["A"]


def test_sorted_worst_first():
    rows = overrated(
        [
            scored_place("Mild", rating_z=-0.2),
            scored_place("Worst", rating_z=-2.5),
            scored_place("Bad", rating_z=-1.1),
        ]
    )
    assert [p["name"] for p in rows] == ["Worst", "Bad", "Mild"]


def test_location_filter():
    rows = overrated(
        [
            scored_place("A", location="Barcelona"),
            scored_place("B", location="Tokyo"),
        ],
        location="Tokyo",
    )
    assert [p["name"] for p in rows] == ["B"]


def test_missing_fields_are_safe():
    assert overrated([{"name": "X"}]) == []
