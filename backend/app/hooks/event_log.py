"""EventLogHook — 將結構化事件寫入 JSONL 檔案，供 Playback 回放使用"""
import json
import logging
import time
from pathlib import Path

from app.hooks import Hook, StreamEvent, TaskContext

logger = logging.getLogger(__name__)

# 只記錄這些事件類型
_RECORD_KINDS = {"tool_call", "text", "result", "output"}

# text 內容最多記錄前 200 字
_TEXT_MAX_LEN = 200


class EventLogHook(Hook):
    """DURING: 記錄事件到 buffer / POST: 寫入 .aegis/cards/card-{id}.events.jsonl"""

    def __init__(self, card_id: int = 0, project_path: str = ""):
        self.card_id = card_id
        self.project_path = project_path
        self._buffer: list[dict] = []

    def on_stream(self, event: StreamEvent) -> None:
        if not self.card_id:
            return
        if event.kind not in _RECORD_KINDS:
            return

        content = event.content
        if event.kind == "text" and len(content) > _TEXT_MAX_LEN:
            content = content[:_TEXT_MAX_LEN] + "..."

        self._buffer.append({
            "ts": time.time(),
            "kind": event.kind,
            "content": content,
            "event_type": event.event_type,
        })

    def on_complete(self, ctx: TaskContext) -> None:
        card_id = self.card_id or ctx.card_id
        if not card_id or not self._buffer:
            return

        project_path = self.project_path or ctx.project_path
        if not project_path:
            logger.debug("[EventLogHook] no project_path, skip writing")
            return

        cards_dir = Path(project_path) / ".aegis" / "cards"
        try:
            cards_dir.mkdir(parents=True, exist_ok=True)
            out_file = cards_dir / f"card-{card_id}.events.jsonl"
            with open(out_file, "a", encoding="utf-8") as f:
                for entry in self._buffer:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            logger.info(f"[EventLogHook] wrote {len(self._buffer)} events → {out_file}")
        except Exception as e:
            logger.warning(f"[EventLogHook] write failed: {e}")
        finally:
            self._buffer.clear()
