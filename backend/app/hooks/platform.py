"""PlatformHook — Telegram/LINE placeholder 即時編輯（DURING only）"""
import time
import logging
from app.hooks import Hook, StreamEvent
from app.core.executor.emitter import sanitize_output

logger = logging.getLogger(__name__)


class PlatformHook(Hook):
    """Chat 路徑：編輯 Telegram/LINE placeholder 顯示工具呼叫摘要"""

    def __init__(self, platform: str = "", chat_id: str = "", placeholder_id: str = "", loop=None):
        self.platform = platform
        self.chat_id = chat_id
        self.placeholder_id = placeholder_id
        self.loop = loop
        self._last_edit_time = 0.0
        self._last_edit_text = ""
        self._throttle = 3.0

    def on_stream(self, event: StreamEvent) -> None:
        if event.kind not in ("tool_call", "output", "thinking", "heartbeat"):
            return
        if not self.placeholder_id:
            return

        content = sanitize_output(event.content)
        summary = f"🤔 {content}" if event.kind != "heartbeat" else content
        now = time.time()
        if now - self._last_edit_time < self._throttle or summary == self._last_edit_text:
            return
        self._last_edit_time = now
        self._last_edit_text = summary

        if self.loop:
            import asyncio
            asyncio.run_coroutine_threadsafe(self._edit(summary), self.loop)
        else:
            try:
                from app.core.http_client import InternalAPI
                InternalAPI.channel_send(self.platform, self.chat_id, summary, self.placeholder_id)
            except Exception:
                pass

    async def _edit(self, text: str) -> None:
        try:
            from app.core.http_client import InternalAPIAsync
            await InternalAPIAsync.channel_send(
                self.platform, self.chat_id, text, self.placeholder_id,
            )
        except Exception:
            pass
