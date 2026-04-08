"""Cross Review Engine 測試"""
from __future__ import annotations

import pytest

from app.core.cross_review import (
    ReviewPolicy,
    ReviewPolicyRegistry,
    ReviewRequest,
    ReviewScope,
    build_review_request,
)


# ── ReviewScope enum ──────────────────────────────────────────────


class TestReviewScope:
    def test_values(self):
        assert ReviewScope.CODE.value == "code"
        assert ReviewScope.CONFIG.value == "config"
        assert ReviewScope.DOCS.value == "docs"
        assert ReviewScope.ALL.value == "all"

    def test_member_count(self):
        assert len(ReviewScope) == 4


# ── ReviewPolicy frozen dataclass ─────────────────────────────────


class TestReviewPolicy:
    def test_create_with_defaults(self):
        policy = ReviewPolicy(
            source_member_id="xiao-yin",
            reviewer_member_id="xiao-liang",
            scope=ReviewScope.CODE,
        )
        assert policy.source_member_id == "xiao-yin"
        assert policy.reviewer_member_id == "xiao-liang"
        assert policy.scope == ReviewScope.CODE
        assert policy.auto_trigger is True

    def test_create_with_explicit_auto_trigger(self):
        policy = ReviewPolicy(
            source_member_id="a",
            reviewer_member_id="b",
            scope=ReviewScope.DOCS,
            auto_trigger=False,
        )
        assert policy.auto_trigger is False

    def test_frozen_immutability(self):
        policy = ReviewPolicy(
            source_member_id="a",
            reviewer_member_id="b",
            scope=ReviewScope.ALL,
        )
        with pytest.raises(AttributeError):
            policy.source_member_id = "c"  # type: ignore[misc]

    def test_equality(self):
        kwargs = dict(
            source_member_id="a",
            reviewer_member_id="b",
            scope=ReviewScope.CODE,
            auto_trigger=True,
        )
        assert ReviewPolicy(**kwargs) == ReviewPolicy(**kwargs)


# ── ReviewRequest frozen dataclass ────────────────────────────────


class TestReviewRequest:
    def test_create(self):
        req = ReviewRequest(
            card_id=42,
            card_title="Fix login bug",
            source_member_id="xiao-yin",
            reviewer_member_id="xiao-liang",
            diff_summary="修正登入邏輯",
            changed_files=("backend/app/auth.py",),
        )
        assert req.card_id == 42
        assert req.changed_files == ("backend/app/auth.py",)

    def test_frozen_immutability(self):
        req = ReviewRequest(
            card_id=1,
            card_title="t",
            source_member_id="a",
            reviewer_member_id="b",
            diff_summary="d",
            changed_files=(),
        )
        with pytest.raises(AttributeError):
            req.card_id = 99  # type: ignore[misc]


# ── ReviewPolicyRegistry ──────────────────────────────────────────


class TestReviewPolicyRegistry:
    def _make_policy(
        self,
        source: str = "xiao-yin",
        reviewer: str = "xiao-liang",
        scope: ReviewScope = ReviewScope.CODE,
        auto_trigger: bool = True,
    ) -> ReviewPolicy:
        return ReviewPolicy(
            source_member_id=source,
            reviewer_member_id=reviewer,
            scope=scope,
            auto_trigger=auto_trigger,
        )

    def test_register_and_find_exact(self):
        reg = ReviewPolicyRegistry()
        policy = self._make_policy(scope=ReviewScope.CODE)
        reg.register(policy)

        found = reg.find_reviewer("xiao-yin", ReviewScope.CODE)
        assert found is policy

    def test_find_reviewer_returns_none_when_empty(self):
        reg = ReviewPolicyRegistry()
        assert reg.find_reviewer("xiao-yin", ReviewScope.CODE) is None

    def test_find_reviewer_returns_none_when_no_match(self):
        reg = ReviewPolicyRegistry()
        reg.register(self._make_policy(scope=ReviewScope.DOCS))

        assert reg.find_reviewer("xiao-yin", ReviewScope.CODE) is None

    def test_find_reviewer_fallback_to_all(self):
        reg = ReviewPolicyRegistry()
        all_policy = self._make_policy(scope=ReviewScope.ALL)
        reg.register(all_policy)

        found = reg.find_reviewer("xiao-yin", ReviewScope.CONFIG)
        assert found is all_policy

    def test_exact_scope_takes_precedence_over_all(self):
        reg = ReviewPolicyRegistry()
        all_policy = self._make_policy(reviewer="fallback", scope=ReviewScope.ALL)
        code_policy = self._make_policy(reviewer="specialist", scope=ReviewScope.CODE)
        reg.register(all_policy)
        reg.register(code_policy)

        found = reg.find_reviewer("xiao-yin", ReviewScope.CODE)
        assert found is code_policy
        assert found.reviewer_member_id == "specialist"

    def test_different_sources_isolated(self):
        reg = ReviewPolicyRegistry()
        reg.register(self._make_policy(source="a", reviewer="b", scope=ReviewScope.CODE))
        reg.register(self._make_policy(source="c", reviewer="d", scope=ReviewScope.CODE))

        found_a = reg.find_reviewer("a", ReviewScope.CODE)
        found_c = reg.find_reviewer("c", ReviewScope.CODE)
        assert found_a is not None and found_a.reviewer_member_id == "b"
        assert found_c is not None and found_c.reviewer_member_id == "d"

    def test_list_policies_empty(self):
        reg = ReviewPolicyRegistry()
        assert reg.list_policies() == []

    def test_list_policies(self):
        reg = ReviewPolicyRegistry()
        p1 = self._make_policy(source="a", scope=ReviewScope.CODE)
        p2 = self._make_policy(source="b", scope=ReviewScope.DOCS)
        reg.register(p1)
        reg.register(p2)

        policies = reg.list_policies()
        assert len(policies) == 2
        assert set(policies) == {p1, p2}

    def test_register_overwrites_same_key(self):
        reg = ReviewPolicyRegistry()
        old = self._make_policy(reviewer="old-reviewer", scope=ReviewScope.CODE)
        new = self._make_policy(reviewer="new-reviewer", scope=ReviewScope.CODE)
        reg.register(old)
        reg.register(new)

        found = reg.find_reviewer("xiao-yin", ReviewScope.CODE)
        assert found is new


# ── build_review_request 工廠函式 ─────────────────────────────────


class TestBuildReviewRequest:
    def test_builds_from_policy(self):
        policy = ReviewPolicy(
            source_member_id="xiao-yin",
            reviewer_member_id="xiao-liang",
            scope=ReviewScope.CODE,
        )
        req = build_review_request(
            policy,
            card_id=100,
            card_title="新增互審模組",
            diff_summary="新增 cross_review.py",
            changed_files=("backend/app/core/cross_review.py",),
        )

        assert isinstance(req, ReviewRequest)
        assert req.card_id == 100
        assert req.card_title == "新增互審模組"
        assert req.source_member_id == "xiao-yin"
        assert req.reviewer_member_id == "xiao-liang"
        assert req.diff_summary == "新增 cross_review.py"
        assert req.changed_files == ("backend/app/core/cross_review.py",)

    def test_result_is_frozen(self):
        policy = ReviewPolicy(
            source_member_id="a",
            reviewer_member_id="b",
            scope=ReviewScope.ALL,
        )
        req = build_review_request(
            policy,
            card_id=1,
            card_title="t",
            diff_summary="d",
            changed_files=(),
        )
        with pytest.raises(AttributeError):
            req.diff_summary = "changed"  # type: ignore[misc]

    def test_empty_changed_files(self):
        policy = ReviewPolicy(
            source_member_id="a",
            reviewer_member_id="b",
            scope=ReviewScope.DOCS,
        )
        req = build_review_request(
            policy,
            card_id=5,
            card_title="Docs update",
            diff_summary="更新文件",
            changed_files=(),
        )
        assert req.changed_files == ()
