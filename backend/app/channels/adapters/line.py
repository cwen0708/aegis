"""
LINE 頻道適配器

使用 line-bot-sdk v3 (Webhook 模式)
需要在 LINE Developers Console 設定 Webhook URL
"""
from linebot.v3.webhook import WebhookParser
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.messaging import (
    Configuration,
    AsyncApiClient,
    AsyncMessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
)
from linebot.v3.exceptions import InvalidSignatureError
from ..base import ChannelBase
from ..registry import register_channel
from ..bus import message_bus
from ..types import (
    InboundMessage,
    OutboundMessage,
    ChannelStatus,
    MessageType,
)
from datetime import datetime, timezone
from typing import AsyncIterator
import asyncio
import logging

logger = logging.getLogger(__name__)


@register_channel("line")
class LineChannel(ChannelBase):
    """
    LINE 頻道適配器

    使用 Webhook 模式接收訊息（需要 HTTPS 公網端點）
    """

    PLATFORM = "line"

    def __init__(self, channel_secret: str, access_token: str):
        """
        Args:
            channel_secret: LINE Channel Secret
            access_token: LINE Channel Access Token
        """
        self.channel_secret = channel_secret
        self.parser = WebhookParser(channel_secret)
        self.config = Configuration(access_token=access_token)
        self._api_client: AsyncApiClient | None = None
        self._api: AsyncMessagingApi | None = None
        self._running = False

    async def start(self):
        """初始化 LINE API Client"""
        self._running = True
        self._api_client = AsyncApiClient(self.config)
        self._api = AsyncMessagingApi(self._api_client)
        logger.info("[LINE] Channel ready (webhook mode)")

    async def stop(self):
        """關閉 API Client"""
        self._running = False
        if self._api_client:
            await self._api_client.close()
            self._api_client = None
            self._api = None
        logger.info("[LINE] Channel stopped")

    async def handle_webhook(self, body: str, signature: str) -> int:
        """
        處理 LINE Webhook（由 FastAPI route 調用）

        Args:
            body: Request body (raw string)
            signature: X-Line-Signature header

        Returns:
            處理的事件數量

        Raises:
            InvalidSignatureError: 簽名驗證失敗
        """
        events = self.parser.parse(body, signature)
        count = 0

        for event in events:
            if isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent):
                # 翻譯為統一格式
                msg = InboundMessage(
                    id=event.message.id,
                    platform=self.PLATFORM,
                    user_id=event.source.user_id,
                    chat_id=event.source.user_id,  # LINE 1:1 chat
                    text=event.message.text,
                    timestamp=datetime.now(timezone.utc),
                    message_type=(
                        MessageType.COMMAND
                        if event.message.text.startswith("/")
                        else MessageType.TEXT
                    ),
                    raw_data={"reply_token": event.reply_token},
                )
                await message_bus.publish_inbound(msg)
                count += 1

        return count

    async def send(self, msg: OutboundMessage) -> bool:
        """
        發送訊息（Push API，免費版每月 200 則限制）
        """
        if not self._api:
            logger.warning("[LINE] API not ready")
            return False

        try:
            await self._api.push_message(
                PushMessageRequest(
                    to=msg.chat_id,
                    messages=[TextMessage(text=msg.text)]
                )
            )
            return True
        except Exception as e:
            logger.error(f"[LINE] Send failed: {e}")
            return False

    async def reply(self, reply_token: str, text: str) -> bool:
        """
        使用 Reply Token 回覆（不計入訊息額度）
        """
        if not self._api:
            return False

        try:
            await self._api.reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[TextMessage(text=text)]
                )
            )
            return True
        except Exception as e:
            logger.error(f"[LINE] Reply failed: {e}")
            return False

    async def listen(self) -> AsyncIterator[InboundMessage]:
        """Webhook 模式不需要此方法"""
        while self._running:
            await asyncio.sleep(1)
            if False:
                yield  # type: ignore

    async def health_check(self) -> ChannelStatus:
        """健康檢查"""
        if not self._api:
            return ChannelStatus(
                platform=self.PLATFORM,
                is_connected=False,
                error="API not initialized",
            )

        try:
            # LINE 沒有簡單的 ping API，只能檢查 client 是否存在
            return ChannelStatus(
                platform=self.PLATFORM,
                is_connected=True,
                last_heartbeat=datetime.now(timezone.utc),
            )
        except Exception as e:
            return ChannelStatus(
                platform=self.PLATFORM,
                is_connected=False,
                error=str(e),
            )
