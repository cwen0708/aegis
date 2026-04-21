"""Tests for app.core.request_dedup (cache key computation only)."""

from __future__ import annotations

import re

import pytest

from app.core import request_dedup


def test_same_dict_with_different_key_order_produces_same_key() -> None:
    a = request_dedup.compute_dedup_key({"a": 1, "b": 2})
    b = request_dedup.compute_dedup_key({"b": 2, "a": 1})
    assert a is not None
    assert a == b


def test_nested_dict_key_order_normalized() -> None:
    a = request_dedup.compute_dedup_key(
        {"outer": {"a": 1, "b": 2}, "list": [{"x": 1, "y": 2}]}
    )
    b = request_dedup.compute_dedup_key(
        {"list": [{"y": 2, "x": 1}], "outer": {"b": 2, "a": 1}}
    )
    assert a is not None
    assert a == b


def test_different_content_produces_different_key() -> None:
    a = request_dedup.compute_dedup_key({"msg": "hello"})
    b = request_dedup.compute_dedup_key({"msg": "world"})
    assert a is not None and b is not None
    assert a != b


def test_timestamp_prefix_stripped() -> None:
    a = request_dedup.compute_dedup_key(
        {"messages": [{"role": "user", "content": "[SUN 2026-02-07 13:30 PST] hello"}]}
    )
    b = request_dedup.compute_dedup_key(
        {"messages": [{"role": "user", "content": "[MON 2026-02-08 14:30 UTC] hello"}]}
    )
    assert a is not None
    assert a == b


def test_accepts_bytes_input() -> None:
    key = request_dedup.compute_dedup_key(b'{"msg":"hello"}')
    assert key is not None
    assert len(key) == 16


def test_accepts_string_input() -> None:
    key = request_dedup.compute_dedup_key('{"msg":"hello"}')
    assert key is not None
    assert len(key) == 16


def test_body_exceeds_max_size_returns_none() -> None:
    big = {"blob": "x" * (request_dedup.MAX_BODY_SIZE + 1)}
    assert request_dedup.compute_dedup_key(big) is None


def test_hash_is_16_hex_chars() -> None:
    key = request_dedup.compute_dedup_key({"msg": "hello"})
    assert key is not None
    assert len(key) == 16
    assert re.fullmatch(r"[0-9a-f]{16}", key) is not None
