"""CleanupHook — 清理工作區（永遠最後執行）"""
import logging
from app.hooks import TaskContext

logger = logging.getLogger(__name__)


class CleanupHook:
    def on_complete(self, ctx: TaskContext) -> None:
        if ctx.workspace_dir:
            from app.core.task_workspace import cleanup_workspace
            cleanup_workspace(ctx.card_id)
