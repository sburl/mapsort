#!/usr/bin/env python3
"""Build both a reclassify queue and a review template in one command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from auto_reclassify_rules import AUTO_TAG_RULE_PACK_DIR, RuleEntry, load_rules
from build_reclassify_review_template import build_review_template
from build_reclassify_review_ui import build_review_ui
from reclassify_queue import (
    build_reclassify_queue,
    run_low_confidence_backlog_hook,
    write_queue_output,
)
from settings import (
    CLASSIFIED_JSON,
    LOW_CONFIDENCE_REVIEW_JSON,
    RECLASSIFICATION_REVIEW_UI_HTML,
    RECLASSIFY_DECISION_TEMPLATE_CSV,
    RECLASSIFY_QUEUE_JSON,
)


def build_reclassify_review_round(
    classified_path: Path,
    low_confidence_path: Path,
    queue_output: Path,
    template_output: Path,
    *,
    include_low_confidence: bool = True,
    include_stale: bool = False,
    stale_days: int = 365,
    max_items: int | None = None,
    history_path: Path | None = None,
    retry_days: int = 0,
    priority: str = "default",
    notify_threshold: int = 0,
    notify_command: str | None = None,
    auto_tag: bool = False,
    auto_rules: tuple[RuleEntry, ...] | None = None,
    auto_country: str | None = None,
    auto_travel_plan: str | None = None,
    rule_pack_dir: str | Path = AUTO_TAG_RULE_PACK_DIR,
    queue_output_format: str = "json",
    template_output_format: str = "csv",
    build_ui: bool = False,
    ui_output: Path = RECLASSIFICATION_REVIEW_UI_HTML,
    ui_title: str = "Reclassification Review UI",
) -> tuple[int, int]:
    """Build queue + template artifacts and return `(queue_rows, template_rows)`."""
    queue_rows = build_reclassify_queue(
        classified_path,
        low_confidence_path,
        include_low_confidence=include_low_confidence,
        include_stale=include_stale,
        stale_days=stale_days,
        max_items=max_items,
        history_path=history_path,
        retry_days=retry_days,
        priority=priority,
    )
    write_queue_output(queue_rows, queue_output, queue_output_format)
    if build_ui and template_output_format != "csv":
        raise ValueError("build_ui requires template output in CSV format.")

    template_count = build_review_template(
        queue_output,
        classified_path,
        template_output,
        auto_tag=auto_tag,
        auto_rules=auto_rules,
        auto_country=auto_country,
        auto_travel_plan=auto_travel_plan,
        rule_pack_dir=Path(rule_pack_dir),
        output_format=template_output_format,
        queue_format=queue_output_format,
    )
    run_low_confidence_backlog_hook(queue_rows, notify_threshold, notify_command)
    if build_ui:
        build_review_ui(template_output, ui_output, title=ui_title)
    return len(queue_rows), template_count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a full reclassification review round (queue + template)."
    )
    parser.add_argument(
        "--classified",
        default=str(CLASSIFIED_JSON),
        help="Input classified places path (default: output/places_classified.json).",
    )
    parser.add_argument(
        "--low-confidence",
        default=str(LOW_CONFIDENCE_REVIEW_JSON),
        help="Low-confidence queue source (default: output/low_confidence_review.json).",
    )
    parser.add_argument(
        "--queue",
        default=str(RECLASSIFY_QUEUE_JSON),
        help="Queue output path (default: output/reclassification_queue.json).",
    )
    parser.add_argument(
        "--template",
        default=str(RECLASSIFY_DECISION_TEMPLATE_CSV),
        help="Template output path (default: output/reclassification_review_template.csv).",
    )
    parser.add_argument(
        "--queue-format",
        default="json",
        choices=("json", "csv"),
        help="Reclassify queue output format (default: json).",
    )
    parser.add_argument(
        "--output-format",
        default=None,
        choices=("json", "csv"),
        help="Alias for --queue-format (json|csv).",
    )
    parser.add_argument(
        "--template-format",
        default="csv",
        choices=("csv", "json"),
        help="Template output format (default: csv).",
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
        help=(
            "Minimum days old to treat as stale when --include-stale is set "
            "(default: 365)."
        ),
    )
    parser.add_argument(
        "--history",
        default=None,
        help=(
            "Optional history JSON file to skip recently reviewed IDs "
            "(expects array of objects with `id` and optional `reviewed_at`)."
        ),
    )
    parser.add_argument(
        "--retry-days",
        type=int,
        default=0,
        help="If --history is used, suppress IDs reviewed within this many days.",
    )
    parser.add_argument(
        "--priority",
        default="default",
        choices=("default", "oldest", "lowest-confidence", "most-recently-reviewed"),
        help="Reclassify queue sorting strategy.",
    )
    parser.add_argument(
        "--notify-threshold",
        type=int,
        default=0,
        help="If positive, run --notify-command when low-confidence queue rows exceed this number.",
    )
    parser.add_argument(
        "--notify-command",
        default=None,
        help=(
            "Command to run when low-confidence threshold is exceeded. "
            "Payload is sent on stdin as JSON."
        ),
    )
    parser.add_argument(
        "--auto-tag",
        action="store_true",
        help="Prefill template `decision_category` using heuristics.",
    )
    parser.add_argument(
        "--rule-file",
        default=None,
        help=(
            "Optional JSON file with custom regex/category rules for --auto-tag "
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
        "--build-ui",
        action="store_true",
        help="Build browser-friendly review UI HTML in addition to queue/template.",
    )
    parser.add_argument(
        "--ui",
        default=str(RECLASSIFICATION_REVIEW_UI_HTML),
        help="Review UI output path (default: output/reclassification_review_ui.html).",
    )
    parser.add_argument(
        "--ui-title",
        default="Reclassification Review UI",
        help="Review UI page title and heading.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print structured output summary details.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.max_items is not None and args.max_items < 0:
        print("ERROR: --max-items must be non-negative.")
        return 2
    if args.retry_days < 0:
        print("ERROR: --retry-days must be >= 0.")
        return 2
    if args.notify_threshold < 0:
        print("ERROR: --notify-threshold must be >= 0.")
        return 2
    if not args.include_low_confidence and not args.include_stale:
        print("ERROR: enable at least one source with --include-low-confidence or --include-stale.")
        return 2

    auto_rules = None
    if args.auto_tag and args.rule_file:
        try:
            auto_rules = load_rules(Path(args.rule_file))
        except (ValueError, OSError) as e:
            print(f"ERROR: {e}")
            return 2

    queue_output_format = args.output_format or args.queue_format

    try:
        queue_count, template_count = build_reclassify_review_round(
            Path(args.classified),
            Path(args.low_confidence),
            Path(args.queue),
            Path(args.template),
            include_low_confidence=args.include_low_confidence,
            include_stale=args.include_stale,
            stale_days=args.stale_days,
            max_items=args.max_items,
            history_path=Path(args.history) if args.history else None,
            retry_days=args.retry_days,
            priority=args.priority,
            notify_threshold=args.notify_threshold,
            notify_command=args.notify_command,
            auto_tag=args.auto_tag,
            auto_rules=auto_rules,
            auto_country=args.country,
            auto_travel_plan=args.travel_plan,
            rule_pack_dir=Path(args.rule_pack_dir),
            queue_output_format=queue_output_format,
            template_output_format=args.template_format,
            build_ui=args.build_ui,
            ui_output=Path(args.ui),
            ui_title=args.ui_title,
        )
    except (FileNotFoundError, ValueError, OSError) as e:
        print(f"ERROR: {e}")
        return 2

    if args.verbose:
        print(f"Built reclassify queue ({queue_output_format}): {queue_count} rows -> {args.queue}")
        print(
            f"Built review template ({args.template_format}): {template_count} rows -> {args.template}"
        )
        if args.build_ui:
            print(f"Built review UI ({args.ui_title!r}): {args.ui}")
    else:
        payload = {
            "queue_rows": queue_count,
            "template_rows": template_count,
            "queue": str(args.queue),
            "template": str(args.template),
        }
        if args.build_ui:
            payload["review_ui"] = str(args.ui)
        print(
            json.dumps(payload)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
