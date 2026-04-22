"""
Cross Review Engine — Agent 互審機制核心

定義審查範圍、策略與請求的資料模型，
提供 Protocol-based 審查策略路由，為後續 CrossReviewHook 奠定基礎。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class ReviewScope(Enum):
    """審查範圍"""

    CODE = "code"
    CONFIG = "config"
    DOCS = "docs"
    ALL = "all"


@dataclass(frozen=True)
class ReviewPolicy:
    """審查策略 — 定義誰的產出由誰審查、範圍與觸發方式

    Attributes:
        source_member_id: 被審查者（產出方）的 member ID
        reviewer_member_id: 審查者的 member ID
        scope: 審查範圍（code / config / docs / all）
        auto_trigger: 是否自動觸發審查（commit 後自動派發）
    """

    source_member_id: str
    reviewer_member_id: str
    scope: ReviewScope
    auto_trigger: bool = True


@dataclass(frozen=True)
class ReviewRequest:
    """審查請求 — 攜帶卡片與變更摘要，派發給審查者

    Attributes:
        card_id: 關聯卡片 ID
        card_title: 卡片標題
        source_member_id: 產出方 member ID
        reviewer_member_id: 審查者 member ID
        diff_summary: 變更摘要文字
        changed_files: 變更檔案路徑列表（不可變 tuple）
    """

    card_id: int
    card_title: str
    source_member_id: str
    reviewer_member_id: str
    diff_summary: str
    changed_files: tuple[str, ...]


class ReviewPolicyProvider(Protocol):
    """審查策略提供者介面（Protocol-based 設計）"""

    def find_reviewer(
        self, source_member_id: str, scope: ReviewScope,
    ) -> ReviewPolicy | None:
        """根據產出方與範圍找到對應的審查策略。"""
        ...

    def list_policies(self) -> list[ReviewPolicy]:
        """列出所有已註冊的審查策略。"""
        ...


class ReviewPolicyRegistry:
    """審查策略註冊表 — 管理 Agent 互審的策略路由

    以 (source_member_id, scope) 為鍵儲存策略，
    支援 scope=ALL 的通配匹配。
    """

    def __init__(self) -> None:
        self._policies: dict[tuple[str, ReviewScope], ReviewPolicy] = {}

    def register(self, policy: ReviewPolicy) -> None:
        """註冊審查策略，以 (source_member_id, scope) 為鍵。"""
        key = (policy.source_member_id, policy.scope)
        self._policies[key] = policy

    def find_reviewer(
        self, source_member_id: str, scope: ReviewScope,
    ) -> ReviewPolicy | None:
        """根據產出方與範圍查找審查策略。

        查詢順序：精確 scope 匹配 → ALL 通配匹配 → None。
        """
        exact = self._policies.get((source_member_id, scope))
        if exact is not None:
            return exact

        # fallback: scope=ALL 通配
        return self._policies.get((source_member_id, ReviewScope.ALL))

    def list_policies(self) -> list[ReviewPolicy]:
        """列出所有已註冊的審查策略。"""
        return list(self._policies.values())


def build_review_request(
    policy: ReviewPolicy,
    *,
    card_id: int,
    card_title: str,
    diff_summary: str,
    changed_files: tuple[str, ...],
) -> ReviewRequest:
    """根據審查策略建立審查請求。

    從 policy 提取 source/reviewer member ID，
    搭配卡片資訊與變更摘要組裝成不可變的 ReviewRequest。
    """
    return ReviewRequest(
        card_id=card_id,
        card_title=card_title,
        source_member_id=policy.source_member_id,
        reviewer_member_id=policy.reviewer_member_id,
        diff_summary=diff_summary,
        changed_files=changed_files,
    )


# ── PRM Gate 多數決審查面板（P2-SH-18 step 1，純函式資料模型，未接線） ─


@dataclass(frozen=True)
class ReviewPanel:
    """多數決審查面板 — 多個 reviewer 平行投票

    Attributes:
        source_member_id: 產出方 member ID
        reviewer_member_ids: 參與投票的 reviewer member ID 清單（不可變 tuple）
        required_approvals: 通過所需的最少贊成票數（例如 3 取 2）
        scope: 審查範圍
    """

    source_member_id: str
    reviewer_member_ids: tuple[str, ...]
    required_approvals: int
    scope: ReviewScope


@dataclass(frozen=True)
class Vote:
    """單一 reviewer 的投票結果"""

    reviewer_member_id: str
    approved: bool
    comment: str = ""


@dataclass(frozen=True)
class VoteTally:
    """計票結果

    Attributes:
        approved: 是否達到 required_approvals 門檻
        approval_count: 贊成票數
        rejection_count: 反對票數
        votes: 原始投票（依 reviewer_member_id 字典序排序）
    """

    approved: bool
    approval_count: int
    rejection_count: int
    votes: tuple[Vote, ...]


def tally_votes(
    votes: tuple[Vote, ...], required_approvals: int,
) -> VoteTally:
    """多數決計票 — 純函式，不接線、不寫 DB、不呼叫外部。

    規則：
    - approval_count = 所有 v.approved 為 True 的票數
    - approved = approval_count >= required_approvals
    - 回傳 votes 以 reviewer_member_id 字典序排序（確保可比較）
    - 重複 reviewer_member_id 視為錯誤 → raise ValueError
    """
    seen: set[str] = set()
    for v in votes:
        if v.reviewer_member_id in seen:
            raise ValueError(
                f"duplicate reviewer_member_id: {v.reviewer_member_id}",
            )
        seen.add(v.reviewer_member_id)

    ordered = tuple(sorted(votes, key=lambda v: v.reviewer_member_id))
    approval_count = sum(1 for v in ordered if v.approved)
    rejection_count = len(ordered) - approval_count
    return VoteTally(
        approved=approval_count >= required_approvals,
        approval_count=approval_count,
        rejection_count=rejection_count,
        votes=ordered,
    )
