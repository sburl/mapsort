#!/usr/bin/env python3
"""Build a reclassification queue for uncertain or stale places."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from coord_utils import coord_distance_km, parse_coordinate_pair
from dates import days_since, parse_iso_datetime, utc_now
from file_writers import write_csv_rows
from fuzzy_dedupe import name_similarity
from json_utils import safe_str
from payload_validation import (
    CLASSIFIED_PLACES_REQUIRED_FIELDS,
    PayloadValidationError,
    load_json_rows,
)
from settings import CLASSIFIED_JSON, LOW_CONFIDENCE_REVIEW_JSON, RECLASSIFY_QUEUE_JSON

RECLASSIFY_FIELDNAMES = (
    "id",
    "name",
    "address",
    "category",
    "confidence",
    "status",
    "date",
    "source",
    "tier",
    "days_since_saved",
    "reclassify_reasons",
    "explain_best_match_id",
    "explain_name_score",
    "explain_address_score",
    "explain_distance_km",
    "explain_similarity",
)


def _stale_reference_timestamp(place: dict) -> Any:
    return place.get("classified_at") or place.get("date")


def _coord_distance_km(a: tuple[float, float] | None, b: tuple[float, float] | None) -> float | None:
    if a is None or b is None:
        return None
    return coord_distance_km(a, b)


def _best_similarity_candidate(
    index: int,
    target: dict,
    rows: list[dict],
) -> tuple[str, float | str, float | str, float | str, float | str]:
    """Return the best nearby match for review explainability.

    Similarity is a lightweight, local nearest-neighbor score that blends
    normalized name/address fuzz match plus optional coordinate proximity.
    """
    best_id = ""
    best_name = ""
    best_address = ""
    best_distance = ""
    best_score = 0.0

    target_name = safe_str(target.get("name"))
    target_address = safe_str(target.get("address"))
    target_coords = parse_coordinate_pair(
        target.get("lat"), target.get("lng"), disallow_origin=False
    )

    for candidate_index, candidate in enumerate(rows):
        if candidate_index == index:
            continue

        name_score = name_similarity(target_name, safe_str(candidate.get("name")))
        address_score = name_similarity(target_address, safe_str(candidate.get("address")))
        candidate_coords = parse_coordinate_pair(
            candidate.get("lat"),
            candidate.get("lng"),
            disallow_origin=False,
        )
        coord_distance = _coord_distance_km(target_coords, candidate_coords)
        if coord_distance is None:
            coord_score = 0.0
        else:
            coord_score = max(0.0, 1.0 - (coord_distance / 3.0))

        similarity = (name_score * 0.6) + (address_score * 0.3) + (coord_score * 0.1)

        if similarity <= best_score:
            continue

        best_score = similarity
        best_id = safe_str(candidate.get("id")) or f"index:{candidate_index}"
        best_name = round(name_score, 3)
        best_address = round(address_score, 3)
        best_distance = "" if coord_distance is None else round(coord_distance, 3)

    if best_score == 0.0:
        return "", "", "", "", ""

    return best_id, best_name, best_address, best_distance, round(best_score, 3)


def _priority_key_oldest(entry: dict[str, Any]) -> tuple[int, int, str]:
    saved_days = entry.get("days_since_saved")
    if saved_days is None or isinstance(saved_days, str):
        return (1, 0, safe_str(entry.get("id")))
    return (0, -int(saved_days), safe_str(entry.get("id")))


def _confidence_rank(value: Any) -> int:
    value = safe_str(value).lower().strip()
    if value == "low":
        return 0
    if value == "medium":
        return 1
    if value == "high":
        return 2
    return 3


def _priority_key_lowest_confidence(entry: dict[str, Any]) -> tuple[int, str]:
    return (_confidence_rank(entry.get("confidence")), safe_str(entry.get("id")))


def _priority_key_most_recently_reviewed(
    entry: dict[str, Any],
    review_at_by_id: dict[str, datetime | None],
) -> tuple[int, float, str]:
    reviewed_at = review_at_by_id.get(safe_str(entry.get("id")))
    if reviewed_at is None:
        return (1, 0.0, safe_str(entry.get("id")))
    return (0, -reviewed_at.timestamp(), safe_str(entry.get("id")))


def _get_review_priority_key(
    priority: str,
    review_at_by_id: dict[str, datetime | None],
) -> Callable[[dict[str, Any]], tuple[object, object, str]]:
    if priority == "oldest":
        return _priority_key_oldest
    if priority == "lowest-confidence":
        return _priority_key_lowest_confidence
    if priority == "most-recently-reviewed":
        return lambda entry: _priority_key_most_recently_reviewed(entry, review_at_by_id)
    raise ValueError(f"unsupported priority: {priority}")


def _load_records(
    path: Path,
    *,
    required_fields: tuple[str, ...] = (),
    strict: bool = False,
) -> list[dict]:
    try:
        return load_json_rows(
            path,
            f"reclassify payload: {path}",
            required_fields=required_fields,
            optional=True,
            strict=strict,
        )
    except PayloadValidationError:
        return []


def _load_review_history(
    path: Path,
    *,
    retry_days: int,
    now: datetime | None,
) -> tuple[dict[str, datetime | None], set[str]]:
    history_records = _load_records(path, required_fields=("id",))
    if not history_records:
        return {}, set()

    cutoff = now or utc_now()
    reviewed_at_by_id: dict[str, datetime | None] = {}
    reviewed_ids: set[str] = set()
    for record in history_records:
        record_id = safe_str(record.get("id"))
        if not record_id:
            continue
        reviewed_at = parse_iso_datetime(record.get("reviewed_at"))
        reviewed_at_by_id[record_id] = reviewed_at
        if retry_days <= 0:
            continue
        if reviewed_at is None or (cutoff - reviewed_at).days < retry_days:
            reviewed_ids.add(record_id)

    return reviewed_at_by_id, reviewed_ids


def build_reclassify_queue(
    classified_path: Path,
    low_confidence_path: Path,
    *,
    include_low_confidence: bool = True,
    include_stale: bool = False,
    stale_days: int = 0,
    max_items: int | None = None,
    history_path: Path | None = None,
    retry_days: int = 0,
    priority: str = "default",
    now: datetime | None = None,
) -> list[dict]:
    """Build queue rows eligible for reclassification."""
    if not include_low_confidence and not include_stale:
        return []

    if stale_days < 0:
        raise ValueError("stale_days must be >= 0")
    if include_stale and stale_days <= 0:
        raise ValueError("stale_days must be > 0 when include_stale is enabled")

    classified = _load_records(classified_path)
    if not classified:
        return []

    low_confidence_by_id: set[str] = set()
    if include_low_confidence:
        low_conf_rows = _load_records(low_confidence_path, required_fields=CLASSIFIED_PLACES_REQUIRED_FIELDS)
        for row in low_conf_rows:
            place_id = row.get("id")
            if place_id:
                low_confidence_by_id.add(safe_str(place_id))

        if not low_confidence_by_id:
            low_confidence_by_id = {
                safe_str(row.get("id"))
                for row in classified
                if row.get("id") and row.get("confidence") == "low"
            }

    now = now or utc_now()
    reviewed_ids: set[str] = set()
    review_at_by_id: dict[str, datetime | None] = {}
    if history_path is not None:
        review_at_by_id, reviewed_ids = _load_review_history(
            history_path, retry_days=retry_days, now=now
        )

    selected: list[dict] = []
    for index, place in enumerate(classified):
        place_id = safe_str(place.get("id") or f"index:{index}")
        stale_reference = _stale_reference_timestamp(place)
        reasons: list[str] = []

        if include_low_confidence and (
            place.get("confidence") == "low" or place_id in low_confidence_by_id
        ):
            reasons.append("low_confidence")

        saved_days: int | None = None
        if include_stale:
            saved_days = days_since(stale_reference, now=now)
            if saved_days is not None and saved_days >= stale_days:
                reasons.append("stale")

        if not reasons:
            continue

        if place_id in reviewed_ids:
            continue

        explain_id, explain_name_score, explain_address_score, explain_distance, explain_score = (
            _best_similarity_candidate(index, place, classified)
        )

        selected.append({
            "id": place_id,
            "name": place.get("name", ""),
            "address": place.get("address", ""),
            "category": place.get("category", ""),
            "confidence": place.get("confidence", ""),
            "status": place.get("status", ""),
            "date": safe_str(place.get("date")) if not include_stale else safe_str(stale_reference),
            "source": place.get("source", ""),
            "tier": place.get("tier", "visited"),
            "days_since_saved": "" if saved_days is None else saved_days,
            "reclassify_reasons": ",".join(reasons),
            "explain_best_match_id": explain_id,
            "explain_name_score": explain_name_score,
            "explain_address_score": explain_address_score,
            "explain_distance_km": explain_distance,
            "explain_similarity": explain_score,
        })

    if priority != "default":
        selected.sort(key=_get_review_priority_key(priority, review_at_by_id))

    if max_items is not None:
        selected = selected[: max_items]

    return selected


def write_queue_output(queue: list[dict], output: Path, output_format: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "json":
        with output.open("w", encoding="utf-8") as f:
            json.dump(queue, f, indent=2, ensure_ascii=False)
        return

    write_csv_rows(output, RECLASSIFY_FIELDNAMES, queue)


def _print_summary(queue: list[dict], output: Path, *, verbose: bool = False) -> None:
    if not queue:
        print("Reclassify queue empty for current criteria.")
        return

    print(f"Reclassify queue: {len(queue)} rows -> {output}")
    if not verbose:
        return

    reasons = Counter()
    for row in queue:
        reasons[row["reclassify_reasons"]] += 1

    for reason, count in sorted(reasons.items()):
        print(f"  {reason}: {count}")


def _low_confidence_backlog_count(queue: list[dict]) -> int:
    count = 0
    for row in queue:
        reasons = safe_str(row.get("reclassify_reasons")).split(",")
        if "low_confidence" in [r.strip().lower() for r in reasons if r.strip()]:
            count += 1
    return count


def run_low_confidence_backlog_hook(
    queue: list[dict],
    threshold: int,
    command: str | None,
) -> None:
    if threshold <= 0 or not command:
        return
    low_confidence_backlog = _low_confidence_backlog_count(queue)
    if low_confidence_backlog <= threshold:
        return

    args = shlex.split(command)
    if not args:
        return

    payload = {
        "event": "low_confidence_backlog_threshold_exceeded",
        "threshold": threshold,
        "low_confidence_backlog": low_confidence_backlog,
        "queue_size": len(queue),
    }

    try:
        completed = subprocess.run(
            args,
            input=json.dumps(payload, indent=2),
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        print("WARNING: low-confidence backlog hook timed out after 30s")
        return
    except OSError as exc:
        print(f"WARNING: failed to run low-confidence backlog hook: {exc}")
        return

    if completed.returncode != 0:
        print(
            "WARNING: low-confidence backlog hook returned non-zero status: "
            f"{completed.returncode}"
        )
        if completed.stderr:
            print(completed.stderr.strip())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a reclassification queue for low-confidence and stale places."
    )
    parser.add_argument(
        "--classified",
        default=str(CLASSIFIED_JSON),
        help="Path to classified places JSON (default: output/places_classified.json).",
    )
    parser.add_argument(
        "--low-confidence",
        default=str(LOW_CONFIDENCE_REVIEW_JSON),
        help="Low-confidence source file (default: output/low_confidence_review.json).",
    )
    parser.add_argument(
        "--output",
        default=str(RECLASSIFY_QUEUE_JSON),
        help="Output queue path (default: output/reclassification_queue.json).",
    )
    parser.add_argument(
        "--output-format",
        default="json",
        choices=("json", "csv"),
        help="Queue output format (default: json).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-reason breakdown in addition to row count.",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=None,
        help="Cap queue output to first N rows.",
    )
    parser.add_argument(
        "--include-low-confidence",
        action="store_true",
        default=True,
        dest="include_low_confidence",
        help="Include low-confidence candidates (default: enabled).",
    )
    parser.add_argument(
        "--no-low-confidence",
        action="store_false",
        dest="include_low_confidence",
        help="Disable low-confidence queueing.",
    )
    parser.add_argument(
        "--include-stale",
        action="store_true",
        help="Include rows older than `--stale-days`.",
    )
    parser.add_argument(
        "--stale-days",
        type=int,
        default=365,
        help="Minimum days old to treat as stale when --include-stale is set (default: 365).",
    )
    parser.add_argument(
        "--history",
        default=None,
        help=(
            "Optional JSON history file to skip recently reviewed rows "
            "(expects array of objects with `id` and optional `reviewed_at`)."
        ),
    )
    parser.add_argument(
        "--retry-days",
        type=int,
        default=0,
        help="If --history is used, suppress re-queueing IDs reviewed within this many days.",
    )
    parser.add_argument(
        "--priority",
        default="default",
        choices=("default", "oldest", "lowest-confidence", "most-recently-reviewed"),
        help="Sort rows before output for review scheduling.",
    )
    parser.add_argument(
        "--notify-threshold",
        type=int,
        default=0,
        help=(
            "If positive, run --notify-command when low-confidence queue rows exceed this number."
        ),
    )
    parser.add_argument(
        "--notify-command",
        default=None,
        help=(
            "Command to run when the low-confidence threshold is exceeded. "
            "Payload is sent on stdin as JSON."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.include_low_confidence and not args.include_stale:
        print("ERROR: enable at least one source with --include-low-confidence or --include-stale.")
        return 2

    if args.max_items is not None and args.max_items < 0:
        print("ERROR: --max-items must be non-negative.")
        return 2
    if args.retry_days < 0:
        print("ERROR: --retry-days must be >= 0.")
        return 2
    if args.notify_threshold < 0:
        print("ERROR: --notify-threshold must be >= 0.")
        return 2

    queue = build_reclassify_queue(
        Path(args.classified),
        Path(args.low_confidence),
        include_low_confidence=args.include_low_confidence,
        include_stale=args.include_stale,
        stale_days=args.stale_days,
        max_items=args.max_items,
        history_path=Path(args.history) if args.history else None,
        retry_days=args.retry_days,
        priority=args.priority,
    )
    run_low_confidence_backlog_hook(queue, args.notify_threshold, args.notify_command)

    output = Path(args.output)
    write_queue_output(queue, output, args.output_format)
    if args.verbose:
        _print_summary(queue, output, verbose=True)
    else:
        print(
            json.dumps(
                {
                    "rows": len(queue),
                    "output": str(args.output),
                    "format": args.output_format,
                }
            )
        )
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
