"""Cross Review Panel / 多數決計票 — P2-SH-18 step 1 測試

僅測試純函式資料模型（ReviewPanel / Vote / VoteTally）與 tally_votes，
不涉及任何 API / Hook / Runner / DB 接線。
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.core.cross_review import (
    ReviewPanel,
    ReviewScope,
    Vote,
    VoteTally,
    tally_votes,
)


# ── tally_votes 多數決計票 ─────────────────────────────────────────


class TestTallyVotes:
    def test_tally_three_of_two_passes(self):
        """3 票中 2 贊成 1 反對 → approved=True"""
        votes = (
            Vote(reviewer_member_id="a", approved=True),
            Vote(reviewer_member_id="b", approved=True),
            Vote(reviewer_member_id="c", approved=False),
        )
        result = tally_votes(votes, required_approvals=2)
        assert result.approved is True
        assert result.approval_count == 2
        assert result.rejection_count == 1

    def test_tally_three_of_one_fails(self):
        """3 票中 1 贊成 2 反對 → approved=False"""
        votes = (
            Vote(reviewer_member_id="a", approved=True),
            Vote(reviewer_member_id="b", approved=False),
            Vote(reviewer_member_id="c", approved=False),
        )
        result = tally_votes(votes, required_approvals=2)
        assert result.approved is False
        assert result.approval_count == 1
        assert result.rejection_count == 2

    def test_tally_all_approve(self):
        """3 票全贊成 → approved=True, approval_count=3"""
        votes = (
            Vote(reviewer_member_id="a", approved=True),
            Vote(reviewer_member_id="b", approved=True),
            Vote(reviewer_member_id="c", approved=True),
        )
        result = tally_votes(votes, required_approvals=2)
        assert result.approved is True
        assert result.approval_count == 3
        assert result.rejection_count == 0

    def test_tally_sorted_by_member_id(self):
        """輸入亂序，輸出 votes 按 member_id 字典序排序"""
        votes = (
            Vote(reviewer_member_id="charlie", approved=True),
            Vote(reviewer_member_id="alice", approved=False),
            Vote(reviewer_member_id="bob", approved=True),
        )
        result = tally_votes(votes, required_approvals=2)
        ordered_ids = tuple(v.reviewer_member_id for v in result.votes)
        assert ordered_ids == ("alice", "bob", "charlie")

    def test_tally_duplicate_reviewer_raises(self):
        """同一 reviewer_member_id 出現兩次 → ValueError"""
        votes = (
            Vote(reviewer_member_id="a", approved=True),
            Vote(reviewer_member_id="a", approved=False),
        )
        with pytest.raises(ValueError):
            tally_votes(votes, required_approvals=1)


# ── ReviewPanel frozen dataclass ──────────────────────────────────


class TestReviewPanel:
    def test_review_panel_frozen(self):
        """ReviewPanel 物件是 frozen，assigning 新欄位 raises"""
        panel = ReviewPanel(
            source_member_id="xiao-yin",
            reviewer_member_ids=("xiao-liang", "xiao-mu", "xiao-hao"),
            required_approvals=2,
            scope=ReviewScope.CODE,
        )
        with pytest.raises(FrozenInstanceError):
            panel.required_approvals = 3  # type: ignore[misc]


# ── VoteTally 回傳型別 ────────────────────────────────────────────


class TestVoteTallyType:
    def test_votes_is_tuple(self):
        """VoteTally.votes 必須是 tuple（不可變）"""
        votes = (
            Vote(reviewer_member_id="a", approved=True),
            Vote(reviewer_member_id="b", approved=False),
        )
        result = tally_votes(votes, required_approvals=1)
        assert isinstance(result.votes, tuple)
