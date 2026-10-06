"""Shared payload validation helpers for JSON/CSV review artifacts."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from json_utils import load_json_file


class PayloadValidationError(ValueError):
    """Raised when a payload violates a required schema."""


REVIEW_TEMPLATE_REQUIRED_FIELDS = ("id", "reclassify_reasons")
REVIEW_DECISION_REQUIRED_FIELDS = ("id",)
CLASSIFIED_PLACES_REQUIRED_FIELDS = ("id",)


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    return str(value).strip() == ""


def _validate_required_fields(row: dict[str, Any], required_fields: tuple[str, ...]) -> list[str]:
    missing: list[str] = []
    for field in required_fields:
        if field not in row or _is_blank(row.get(field)):
            missing.append(field)
    return missing


def load_json_rows(
    path: Path,
    source_name: str,
    *,
    required_fields: tuple[str, ...] = (),
    optional: bool = False,
    strict: bool = False,
) -> list[dict[str, Any]]:
    """Load and validate JSON array payload rows."""
    payload = load_json_file(path, source_name, expected_types=(), optional=optional)
    if payload is None:
        if optional:
            return []
        raise PayloadValidationError(f"{source_name} is missing or invalid JSON: {path}")

    if not isinstance(payload, list):
        raise PayloadValidationError(f"{source_name} JSON must be a list")

    rows: list[dict[str, Any]] = []
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            if strict:
                raise PayloadValidationError(
                    f"{source_name} row {index} must be an object; got {type(row).__name__}"
                )
            print(f"  WARNING: {source_name} row {index} is not an object; skipping.")
            continue

        missing = _validate_required_fields(row, required_fields)
        if missing:
            if strict:
                raise PayloadValidationError(
                    f"{source_name} row {index} missing required field(s): "
                    f"{', '.join(sorted(missing))}"
                )
            print(
                f"  WARNING: {source_name} row {index} missing required field(s): "
                f"{', '.join(sorted(missing))}; skipping."
            )
            continue
        rows.append(row)

    return rows


def load_csv_rows(
    path: Path,
    source_name: str,
    *,
    required_fields: tuple[str, ...] = (),
    optional: bool = False,
    strict: bool = False,
) -> list[dict[str, str]]:
    """Load and validate CSV rows."""
    if not path.exists():
        if optional:
            return []
        raise PayloadValidationError(f"{source_name} missing: {path}")

    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        if required_fields:
            missing = [field for field in required_fields if field not in header]
            if missing:
                if strict:
                    raise PayloadValidationError(
                        f"{source_name} is missing required column(s): {', '.join(sorted(missing))}"
                    )
                print(
                    f"  WARNING: {source_name} is missing required column(s): "
                    f"{', '.join(sorted(missing))}; skipping invalid rows."
                )
        rows = []
        for index, row in enumerate(reader):
            if required_fields:
                missing = _validate_required_fields(row, required_fields)
                if missing:
                    if strict:
                        raise PayloadValidationError(
                            f"{source_name} row {index} missing required field(s): "
                            f"{', '.join(sorted(missing))}"
                        )
                    print(
                        f"  WARNING: {source_name} row {index} missing required field(s): "
                        f"{', '.join(sorted(missing))}; skipping."
                    )
                    continue
            rows.append(dict(row))
    return rows
