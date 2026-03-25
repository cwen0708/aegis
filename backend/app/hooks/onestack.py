"""OneStackHook — DURING 串流 + POST 任務回報（OneStack 邏輯集中管理）"""
import re
import time
import logging
from app.hooks import Hook, StreamEvent, TaskContext

logger = logging.getLogger(__name__)


class OneStackHook(Hook):
    """OneStack 整合 — 串流推送 + 任務完成回報 + 文件分析結果

    DURING: aegis_stream Supabase Realtime（tool_call / output，2 秒節流）
    POST: report_task_completion + document report
    """

    def __init__(self, card_id: int = 0, member_slug: str = "", chat_id: str = ""):
        self.card_id = card_id
        self.member_slug = member_slug
        self.chat_id = chat_id
        self._last_stream_time = 0.0
        self._throttle = 2.0

    # ── DURING ──

    def on_stream(self, event: StreamEvent) -> None:
        if event.kind not in ("tool_call", "output"):
            return
        if not self.card_id:
            return
        now = time.time()
        if now - self._last_stream_time < self._throttle:
            return
        self._last_stream_time = now
        try:
            import asyncio
            from app.core.onestack_connector import connector
            if not connector.enabled:
                return
            loop = asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(
                connector.stream_event(
                    self.card_id,
                    event.event_type or event.kind,
                    event.content,
                    self.member_slug,
                    chat_id=self.chat_id,
                ),
                loop,
            )
        except Exception:
            pass

    # ── POST ──

    def on_complete(self, ctx: TaskContext) -> None:
        self._report_completion(ctx)
        self._report_document(ctx)

    def _report_completion(self, ctx: TaskContext) -> None:
        try:
            from app.core.onestack_connector import connector
            if not connector.enabled:
                return
            import asyncio
            asyncio.run(connector.report_task_completion(
                card_id=ctx.card_id, output=ctx.output,
                status=ctx.status,
                duration_ms=ctx.token_info.get("duration_ms", 0),
                cost_usd=ctx.token_info.get("total_cost_usd", 0),
            ))
        except Exception as e:
            logger.debug(f"[OneStackHook] Report: {e}")

    def _report_document(self, ctx: TaskContext) -> None:
        doc_match = re.search(r'<!-- document_id: (.+?) -->', ctx.card_content)
        if not doc_match:
            return
        doc_id = doc_match.group(1)
        try:
            from app.core.onestack_connector import connector
            if not connector.enabled:
                return
            import asyncio
            doc_output = ctx.token_info.get("result_text", "") or ctx.output[:3000]
            doc_evt = "result" if ctx.status == "completed" else "error"
            json_match = re.search(r'```json\s*\n([\s\S]*?)\n```', doc_output)
            if json_match:
                doc_output = json_match.group(1).strip()
            asyncio.run(connector.stream_event(
                card_id=ctx.card_id, event_type=doc_evt, content=doc_output[:5000],
                member_slug=ctx.member_slug,
                metadata={"document_id": doc_id, "type": "file_result"},
                chat_id=f"doc:{doc_id}",
            ))
            logger.info(f"[OneStackHook] Document {doc_id[:8]}... sent")
        except Exception as e:
            logger.debug(f"[OneStackHook] Document: {e}")
