"""
Agent Chat — AI 成員間對話 API

- POST /agent-chat/ask — 一對一即時諮詢
- POST /agent-chat/meeting — 啟動多人會議（輪流制 / 主持人制）
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


# ════════════════════════════════════════
# Meeting — 多人會議
# ════════════════════════════════════════

class MeetingRequest(BaseModel):
    meeting_id: str                     # 會議 ID（如 standup-2026-03-25）
    title: str = ""                     # 會議標題
    moderator: str                      # 主持人 slug
    speakers: list[str]                 # 發言者 slug 列表
    mode: str = "round_robin"           # "round_robin" | "moderated"
    rounds: int | list[str] = 1         # int=輪數, list[str]=每輪自訂指令
    max_turns: int = 10                 # 主持人制的最大輪數
    opening: str = ""                   # 開場白


class MeetingResponse(BaseModel):
    meeting_id: str
    file_path: str
    total_entries: int
    history: list[dict]   # [{speaker, slug, content}]
    status: str


@router.post("/meeting", response_model=MeetingResponse)
async def start_meeting(req: MeetingRequest):
    """啟動多人會議。

    輪流制：固定順序，每人發言 N 輪，最後主持人總結。
    主持人制：主持人每輪決定下一個誰講，[DONE] 結束。
    """
    from app.core.conversation.room import ConversationRoom
    from app.core.conversation.coordinator import run_round_robin, run_moderated

    all_participants = [req.moderator] + req.speakers
    room = ConversationRoom(
        meeting_id=req.meeting_id,
        title=req.title or req.meeting_id,
        participants=all_participants,
    )

    try:
        if req.mode == "moderated":
            await run_moderated(
                room=room,
                moderator=req.moderator,
                participants=req.speakers,
                opening=req.opening,
                max_turns=req.max_turns,
            )
        else:
            await run_round_robin(
                room=room,
                moderator=req.moderator,
                speakers=req.speakers,
                rounds=req.rounds,
                opening=req.opening,
            )
    except Exception as e:
        logger.error(f"[Meeting] Failed: {e}")
        raise HTTPException(500, f"會議執行失敗: {e}")

    return MeetingResponse(
        meeting_id=room.meeting_id,
        file_path=str(room.file_path),
        total_entries=len(room.history),
        history=room.history,
        status="completed",
    )
