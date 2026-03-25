"""MemoryHook — 寫入成員短期記憶"""
import logging
from app.hooks import TaskContext

logger = logging.getLogger(__name__)


class MemoryHook:
    def on_complete(self, ctx: TaskContext) -> None:
        if not ctx.member_slug:
            return
        try:
            from app.core.memory_manager import write_member_short_term_memory
            write_member_short_term_memory(
                ctx.member_slug,
                f"## 任務: {ctx.card_title}\n專案: {ctx.project_name}\n結果: {ctx.status}\n\n{ctx.output[:500]}"
            )
        except Exception as e:
            logger.warning(f"[MemoryHook] {e}")
