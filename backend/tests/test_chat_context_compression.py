"""Tests for app.core.chat_context_compression — pure compression skeleton.

Step 1 (#13105 P1-SH-13) covers only pure functions. Wiring to chat flow,
real LLM summarization, and BM25 scoring land in follow-up steps.
"""

from __future__ import annotations

import copy

from app.core import chat_context_compression as ccc


def _msgs(n: int) -> list[dict[str, str]]:
    return [{"role": "user", "content": f"m{i}"} for i in range(n)]


def test_compress_within_limit_returns_input_unchanged() -> None:
    src = _msgs(5)
    out = ccc.compress_history(src, target_count=10, recent_keep=3)
    assert out == src
    assert out is not src  # defensive copy, not the same list object


def test_compress_exceeds_limit_yields_summary_plus_recent_keep() -> None:
    src = _msgs(20)
    out = ccc.compress_history(src, target_count=8, recent_keep=5)
    assert len(out) == 1 + 5
    assert out[0]["role"] == "system"
    assert out[1:] == src[-5:]


def test_compress_uses_injected_summarizer_with_older_messages() -> None:
    src = _msgs(12)
    captured: dict[str, object] = {}

    def fake_summarizer(older: list[dict[str, str]]) -> str:
        captured["older"] = list(older)
        return "SUMMARY-OK"

    out = ccc.compress_history(
        src,
        target_count=4,
        recent_keep=3,
        summarizer=fake_summarizer,
    )
    assert captured["older"] == src[:-3]
    assert out[0]["content"] == "SUMMARY-OK"
    assert out[0]["role"] == "system"


def test_compress_does_not_mutate_input_list() -> None:
    src = _msgs(15)
    snapshot = copy.deepcopy(src)
    _ = ccc.compress_history(src, target_count=5, recent_keep=2)
    assert src == snapshot


def test_select_top_chunks_returns_last_top_k_indices() -> None:
    chunks = [[{"role": "user", "content": f"c{i}"}] for i in range(6)]
    indices = ccc.select_top_chunks(chunks, top_k=3)
    assert indices == [3, 4, 5]


def test_select_top_chunks_top_k_exceeds_available_returns_all_indices() -> None:
    chunks = [[{"role": "user", "content": "x"}] for _ in range(2)]
    indices = ccc.select_top_chunks(chunks, top_k=10)
    assert indices == [0, 1]


def test_chunk_messages_remainder_becomes_final_chunk() -> None:
    src = _msgs(7)
    chunks = ccc.chunk_messages(src, chunk_size=3)
    assert len(chunks) == 3
    assert chunks[0] == src[0:3]
    assert chunks[1] == src[3:6]
    assert chunks[2] == src[6:7]


def test_chunk_messages_exact_multiple_no_remainder() -> None:
    src = _msgs(6)
    chunks = ccc.chunk_messages(src, chunk_size=3)
    assert len(chunks) == 2
    assert chunks[0] == src[0:3]
    assert chunks[1] == src[3:6]


def test_chunk_messages_empty_returns_empty_list() -> None:
    assert ccc.chunk_messages([], chunk_size=4) == []


def test_default_summarizer_is_placeholder_string() -> None:
    src = _msgs(20)
    out = ccc.compress_history(src, target_count=4, recent_keep=2)
    assert isinstance(out[0]["content"], str)
    assert out[0]["content"]  # non-empty placeholder


def test_chunk_messages_rejects_non_positive_size() -> None:
    import pytest

    with pytest.raises(ValueError):
        ccc.chunk_messages(_msgs(3), chunk_size=0)


def test_select_top_chunks_zero_or_negative_returns_empty() -> None:
    chunks = [[{"role": "user", "content": "x"}] for _ in range(3)]
    assert ccc.select_top_chunks(chunks, top_k=0) == []
    assert ccc.select_top_chunks(chunks, top_k=-1) == []
