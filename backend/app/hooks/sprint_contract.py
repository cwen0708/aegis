"""SprintContractHook — 任務完成時驗證 acceptance_criteria 並記錄日誌"""
import logging
from app.hooks import Hook, TaskContext

logger = logging.getLogger(__name__)


class SprintContractHook(Hook):
    """任務完成後檢查 acceptance_criteria 並記錄結果。

    目前僅做日誌記錄，不阻擋執行結果。
    """

    def on_complete(self, ctx: TaskContext) -> None:
        if not ctx.acceptance_criteria:
            return

        if ctx.status == "completed":
            logger.info(
                "[SprintContract] Card %d completed with acceptance_criteria: %s",
                ctx.card_id, ctx.acceptance_criteria,
            )
        elif ctx.status == "failed":
            logger.warning(
                "[SprintContract] Card %d failed — acceptance_criteria not met: %s",
                ctx.card_id, ctx.acceptance_criteria,
            )
