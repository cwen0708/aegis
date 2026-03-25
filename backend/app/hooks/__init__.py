"""
Task Lifecycle Hooks — 前中後處理的解耦介面

每個 Hook 獨立一個檔案，所有路徑（Worker/Chat/Meeting）共用。
新增 Hook 只需：
1. 在 app/hooks/ 下新增 xxx.py，實作 on_complete(ctx)
2. 在 HOOK_REGISTRY 加一行

DURING 階段已由 StreamEmitter + StreamTarget 處理，不在此範圍。
"""
import logging
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass
class TaskContext:
    """任務上下文 — 一次建好，所有 Hook 共用"""
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


@runtime_checkable
class TaskHook(Protocol):
    """Hook 介面 — 實作 on_complete 即可"""
    def on_complete(self, ctx: TaskContext) -> None: ...


# ── Hook 註冊表（按順序執行，cleanup 永遠最後）──

def collect_hooks() -> list[TaskHook]:
    """收集所有已註冊的 Hook"""
    from app.hooks.broadcast import BroadcastHook
    from app.hooks.dialogue import DialogueHook
    from app.hooks.onestack import OneStackHook
    from app.hooks.memory import MemoryHook
    from app.hooks.cleanup import CleanupHook

    return [
        BroadcastHook(),
        DialogueHook(),
        OneStackHook(),
        MemoryHook(),
        CleanupHook(),   # 清理永遠最後
    ]


def run_hooks(ctx: TaskContext, hooks: list[TaskHook] = None) -> None:
    """依序執行所有 Hook，任一失敗不影響後續"""
    if hooks is None:
        hooks = collect_hooks()
    for hook in hooks:
        try:
            hook.on_complete(ctx)
        except Exception as e:
            logger.warning(f"[Hook] {type(hook).__name__} failed: {e}")
