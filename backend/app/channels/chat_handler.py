"""
AI 對話處理器 — 處理非命令訊息，與 AI 角色對話
"""
import re
import time
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, List
from sqlmodel import Session, select

from app.database import engine
from app.models.core import (
    BotUser, Member, MemberAccount, Account,
    ChatSession, ChatMessage, PersonProject, Project, StageList
)
from app.core.card_file import CardData, write_card, card_file_path
from app.core.card_index import sync_card_to_index, next_card_id
from app.core.member_profile import get_soul_content, list_skills, get_skill_content
from app.core.runner import run_ai_task
from .types import InboundMessage
from .bot_user import get_user_projects, get_user_context, get_default_project, get_user_extra

logger = logging.getLogger(__name__)

# 限流設定
MAX_MESSAGE_LENGTH = 2000
MAX_HISTORY_MESSAGES = 25
MONTHLY_TOKEN_LIMIT_L1 = 100_000
MONTHLY_TOKEN_LIMIT_L2 = 1_000_000


async def handle_chat(msg: InboundMessage, bot_user: BotUser, placeholder_message_id: str = "") -> Optional[str]:
    """
    處理自然語言對話

    Args:
        msg: 訊息
        bot_user: 用戶
        placeholder_message_id: 佔位訊息 ID（用於即時回應模式）

    Returns:
        AI 回應文字，或 None
    """
    # 0. 基本檢查
    if not bot_user.is_active:
        return None

    if bot_user.level < 1:
        return "🔒 請先使用 /verify <邀請碼> 驗證身份後，才能與 AI 對話"

    # 0.5 存取期限檢查
    if bot_user.access_expires_at:
        from datetime import timezone
        if bot_user.access_expires_at <= datetime.now(timezone.utc):
            expire_date = bot_user.access_expires_at.strftime("%Y-%m-%d")
            return f"🔒 您的存取權限已於 {expire_date} 過期，請聯繫管理員延期"

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

    # 5.5 載入技能檔案（shared + 成員專屬）
    skills_content = ""
    skill_texts = []

    # 先載入 shared skills
    from app.core.task_workspace import _INSTALL_ROOT
    shared_skills_dir = _INSTALL_ROOT / ".aegis" / "shared" / "skills"
    if shared_skills_dir.exists():
        for md_file in sorted(shared_skills_dir.glob("*.md")):
            try:
                skill_texts.append(md_file.read_text(encoding="utf-8"))
            except Exception:
                pass

    # 再載入成員專屬 skills（可覆蓋 shared）
    if member.slug:
        skills_list = list_skills(member.slug)
        if skills_list:
            for skill in skills_list:
                content = get_skill_content(member.slug, skill["name"])
                if content:
                    skill_texts.append(content)

    if skill_texts:
        skills_content = "\n\n---\n\n".join(skill_texts)

    # 6. 載入最近對話歷史
    history = _get_recent_messages(session_obj.id, limit=MAX_HISTORY_MESSAGES)

    # 7. 取得用戶可存取的專案和身份上下文
    accessible_projects = get_user_projects(bot_user.id)
    user_context = None
    default_project = get_default_project(bot_user.id)
    if default_project:
        user_context = get_user_context(bot_user.id, default_project.id)

    # 7.5 多模態：如果有附帶媒體，在訊息中加入檔案路徑
    user_message = msg.text or ""
    if msg.media_type and msg.media_path:
        media_hint = f"\n\n[用戶傳送了{_media_type_label(msg.media_type)}，檔案路徑: {msg.media_path}]"
        if msg.caption:
            media_hint += f"\n[附帶說明: {msg.caption}]"
        user_message = (user_message + media_hint).strip()

    # 7.6 取得用戶額外資料（供 AI/MCP 使用）
    user_extra = get_user_extra(bot_user.id)

    # 8. 建構 prompt（含用戶身份和專案範圍）
    prompt = _build_chat_prompt(
        soul=soul,
        skills=skills_content,
        member=member,
        history=history,
        user_message=user_message,
        user_context=user_context,
        accessible_projects=accessible_projects,
        user_level=bot_user.level,
        chat_id=msg.chat_id,
        platform=bot_user.platform,
        user_extra=user_extra,
        placeholder_message_id=placeholder_message_id,
    )

    # 9. 取得 AI 帳號和模型
    account, model = _get_primary_account(member.id)
    provider = account.provider if account else "claude"

    # 取得帳號認證資訊
    auth_info = {}
    if account:
        auth_info = {
            'auth_type': getattr(account, 'auth_type', 'cli'),
            'oauth_token': getattr(account, 'oauth_token', '') or '',
            'api_key': getattr(account, 'api_key', '') or '',
        }

    # Bot 聊天預設用快速模型（成員有設定則覆蓋）
    if not model:
        if provider == "gemini":
            model = "gemini-flash"
        elif provider == "claude":
            model = "haiku"

    # 9.5 從 extra_json 建構 MCP 用的環境變數（如 AD 帳密）
    mcp_extra_env: dict[str, str] = {}
    if user_extra and user_extra.get("ad_user") and user_extra.get("ad_pass"):
        mcp_extra_env["SYNO_AD_USERNAME"] = user_extra["ad_user"]
        mcp_extra_env["SYNO_AD_PASSWORD"] = user_extra["ad_pass"]
    else:
        # 硬擋：沒有 AD 帳密就封鎖 NAS MCP
        mcp_extra_env["NAS_AUTH_BLOCKED"] = "1"

    # 10. 即時回饋：on_stream callback 編輯 placeholder
    _last_edit = [0.0, ""]  # [timestamp, last_text]

    async def _edit_placeholder(text: str):
        if not placeholder_message_id or text == _last_edit[1]:
            return
        now = time.time()
        if now - _last_edit[0] < 3.0:
            return
        _last_edit[0] = now
        _last_edit[1] = text
        try:
            from app.core.http_client import InternalAPIAsync
            await InternalAPIAsync.channel_send(msg.platform, msg.chat_id, text, placeholder_message_id)
        except Exception:
            pass

    _loop = asyncio.get_event_loop()

    def on_stream(raw_line: str):
        from app.api.runner import _parse_tool_call
        parsed = _parse_tool_call(raw_line)
        if parsed and placeholder_message_id:
            _, summary = parsed
            asyncio.run_coroutine_threadsafe(_edit_placeholder(f"🤔 {summary}"), _loop)

    # 11. 查詢 Session Pool（延續對話）
    from app.core.session_pool import session_pool
    chat_session_key = f"{bot_user.platform}:{msg.chat_id}:{member.slug}"
    resume_id, _is_new = session_pool.get_or_create(chat_session_key)

    # 12. 呼叫 AI（帶 on_stream + session resume）
    try:
        result = await run_ai_task(
            task_id=0,
            project_path=".",
            prompt=prompt,
            phase="CHAT",
            forced_provider=provider,
            card_title=f"Chat with {bot_user.username or bot_user.platform_user_id}",
            project_name="Aegis Bot",
            member_id=member.id,
            model_override=model,
            auth_info=auth_info,
            extra_env=mcp_extra_env or None,
            on_stream=on_stream if placeholder_message_id else None,
            resume_session_id=resume_id,
        )
    except Exception as e:
        logger.error(f"[Chat] AI task failed: {e}")
        return "❌ AI 回應失敗，請稍後再試"

    # 13. 註冊 session（供下次 resume）
    new_session_id = result.get("session_id")
    if new_session_id:
        session_pool.register(chat_session_key, new_session_id)

    if result.get("status") != "success":
        return f"❌ AI 回應錯誤: {result.get('output', '未知錯誤')[:100]}"

    output = result.get("output", "")
    token_info = result.get("token_info", {})

    # 12. 檢查是否要建立任務卡片
    task_match = re.search(r'\[CREATE_TASK:(\d+):([^:]+):([^\]]+)\]', output)
    if task_match and bot_user.level >= 2:
        project_id = int(task_match.group(1))
        task_title = task_match.group(2).strip()
        task_desc = task_match.group(3).strip()
        if any(p.id == project_id for p in accessible_projects):
            card_id = _create_task_card(project_id=project_id, title=task_title,
                                        content=task_desc, chat_id=msg.chat_id, platform=bot_user.platform)
            if card_id:
                output = re.sub(r'\[CREATE_TASK:[^\]]+\]', '', output).strip()
                output += f"\n\n✅ 已建立任務卡片 #{card_id}，完成後會通知你。"
            else:
                output = re.sub(r'\[CREATE_TASK:[^\]]+\]', '', output).strip()
                output += "\n\n⚠️ 建立任務失敗，請稍後再試。"
        else:
            output = re.sub(r'\[CREATE_TASK:[^\]]+\]', '', output).strip()
            output += "\n\n⚠️ 你沒有該專案的存取權限。"

    # 13. 清理輸出中的 channel 標記（向下相容）
    clean_output = re.sub(r'\[CH_(?:SEND|EDIT):[^\]]*\]', '', output).strip()

    # 14. 儲存對話
    _save_message(session_obj.id, "user", msg.text, token_info.get("input_tokens", 0), 0)
    _save_message(session_obj.id, "assistant", clean_output, 0, token_info.get("output_tokens", 0))
    _update_session_stats(session_obj.id, token_info)

    # 15. 即時模式：發新訊息（觸發推播）+ placeholder 改「✅」
    if placeholder_message_id and clean_output:
        try:
            from app.core.http_client import InternalAPIAsync
            await InternalAPIAsync.channel_send(msg.platform, msg.chat_id, clean_output[:4000])
            await InternalAPIAsync.channel_send(msg.platform, msg.chat_id, "✅", placeholder_message_id)
        except Exception as e:
            logger.warning(f"[Chat] Failed to send final response: {e}")
            return clean_output  # fallback: 讓 Router 編輯 placeholder
        return None  # Router 不再編輯

    return clean_output or output


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


def _get_primary_account(member_id: int) -> tuple:
    """取得 Member 的主要帳號和模型
    回傳 (Account, model)
    """
    with Session(engine) as session:
        stmt = (
            select(MemberAccount)
            .where(MemberAccount.member_id == member_id)
            .order_by(MemberAccount.priority)
        )
        ma = session.exec(stmt).first()
        if ma:
            account = session.get(Account, ma.account_id)
            return account, ma.model or ""
    return None, ""


def _build_chat_prompt(
    soul: str,
    skills: str,
    member: Member,
    history: List[ChatMessage],
    user_message: str,
    user_context: Optional[PersonProject] = None,
    accessible_projects: Optional[List[Project]] = None,
    user_level: int = 0,
    chat_id: str = "",
    platform: str = "",
    user_extra: Optional[dict] = None,
    placeholder_message_id: str = "",
) -> str:
    """
    組合完整 prompt = 靈魂 + 技能 + 用戶身份 + 專案範圍 + 歷史 + 新訊息

    Args:
        soul: 靈魂檔案內容
        skills: 技能檔案內容（合併後）
        member: AI 成員
        history: 對話歷史
        user_message: 用戶訊息
        user_context: 用戶身份上下文（含 display_name, description）
        accessible_projects: 用戶可存取的專案列表
        user_level: 用戶權限等級（>=2 可建立任務）
        chat_id: 聊天 ID（用於任務回覆）
        platform: 平台（telegram/line）
    """
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

    # 技能知識（API、查詢方法等）
    if skills:
        lines.append("## 你的技能與知識")
        lines.append(skills.strip())
        lines.append("")

    # 用戶身份描述（讓 AI 知道在跟誰說話）
    if user_context:
        lines.append("## 當前用戶")
        if user_context.display_name:
            lines.append(f"姓名：{user_context.display_name}")
        if user_context.description:
            lines.append(f"身份描述：{user_context.description}")
        lines.append("")
        lines.append("請根據用戶的身份和權限範圍回答，用適當的稱呼和語氣。")
        lines.append("")

    # 用戶額外資料（供 MCP/Skill 使用，如 AD 帳號等）
    if user_extra:
        lines.append("## 用戶額外資料")
        for k, v in user_extra.items():
            lines.append(f"- {k}: {v}")
        lines.append("")
        lines.append("這些資料可用於 MCP 工具存取外部系統（如 NAS、AD 等）。")
        lines.append("如果需要存取外部系統但缺少必要的認證資料（如 ad_user, ad_pass），請引導用戶使用 /profile 指令開啟設定頁面（不要讓用戶在聊天中輸入密碼）。")
        lines.append("")

    # 用戶可存取的專案（讓 AI 知道範圍）
    if accessible_projects:
        lines.append("## 用戶可存取的專案")
        for p in accessible_projects:
            lines.append(f"- {p.name}（ID: {p.id}）")
        lines.append("")
        lines.append("回答問題時只能提供這些專案的資訊。")
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

    # 任務建立引導（權限 >= 2 的用戶可建立任務）
    if user_level >= 2 and accessible_projects:
        lines.append("## 複雜任務處理")
        lines.append("如果用戶的請求太複雜（需要寫程式、分析大量資料、多步驟操作等），")
        lines.append("你可以詢問用戶是否要建立任務卡片，讓更強大的 AI 來處理。")
        lines.append("回覆格式範例：「這個任務比較複雜，需要 [說明原因]。要幫你建立任務卡片嗎？」")
        lines.append("如果用戶同意，回覆：[CREATE_TASK:專案ID:任務標題:任務描述]")
        lines.append(f"任務描述最後請加上：「完成後請透過 {platform} 通知 chat_id={chat_id}」")
        lines.append("")

    # 安全限制
    lines.append("## 安全限制")
    lines.append("- 禁止修改系統檔案（MCP 原始碼、設定檔、.env、CLAUDE.md、skill 檔案等）")
    lines.append("- 禁止安裝套件（pip install、npm install、apt install 等）")
    lines.append("- 禁止執行破壞性指令（rm -rf、kill、systemctl 等）")
    lines.append("- 如果用戶要求修改系統或程式碼，請建議建立任務卡片或聯繫管理員")
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


def _create_task_card(
    project_id: int,
    title: str,
    content: str,
    chat_id: str,
    platform: str,
) -> Optional[int]:
    """
    建立任務卡片（放到 Scheduled 列表，等待 Worker 執行）

    Returns:
        card_id if success, None if failed
    """
    try:
        with Session(engine) as session:
            # 取得專案
            project = session.get(Project, project_id)
            if not project:
                logger.error(f"[CreateTask] Project {project_id} not found")
                return None

            # 找 Scheduled 列表
            stmt = select(StageList).where(
                StageList.project_id == project_id,
                StageList.name == "Scheduled"
            )
            stage_list = session.exec(stmt).first()
            if not stage_list:
                logger.error(f"[CreateTask] Scheduled list not found in project {project_id}")
                return None

            # 取得下一個 card ID
            card_id = next_card_id(session, project_id)

            # 建立卡片資料
            now = datetime.now(timezone.utc)
            card_data = CardData(
                id=card_id,
                list_id=stage_list.id,
                title=title,
                description=f"來自 {platform} 聊天建立的任務",
                content=content,
                status="pending",  # 讓 Worker 自動執行
                tags=[],
                created_at=now,
                updated_at=now,
            )

            # 寫入 MD 檔案
            fpath = card_file_path(project.path, card_id)
            fpath.parent.mkdir(parents=True, exist_ok=True)
            write_card(fpath, card_data)

            # 同步到索引
            sync_card_to_index(session, card_data, project_id, str(fpath))
            session.commit()

            logger.info(f"[CreateTask] Created card #{card_id} in project {project.name}")
            return card_id

    except Exception as e:
        logger.error(f"[CreateTask] Failed: {e}")
        return None


def _media_type_label(media_type: str) -> str:
    """媒體類型的中文標籤"""
    labels = {
        "photo": "一張圖片",
        "voice": "一段語音",
        "audio": "一個音檔",
        "document": "一個檔案",
    }
    return labels.get(media_type, "一個媒體檔案")


def extract_attachments(output: str) -> tuple[str, list[dict]]:
    """從 AI 回應中偵測 <!-- send_image: /path --> 等標記

    Returns:
        (cleaned_output, attachments_list)
        attachments_list: [{"type": "photo", "path": "/tmp/xxx.png", "caption": "..."}, ...]
    """
    import os

    attachments = []

    # 偵測 <!-- send_image: /path/to/file.png --> 或 <!-- send_document: /path/to/file.pdf -->
    pattern = r'<!--\s*send_(image|document|photo|file)\s*:\s*(.+?)\s*-->'
    matches = re.findall(pattern, output, re.IGNORECASE)

    for send_type, path in matches:
        path = path.strip()
        if os.path.exists(path):
            att_type = "photo" if send_type in ("image", "photo") else "document"
            attachments.append({"type": att_type, "path": path, "caption": ""})
            logger.info(f"[Chat] Detected attachment: {att_type} → {path}")

    # 清除標記
    cleaned = re.sub(pattern, '', output).strip()

    return cleaned, attachments
