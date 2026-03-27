"""閒時偵測模組 — 統一判斷系統是否閒置，供排程、資源管理等模組使用。

從 cron_poller.py 提取並增強，新增 ChatSession 活躍度與 ProcessPool 檢查。
"""
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlmodel import Session, select

from app.models.core import CardIndex, ChatSession
from app.core.telemetry import get_system_metrics

logger = logging.getLogger(__name__)

# 閒時偵測 CPU 門檻
IDLE_CPU_THRESHOLD = 80.0

# ChatSession 活躍判定：最近 N 分鐘內有訊息視為活躍
CHAT_ACTIVE_MINUTES = 5

# 模組級狀態：追蹤閒置起始時間
_idle_since: Optional[float] = None


@dataclass
class IdleStatus:
    """系統閒置狀態"""
    is_idle: bool
    idle_since: Optional[float] = None    # Unix timestamp，首次進入閒置的時間
    idle_seconds: float = 0.0             # 已閒置秒數
    busy_reasons: list[str] = field(default_factory=list)


def get_idle_status(session: Session) -> IdleStatus:
    """統一入口：檢查系統各信號源，回傳 IdleStatus。"""
    global _idle_since

    busy_reasons: list[str] = []

    # 1. CardIndex running/pending 檢查
    running = session.exec(
        select(CardIndex).where(CardIndex.status == "running")
    ).first()
    if running:
        busy_reasons.append(f"running card: {running.title}")

    pending = session.exec(
        select(CardIndex).where(CardIndex.status == "pending")
    ).first()
    if pending:
        busy_reasons.append(f"pending card: {pending.title}")

    # 2. CPU 使用率檢查
    metrics = get_system_metrics()
    if metrics["cpu_percent"] >= IDLE_CPU_THRESHOLD:
        busy_reasons.append(f"CPU {metrics['cpu_percent']:.1f}% >= {IDLE_CPU_THRESHOLD}%")

    # 3. ChatSession 活躍度（最近 5 分鐘內有新訊息）
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=CHAT_ACTIVE_MINUTES)
    active_chat = session.exec(
        select(ChatSession).where(ChatSession.last_message_at >= cutoff)
    ).first()
    if active_chat:
        busy_reasons.append(f"active chat: {active_chat.chat_id}")

    # 4. ProcessPool 活躍數量
    try:
        from app.core.session_pool import process_pool
        pool_count = process_pool.active_count()
        if pool_count > 0:
            busy_reasons.append(f"process pool: {pool_count} active")
    except Exception:
        pass  # 模組未初始化時不阻斷

    # 判定與追蹤
    is_idle = len(busy_reasons) == 0
    now = time.time()

    if is_idle:
        if _idle_since is None:
            _idle_since = now
        return IdleStatus(
            is_idle=True,
            idle_since=_idle_since,
            idle_seconds=now - _idle_since,
        )
    else:
        _idle_since = None
        return IdleStatus(
            is_idle=False,
            busy_reasons=busy_reasons,
        )


def is_system_idle(session: Session) -> bool:
    """相容介面：回傳 bool，內部呼叫 get_idle_status。"""
    return get_idle_status(session).is_idle


def reset_idle_tracking():
    """重置閒置追蹤狀態（供測試用）。"""
    global _idle_since
    _idle_since = None
