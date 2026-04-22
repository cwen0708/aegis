"""向後相容 — 已搬遷至 app/hooks/，此檔案僅 re-export。"""
from app.hooks import (  # noqa: F401
    Hook, TaskHook, StreamEvent, TaskContext,
    collect_hooks, run_hooks, run_on_stream, run_on_exit,
)
from app.hooks import run_hooks as run_post_hooks  # noqa: F401 — 舊名別名
