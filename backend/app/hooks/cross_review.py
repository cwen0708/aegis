"""
CrossReviewHook — 任務完成後自動派發交叉審查

當 worker 任務 completed 時，根據 ReviewPolicyRegistry 找到審查者，
建立審查卡片到「審查中」列表。
"""
import logging
from typing import Optional

from sqlmodel import Session, select

from app.core.card_factory import create_card
from app.core.cross_review import (
    ReviewPolicy,
    ReviewPolicyRegistry,
    ReviewScope,
    build_review_request,
)
from app.hooks import Hook, TaskContext

logger = logging.getLogger(__name__)

# 摘要最大長度
_MAX_SUMMARY_LEN = 500


def _default_registry() -> ReviewPolicyRegistry:
    """建立預設的交叉審查策略（小茵↔小良互審）"""
    registry = ReviewPolicyRegistry()
    registry.register(ReviewPolicy(
        source_member_id="xiao-yin",
        reviewer_member_id="xiao-liang",
        scope=ReviewScope.ALL,
    ))
    registry.register(ReviewPolicy(
        source_member_id="xiao-liang",
        reviewer_member_id="xiao-yin",
        scope=ReviewScope.ALL,
    ))
    return registry


def _extract_diff_summary(output: str) -> str:
    """從任務輸出截取摘要作為 diff_summary"""
    if not output:
        return "(no output)"
    text = output.strip()
    if len(text) <= _MAX_SUMMARY_LEN:
        return text
    return text[:_MAX_SUMMARY_LEN] + "..."


def _find_review_list_id(project_id: int) -> Optional[int]:
    """查詢專案的「審查中」列表 ID"""
    from app.database import engine
    from app.models.core import StageList

    with Session(engine) as session:
        stage = session.exec(
            select(StageList).where(
                StageList.project_id == project_id,
                StageList.name == "審查中",
            )
        ).first()
        return stage.id if stage else None


class CrossReviewHook(Hook):
    """任務完成後自動派發交叉審查卡片"""

    def __init__(
        self,
        registry: ReviewPolicyRegistry | None = None,
    ) -> None:
        self._registry = registry or _default_registry()

    def on_complete(self, ctx: TaskContext) -> None:
        # 只在 worker 完成時觸發
        if ctx.status != "completed" or ctx.source != "worker":
            return

        if not ctx.member_slug:
            logger.debug("[CrossReview] No member_slug, skipping")
            return

        # 查找審查策略
        policy = self._registry.find_reviewer(
            ctx.member_slug, ReviewScope.CODE,
        )
        if policy is None:
            logger.debug(
                "[CrossReview] No review policy for %s", ctx.member_slug,
            )
            return

        # 找「審查中」列表
        review_list_id = _find_review_list_id(ctx.project_id)
        if review_list_id is None:
            logger.warning(
                "[CrossReview] 審查中 list not found for project %d",
                ctx.project_id,
            )
            return

        # 建立審查請求
        diff_summary = _extract_diff_summary(ctx.output)
        review_req = build_review_request(
            policy,
            card_id=ctx.card_id,
            card_title=ctx.card_title,
            diff_summary=diff_summary,
            changed_files=(),
        )

        # 建立審查卡片
        reviewer = review_req.reviewer_member_id
        title = f"review(cross): {ctx.card_title} — by {reviewer}"
        content = (
            f"## 交叉審查\n\n"
            f"- 原始卡片: #{ctx.card_id}\n"
            f"- 產出者: {ctx.member_slug}\n"
            f"- 審查者: {reviewer}\n\n"
            f"## 變更摘要\n\n{diff_summary}"
        )

        card = create_card(
            project_id=ctx.project_id,
            list_id=review_list_id,
            title=title,
            content=content,
            status="pending",
            tags=["CrossReview"],
        )

        if card:
            logger.info(
                "[CrossReview] Created review card #%d for %s → %s",
                card.id, ctx.member_slug, reviewer,
            )
        else:
            logger.warning(
                "[CrossReview] Failed to create review card for #%d",
                ctx.card_id,
            )
