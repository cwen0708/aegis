"""BroadcastHook — 廣播任務完成事件到 WebSocket"""
import logging
from app.hooks import Hook, TaskContext

logger = logging.getLogger(__name__)


class BroadcastHook(Hook):
    def on_complete(self, ctx: TaskContext) -> None:
        event = "task_completed" if ctx.status == "completed" else "task_failed"
        payload = {"card_id": ctx.card_id, "status": ctx.status}
        try:
            from app.core.http_client import InternalAPI
            InternalAPI.post("internal/broadcast-event", {"event": event, "data": payload})
        except Exception as e:
            logger.debug(f"[BroadcastHook] {e}")
