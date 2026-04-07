"""PromptQueueManager — 任務提示佇列管理器。

支援多 session 的 prompt 佇列化，按優先級出隊（同優先級 FIFO）。

用法：
    from app.core.prompt_queue import PromptQueueManager
    from app.database import engine

    pq = PromptQueueManager(engine)
    queue_id = pq.enqueue("telegram:123:xiao-yin", "請分析這份報告", priority=2)
    entry = pq.dequeue("telegram:123:xiao-yin")  # 取出最高優先級的待處理項
    pq.mark_processed(queue_id)
"""
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Engine
from sqlmodel import Session, select

from app.models.core import PromptQueueEntry

logger = logging.getLogger(__name__)


class PromptQueueManager:
    """Prompt 佇列管理器，支援 SQLModel ORM + SQLAlchemy。"""

    def __init__(self, engine: Engine):
        self._engine = engine

    def enqueue(self, session_id: str, prompt: str, priority: int = 1) -> str:
        """將 prompt 加入佇列，回傳 queue_id。

        Args:
            session_id: chat_key 或任意 session 識別字串
            prompt: 要送出的提示文字
            priority: 優先級（數值越大越優先，預設 1）

        Returns:
            queue_id (UUID str)
        """
        queue_id = str(uuid.uuid4())
        entry = PromptQueueEntry(
            queue_id=queue_id,
            session_id=session_id,
            prompt_text=prompt,
            priority=priority,
            status="pending",
        )
        with Session(self._engine) as session:
            session.add(entry)
            session.commit()
        logger.debug(f"[PromptQueue] Enqueued {queue_id[:8]} for session={session_id} priority={priority}")
        return queue_id

    def dequeue(self, session_id: str) -> Optional[PromptQueueEntry]:
        """取出指定 session 優先級最高的待處理項，並將狀態改為 processing。

        同優先級依 created_at 升序（FIFO）。

        Args:
            session_id: 要查詢的 session 識別字串

        Returns:
            PromptQueueEntry（已脫離 session 的副本），無可用項目則回傳 None
        """
        with Session(self._engine) as session:
            stmt = (
                select(PromptQueueEntry)
                .where(PromptQueueEntry.session_id == session_id)
                .where(PromptQueueEntry.status == "pending")
                .order_by(
                    PromptQueueEntry.priority.desc(),   # type: ignore[union-attr]
                    PromptQueueEntry.created_at.asc(),  # type: ignore[union-attr]
                )
                .limit(1)
            )
            entry = session.exec(stmt).first()
            if not entry:
                return None

            # 更新狀態為 processing
            entry.status = "processing"
            entry.updated_at = datetime.now(timezone.utc)
            session.add(entry)
            session.commit()
            session.refresh(entry)

            # 建立脫離 session 的資料副本（避免 DetachedInstanceError）
            detached = PromptQueueEntry(
                id=entry.id,
                queue_id=entry.queue_id,
                session_id=entry.session_id,
                prompt_text=entry.prompt_text,
                priority=entry.priority,
                status=entry.status,
                created_at=entry.created_at,
                updated_at=entry.updated_at,
            )

        logger.debug(f"[PromptQueue] Dequeued {detached.queue_id[:8]} for session={session_id}")
        return detached

    def get_status(self, queue_id: str) -> Optional[str]:
        """查詢 queue_id 對應項目的狀態。

        Returns:
            status 字串，或 None（找不到時）
        """
        with Session(self._engine) as session:
            stmt = select(PromptQueueEntry).where(PromptQueueEntry.queue_id == queue_id)
            entry = session.exec(stmt).first()
            return entry.status if entry else None

    def mark_processed(self, queue_id: str) -> None:
        """將指定 queue_id 的狀態標記為 processed。"""
        with Session(self._engine) as session:
            stmt = select(PromptQueueEntry).where(PromptQueueEntry.queue_id == queue_id)
            entry = session.exec(stmt).first()
            if entry:
                entry.status = "processed"
                entry.updated_at = datetime.now(timezone.utc)
                session.add(entry)
                session.commit()
                logger.debug(f"[PromptQueue] Marked processed: {queue_id[:8]}")

    def mark_failed(self, queue_id: str) -> None:
        """將指定 queue_id 的狀態標記為 failed。"""
        with Session(self._engine) as session:
            stmt = select(PromptQueueEntry).where(PromptQueueEntry.queue_id == queue_id)
            entry = session.exec(stmt).first()
            if entry:
                entry.status = "failed"
                entry.updated_at = datetime.now(timezone.utc)
                session.add(entry)
                session.commit()
                logger.debug(f"[PromptQueue] Marked failed: {queue_id[:8]}")
