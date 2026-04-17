"""Tests for token_estimator module."""

import pytest

from app.core.executor.token_estimator import (
    ContextBudget,
    MODEL_CONTEXT_LIMITS,
    estimate_tokens,
    check_context_budget,
)


# ── estimate_tokens ──────────────────────────────────────────

class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_short_text(self):
        # 12 chars -> 12 // 4 = 3
        assert estimate_tokens("Hello World!") == 3

    def test_long_text(self):
        text = "a" * 10_000
        assert estimate_tokens(text) == 2_500

    def test_non_divisible_length(self):
        # 5 chars -> 5 // 4 = 1 (floor division)
        assert estimate_tokens("abcde") == 1


# ── check_context_budget ─────────────────────────────────────

class TestCheckContextBudget:
    def test_low_usage_no_compaction(self):
        # 小 prompt，使用率遠低於 60%
        budget = check_context_budget("hello", "claude-sonnet")
        assert budget.model_limit == 200_000
        assert budget.estimated_used == 1  # 5 // 4
        assert budget.remaining == 199_999
        assert budget.usage_pct < 0.01
        assert budget.needs_compaction is False

    def test_high_usage_triggers_compaction(self):
        # 製造使用率 > 60% 的 prompt
        limit = MODEL_CONTEXT_LIMITS["claude-sonnet"]  # 200_000
        # 需要 estimated > limit * 0.6 = 120_000 tokens
        # 120_001 tokens = 480_004 chars
        text = "x" * 480_004
        budget = check_context_budget(text, "claude-sonnet")
        assert budget.estimated_used == 120_001
        assert budget.usage_pct > 0.6
        assert budget.needs_compaction is True

    def test_exactly_at_threshold(self):
        # 剛好 60%: 120_000 tokens = 480_000 chars
        text = "x" * 480_000
        budget = check_context_budget(text, "claude-sonnet")
        assert budget.estimated_used == 120_000
        assert budget.usage_pct == pytest.approx(0.6)
        # 0.6 不大於 0.6，所以 needs_compaction = False
        assert budget.needs_compaction is False

    def test_exceeds_limit(self):
        # 超過 model limit，remaining 應為 0
        limit = MODEL_CONTEXT_LIMITS["claude-sonnet"]
        text = "x" * (limit * 4 + 100)
        budget = check_context_budget(text, "claude-sonnet")
        assert budget.remaining == 0
        assert budget.usage_pct > 1.0
        assert budget.needs_compaction is True

    def test_gemini_model_limit(self):
        budget = check_context_budget("test", "gemini")
        assert budget.model_limit == 1_000_000

    def test_unknown_model_fallback(self):
        budget = check_context_budget("test", "unknown-model-xyz")
        # fallback 到預設 200_000
        assert budget.model_limit == 200_000
        assert budget.estimated_used == 1
        assert budget.needs_compaction is False

    def test_returns_frozen_dataclass(self):
        budget = check_context_budget("test", "claude-sonnet")
        with pytest.raises(AttributeError):
            budget.model_limit = 999  # type: ignore[misc]


# ── ContextBudget dataclass ──────────────────────────────────

class TestContextBudget:
    def test_frozen(self):
        b = ContextBudget(
            model_limit=200_000,
            estimated_used=100,
            remaining=199_900,
            usage_pct=0.0005,
            needs_compaction=False,
        )
        with pytest.raises(AttributeError):
            b.needs_compaction = True  # type: ignore[misc]
