"""Request deduplication — pure cache-key computation.

Compute a stable, short SHA256-based key from a request body so that
identical requests (regardless of dict key order or timestamp prefixes
inside message content) collapse to the same key.

This module handles **only** key computation. Inflight/completed cache
state, TTL expiry, and proxy integration live in follow-up steps.

The default ``TIMESTAMP_PATTERN`` targets a day-date-time-tz prefix like
``[SUN 2026-02-07 13:30 PST]`` (ported from the OpenClaw reference).
Aegis callers may inject a custom ``timestamp_pattern`` if their message
format differs.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

MAX_BODY_SIZE = 1_048_576  # 1 MiB — larger bodies are treated as undedup-able
DEFAULT_TTL_SECONDS = 30.0  # reserved for follow-up steps (inflight/completed cache)

# Matches prefixes like "[SUN 2026-02-07 13:30 PST] " at the start of text.
# Day = 3 uppercase letters, date = YYYY-MM-DD, time = HH:MM, tz = uppercase letters.
TIMESTAMP_PATTERN = re.compile(
    r"\[[A-Z]{3}\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+[A-Z]+\]\s*"
)

_HASH_PREFIX_LEN = 16


def _canonicalize_json(data: Any) -> str:
    """Produce a canonical JSON string with all dict keys recursively sorted."""
    return json.dumps(
        _sort_recursive(data),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _sort_recursive(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _sort_recursive(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_sort_recursive(item) for item in value]
    return value


def _strip_timestamps(text: str, pattern: re.Pattern[str] | None = None) -> str:
    """Remove timestamp-like prefixes so retries with refreshed timestamps match."""
    return (pattern or TIMESTAMP_PATTERN).sub("", text)


def _strip_timestamps_in_tree(value: Any, pattern: re.Pattern[str]) -> Any:
    if isinstance(value, str):
        return _strip_timestamps(value, pattern)
    if isinstance(value, dict):
        return {k: _strip_timestamps_in_tree(v, pattern) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_timestamps_in_tree(item, pattern) for item in value]
    return value


def _body_to_canonical(
    body: dict | list | bytes | str,
    pattern: re.Pattern[str],
) -> str:
    if isinstance(body, (bytes, bytearray)):
        return _strip_timestamps(body.decode("utf-8", errors="replace"), pattern)
    if isinstance(body, str):
        return _strip_timestamps(body, pattern)
    if isinstance(body, (dict, list)):
        cleaned = _strip_timestamps_in_tree(body, pattern)
        return _canonicalize_json(cleaned)
    raise TypeError(f"Unsupported body type: {type(body).__name__}")


def compute_dedup_key(
    body: dict | list | bytes | str,
    *,
    timestamp_pattern: re.Pattern[str] | None = None,
) -> str | None:
    """Return a 16-char hex dedup key, or ``None`` if body exceeds ``MAX_BODY_SIZE``.

    - dict/list inputs are canonicalized (recursive key sort) before hashing.
    - string fields inside the body have timestamp prefixes stripped.
    - bytes/str inputs are treated as raw bodies.
    """
    pattern = timestamp_pattern or TIMESTAMP_PATTERN
    canonical = _body_to_canonical(body, pattern)
    encoded = canonical.encode("utf-8")
    if len(encoded) > MAX_BODY_SIZE:
        return None
    digest = hashlib.sha256(encoded).hexdigest()
    return digest[:_HASH_PREFIX_LEN]
