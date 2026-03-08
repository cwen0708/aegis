"""
訊息路由器 — 處理 inbound 訊息，產生 outbound 回應
"""
import asyncio
from .bus import message_bus
from .types import InboundMessage, OutboundMessage, MessageType
from .commands.parser import parse_command
from .commands.handlers import handle_command
import logging

logger = logging.getLogger(__name__)


class MessageRouter:
    """
    訊息路由器

    職責：
    - 從 Bus 消費 InboundMessage
    - 解析命令
    - 執行業務邏輯
    - 產生 OutboundMessage 發回 Bus
    """

    def __init__(self):
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self):
        """啟動路由循環"""
        self._running = True
        self._task = asyncio.create_task(self._route_loop())
        logger.info("[Router] MessageRouter started")

    async def stop(self):
        """停止路由"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[Router] MessageRouter stopped")

    async def _route_loop(self):
        """主路由循環"""
        while self._running:
            try:
                msg = await message_bus.consume_inbound(timeout=1.0)
                if msg:
                    await self._handle_message(msg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Router] Error: {e}", exc_info=True)

    async def _handle_message(self, msg: InboundMessage):
        """處理單一訊息"""
        logger.debug(f"[Router] Processing: [{msg.platform}] {msg.text[:50]}")

        # 解析命令
        cmd = parse_command(msg.text)

        response_text: str | None = None

        if cmd:
            # 執行命令
            response_text = await handle_command(cmd, msg)
        else:
            # 非命令訊息
            # 目前不處理，未來可接 AI 對話
            pass

        # 產生回應
        if response_text:
            await message_bus.publish_outbound(OutboundMessage(
                chat_id=msg.chat_id,
                platform=msg.platform,
                text=response_text,
                reply_to_id=msg.id,
            ))


# 全域 Router 實例
message_router = MessageRouter()
