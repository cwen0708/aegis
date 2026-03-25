"""WebSocketHook — Worker Kanban 即時 log（DURING only）"""
import logging
from app.hooks import Hook, StreamEvent
from app.core.executor.emitter import clean_ansi

logger = logging.getLogger(__name__)


class WebSocketHook(Hook):
    """Worker 路徑：broadcast_log → BroadcastLog DB + HTTP → WS → 前端 Kanban"""

    def __init__(self, card_id: int = 0):
        self.card_id = card_id

    def on_stream(self, event: StreamEvent) -> None:
        if event.kind == "result" or not self.card_id:
            return

        # directive → 走 /internal/directive 路徑
        if event.kind == "directive":
            try:
                from app.core.http_client import InternalAPI
                directive_data = event.token_info  # {action, params, ...}
                InternalAPI.post("/internal/directive", {
                    "card_id": self.card_id,
                    "action": directive_data.get("action", "notify"),
                    "params": directive_data.get("params", {}),
                })
            except Exception as e:
                logger.warning(f"[WebSocketHook] directive: {e}")
            return

        clean = clean_ansi(event.content)
        if not clean.strip():
            return
        # DB
        try:
            from sqlmodel import Session
            from app.database import engine
            from app.models.core import BroadcastLog
            with Session(engine) as session:
                session.add(BroadcastLog(card_id=self.card_id, line=clean))
                session.commit()
        except Exception:
            pass
        # WS
        try:
            from app.core.http_client import InternalAPI
            InternalAPI.broadcast_log(self.card_id, clean)
        except Exception as e:
            logger.warning(f"[WebSocketHook] {e}")
