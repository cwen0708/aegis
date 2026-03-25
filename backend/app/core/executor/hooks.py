"""
Task Lifecycle Hooks — 前中後處理的解耦介面

每個 Hook 實作 on_complete()，worker 只負責依序呼叫，不碰業務邏輯。
DURING 階段已由 StreamEmitter + StreamTarget 處理，不在此範圍。

使用方式：
    hooks = collect_hooks(card_type, member_slug, ...)
    for hook in hooks:
        hook.on_complete(ctx)
"""
import logging
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass
class TaskContext:
    """任務上下文 — 一次建好，所有 Hook 共用"""
    card_id: int
    card_title: str
    project_id: int
    project_name: str
    project_path: str
    member_id: Optional[int]
    member_slug: str
    list_id: int

    # 結果
    status: str = ""           # "completed" | "failed"
    output: str = ""
    provider: str = ""
    exit_code: int = 0
    token_info: dict = field(default_factory=dict)

    # 卡片資料
    card_content: str = ""     # 原始卡片 content
    workspace_dir: str = ""

    # Chat 專用
    is_chat: bool = False
    chat_id: str = ""

    # Cron 專用
    cron_job_id: Optional[int] = None


@runtime_checkable
class TaskHook(Protocol):
    """任務完成後的 Hook 介面"""
    def on_complete(self, ctx: TaskContext) -> None: ...


class BroadcastHook:
    """廣播任務完成事件到 WebSocket"""

    def on_complete(self, ctx: TaskContext) -> None:
        from worker import broadcast_event
        event = "task_completed" if ctx.status == "completed" else "task_failed"
        broadcast_event(event, {"card_id": ctx.card_id, "status": ctx.status})


class DialogueHook:
    """從 AI 輸出提取 AVG 對話並儲存"""

    def on_complete(self, ctx: TaskContext) -> None:
        if not ctx.member_id:
            return
        import re
        match = re.search(r'<!-- dialogue: (.+?) -->', ctx.output)
        if not match:
            return
        try:
            from worker import _save_member_dialogue
            _save_member_dialogue(
                ctx.member_id, ctx.card_id, ctx.card_title, ctx.project_name,
                "task_complete" if ctx.status == "completed" else "task_failed",
                match.group(1).strip(),
            )
        except Exception as e:
            logger.warning(f"[DialogueHook] {e}")


class MemoryHook:
    """寫入成員短期記憶"""

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


class OneStackHook:
    """OneStack 整合 — 任務回報 + 文件分析結果"""

    def on_complete(self, ctx: TaskContext) -> None:
        self._report_completion(ctx)
        self._report_document(ctx)

    def _report_completion(self, ctx: TaskContext) -> None:
        try:
            from app.core.onestack_connector import connector
            if not connector.enabled:
                return
            import asyncio
            asyncio.run(connector.report_task_completion(
                card_id=ctx.card_id, output=ctx.output,
                status=ctx.status,
                duration_ms=ctx.token_info.get("duration_ms", 0),
                cost_usd=ctx.token_info.get("total_cost_usd", 0),
            ))
        except Exception as e:
            logger.debug(f"[OneStackHook] Report: {e}")

    def _report_document(self, ctx: TaskContext) -> None:
        import re
        doc_match = re.search(r'<!-- document_id: (.+?) -->', ctx.card_content)
        if not doc_match:
            return
        doc_id = doc_match.group(1)
        try:
            from app.core.onestack_connector import connector
            if not connector.enabled:
                return
            import asyncio
            doc_output = ctx.token_info.get("result_text", "") or ctx.output[:3000]
            doc_evt = "result" if ctx.status == "completed" else "error"
            json_match = re.search(r'```json\s*\n([\s\S]*?)\n```', doc_output)
            if json_match:
                doc_output = json_match.group(1).strip()
            asyncio.run(connector.stream_event(
                card_id=ctx.card_id, event_type=doc_evt, content=doc_output[:5000],
                member_slug=ctx.member_slug,
                metadata={"document_id": doc_id, "type": "file_result"},
                chat_id=f"doc:{doc_id}",
            ))
            logger.info(f"[OneStackHook] Document {doc_id[:8]}... sent")
        except Exception as e:
            logger.debug(f"[OneStackHook] Document: {e}")


class CleanupHook:
    """清理工作區"""

    def on_complete(self, ctx: TaskContext) -> None:
        if ctx.workspace_dir:
            from app.core.task_workspace import cleanup_workspace
            cleanup_workspace(ctx.card_id)


def collect_post_hooks() -> list[TaskHook]:
    """收集所有 POST Hook（固定順序）"""
    return [
        BroadcastHook(),
        DialogueHook(),
        OneStackHook(),
        MemoryHook(),
        CleanupHook(),   # 清理永遠最後
    ]


def run_post_hooks(ctx: TaskContext, hooks: list[TaskHook] = None) -> None:
    """依序執行所有 POST Hook，任一失敗不影響後續"""
    if hooks is None:
        hooks = collect_post_hooks()
    for hook in hooks:
        try:
            hook.on_complete(ctx)
        except Exception as e:
            logger.warning(f"[Hook] {type(hook).__name__} failed: {e}")
