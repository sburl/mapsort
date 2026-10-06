"""Heuristic rule set for quick auto-suggestions on reclassification rows."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from json_utils import load_json_file


def _safe_int(raw: Any) -> int | None:
    try:
        if raw is None:
            return None
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None

_RULES: Sequence[tuple[re.Pattern[str], int, str]] = (
    (re.compile(r"\b(airport|airline|flight|terminal)\b", re.IGNORECASE), 14, "airport/aviation"),
    (
        re.compile(r"\b(train|metro|subway|rail|station|trm)\b", re.IGNORECASE),
        15,
        "train/transit",
    ),
    (re.compile(r"\b(hotel|hostel|resort|bnb|bed & breakfast)\b", re.IGNORECASE), 6, "lodging"),
    (re.compile(r"\b(bar|pub|cocktail|nightclub|night club|brewery)\b", re.IGNORECASE), 5, "bars"),
    (re.compile(r"\b(church|cathedral|temple|synagogue|mosque)\b", re.IGNORECASE), 9, "sacred/religious"),
    (re.compile(r"\b(restaurant|bistro|caf[eé]|coffee|bakery|dessert)\b", re.IGNORECASE), 1, "restaurants/food"),
    (re.compile(r"\b(museum|gallery|theater|theatre)\b", re.IGNORECASE), 7, "culture/museums"),
)

RuleEntry = tuple[re.Pattern[str], int, str]

_DEFAULT_RULES = tuple(_RULES)

AUTO_TAG_RULE_PACK_DIR = Path(__file__).resolve().parent / "auto_tag_rule_packs"


def _normalize_pattern(pattern: str) -> str:
    """Normalize JSON-escaped regex text into a usable pattern."""
    if "\\\\" not in pattern:
        return pattern
    try:
        return pattern.encode("utf-8").decode("unicode_escape")
    except (UnicodeDecodeError, UnicodeError, ValueError):
        return pattern


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def _pack_paths(
    country: str | None,
    travel_plan: str | None,
    rule_pack_dir: Path = AUTO_TAG_RULE_PACK_DIR,
) -> tuple[Path, ...]:
    paths = []
    if country:
        paths.append(rule_pack_dir / f"country-{_slug(country)}.json")
    if travel_plan:
        paths.append(rule_pack_dir / f"travel-{_slug(travel_plan)}.json")
    return tuple(paths)


def load_rules(path: Path) -> tuple[RuleEntry, ...]:
    payload = load_json_file(path, f"rules: {path}", expected_types=(), optional=False)
    if payload is None:
        raise ValueError(f"rules file is invalid JSON: {path}")
    if not isinstance(payload, list):
        # Bad input, not a programming error, so ValueError not TypeError.
        raise ValueError("rules file JSON must be a list")  # noqa: TRY004

    custom_rules: list[RuleEntry] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        pattern_raw = str(row.get("pattern", "")).strip()
        category = _safe_int(row.get("category"))
        if not pattern_raw or category is None:
            continue
        try:
            pattern = re.compile(_normalize_pattern(pattern_raw), re.IGNORECASE)
        except re.error:
            continue
        reason = str(row.get("reason", "custom"))
        custom_rules.append((pattern, category, reason))

    if not custom_rules:
        raise ValueError(f"rules file has no valid entries: {path}")
    return tuple(custom_rules)


def load_region_rules(
    country: str | None = None,
    travel_plan: str | None = None,
    rule_pack_dir: Path = AUTO_TAG_RULE_PACK_DIR,
) -> tuple[RuleEntry, ...]:
    """Load packaged rule packs for optional context (country/travel plan)."""
    rules: list[RuleEntry] = []
    for path in _pack_paths(country, travel_plan, rule_pack_dir=rule_pack_dir):
        if not path.exists():
            continue
        try:
            rules.extend(load_rules(path))
        except ValueError:
            # Bad custom packs should not break the whole auto-tag flow.
            continue
    return tuple(rules)


def infer_category_hint(
    name: str,
    address: str,
    *,
    rules: Sequence[RuleEntry] | None = None,
    include_default_rules: bool = True,
) -> tuple[int | None, str | None]:
    """Return a best-effort category and rationale for a row."""
    text = f"{name} {address}".strip().lower()
    if not text:
        return None, None
    if rules is None:
        active_rules = _DEFAULT_RULES
    elif include_default_rules:
        active_rules = tuple(rules) + _DEFAULT_RULES
    else:
        active_rules = tuple(rules)
    for pattern, category_id, reason in active_rules:
        if pattern.search(text):
            return category_id, reason
    return None, None
