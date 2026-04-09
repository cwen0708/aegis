"""CrossReviewHook 測試"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.cross_review import ReviewPolicy, ReviewPolicyRegistry, ReviewScope
from app.hooks import TaskContext
from app.hooks.cross_review import (
    CrossReviewHook,
    _default_registry,
    _extract_diff_summary,
)


# ── _extract_diff_summary ───────────────────────────────────────────


class TestExtractDiffSummary:
    def test_empty_output(self):
        assert _extract_diff_summary("") == "(no output)"

    def test_short_output_unchanged(self):
        text = "修正登入邏輯"
        assert _extract_diff_summary(text) == text

    def test_long_output_truncated(self):
        text = "x" * 600
        result = _extract_diff_summary(text)
        assert result.endswith("...")
        assert len(result) == 500 + 3  # _MAX_SUMMARY_LEN + "..."

    def test_strips_whitespace(self):
        assert _extract_diff_summary("  hello  ") == "hello"


# ── _default_registry ───────────────────────────────────────────────


class TestDefaultRegistry:
    def test_xiao_yin_reviewed_by_xiao_liang(self):
        reg = _default_registry()
        policy = reg.find_reviewer("xiao-yin", ReviewScope.CODE)
        assert policy is not None
        assert policy.reviewer_member_id == "xiao-liang"

    def test_xiao_liang_reviewed_by_xiao_yin(self):
        reg = _default_registry()
        policy = reg.find_reviewer("xiao-liang", ReviewScope.CODE)
        assert policy is not None
        assert policy.reviewer_member_id == "xiao-yin"

    def test_unknown_member_returns_none(self):
        reg = _default_registry()
        assert reg.find_reviewer("unknown", ReviewScope.CODE) is None


# ── CrossReviewHook.on_complete ─────────────────────────────────────


def _make_ctx(**overrides) -> TaskContext:
    """建立測試用 TaskContext"""
    defaults = dict(
        card_id=42,
        card_title="修正登入 bug",
        project_id=1,
        member_slug="xiao-yin",
        status="completed",
        source="worker",
        output="修正了 auth.py 的登入邏輯",
    )
    defaults.update(overrides)
    return TaskContext(**defaults)


class TestCrossReviewHookTriggerCondition:
    """測試 on_complete 觸發條件"""

    def test_skips_when_status_not_completed(self):
        """non-completed 狀態不觸發"""
        hook = CrossReviewHook()
        ctx = _make_ctx(status="failed")
        with patch("app.hooks.cross_review._find_review_list_id") as mock_find:
            hook.on_complete(ctx)
            mock_find.assert_not_called()

    def test_skips_when_source_not_worker(self):
        """non-worker 來源不觸發"""
        hook = CrossReviewHook()
        ctx = _make_ctx(source="chat")
        with patch("app.hooks.cross_review._find_review_list_id") as mock_find:
            hook.on_complete(ctx)
            mock_find.assert_not_called()

    def test_skips_when_no_member_slug(self):
        """無 member_slug 不觸發"""
        hook = CrossReviewHook()
        ctx = _make_ctx(member_slug="")
        with patch("app.hooks.cross_review._find_review_list_id") as mock_find:
            hook.on_complete(ctx)
            mock_find.assert_not_called()

    def test_skips_when_no_review_policy(self):
        """無對應審查策略不觸發"""
        empty_registry = ReviewPolicyRegistry()
        hook = CrossReviewHook(registry=empty_registry)
        ctx = _make_ctx(member_slug="unknown-member")
        with patch("app.hooks.cross_review._find_review_list_id") as mock_find:
            hook.on_complete(ctx)
            mock_find.assert_not_called()

    def test_skips_when_review_list_not_found(self):
        """找不到「審查中」列表不觸發建卡"""
        hook = CrossReviewHook()
        ctx = _make_ctx()
        with patch("app.hooks.cross_review._find_review_list_id", return_value=None):
            with patch("app.hooks.cross_review.create_card") as mock_create:
                hook.on_complete(ctx)
                mock_create.assert_not_called()


class TestCrossReviewHookCardCreation:
    """測試審查卡片建立邏輯"""

    @patch("app.hooks.cross_review.create_card")
    @patch("app.hooks.cross_review._find_review_list_id", return_value=99)
    def test_creates_review_card(self, _mock_find, mock_create):
        """completed + worker → 建立審查卡片"""
        mock_create.return_value = MagicMock(id=200)
        hook = CrossReviewHook()
        ctx = _make_ctx()

        hook.on_complete(ctx)

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["project_id"] == 1
        assert call_kwargs["list_id"] == 99
        assert call_kwargs["status"] == "pending"
        assert "CrossReview" in call_kwargs["tags"]

    @patch("app.hooks.cross_review.create_card")
    @patch("app.hooks.cross_review._find_review_list_id", return_value=99)
    def test_card_title_format(self, _mock_find, mock_create):
        """卡片標題格式: review(cross): {title} — by {reviewer}"""
        mock_create.return_value = MagicMock(id=200)
        hook = CrossReviewHook()
        ctx = _make_ctx(card_title="修正登入 bug", member_slug="xiao-yin")

        hook.on_complete(ctx)

        title = mock_create.call_args[1]["title"]
        assert title == "review(cross): 修正登入 bug — by xiao-liang"

    @patch("app.hooks.cross_review.create_card")
    @patch("app.hooks.cross_review._find_review_list_id", return_value=99)
    def test_card_content_includes_diff_summary(self, _mock_find, mock_create):
        """卡片內容包含 diff_summary"""
        mock_create.return_value = MagicMock(id=200)
        hook = CrossReviewHook()
        ctx = _make_ctx(output="修正了 auth.py 的登入邏輯")

        hook.on_complete(ctx)

        content = mock_create.call_args[1]["content"]
        assert "修正了 auth.py 的登入邏輯" in content
        assert "交叉審查" in content
        assert "#42" in content

    @patch("app.hooks.cross_review.create_card")
    @patch("app.hooks.cross_review._find_review_list_id", return_value=99)
    def test_xiao_liang_reviewed_by_xiao_yin(self, _mock_find, mock_create):
        """小良的產出由小茵審查"""
        mock_create.return_value = MagicMock(id=201)
        hook = CrossReviewHook()
        ctx = _make_ctx(member_slug="xiao-liang")

        hook.on_complete(ctx)

        title = mock_create.call_args[1]["title"]
        assert "by xiao-yin" in title

    @patch("app.hooks.cross_review.create_card")
    @patch("app.hooks.cross_review._find_review_list_id", return_value=99)
    def test_create_card_failure_handled(self, _mock_find, mock_create):
        """create_card 回傳 None 時不拋錯"""
        mock_create.return_value = None
        hook = CrossReviewHook()
        ctx = _make_ctx()

        # 不應拋出例外
        hook.on_complete(ctx)
        mock_create.assert_called_once()

    @patch("app.hooks.cross_review.create_card")
    @patch("app.hooks.cross_review._find_review_list_id", return_value=99)
    def test_custom_registry(self, _mock_find, mock_create):
        """支援自訂 registry"""
        custom = ReviewPolicyRegistry()
        custom.register(ReviewPolicy(
            source_member_id="alpha",
            reviewer_member_id="beta",
            scope=ReviewScope.ALL,
        ))
        mock_create.return_value = MagicMock(id=300)

        hook = CrossReviewHook(registry=custom)
        ctx = _make_ctx(member_slug="alpha")

        hook.on_complete(ctx)

        title = mock_create.call_args[1]["title"]
        assert "by beta" in title
