"""SprintContractHook — 任務完成時驗證 acceptance_criteria 並記錄日誌"""
import re
import logging
from app.hooks import Hook, TaskContext

logger = logging.getLogger(__name__)

# 從 frontmatter 解析 acceptance_criteria
_AC_RE = re.compile(r'^acceptance_criteria:\s*["\']?(.+?)["\']?\s*$', re.MULTILINE)


def _extract_acceptance_criteria(card_content: str) -> str:
    """從卡片內容（含 frontmatter）中提取 acceptance_criteria。"""
    match = _AC_RE.search(card_content)
    return match.group(1).strip() if match else ""


class SprintContractHook(Hook):
    """任務完成後檢查 acceptance_criteria 並記錄結果。

    目前僅做日誌記錄，不阻擋執行結果。
    """

    def on_complete(self, ctx: TaskContext) -> None:
        criteria = _extract_acceptance_criteria(ctx.card_content)
        if not criteria:
            return

        if ctx.status == "completed":
            logger.info(
                "[SprintContract] Card %d completed with acceptance_criteria: %s",
                ctx.card_id, criteria,
            )
        elif ctx.status == "failed":
            logger.warning(
                "[SprintContract] Card %d failed — acceptance_criteria not met: %s",
                ctx.card_id, criteria,
            )
