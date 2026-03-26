"""
Task Lifecycle Hooks — DURING + POST 統一介面

每個 Hook 可選擇實作：
- on_stream(event): DURING — 每行串流輸出都呼叫（高頻）
- on_complete(ctx): POST — 任務完成後呼叫一次

新增 Hook 只需：
1. 在 app/hooks/ 下新增 xxx.py
2. 在 collect_hooks() 註冊

使用方式：
    hooks = collect_hooks("worker")

    # DURING（PTY read loop 每行）
    for hook in hooks:
        hook.on_stream(event)

    # POST（任務完成）
    for hook in hooks:
        hook.on_complete(ctx)
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

from app.core.executor.emitter import StreamEvent, parse_stream_event  # noqa: F401 — 唯一定義點

logger = logging.getLogger(__name__)


@dataclass
class TaskContext:
    """任務上下文（POST 階段）"""
    card_id: int = 0
    card_title: str = ""
    project_id: int = 0
    project_name: str = ""
    project_path: str = ""
    member_id: Optional[int] = None
    member_slug: str = ""
    list_id: int = 0

    # 結果
    status: str = ""           # "completed" | "failed"
    output: str = ""
    provider: str = ""
    exit_code: int = 0
    token_info: dict = field(default_factory=dict)

    # 卡片資料
    card_content: str = ""
    workspace_dir: str = ""

    # Chat 專用
    is_chat: bool = False
    chat_id: str = ""

    # Cron 專用
    cron_job_id: Optional[int] = None

    # 來源路徑
    source: str = ""           # "worker" | "chat" | "meeting" | "onestack"


class Hook:
    """Hook 基底類 — 預設空實作，子類覆寫需要的方法即可"""

    def on_stream(self, event: StreamEvent) -> None:
        """DURING — 每行串流輸出（預設不做事）"""
        pass

    def on_complete(self, ctx: TaskContext) -> None:
        """POST — 任務完成後（預設不做事）"""
        pass


# ── 向後相容 ──
TaskHook = Hook


def collect_hooks(source: str = "worker") -> list[Hook]:
    """收集適用於指定來源的 Hook。"""
    from app.hooks.broadcast import BroadcastHook
    from app.hooks.dialogue import DialogueHook
    from app.hooks.onestack import OneStackHook
    from app.hooks.memory import MemoryHook
    from app.hooks.cleanup import CleanupHook
    from app.hooks.websocket import WebSocketHook
    from app.hooks.platform import PlatformHook
    from app.hooks.media import MediaHook

    if source == "worker":
        return [
            WebSocketHook(),    # DURING: Kanban log
            OneStackHook(),     # DURING: aegis_stream + POST: 任務回報
            BroadcastHook(),    # POST: task_completed 事件
            DialogueHook(),     # POST: AVG 對話
            MediaHook(),        # POST: send_file 標記 → 頻道發送
            MemoryHook(),       # POST: 成員記憶
            CleanupHook(),      # POST: 清理（永遠最後）
        ]
    elif source == "chat":
        return [
            # PlatformHook 由 chat_handler 按需 insert（需要 platform/chat_id/placeholder_id）
            MediaHook(),        # POST: send_file 標記 → 頻道發送
            MemoryHook(),       # POST: 成員記憶
        ]
    elif source == "onestack":
        return [
            OneStackHook(),     # DURING: aegis_stream
            MemoryHook(),       # POST: 成員記憶
        ]
    elif source == "meeting":
        return [
            MemoryHook(),       # POST: 成員記憶
        ]
    else:
        return [MemoryHook()]


def run_on_stream(hooks: list[Hook], event: StreamEvent) -> None:
    """DURING — 分發串流事件給所有 Hook"""
    for hook in hooks:
        try:
            hook.on_stream(event)
        except Exception as e:
            logger.warning(f"[Hook] {type(hook).__name__}.on_stream failed: {e}")


def run_hooks(ctx: TaskContext, hooks: list[Hook] = None) -> None:
    """POST — 依序執行所有 Hook 的 on_complete"""
    if hooks is None:
        hooks = collect_hooks(ctx.source or "worker")
    for hook in hooks:
        try:
            hook.on_complete(ctx)
        except Exception as e:
            logger.warning(f"[Hook] {type(hook).__name__}.on_complete failed: {e}")
