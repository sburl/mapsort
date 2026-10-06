import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import enrich_descriptions
from enrich_descriptions import FIELD_MASK, fetch_description


def test_field_mask_stays_minimal():
    """Extra fields can push the request into a dearer SKU for no gain."""
    assert set(FIELD_MASK.split(",")) == {"id", "editorialSummary"}


def test_fetch_returns_blurb():
    payload = {"id": "x", "editorialSummary": {"text": "A cosy wine bar."}}
    with patch.object(enrich_descriptions, "_request", return_value=payload):
        assert fetch_description("x", "key") == {
            "status": "ok", "description": "A cosy wine bar."
        }


def test_absence_is_recorded_so_we_never_ask_twice():
    with patch.object(enrich_descriptions, "_request", return_value={"id": "x"}):
        assert fetch_description("x", "key") == {"status": "none"}
    with patch.object(enrich_descriptions, "_request", return_value={"id": "x", "editorialSummary": {"text": "  "}}):
        assert fetch_description("x", "key") == {"status": "none"}


def test_only_places_shown_in_guides_are_fetched():
    """Scoring covers everything; only printed places are worth paying for."""
    scored = [
        {"id": f"cid:{i}", "name": f"P{i}", "category": 1, "locations": ["Pittsburgh"],
         "famous": False, "chain": False, "gem_score": 1.0 - i / 100,
         "lat": 40.44 + i / 100, "lng": -79.99, "rating": 4.8, "review_count": 100}
        for i in range(12)
    ]
    ids = enrich_descriptions.shown_place_ids(scored, per_group=5)
    # five per section, so the tail of the pool is never requested
    assert len(ids) == 5
    assert "cid:11" not in ids


def test_attach_descriptions_is_a_noop_without_either_cache(tmp_path):
    import gem_score
    from gem_score import attach_descriptions
    with patch.object(gem_score, "DESCRIPTIONS_CACHE", tmp_path / "a.json"), \
         patch.object(gem_score, "AI_DESCRIPTIONS", tmp_path / "b.json"):
        assert attach_descriptions([{"id": "cid:1"}]) == {"google": 0, "ai": 0}


def test_attach_descriptions_folds_in_blurbs(tmp_path):
    import gem_score
    from gem_score import attach_descriptions
    cache = tmp_path / "d.json"
    cache.write_text(json.dumps({
        "cid:1": {"status": "ok", "description": "A cosy wine bar."},
        "cid:2": {"status": "none"},
    }), encoding="utf-8")
    rows = [{"id": "cid:1"}, {"id": "cid:2"}]
    with patch.object(gem_score, "DESCRIPTIONS_CACHE", cache), \
         patch.object(gem_score, "AI_DESCRIPTIONS", tmp_path / "none.json"):
        assert attach_descriptions(rows) == {"google": 1, "ai": 0}
    assert rows[0]["description"] == "A cosy wine bar."
    assert rows[0]["description_source"] == "google"
    assert "description" not in rows[1]


def test_google_blurb_wins_over_the_model(tmp_path):
    """A sourced sentence always beats an inferred one."""
    import gem_score
    from gem_score import attach_descriptions
    g = tmp_path / "g.json"
    g.write_text(json.dumps({"cid:1": {"status": "ok", "description": "Sourced."}}), encoding="utf-8")
    a = tmp_path / "a.json"
    a.write_text(json.dumps({"cid:1": {"status": "ok", "description": "Guessed.", "source": "ai"}}), encoding="utf-8")
    rows = [{"id": "cid:1"}]
    with patch.object(gem_score, "DESCRIPTIONS_CACHE", g), patch.object(gem_score, "AI_DESCRIPTIONS", a):
        counts = attach_descriptions(rows)
    assert rows[0]["description"] == "Sourced."
    assert rows[0]["description_source"] == "google"
    assert counts == {"google": 1, "ai": 0}
