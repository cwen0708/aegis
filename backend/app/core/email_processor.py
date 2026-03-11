"""
Email AI 處理器 — 自動分類與摘要

收到的 Email 會透過 AI 進行：
1. 分類（actionable / informational / spam / newsletter）
2. 緊急程度（high / medium / low）
3. 摘要（1-3 句）
4. 建議動作
5. 專案映射
"""
import json
import logging
from typing import Optional

from sqlmodel import Session, select
from app.database import engine
from app.models.core import EmailMessage, Project
from app.core.runner import run_ai_task

logger = logging.getLogger(__name__)

CLASSIFY_PROMPT_TEMPLATE = """你是專業郵件分類助手。分析以下郵件，僅以 JSON 回應，不要加任何其他文字。

From: {from_name} <{from_address}>
Subject: {subject}
Date: {date}
Body:
{body_text}

請以下面的 JSON 格式回覆（不要加 markdown code block）：
{{
  "category": "actionable|informational|spam|newsletter",
  "urgency": "high|medium|low",
  "summary": "1-3 句摘要",
  "suggested_action": "建議動作（如無則空字串）",
  "project_keywords": ["關鍵字1", "關鍵字2"]
}}

分類規則：
- actionable：需要回覆或做決定
- informational：僅供參考，無需行動
- spam：廣告、釣魚
- newsletter：訂閱電子報、自動通知

緊急程度：
- high：24 小時內需回應，或來自重要人物，或包含緊急字眼
- medium：幾天內需回應
- low：無時間壓力"""


async def classify_email(email_msg_id: int) -> Optional[dict]:
    """
    對一封 Email 進行 AI 分類和摘要

    Args:
        email_msg_id: EmailMessage.id

    Returns:
        分類結果 dict 或 None
    """
    # 讀取 email
    with Session(engine) as session:
        email_msg = session.get(EmailMessage, email_msg_id)
        if not email_msg:
            logger.error(f"[EmailProcessor] EmailMessage {email_msg_id} not found")
            return None
        if email_msg.is_processed:
            logger.debug(f"[EmailProcessor] EmailMessage {email_msg_id} already processed")
            return None

        # 建構 prompt
        prompt = CLASSIFY_PROMPT_TEMPLATE.format(
            from_name=email_msg.from_name,
            from_address=email_msg.from_address,
            subject=email_msg.subject,
            date=str(email_msg.date or ""),
            body_text=email_msg.body_text[:3000],  # 限制 body 長度
        )

    # 呼叫 AI（用快速模型）
    try:
        result = await run_ai_task(
            task_id=0,
            project_path=".",
            prompt=prompt,
            phase="CHAT",
            forced_provider="gemini",
            card_title=f"Email classify: {email_msg.subject[:40]}",
            project_name="Aegis Email",
            model_override="gemini-flash",
        )
    except Exception as e:
        logger.error(f"[EmailProcessor] AI call failed: {e}")
        return None

    if result.get("status") != "success":
        logger.error(f"[EmailProcessor] AI returned error: {result.get('output', '')[:200]}")
        return None

    output = result.get("output", "").strip()

    # 解析 JSON（可能包裹在 code block 中）
    parsed = _parse_json_output(output)
    if not parsed:
        logger.error(f"[EmailProcessor] Failed to parse AI output: {output[:200]}")
        return None

    # 更新 DB
    with Session(engine) as session:
        email_msg = session.get(EmailMessage, email_msg_id)
        if not email_msg:
            return None

        email_msg.category = parsed.get("category", "unclassified")
        email_msg.urgency = parsed.get("urgency", "unknown")
        email_msg.summary = parsed.get("summary", "")
        email_msg.suggested_action = parsed.get("suggested_action", "")
        email_msg.is_processed = True

        # 專案映射
        keywords = parsed.get("project_keywords", [])
        if keywords:
            project_id = _match_project(session, keywords)
            if project_id:
                email_msg.project_id = project_id

        session.commit()

    logger.info(
        f"[EmailProcessor] Classified email {email_msg_id}: "
        f"category={parsed.get('category')}, urgency={parsed.get('urgency')}"
    )

    return parsed


async def notify_high_urgency(email_msg_id: int):
    """
    高緊急度 actionable 信件 → 推送到其他已綁定頻道

    Args:
        email_msg_id: EmailMessage.id
    """
    from app.channels.bus import message_bus
    from app.channels.types import OutboundMessage
    from app.models.core import ChannelBinding

    with Session(engine) as session:
        email_msg = session.get(EmailMessage, email_msg_id)
        if not email_msg:
            return
        if email_msg.category != "actionable" or email_msg.urgency != "high":
            return

        # 查詢所有已綁定的通知頻道（排除 email 自身）
        bindings = session.exec(
            select(ChannelBinding).where(
                ChannelBinding.notify_on_complete == True,
                ChannelBinding.platform != "email",
            )
        ).all()

        if not bindings:
            return

        # 格式化通知
        text = (
            f"[Email Alert] {email_msg.from_name or email_msg.from_address}\n"
            f"Subject: {email_msg.subject}\n"
            f"\n{email_msg.summary}"
        )
        if email_msg.suggested_action:
            text += f"\n\nAction: {email_msg.suggested_action}"

        for binding in bindings:
            await message_bus.publish_outbound(OutboundMessage(
                chat_id=binding.chat_id,
                platform=binding.platform,
                text=text,
            ))

    logger.info(f"[EmailProcessor] Sent high-urgency notification for email {email_msg_id}")


def _match_project(session: Session, keywords: list[str]) -> Optional[int]:
    """用關鍵字模糊匹配 Project.name"""
    if not keywords:
        return None

    projects = session.exec(select(Project).where(Project.is_active == True)).all()
    if not projects:
        return None

    best_match = None
    best_score = 0

    for project in projects:
        name_lower = project.name.lower()
        score = 0
        for kw in keywords:
            if kw.lower() in name_lower:
                score += 1
        if score > best_score:
            best_score = score
            best_match = project.id

    return best_match if best_score > 0 else None


def _parse_json_output(text: str) -> Optional[dict]:
    """解析 AI 輸出的 JSON（可能包裹在 code block 中）"""
    # 去掉 markdown code block
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # 去掉首行 ```json 和末行 ```
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 嘗試找到 JSON 物件
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
    return None
