"""OneStackHook — 任務回報 + 文件分析結果推送到 OneStack"""
import re
import logging
from app.hooks import TaskContext

logger = logging.getLogger(__name__)


class OneStackHook:
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
