"""
AI 對話處理器 — 處理非命令訊息，與 AI 角色對話
"""
import logging
from datetime import datetime, timezone
from typing import Optional, List
from sqlmodel import Session, select

from app.database import engine
from app.models.core import (
    BotUser, Member, MemberAccount, Account,
    ChatSession, ChatMessage
)
from app.core.member_profile import get_soul_content
from app.core.runner import run_ai_task
from .types import InboundMessage

logger = logging.getLogger(__name__)

# 限流設定
MAX_MESSAGE_LENGTH = 2000
MAX_HISTORY_MESSAGES = 10
MONTHLY_TOKEN_LIMIT_L1 = 100_000
MONTHLY_TOKEN_LIMIT_L2 = 1_000_000


async def handle_chat(msg: InboundMessage, bot_user: BotUser) -> Optional[str]:
    """
    處理自然語言對話

    Args:
        msg: 訊息
        bot_user: 用戶

    Returns:
        AI 回應文字，或 None
    """
    # 0. 基本檢查
    if not bot_user.is_active:
        return None

    if bot_user.level < 1:
        return "🔒 請先使用 /verify <邀請碼> 驗證身份後，才能與 AI 對話"

    # 1. 檢查訊息長度
    if len(msg.text) > MAX_MESSAGE_LENGTH:
        return f"⚠️ 訊息過長（最多 {MAX_MESSAGE_LENGTH} 字）"

    # 2. 取得 Member
    member = _get_member(bot_user.default_member_id)
    if not member:
        return "⚠️ 尚未設定 AI 角色，請聯繫管理員"

    # 3. 取得/建立 ChatSession
    session_obj = _get_or_create_session(bot_user.id, member.id, msg.chat_id)

    # 4. 檢查 token 配額
    token_limit = MONTHLY_TOKEN_LIMIT_L2 if bot_user.level >= 2 else MONTHLY_TOKEN_LIMIT_L1
    if session_obj.total_output_tokens > token_limit:
        return "📊 本月 token 配額已用盡，請聯繫管理員"

    # 5. 載入靈魂檔案
    soul = ""
    if member.slug:
        soul = get_soul_content(member.slug)

    # 6. 載入最近對話歷史
    history = _get_recent_messages(session_obj.id, limit=MAX_HISTORY_MESSAGES)

    # 7. 建構 prompt
    prompt = _build_chat_prompt(soul, member, history, msg.text)

    # 8. 取得 AI 帳號
    account = _get_primary_account(member.id)
    provider = account.provider if account else "claude"

    # 9. 呼叫 AI
    try:
        result = await run_ai_task(
            task_id=0,  # 非卡片任務
            project_path=".",
            prompt=prompt,
            phase="CHAT",
            forced_provider=provider,
            card_title=f"Chat with {bot_user.username or bot_user.platform_user_id}",
            project_name="Aegis Bot",
            member_id=member.id,
        )
    except Exception as e:
        logger.error(f"[Chat] AI task failed: {e}")
        return "❌ AI 回應失敗，請稍後再試"

    if result.get("status") != "success":
        return f"❌ AI 回應錯誤: {result.get('output', '未知錯誤')[:100]}"

    output = result.get("output", "")
    token_info = result.get("token_info", {})

    # 10. 儲存對話訊息
    _save_message(session_obj.id, "user", msg.text, token_info.get("input_tokens", 0), 0)
    _save_message(session_obj.id, "assistant", output, 0, token_info.get("output_tokens", 0))

    # 11. 更新 Session 統計
    _update_session_stats(session_obj.id, token_info)

    return output


def _get_member(member_id: Optional[int]) -> Optional[Member]:
    """取得 Member"""
    if not member_id:
        return None
    with Session(engine) as session:
        return session.get(Member, member_id)


def _get_or_create_session(bot_user_id: int, member_id: int, chat_id: str) -> ChatSession:
    """取得或建立 ChatSession"""
    with Session(engine) as session:
        stmt = select(ChatSession).where(
            ChatSession.bot_user_id == bot_user_id,
            ChatSession.member_id == member_id,
            ChatSession.chat_id == chat_id,
        )
        chat_session = session.exec(stmt).first()

        if chat_session:
            return chat_session

        # 建立新 Session
        chat_session = ChatSession(
            bot_user_id=bot_user_id,
            member_id=member_id,
            chat_id=chat_id,
        )
        session.add(chat_session)
        session.commit()
        session.refresh(chat_session)
        return chat_session


def _get_recent_messages(session_id: int, limit: int = 10) -> List[ChatMessage]:
    """取得最近的對話訊息"""
    with Session(engine) as session:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        messages = session.exec(stmt).all()
        # 反轉順序（從舊到新）
        return list(reversed(messages))


def _get_primary_account(member_id: int) -> Optional[Account]:
    """取得 Member 的主要帳號"""
    with Session(engine) as session:
        stmt = (
            select(MemberAccount)
            .where(MemberAccount.member_id == member_id)
            .order_by(MemberAccount.priority)
        )
        ma = session.exec(stmt).first()
        if ma:
            return session.get(Account, ma.account_id)
    return None


def _build_chat_prompt(soul: str, member: Member, history: List[ChatMessage], user_message: str) -> str:
    """組合完整 prompt = 靈魂 + 歷史 + 新訊息"""
    lines = []

    # 靈魂人設（放最前面，定義角色）
    if soul:
        lines.append(soul.strip())
        lines.append("")
    else:
        # 沒有 soul.md，用基本資訊
        lines.append(f"你是 {member.name}，{member.role}。")
        if member.description:
            lines.append(member.description)
        lines.append("")

    # 對話歷史
    if history:
        lines.append("## 對話歷史")
        for msg in history:
            role = "用戶" if msg.role == "user" else "你"
            # 截斷過長的歷史訊息
            content = msg.content[:500] + "..." if len(msg.content) > 500 else msg.content
            lines.append(f"{role}：{content}")
        lines.append("")

    # 當前訊息
    lines.append(f"用戶：{user_message}")
    lines.append("")
    lines.append("請以你的角色身份回應（簡潔、友善、專業）：")

    return "\n".join(lines)


def _save_message(session_id: int, role: str, content: str, input_tokens: int, output_tokens: int):
    """儲存對話訊息"""
    with Session(engine) as session:
        msg = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        session.add(msg)
        session.commit()


def _update_session_stats(session_id: int, token_info: dict):
    """更新 Session 統計"""
    with Session(engine) as session:
        chat_session = session.get(ChatSession, session_id)
        if chat_session:
            chat_session.total_input_tokens += token_info.get("input_tokens", 0)
            chat_session.total_output_tokens += token_info.get("output_tokens", 0)
            chat_session.message_count += 2  # user + assistant
            chat_session.last_message_at = datetime.now(timezone.utc)
            session.commit()
