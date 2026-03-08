"""
訊息總線 — 解耦頻道與核心邏輯

參考: Nanobot Message Bus 設計
"""
import asyncio
from typing import Optional, Callable, Awaitable
from .types import InboundMessage, OutboundMessage
import logging

logger = logging.getLogger(__name__)

# 訊息處理器類型
InboundHandler = Callable[[InboundMessage], Awaitable[None]]
OutboundHandler = Callable[[OutboundMessage], Awaitable[None]]


class MessageBus:
    """
    訊息總線

    職責：
    - 接收來自頻道的 InboundMessage
    - 接收來自 Router 的 OutboundMessage
    - 分發訊息給訂閱者

    架構：
        Channels → [inbound_queue] → Router
        Router   → [outbound_queue] → Channels
    """

    def __init__(self, maxsize: int = 1000):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue(maxsize=maxsize)
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue(maxsize=maxsize)
        self._inbound_handlers: list[InboundHandler] = []
        self._outbound_handlers: list[OutboundHandler] = []
        self._running = False
        self._dispatch_task: Optional[asyncio.Task] = None

    # ===== 發布方法 =====

    async def publish_inbound(self, msg: InboundMessage):
        """
        頻道調用：發布收到的訊息

        Args:
            msg: 來自平台的訊息（已轉換為統一格式）
        """
        await self.inbound.put(msg)
        logger.debug(f"[Bus] Inbound: [{msg.platform}] {msg.user_id}: {msg.text[:50]}")

    async def publish_outbound(self, msg: OutboundMessage):
        """
        Router/Core 調用：發布要發送的訊息

        Args:
            msg: 要發送到平台的訊息
        """
        await self.outbound.put(msg)
        target = msg.platform or "broadcast"
        logger.debug(f"[Bus] Outbound: [{target}] {msg.text[:50]}")

    # ===== 消費方法 =====

    async def consume_inbound(self, timeout: float = 1.0) -> Optional[InboundMessage]:
        """
        Router 調用：取得待處理訊息

        Args:
            timeout: 等待超時秒數

        Returns:
            訊息或 None（超時）
        """
        try:
            return await asyncio.wait_for(self.inbound.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def consume_outbound(self, timeout: float = 1.0) -> Optional[OutboundMessage]:
        """
        頻道調用：取得待發送訊息

        Args:
            timeout: 等待超時秒數

        Returns:
            訊息或 None（超時）
        """
        try:
            return await asyncio.wait_for(self.outbound.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    # ===== Handler 訂閱 =====

    def on_inbound(self, handler: InboundHandler):
        """訂閱 inbound 訊息"""
        self._inbound_handlers.append(handler)

    def on_outbound(self, handler: OutboundHandler):
        """訂閱 outbound 訊息"""
        self._outbound_handlers.append(handler)

    # ===== 生命週期 =====

    async def start(self):
        """啟動訊息分發"""
        self._running = True
        logger.info("[Bus] MessageBus started")

    async def stop(self):
        """停止訊息分發"""
        self._running = False
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
        logger.info("[Bus] MessageBus stopped")

    # ===== 狀態查詢 =====

    @property
    def inbound_pending(self) -> int:
        """待處理的 inbound 訊息數"""
        return self.inbound.qsize()

    @property
    def outbound_pending(self) -> int:
        """待發送的 outbound 訊息數"""
        return self.outbound.qsize()


# 全域 Bus 實例
message_bus = MessageBus()
