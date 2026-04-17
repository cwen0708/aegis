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
