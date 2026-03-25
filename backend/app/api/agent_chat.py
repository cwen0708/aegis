"""
Agent Chat — AI 成員間對話 API

讓 AI 成員可以在對話中諮詢其他成員，底層復用 ProcessPool 持久進程。
用法：
  - Shared skill 呼叫 POST /api/v1/agent-chat/ask
  - ConversationRoom coordinator 呼叫同一個 endpoint（未來）
"""
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/agent-chat", tags=["agent-chat"])
logger = logging.getLogger(__name__)


class AskRequest(BaseModel):
    target: str                    # 目標成員 slug（誰來回答）
    question: str                  # 問題內容
    from_member: Optional[str] = None  # 發問者 slug（可選，用於 prompt 前綴）
    context: Optional[str] = None  # 補充背景（可選）


class AskResponse(BaseModel):
    answer: str
    member: str        # 回答者 slug
    member_name: str   # 回答者名字
    status: str        # "success" | "error"
    token_info: dict = {}


@router.post("/ask", response_model=AskResponse)
async def ask_member(req: AskRequest):
    """向指定 AI 成員提問，等待回應後回傳。

    底層使用 ProcessPool 持久進程，同一成員的 session 會被復用（30 分鐘 TTL）。
    """
    from app.core.executor.context import resolve_member_for_chat
    from app.core.chat_workspace import ensure_chat_workspace
    from app.core.session_pool import process_pool

    # 1. 解析目標成員
    from sqlmodel import Session, select
    from app.database import engine
    from app.models.core import Member

    with Session(engine) as s:
        target_member = s.exec(
            select(Member).where(Member.slug == req.target)
        ).first()
        if not target_member:
            raise HTTPException(404, f"成員 '{req.target}' 不存在")

    ctx = resolve_member_for_chat(target_member.id)
    if not ctx.has_member:
        raise HTTPException(404, f"成員 '{req.target}' 無法載入")

    # 2. 查詢發問者名字（如果有）
    from_name = req.from_member or "隊友"
    if req.from_member:
        with Session(engine) as s:
            from_m = s.exec(select(Member).where(Member.slug == req.from_member)).first()
            if from_m:
                from_name = from_m.name

    # 3. 確保 workspace（agent 對 agent 專用目錄）
    chat_key = f"agent:{req.from_member or 'unknown'}:{req.target}"
    ws_path = ensure_chat_workspace(
        member_slug=ctx.member_slug,
        chat_key=chat_key,
        bot_user_id=0,  # agent 對 agent，無 bot_user
        soul=ctx.soul,
    )

    # 4. 組裝 prompt
    prompt = f"你的隊友「{from_name}」想請教你：\n\n{req.question}"
    if req.context:
        prompt += f"\n\n背景補充：\n{req.context}"
    prompt += "\n\n請簡潔回答，直接給出你的專業意見。"

    # 5. 送進 ProcessPool
    logger.info(f"[AgentChat] {req.from_member} → {req.target}: {req.question[:50]}...")

    try:
        result = await asyncio.to_thread(
            process_pool.send_message,
            chat_key=chat_key,
            message=prompt,
            model=ctx.effective_model("chat"),
            member_id=ctx.member_id,
            auth_info=ctx.primary_auth,
            cwd=ws_path,
        )
    except Exception as e:
        logger.error(f"[AgentChat] Failed: {e}")
        raise HTTPException(500, f"AI 回應失敗: {e}")

    answer = result.get("output", "").strip()
    status = result.get("status", "error")

    if status != "success":
        logger.warning(f"[AgentChat] {req.target} responded with status={status}")

    logger.info(f"[AgentChat] {req.target} answered ({len(answer)} chars)")

    return AskResponse(
        answer=answer,
        member=req.target,
        member_name=ctx.member_name or req.target,
        status=status,
        token_info=result.get("token_info", {}),
    )
