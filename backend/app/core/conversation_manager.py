"""
Conversation Manager — 統一的對話歷史管理模組。

提供可複用的對話歷史查詢介面，供 chat_handler、chat_workspace 等模組使用。

設計：
  - Message dataclass：統一的訊息格式（含 timestamp）
  - ConversationManager：依 chat_id 查詢，支援 source 參數擴充
  - 舊版函式（get_chat_history / format_history_block）保留供向下相容
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from sqlmodel import Session, select

from app.database import engine
from app.models.core import ChatMessage, ChatSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 統一訊息格式
# ---------------------------------------------------------------------------

@dataclass
class Message:
    """統一的對話訊息格式。"""
    role: str                        # "user" | "assistant"
    content: str                     # 訊息內容
    timestamp: datetime              # 訊息建立時間（UTC）
    session_id: Optional[int] = None  # 來源 ChatSession.id
    message_id: Optional[int] = None  # 來源 ChatMessage.id


# ---------------------------------------------------------------------------
# ConversationManager
# ---------------------------------------------------------------------------

class ConversationManager:
    """統一的對話歷史管理器。

    使用方式：
        manager = ConversationManager()
        history = manager.get_chat_history("LINE_USER_123")

    測試注入：
        manager = ConversationManager(db_session=test_session)
    """

    def __init__(self, db_session: Optional[Session] = None):
        """
        Args:
            db_session: 若提供，優先使用此 session（主要用於單元測試）；
                        若為 None，則每次查詢建立新 session（生產環境）。
        """
        self._db_session = db_session

    def get_chat_history(
        self,
        chat_id: str,
        source: str = "chatmessage",
        limit: int = 20,
    ) -> List[Message]:
        """取得指定 chat_id 的對話歷史。

        Args:
            chat_id:  頻道 ID（對應 ChatSession.chat_id）
            source:   資料來源，目前支援 "chatmessage"
            limit:    最多回傳幾筆（預設 20）

        Returns:
            List[Message]，按 created_at ASC 排序（最舊在前）

        Raises:
            ValueError: source 不支援時
        """
        if source == "chatmessage":
            return self._from_chatmessage(chat_id, limit)
        raise ValueError(f"不支援的 source：{source!r}，目前只支援 'chatmessage'")

    # ------------------------------------------------------------------
    # 私有：chatmessage 源
    # ------------------------------------------------------------------

    def _from_chatmessage(self, chat_id: str, limit: int) -> List[Message]:
        if self._db_session is not None:
            return self._query_chatmessage(self._db_session, chat_id, limit)
        with Session(engine) as db:
            return self._query_chatmessage(db, chat_id, limit)

    @staticmethod
    def _query_chatmessage(db: Session, chat_id: str, limit: int) -> List[Message]:
        stmt = (
            select(ChatMessage)
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .where(ChatSession.chat_id == chat_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        rows = db.exec(stmt).all()
        return [
            Message(
                role=row.role,
                content=row.content,
                timestamp=row.created_at,
                session_id=row.session_id,
                message_id=row.id,
            )
            for row in reversed(rows)  # 反轉為時間正序
        ]


# ---------------------------------------------------------------------------
# 向下相容：舊版函式介面（保留給既有呼叫者）
# ---------------------------------------------------------------------------

def get_chat_history(session_id: int, limit: int = 10) -> List[dict]:
    """取得指定 session 的近期對話歷史（舊版介面）。

    Args:
        session_id: ChatSession ID
        limit: 最多回傳幾筆（預設 10）

    Returns:
        [{"role": "user"|"assistant", "content": "..."}]，按 created_at ASC 排序
    """
    with Session(engine) as db:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        messages = db.exec(stmt).all()

    return [
        {"role": msg.role, "content": msg.content}
        for msg in reversed(messages)
    ]


def format_history_block(history: List[dict], max_content_len: int = 500) -> str:
    """將對話歷史格式化為可注入 prompt 的文字區塊。

    Args:
        history: get_chat_history() 的回傳值
        max_content_len: 每筆訊息的最大長度

    Returns:
        格式化的歷史區塊字串，空歷史回傳空字串
    """
    if not history:
        return ""

    lines = ["## 近期對話"]
    for msg in history:
        label = "user" if msg["role"] == "user" else "assistant"
        content = msg["content"]
        if len(content) > max_content_len:
            content = content[:max_content_len] + "..."
        lines.append(f"[{label}]: {content}")
    lines.append("")
    return "\n".join(lines)
