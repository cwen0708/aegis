"""DialogueHook — 從 AI 輸出提取 AVG 對話並儲存"""
import re
import logging
from app.hooks import TaskContext

logger = logging.getLogger(__name__)


class DialogueHook:
    def on_complete(self, ctx: TaskContext) -> None:
        if not ctx.member_id:
            return
        match = re.search(r'<!-- dialogue: (.+?) -->', ctx.output)
        if not match:
            return
        try:
            from sqlmodel import Session
            from app.database import engine
            from app.models.core import MemberDialogue
            from app.core.ws_manager import broadcast_event_sync

            dialogue_text = match.group(1).strip()
            with Session(engine) as s:
                s.add(MemberDialogue(
                    member_id=ctx.member_id,
                    card_id=ctx.card_id,
                    card_title=ctx.card_title,
                    project_name=ctx.project_name,
                    dialogue_type="task_complete" if ctx.status == "completed" else "task_failed",
                    text=dialogue_text,
                ))
                s.commit()

            try:
                broadcast_event_sync("member_dialogue", {
                    "member_id": ctx.member_id,
                    "text": dialogue_text,
                    "type": "task_complete" if ctx.status == "completed" else "task_failed",
                })
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"[DialogueHook] {e}")
