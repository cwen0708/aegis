"""
Chat Memory Export — 定時將用戶對話匯出到成員短期記憶

每小時執行一次，把今天有新訊息的 ChatSession 匯出為
members/{slug}/memory/short-term/chat-{date}-{username}.md

純格式化，不用 AI 摘要（省 token）。
"""
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from sqlmodel import Session, select

from app.database import engine
from app.models.core import ChatSession, ChatMessage, BotUser, Member
from app.core.memory_manager import _get_member_short_term_dir

logger = logging.getLogger(__name__)

# 追蹤上次匯出時間（避免重複匯出）
_last_export_time: datetime | None = None


def export_recent_chats(hours: int = 2) -> int:
    """匯出最近 N 小時內有新訊息的對話到成員記憶。

    Returns: 匯出的 session 數量
    """
    global _last_export_time

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    # 如果上次匯出時間更近，就用上次的時間（避免重複）
    if _last_export_time and _last_export_time > cutoff:
        cutoff = _last_export_time

    exported = 0

    with Session(engine) as s:
        # 找有新訊息的 session
        sessions = s.exec(
            select(ChatSession).where(
                ChatSession.last_message_at != None,  # noqa: E711
                ChatSession.last_message_at > cutoff,
            )
        ).all()

        for chat_session in sessions:
            try:
                exported += _export_session(s, chat_session, cutoff)
            except Exception as e:
                logger.warning(f"[ChatExport] Failed session {chat_session.id}: {e}")

    _last_export_time = datetime.now(timezone.utc)

    if exported:
        logger.info(f"[ChatExport] Exported {exported} sessions")
    return exported


def _export_session(s: Session, chat_session: ChatSession, since: datetime) -> int:
    """匯出單一 ChatSession 的近期訊息。"""
    # 查成員
    member = s.get(Member, chat_session.member_id)
    if not member or not member.slug:
        return 0

    # 查用戶
    bot_user = s.get(BotUser, chat_session.bot_user_id)
    username = bot_user.username or bot_user.platform_user_id if bot_user else "unknown"
    platform = bot_user.platform if bot_user else "unknown"

    # 查近期訊息
    messages = s.exec(
        select(ChatMessage)
        .where(
            ChatMessage.session_id == chat_session.id,
            ChatMessage.created_at > since,
        )
        .order_by(ChatMessage.created_at)
    ).all()

    if not messages:
        return 0

    # 格式化
    tz = timezone(timedelta(hours=8))
    lines = [
        f"# 對話紀錄：{username}（{platform}）",
        f"時間：{messages[0].created_at.astimezone(tz).strftime('%Y-%m-%d %H:%M')} ~ {messages[-1].created_at.astimezone(tz).strftime('%H:%M')}",
        f"訊息數：{len(messages)}",
        "",
    ]

    for msg in messages:
        time_str = msg.created_at.astimezone(tz).strftime("%H:%M")
        role_label = username if msg.role == "user" else member.name
        # 截斷過長訊息（避免記憶檔案太大）
        content = msg.content[:500]
        if len(msg.content) > 500:
            content += "...（截斷）"
        lines.append(f"**[{time_str}] {role_label}**：{content}")
        lines.append("")

    # 寫入成員記憶
    now = datetime.now(timezone.utc)
    safe_user = "".join(c if c.isalnum() or c in "-_" else "_" for c in username)
    filename = f"chat-{now.strftime('%Y-%m-%d')}-{safe_user}.md"
    memory_dir = _get_member_short_term_dir(member.slug)
    file_path = memory_dir / filename

    content = "\n".join(lines)

    # 如果今天已有同用戶的匯出，追加而非覆蓋
    if file_path.exists():
        existing = file_path.read_text(encoding="utf-8")
        content = existing + "\n---\n\n" + content

    file_path.write_text(content, encoding="utf-8")
    logger.info(f"[ChatExport] {member.slug} ← {username}: {len(messages)} msgs → {filename}")
    return 1
