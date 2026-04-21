"""Zombie Agent Scanner — 純函式掃描模組（Step 1 最小可執行版）。

偵測 DB 中狀態為 running 但實際 worker 已失聯的「zombie 卡片」：
- worker_pid 為空（pid_missing）
- worker_pid 對應的 process 已死（pid_dead）
- 執行時間超過門檻（timeout）

本步驟僅提供純函式與 PID 存活檢查；worker_pid 欄位持久化、排程與處置動作
（Telegram 通知 / 自動標記失敗）留到後續步驟。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

__all__ = [
    "ZombieCandidate",
    "ZombieRecord",
    "list_zombie_cards",
]


@dataclass(frozen=True)
class ZombieCandidate:
    """候選卡片（從 DB 撈出來的 running 卡片投影，UTC 時區）。"""

    card_id: int
    worker_pid: int | None
    started_at: datetime


@dataclass(frozen=True)
class ZombieRecord:
    """Zombie 偵測結果。reason ∈ {"pid_missing", "pid_dead", "timeout"}。"""

    card_id: int
    worker_pid: int | None
    reason: str


def _pid_alive(pid: int) -> bool:
    """用 signal 0 探測 PID 是否存活。

    - ProcessLookupError：process 不存在 → dead。
    - PermissionError：存在但無權限 signal → 視為 alive。
    - 其他 OSError：保守視為 alive（避免誤殺）。
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def list_zombie_cards(
    candidates: list[ZombieCandidate],
    now: datetime,
    max_hours: float = 2.0,
    pid_checker: Callable[[int], bool] = _pid_alive,
) -> list[ZombieRecord]:
    """對候選清單套用 zombie 判斷規則，回傳新的 ZombieRecord 列表。

    判斷順序（命中即輸出，不 mutate 輸入）：
        1. worker_pid is None → pid_missing
        2. not pid_checker(worker_pid) → pid_dead
        3. now - started_at > max_hours → timeout
        4. 其他 → 非 zombie，跳過

    Args:
        candidates: 候選卡片列表（不被修改）
        now: 當下時間（UTC）
        max_hours: 執行時間上限（小時）
        pid_checker: 可注入的 PID 存活檢查函式

    Returns:
        新的 list[ZombieRecord]，保持輸入順序。
    """
    timeout_delta = timedelta(hours=max_hours)
    records: list[ZombieRecord] = []

    for candidate in candidates:
        reason = _classify(candidate, now, timeout_delta, pid_checker)
        if reason is None:
            continue
        records.append(
            ZombieRecord(
                card_id=candidate.card_id,
                worker_pid=candidate.worker_pid,
                reason=reason,
            )
        )

    return records


def _classify(
    candidate: ZombieCandidate,
    now: datetime,
    timeout_delta: timedelta,
    pid_checker: Callable[[int], bool],
) -> str | None:
    if candidate.worker_pid is None:
        return "pid_missing"
    if not pid_checker(candidate.worker_pid):
        return "pid_dead"
    if now - candidate.started_at > timeout_delta:
        return "timeout"
    return None
