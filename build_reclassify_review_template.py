#!/usr/bin/env python3
"""Build a review CSV template from the reclassification queue."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from auto_reclassify_rules import (
    AUTO_TAG_RULE_PACK_DIR,
    RuleEntry,
    infer_category_hint,
    load_region_rules,
    load_rules,
)
from file_writers import write_csv_rows
from json_utils import safe_str
from payload_validation import (
    CLASSIFIED_PLACES_REQUIRED_FIELDS,
    REVIEW_TEMPLATE_REQUIRED_FIELDS,
    PayloadValidationError,
    load_csv_rows,
    load_json_rows,
)
from settings import (
    CLASSIFIED_JSON,
    RECLASSIFY_DECISION_TEMPLATE_CSV,
    RECLASSIFY_QUEUE_JSON,
)

FIELDNAMES = (
    "id",
    "name",
    "address",
    "category",
    "confidence",
    "reclassify_reasons",
    "decision_category",
    "decision_confidence",
    "notes",
)


def _load_queue(path: Path, *, queue_format: str | None = None) -> list[dict]:
    if not path.exists():
        return []

    use_csv = queue_format == "csv" if queue_format else path.suffix.lower() == ".csv"

    if use_csv:
        return load_csv_rows(
            path,
            f"queue: {path}",
            required_fields=REVIEW_TEMPLATE_REQUIRED_FIELDS,
            strict=False,
        )

    try:
        return load_json_rows(
            path,
            f"queue file: {path}",
            required_fields=REVIEW_TEMPLATE_REQUIRED_FIELDS,
            optional=False,
        )
    except PayloadValidationError as exc:
        message = str(exc)
        if "JSON must be a list" in message:
            raise ValueError("queue file JSON must be a list")
        raise ValueError(f"queue file is invalid JSON: {path}") from exc


def _load_places(path: Path) -> dict[str, dict]:
    try:
        payload = load_json_rows(
            path,
            f"classified: {path}",
            required_fields=CLASSIFIED_PLACES_REQUIRED_FIELDS,
            optional=True,
            strict=False,
        )
    except PayloadValidationError:
        return {}

    rows: dict[str, dict] = {}
    for row in payload:
        place_id = safe_str(row.get("id"))
        if place_id:
            rows[place_id] = row
    return rows


def _safe_int_or_none(value) -> int | None:
    try:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        return int(text)
    except (TypeError, ValueError):
        return None


def build_review_template(
    queue_path: Path,
    classified_path: Path,
    output_path: Path,
    *,
    auto_tag: bool = False,
    auto_rules: tuple[RuleEntry, ...] | None = None,
    auto_country: str | None = None,
    auto_travel_plan: str | None = None,
    rule_pack_dir: Path = AUTO_TAG_RULE_PACK_DIR,
    output_format: str = "csv",
    queue_format: str | None = None,
) -> int:
    queue_rows = _load_queue(queue_path, queue_format=queue_format)
    if not queue_rows:
        if output_format == "json":
            with output_path.open("w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False)
        else:
            write_csv_rows(
                output_path,
                FIELDNAMES,
                [],
            )
        return 0

    places_by_id = _load_places(classified_path)
    region_rules = (
        load_region_rules(
            country=auto_country,
            travel_plan=auto_travel_plan,
            rule_pack_dir=rule_pack_dir,
        )
        if auto_tag
        else ()
    )
    template_rows: list[dict] = []
    seen_ids: set[str] = set()

    for row in queue_rows:
        place_id = safe_str(row.get("id"))
        if not place_id or place_id in seen_ids:
            continue
        seen_ids.add(place_id)

        source = places_by_id.get(place_id, {})
        name = safe_str(row.get("name") or source.get("name"))
        address = safe_str(row.get("address") or source.get("address"))
        decision_category = _safe_int_or_none(row.get("decision_category"))
        notes = safe_str(row.get("notes"))
        suggested_reason = ""
        if decision_category is None and auto_tag:
            combined_rules = tuple(auto_rules or ()) + tuple(region_rules)
            suggestion, suggested_reason = infer_category_hint(
                name,
                address,
                rules=combined_rules if combined_rules else None,
            )
            decision_category = suggestion
        if not notes and suggested_reason:
            notes = suggested_reason

        template_rows.append(
            {
                "id": place_id,
                "name": name,
                "address": address,
                "category": safe_str(row.get("category") or source.get("category")),
                "confidence": safe_str(row.get("confidence") or source.get("confidence")),
                "reclassify_reasons": safe_str(row.get("reclassify_reasons")),
                "decision_category": safe_str(decision_category) if decision_category is not None else "",
                "decision_confidence": "",
                "notes": notes,
            }
        )

    if output_format == "json":
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(template_rows, f, indent=2, ensure_ascii=False)
    else:
        write_csv_rows(output_path, FIELDNAMES, template_rows)
    return len(template_rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a manual review template for reclassification decisions."
    )
    parser.add_argument(
        "--queue",
        default=str(RECLASSIFY_QUEUE_JSON),
        help="Reclassify queue path (json/csv).",
    )
    parser.add_argument(
        "--classified",
        default=str(CLASSIFIED_JSON),
        help="Classified places path (to enrich context).",
    )
    parser.add_argument(
        "--output",
        default=str(RECLASSIFY_DECISION_TEMPLATE_CSV),
        help="Output template path.",
    )
    parser.add_argument(
        "--auto-tag",
        action="store_true",
        help="Pre-fill decision_category using heuristic name/address rules.",
    )
    parser.add_argument(
        "--rule-file",
        default=None,
        help=(
            "Optional JSON file with custom regex/category rules to use with --auto-tag "
            '(format: [{"pattern": "...", "category": 1, "reason": "..."}]).'
        ),
    )
    parser.add_argument(
        "--country",
        default=None,
        help="Optional country code/name for loading regional auto-tag pack.",
    )
    parser.add_argument(
        "--travel-plan",
        default=None,
        help="Optional travel plan name for loading regional auto-tag pack.",
    )
    parser.add_argument(
        "--rule-pack-dir",
        default=str(AUTO_TAG_RULE_PACK_DIR),
        help="Directory with optional country-/travel-plan rule pack JSON files.",
    )
    parser.add_argument(
        "--output-format",
        default="csv",
        choices=("csv", "json"),
        help="Template output format (default: csv).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="No-op for parity with other review commands.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        auto_rules = None
        if args.auto_tag and args.rule_file:
            auto_rules = load_rules(Path(args.rule_file))
        count = build_review_template(
            Path(args.queue),
            Path(args.classified),
            Path(args.output),
            auto_tag=args.auto_tag,
            auto_rules=auto_rules,
            auto_country=args.country,
            auto_travel_plan=args.travel_plan,
            rule_pack_dir=Path(args.rule_pack_dir),
            output_format=args.output_format,
        )
    except (ValueError, OSError) as e:
        print(f"ERROR: {e}")
        return 2

    if args.verbose:
        print(f"Built review template with {count} rows -> {args.output}")
    else:
        print(
            json.dumps(
                {
                    "rows": count,
                    "output": str(args.output),
                    "format": args.output_format,
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
