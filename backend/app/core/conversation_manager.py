"""
Conversation Manager — 統一的對話歷史管理模組。

提供可複用的對話歷史查詢介面，供 chat_handler、chat_workspace 等模組使用。
"""
import logging
from typing import List

from sqlmodel import Session, select

from app.database import engine
from app.models.core import ChatMessage

logger = logging.getLogger(__name__)


def get_chat_history(session_id: int, limit: int = 10) -> List[dict]:
    """取得指定 session 的近期對話歷史。

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

    # 反轉為時間正序（最舊在前）
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
