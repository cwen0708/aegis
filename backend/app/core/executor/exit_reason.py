"""
Exit Reason — Executor 退出原因純函式分類

對齊：self-healing-alphaclaw-ironclaw.md §1.5（Executor Exit Event Hook）
卡片：#13090 P0-SH-04 step 1 + step 2

step 1：classify_exit_reason() — status/exit_code → ExitReason。
step 2：enrich_result_with_exit_reason() — 把 worker.py 的 result dict 補上
        結構化 exit_reason 欄位，不動 watchdog / Hook / TaskContext。

與現有模組不重疊：
- `crash_loop_detector.py` / `failover_cooldown.py` 判斷「是否要重試」
- 本模組只分類「退出原因」，不決定後續動作

不變性：
- 無全域狀態、純輸入→輸出、不做 IO、不寫 log、不 mutate 輸入
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict


class ExitReason(str, Enum):
    normal = "normal"
    crashed = "crashed"
    killed = "killed"
    truncated = "truncated"
    quarantined = "quarantined"
    user_cancelled = "user_cancelled"


# POSIX 常見的 signal-like exit code（128 + signal number）
_SIGNAL_LIKE_EXIT_CODES = frozenset({137, 143})  # SIGKILL, SIGTERM


def _looks_killed(exit_code: int) -> bool:
    return exit_code < 0 or exit_code in _SIGNAL_LIKE_EXIT_CODES


def classify_exit_reason(
    status: str,
    exit_code: int,
    truncated: bool = False,
    quarantined: bool = False,
    user_cancelled: bool = False,
) -> ExitReason:
    """依照旗標與 exit_code 分類退出原因。

    優先順序（高到低）：
      1. user_cancelled → user_cancelled
      2. quarantined    → quarantined
      3. truncated      → truncated
      4. exit_code 負值或 signal-like → killed
      5. status == 'failed' → crashed
      6. 其他（completed + exit_code=0） → normal
    """
    if user_cancelled:
        return ExitReason.user_cancelled
    if quarantined:
        return ExitReason.quarantined
    if truncated:
        return ExitReason.truncated
    if _looks_killed(exit_code):
        return ExitReason.killed
    if status == "failed":
        return ExitReason.crashed
    return ExitReason.normal


# worker.py 的 status 語彙 → classify_exit_reason 的 status 語彙
_WORKER_STATUS_MAP = {
    "success": "completed",
    "error": "failed",
    "timeout": "failed",
}


def enrich_result_with_exit_reason(result: Dict[str, Any]) -> Dict[str, Any]:
    """把 worker.py 的 result dict 補上 `exit_reason` 欄位後回傳新 dict。

    worker.py 使用 "success" / "error" / "timeout" 三種 status 語彙，
    此處映射到 classify_exit_reason 要求的 "completed" / "failed"。

    不變性：
    - 回傳全新 dict，原輸入不被修改
    - 不做 IO、不寫 log
    - 若 `exit_code` 缺失（例如 exception 路徑），視為 0
    """
    status_worker = result.get("status", "")
    status_for_class = _WORKER_STATUS_MAP.get(status_worker, "failed")
    exit_code = result.get("exit_code", 0)
    reason = classify_exit_reason(status_for_class, exit_code)
    return {**result, "exit_reason": reason.value}
