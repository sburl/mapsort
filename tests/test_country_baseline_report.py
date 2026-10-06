import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from country_baseline_report import country_stats


def make_place(i, country="France"):
    return {
        "id": f"cid:{i}",
        "name": f"Place {i}",
        "address": f"1 Rue Test, Paris, {country}",
    }


def cache_entry(rating, status="ok"):
    return {"status": status, "rating": rating, "user_rating_count": 100}


def test_countries_below_min_n_excluded():
    places = [make_place(i) for i in range(5)]
    cache = {f"cid:{i}": cache_entry(4.5) for i in range(5)}
    assert country_stats(places, cache, min_n=6) == []
    rows = country_stats(places, cache, min_n=5)
    assert [r["country"] for r in rows] == ["France"]
    assert rows[0]["n"] == 5


def test_stats_values_and_sort_order():
    places = [make_place(i, "France") for i in range(3)]
    places += [make_place(i + 100, "Japan") for i in range(3)]
    cache = {
        "cid:0": cache_entry(4.0),
        "cid:1": cache_entry(4.5),
        "cid:2": cache_entry(5.0),
        "cid:100": cache_entry(3.8),
        "cid:101": cache_entry(4.0),
        "cid:102": cache_entry(4.2),
    }
    rows = country_stats(places, cache, min_n=3)
    assert [r["country"] for r in rows] == ["France", "Japan"]  # by mean desc
    fr = rows[0]
    assert fr["mean"] == 4.5 and fr["median"] == 4.5
    jp = rows[1]
    assert jp["mean"] == 4.0 and jp["n"] == 3


def test_non_ok_and_unknown_excluded():
    places = [make_place(0), make_place(1, country=""), make_place(2)]
    places[1]["address"] = ""
    cache = {
        "cid:0": cache_entry(4.5),
        "cid:1": cache_entry(4.5),          # Unknown country
        "cid:2": {"status": "no_match"},    # not rated
    }
    rows = country_stats(places, cache, min_n=1)
    assert [r["country"] for r in rows] == ["France"]
    assert rows[0]["n"] == 1
