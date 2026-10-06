"""Optional local vector-index utilities for fuzzy duplicate detection.

The helpers in this module are intentionally conservative: they only merge records
when names/addresses and location evidence strongly agree. The default thresholds are
chosen to avoid over-merging common place names that are likely distinct venues.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Final

from coord_utils import coord_distance_km, parse_coordinate_pair

Record = dict[str, object]
MergeFn = Callable[[Record, Record], None]

_TOKEN_RE: Final = re.compile(r"[a-z0-9]{2,}")
_COORD_BUCKET_SIZE_DEG: Final = 0.01


def normalize_text(text: str) -> str:
    """Lowercase + remove accents/punctuation for stable text matching."""
    if not text:
        return ""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    lowered = ascii_text.lower()
    tokens = _TOKEN_RE.findall(lowered)
    return " ".join(tokens)


def tokenize(text: str) -> tuple[str, ...]:
    return tuple(_TOKEN_RE.findall(text.lower()))


def build_vector(text: str) -> dict[str, int]:
    return Counter(tokenize(text))


def cosine_similarity(left: dict[str, int], right: dict[str, int]) -> float:
    if not left or not right:
        return 0.0
    if not set(left) or not set(right):
        return 0.0

    dot = 0.0
    for token, count in left.items():
        dot += count * right.get(token, 0)

    left_mag = math.sqrt(sum(count * count for count in left.values()))
    right_mag = math.sqrt(sum(count * count for count in right.values()))
    if left_mag == 0 or right_mag == 0:
        return 0.0
    return dot / (left_mag * right_mag)


def name_similarity(a: str, b: str) -> float:
    """Combine token and character similarity for resilient fuzzy matching."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    a_vec = build_vector(a)
    b_vec = build_vector(b)
    token_score = cosine_similarity(a_vec, b_vec)
    char_score = SequenceMatcher(None, a, b).ratio()
    return max(token_score, char_score)


def _coord_bucket(lat: float, lng: float) -> tuple[int, int]:
    return (int(lat / _COORD_BUCKET_SIZE_DEG), int(lng / _COORD_BUCKET_SIZE_DEG))


def _coord_distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    return coord_distance_km(a, b)


def _neighbor_buckets(bucket: tuple[int, int]) -> tuple[tuple[int, int], ...]:
    x, y = bucket
    return tuple((x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))


@dataclass
class _RecordVector:
    record: Record
    name: str
    address: str
    name_vec: dict[str, int]
    address_vec: dict[str, int]
    index_tokens: tuple[str, ...]
    bucket: tuple[int, int] | None


def _record_vector(record: Record) -> _RecordVector:
    lat_lng = parse_coordinate_pair(record.get("lat"), record.get("lng"), disallow_origin=False)
    name_raw = (record.get("name") or "").strip()
    address_raw = (record.get("address") or "").strip()
    norm_name = normalize_text(name_raw)
    norm_address = normalize_text(address_raw)

    index_text = norm_name if norm_name else norm_address
    tokens = tokenize(index_text)
    return _RecordVector(
        record=record,
        name=norm_name,
        address=norm_address,
        name_vec=build_vector(norm_name),
        address_vec=build_vector(norm_address),
        index_tokens=tokens,
        bucket=_coord_bucket(*lat_lng) if lat_lng else None,
    )


def _find_duplicates(
    existing: _RecordVector,
    candidate: _RecordVector,
    *,
    name_threshold: float,
    address_threshold: float,
    coord_km_threshold: float,
) -> bool:
    name_score = name_similarity(existing.name, candidate.name)
    address_score = name_similarity(existing.address, candidate.address)

    coord_score = 0.0
    coord_a = parse_coordinate_pair(existing.record.get("lat"), existing.record.get("lng"), disallow_origin=False)
    coord_b = parse_coordinate_pair(candidate.record.get("lat"), candidate.record.get("lng"), disallow_origin=False)
    if coord_a and coord_b:
        coord_km = _coord_distance_km(coord_a, coord_b)
        coord_score = max(0.0, 1.0 - (coord_km / coord_km_threshold)) if coord_km_threshold > 0 else 0.0

    same_address = address_score >= address_threshold
    same_name = name_score >= name_threshold
    close_enough = coord_km_threshold > 0 and coord_score > 0.2

    # Require either close coordinates + name OR same normalized address + name signal.
    return (same_name and close_enough) or (same_name and same_address) or (
        same_name and address_score >= 0.92
    )


def dedupe_by_local_vector_index(
    records: list[Record],
    merge_fn: MergeFn,
    *,
    name_threshold: float = 0.86,
    address_threshold: float = 0.82,
    coord_km_threshold: float = 0.25,
) -> list[Record]:
    """Deduplicate records using a local, in-memory token index.

    Args:
        records: Place-like records to deduplicate.
        merge_fn: Merge callback accepting (canonical, incoming).
        name_threshold: Normalized-name similarity threshold for duplicate candidates.
        address_threshold: Normalized-address similarity threshold for duplicate candidates.
        coord_km_threshold: Distance threshold for local coordinate close match.

    Returns:
        Deduplicated records in stable input order.
    """
    deduped: list[Record] = []
    meta: list[_RecordVector] = []
    token_index: dict[str, set[int]] = defaultdict(set)
    bucket_index: dict[tuple[int, int], set[int]] = defaultdict(set)

    for record in records:
        candidate = _record_vector(record.copy())

        candidate_indexes: set[int] = set()
        for token in candidate.index_tokens:
            candidate_indexes.update(token_index.get(token, set()))

        if not candidate_indexes and candidate.bucket is not None:
            for nearby in _neighbor_buckets(candidate.bucket):
                candidate_indexes.update(bucket_index.get(nearby, set()))

        if candidate_indexes:
            best_match = None
            for idx in candidate_indexes:
                existing = meta[idx]
                if _find_duplicates(
                    existing,
                    candidate,
                    name_threshold=name_threshold,
                    address_threshold=address_threshold,
                    coord_km_threshold=coord_km_threshold,
                ):
                    best_match = idx
                    break
        else:
            best_match = None

        if best_match is None:
            record_index = len(deduped)
            deduped.append(candidate.record)
            meta.append(candidate)

            for token in candidate.index_tokens:
                token_index[token].add(record_index)
            if candidate.bucket is not None:
                bucket_index[candidate.bucket].add(record_index)
            continue

        # Merge duplicate into canonical record and refresh indexes if signature changed.
        existing_meta = meta[best_match]
        merge_fn(existing_meta.record, candidate.record)

        merged = _record_vector(existing_meta.record)
        if merged.index_tokens != existing_meta.index_tokens:
            for token in existing_meta.index_tokens:
                bucket = token_index[token]
                bucket.discard(best_match)
                if not bucket:
                    token_index.pop(token, None)
            for token in merged.index_tokens:
                token_index[token].add(best_match)

        if merged.bucket != existing_meta.bucket:
            if existing_meta.bucket is not None:
                old_bucket = bucket_index[existing_meta.bucket]
                old_bucket.discard(best_match)
                if not old_bucket:
                    bucket_index.pop(existing_meta.bucket, None)
            if merged.bucket is not None:
                bucket_index[merged.bucket].add(best_match)

        meta[best_match] = merged

    return deduped
