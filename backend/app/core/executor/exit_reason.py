"""
Exit Reason — Executor 退出原因純函式分類

對齊：self-healing-alphaclaw-ironclaw.md §1.5（Executor Exit Event Hook）
卡片：#13090 P0-SH-04 step 1

本 step 範圍：純函式模組 + TDD 單測。
- 不改 Hook class（`app/hooks/__init__.py`）
- 不改 watchdog（`app/core/watchdog.py`）
- 不改 TaskContext status

與現有模組不重疊：
- `crash_loop_detector.py` / `failover_cooldown.py` 判斷「是否要重試」
- 本模組只分類「退出原因」，不決定後續動作

不變性：
- 無全域狀態、純輸入→輸出、不做 IO、不寫 log
"""
from __future__ import annotations

from enum import Enum


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
