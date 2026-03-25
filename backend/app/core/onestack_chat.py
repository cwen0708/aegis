"""
OneStack Chat — 走 Runner 路徑（ProcessPool 持久進程）

取代原本的「建卡片 → Worker 撿起 → 一次性 subprocess」流程。
好處：零冷啟（第二條訊息起）、多輪上下文自動保留、不佔 workstation。

入口：handle_onestack_chat()，由 _handle_aegis_command("chat") 呼叫。
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def handle_onestack_chat(
    member_slug: str,
    message: str,
    chat_id: str,
    user_id: Optional[str] = None,
) -> dict:
    """處理 OneStack 即時對話 — ProcessPool 路徑。

    Returns: {"ok": True/False, "output": str, ...}
    """
    from app.core.executor.context import resolve_member_for_chat
    from app.core.executor.emitter import StreamEmitter, OneStackTarget
    from sqlmodel import Session, select
    from app.database import engine
    from app.models.core import Member

    # 1. 解析成員
    with Session(engine) as session:
        member = session.exec(select(Member).where(Member.slug == member_slug)).first()
        if not member:
            member = session.exec(select(Member).where(Member.slug == "aegis")).first()
        if not member:
            return {"ok": False, "error": f"Member {member_slug} not found"}
        member_id = member.id

    ctx = resolve_member_for_chat(member_id)
    if not ctx.has_member:
        return {"ok": False, "error": "Member context failed"}

    # 2. Chat workspace（OneStack 用戶 = 管理者，有完整控制權）
    from app.core.chat_workspace import ensure_chat_workspace

    # 簡易 user_context：OneStack 用戶預設為管理者
    class _AdminContext:
        display_name = "管理者"
        description = "OneStack 管理者，對此 Aegis 節點有完整控制權"

    chat_key = f"onestack:{user_id or chat_id}:{ctx.member_slug}"
    ws_path = ensure_chat_workspace(
        member_slug=ctx.member_slug,
        chat_key=chat_key,
        bot_user_id=0,
        soul=ctx.soul,
        user_context=_AdminContext(),
        user_level=3,
        chat_id=chat_id,
        platform="onestack",
    )

    # 3. Emitter（只推 OneStack aegis_stream）
    from app.core.onestack_connector import connector
    emitter = StreamEmitter(targets=[
        OneStackTarget(card_id=0, member_slug=ctx.member_slug, chat_id=chat_id),
    ])

    # 4. 寫 stream: 用戶訊息（供歷史記憶用）
    if connector.enabled:
        await connector.stream_event(0, "output", f"[用戶] {message}", ctx.member_slug, chat_id=chat_id)
        await connector.stream_event(0, "status", "running", ctx.member_slug, chat_id=chat_id)

    # 5. 呼叫 AI（ProcessPool 持久進程）
    from app.core.runner import run_ai_task

    provider = ctx.primary_provider
    model = ctx.effective_model("chat")
    auth_info = ctx.primary_auth

    logger.info(f"[OneStack Chat] member={ctx.member_slug} chat_id={chat_id} provider={provider} model={model}")

    try:
        result = await run_ai_task(
            task_id=0,
            project_path=".",
            prompt=message,
            phase="CHAT",
            forced_provider=provider,
            card_title=f"OneStack chat: {message[:30]}",
            project_name="OneStack",
            member_id=ctx.member_id,
            model_override=model,
            auth_info=auth_info,
            on_stream=emitter.emit_raw,
            use_process_pool=(provider == "claude"),
            chat_key=chat_key if provider == "claude" else None,
            cwd=ws_path,
        )
    except Exception as e:
        logger.error(f"[OneStack Chat] AI failed: {e}")
        if connector.enabled:
            await connector.stream_event(0, "error", str(e)[:500], ctx.member_slug, chat_id=chat_id)
        return {"ok": False, "error": str(e)[:500]}

    # 6. 回寫結果
    output = result.get("output", "")
    status = result.get("status", "error")

    if connector.enabled:
        evt_type = "result" if status == "success" else "error"
        await connector.stream_event(0, evt_type, output[:3000], ctx.member_slug, chat_id=chat_id)

    logger.info(f"[OneStack Chat] Done: status={status} output_len={len(output)}")
    return {"ok": status == "success", "output": output[:3000], "status": status}
