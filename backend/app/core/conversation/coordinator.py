"""
Coordinator — 控制會議發言順序

兩種模式：
- run_round_robin: 固定順序，每人發言 N 輪
- run_moderated: 主持人判斷下一個誰講
"""
import asyncio
import logging
import re
from typing import Optional, Callable

from app.core.conversation.room import ConversationRoom

logger = logging.getLogger(__name__)


async def _speak(
    room: ConversationRoom,
    member_slug: str,
    instruction: str = "",
    on_spoke: Optional[Callable] = None,
) -> str:
    """讓一個成員在會議中發言。

    底層用 ProcessPool（chat_key=f"meeting:{ctx.member_slug}"），復用成員的永久 meeting session。
    """
    from app.core.executor.context import resolve_member_for_chat
    from app.core.chat_workspace import ensure_chat_workspace
    from app.core.session_pool import process_pool

    ctx = resolve_member_for_chat_by_slug(member_slug)
    if not ctx.has_member:
        logger.error(f"[Meeting] Member '{member_slug}' not found")
        return f"（{member_slug} 無法載入）"

    # 確保 meeting workspace
    ws_path = ensure_chat_workspace(
        member_slug=ctx.member_slug,
        chat_key=f"meeting:{ctx.member_slug}",
        bot_user_id=0,
        soul=ctx.soul,
    )

    # 組裝 prompt（帶入完整歷史）
    prompt = room.get_prompt_for(ctx.member_name, instruction)

    # 送進 ProcessPool
    logger.info(f"[Meeting] {ctx.member_name} speaking in {room.meeting_id}...")
    result = await asyncio.to_thread(
        process_pool.send_message,
        chat_key=f"meeting:{ctx.member_slug}",
        message=prompt,
        model=ctx.effective_model("chat"),
        member_id=ctx.member_id,
        auth_info=ctx.primary_auth,
        cwd=ws_path,
    )

    answer = result.get("output", "").strip()
    status = result.get("status", "error")

    if status != "success":
        logger.warning(f"[Meeting] {ctx.member_name} failed: {status}")
        answer = answer or f"（{ctx.member_name} 回應失敗）"

    # 追加到會議紀錄
    room.append(ctx.member_name, ctx.member_slug, answer)

    if on_spoke:
        on_spoke(ctx.member_slug, ctx.member_name, answer)

    logger.info(f"[Meeting] {ctx.member_name} spoke ({len(answer)} chars)")
    return answer


def resolve_member_for_chat_by_slug(slug: str):
    """用 slug 解析 MemberContext（不需 member_id）。"""
    from sqlmodel import Session, select
    from app.database import engine
    from app.models.core import Member
    from app.core.executor.context import resolve_member_for_chat

    with Session(engine) as s:
        member = s.exec(select(Member).where(Member.slug == slug)).first()
        if not member:
            from app.core.executor.context import MemberContext
            return MemberContext()
        return resolve_member_for_chat(member.id)


async def run_round_robin(
    room: ConversationRoom,
    moderator: str,           # 主持人 slug（開場 + 總結）
    speakers: list[str],      # 發言者 slug 列表（不含主持人）
    rounds: int = 1,
    opening: str = "",
    on_spoke: Optional[Callable] = None,
) -> ConversationRoom:
    """輪流制會議。

    流程：主持人開場 → 每位依序發言 × rounds 輪 → 主持人總結

    Args:
        room: 會議室
        moderator: 主持人 slug
        speakers: 發言者列表
        rounds: 每人發言幾輪
        opening: 開場白（寫入檔案）
        on_spoke: 每人發言完的回呼 (slug, name, content)

    Returns:
        room（含完整歷史）
    """
    # 建立檔案
    room.create_file(opening)

    # 主持人開場
    if opening:
        ctx = resolve_member_for_chat_by_slug(moderator)
        room.append(ctx.member_name or moderator, moderator, opening)

    # 多輪發言
    for r in range(rounds):
        for slug in speakers:
            round_hint = f"（第 {r+1}/{rounds} 輪）" if rounds > 1 else ""
            await _speak(room, slug, instruction=round_hint, on_spoke=on_spoke)

    # 主持人總結
    await _speak(
        room, moderator,
        instruction="請總結本次會議的重點，列出具體的 Action Items（格式：- [ ] 內容）。",
        on_spoke=on_spoke,
    )

    logger.info(f"[Meeting] {room.meeting_id} completed, {len(room.history)} entries")
    return room


async def run_moderated(
    room: ConversationRoom,
    moderator: str,
    participants: list[str],   # 所有可能被點名的人（不含主持人）
    opening: str = "",
    max_turns: int = 10,
    on_spoke: Optional[Callable] = None,
) -> ConversationRoom:
    """主持人制會議。

    主持人每輪決定下一個誰講（[NEXT:slug]）或結束（[DONE]）。

    Args:
        room: 會議室
        moderator: 主持人 slug
        participants: 可被點名的成員
        opening: 開場白
        max_turns: 最大輪數（防無限迴圈）
        on_spoke: 每人發言完的回呼

    Returns:
        room（含完整歷史）
    """
    room.create_file(opening)

    if opening:
        ctx = resolve_member_for_chat_by_slug(moderator)
        room.append(ctx.member_name or moderator, moderator, opening)

    participant_list = ", ".join(participants)

    for turn in range(max_turns):
        # 主持人判斷下一步
        mod_instruction = (
            f"你是本次會議的主持人。可點名的成員：{participant_list}\n"
            "請決定下一步：\n"
            "- 點名某人發言：在回應最後加上 [NEXT:成員slug]\n"
            "- 結束會議：在回應最後加上 [DONE]，並附上 Action Items\n"
        )
        mod_response = await _speak(room, moderator, instruction=mod_instruction, on_spoke=on_spoke)

        # 解析 [DONE]
        if "[DONE]" in mod_response:
            logger.info(f"[Meeting] Moderator ended meeting at turn {turn+1}")
            break

        # 解析 [NEXT:slug]
        next_match = re.search(r'\[NEXT:(\S+?)\]', mod_response)
        if next_match:
            next_slug = next_match.group(1)
            if next_slug in participants:
                await _speak(room, next_slug, on_spoke=on_spoke)
            else:
                logger.warning(f"[Meeting] Unknown member: {next_slug}")
        else:
            logger.warning(f"[Meeting] Moderator didn't specify NEXT or DONE, ending")
            break

    logger.info(f"[Meeting] {room.meeting_id} completed, {len(room.history)} entries")
    return room
