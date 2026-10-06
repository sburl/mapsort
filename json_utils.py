"""Shared JSON read/parsing helpers for resilient data loading."""

from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path


def safe_str(value: object) -> str:
    """Convert a value to a string suitable for CSV/display output."""
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value).strip()


def _as_str(data: bytes | bytearray | str) -> str:
    if isinstance(data, bytes | bytearray):
        return bytes(data).decode("utf-8", errors="replace")
    return data


def parse_json_text(
    text: bytes | bytearray | str,
    source_name: str = "input",
    *,
    expected_types: tuple[type, ...] = (dict,),
    optional: bool = False,
) -> object | None:
    """Parse JSON and enforce an expected type."""
    try:
        payload = json.loads(_as_str(text))
    except JSONDecodeError as e:
        level = "WARNING" if optional else "ERROR"
        print(f"  {level}: {source_name} is not valid JSON ({e})")
        return None
    except TypeError as e:
        level = "WARNING" if optional else "ERROR"
        print(f"  {level}: {source_name} could not be parsed as JSON ({e})")
        return None

    if expected_types and not isinstance(payload, expected_types):
        expected = ", ".join(t.__name__ for t in expected_types)
        print(
            f"  WARNING: {source_name} has unexpected JSON root type "
            f"{type(payload).__name__}; expected {expected}"
        )
        return None

    return payload


def load_json_file(
    path: Path,
    source_name: str,
    *,
    expected_types: tuple[type, ...] = (dict,),
    optional: bool = False,
) -> object | None:
    """
    Load JSON from a file with validation and readable diagnostics.

    Args:
        path: Path to JSON file.
        source_name: Human-readable name for error messages.
        expected_types: Accepted JSON root types.
        optional: If True, missing files produce warnings instead of errors.
    """
    if not path.exists():
        level = "WARNING" if optional else "ERROR"
        print(f"  {level}: {source_name} missing: {path}")
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"  ERROR: Could not read {source_name} ({path}): {e}")
        return None
    return parse_json_text(text, source_name=source_name, expected_types=expected_types, optional=optional)

