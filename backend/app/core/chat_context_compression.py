"""Multi-stage chat-history compression — pure-function skeleton (QuantClaw mode).

Step 1 (#13105 P1-SH-13) ports the QuantClaw shape into Python as three
side-effect-free functions with an injectable summarizer. No wiring to
``app.core.executor`` / ``conversation_manager`` / ``runner``; no real LLM call;
no real BM25. Those land in step 2+.

Functions
---------
- ``compress_history(messages, target_count, *, recent_keep, summarizer)``
  Collapse older messages into a single summary system message, then keep the
  ``recent_keep`` tail. If the input is already within ``target_count``, return
  a defensive copy unchanged.
- ``chunk_messages(messages, chunk_size)``
  Split a message list into fixed-size chunks; the trailing remainder forms
  its own final chunk.
- ``select_top_chunks(chunks, top_k)``
  Return the indices of the ``top_k`` "most relevant" chunks. Placeholder
  recency-bias implementation; real BM25 scoring is TODO for step 2+.

Naming note: this module is prefixed ``chat_`` to avoid collision with the
many ``context`` variables in the codebase.
"""

from __future__ import annotations

from typing import Callable

Message = dict[str, str]
Summarizer = Callable[[list[Message]], str]

DEFAULT_RECENT_KEEP = 5
_PLACEHOLDER_SUMMARY = (
    "[compressed: earlier conversation summarized — step-1 placeholder]"
)


def _default_summarizer(_older: list[Message]) -> str:
    """Placeholder summarizer used when no real one is injected.

    Step 2+ replaces this with a Haiku-backed summarization call. Tests pin
    the placeholder string only via ``test_default_summarizer_is_placeholder_string``
    (non-empty + str), so the exact wording can evolve without breaking tests.
    """
    return _PLACEHOLDER_SUMMARY


def compress_history(
    messages: list[Message],
    target_count: int,
    *,
    recent_keep: int = DEFAULT_RECENT_KEEP,
    summarizer: Summarizer | None = None,
) -> list[Message]:
    """Compress a chat history toward ``target_count`` messages.

    - If ``len(messages) <= target_count``: return a shallow copy unchanged.
    - Otherwise: produce ``[summary_system_msg, *messages[-recent_keep:]]``.

    ``summarizer`` receives the *older* slice (everything except the recent
    tail) and must return a string used as the summary message content. When
    omitted, a deterministic placeholder is used so callers can exercise the
    pipeline without a live LLM.
    """
    if len(messages) <= target_count:
        return list(messages)

    summarize = summarizer or _default_summarizer
    older = list(messages[:-recent_keep]) if recent_keep > 0 else list(messages)
    summary_text = summarize(older)
    summary_msg: Message = {"role": "system", "content": summary_text}
    tail = list(messages[-recent_keep:]) if recent_keep > 0 else []
    return [summary_msg, *tail]


def chunk_messages(
    messages: list[Message],
    chunk_size: int,
) -> list[list[Message]]:
    """Split ``messages`` into consecutive chunks of size ``chunk_size``.

    The trailing remainder (if any) becomes the final chunk. An empty input
    yields an empty list.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    return [
        list(messages[i : i + chunk_size])
        for i in range(0, len(messages), chunk_size)
    ]


def select_top_chunks(
    chunks: list[list[Message]],
    top_k: int,
) -> list[int]:
    """Return indices of the ``top_k`` "most relevant" chunks.

    Placeholder behaviour: returns the last ``top_k`` indices (recency bias).
    TODO step 2+: replace with BM25 scoring against the active user query so
    older but semantically-related chunks can survive compression.
    """
    if top_k <= 0:
        return []
    n = len(chunks)
    start = max(0, n - top_k)
    return list(range(start, n))
