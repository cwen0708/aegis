"""
Slack 頻道適配器

使用 slack-sdk (Socket Mode)
"""
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
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


@register_channel("slack")
class SlackChannel(ChannelBase):
    """
    Slack 頻道適配器

    使用 Socket Mode（不需要公網端點）
    需要在 Slack App 設定中啟用 Socket Mode
    """

    PLATFORM = "slack"

    def __init__(self, bot_token: str, app_token: str):
        """
        Args:
            bot_token: Slack Bot Token (xoxb-...)
            app_token: Slack App-Level Token (xapp-...) for Socket Mode
        """
        self.bot_token = bot_token
        self.app_token = app_token
        self._running = False
        self._web_client: AsyncWebClient | None = None
        self._socket_client: SocketModeClient | None = None
        self._task: asyncio.Task | None = None

    async def start(self):
        """啟動 Slack Bot"""
        self._running = True
        self._web_client = AsyncWebClient(token=self.bot_token)
        self._socket_client = SocketModeClient(
            app_token=self.app_token,
            web_client=self._web_client,
        )

        # 註冊事件處理
        self._socket_client.socket_mode_request_listeners.append(self._handle_event)

        # 啟動 Socket Mode
        self._task = asyncio.create_task(self._socket_client.connect())
        logger.info("[Slack] Channel started (Socket Mode)")

    async def _handle_event(self, client: SocketModeClient, req: SocketModeRequest):
        """處理 Slack 事件"""
        # 確認收到
        response = SocketModeResponse(envelope_id=req.envelope_id)
        await client.send_socket_mode_response(response)

        if req.type == "events_api":
            event = req.payload.get("event", {})
            if event.get("type") == "message" and "subtype" not in event:
                text = event.get("text", "")
                msg = InboundMessage(
                    id=event.get("client_msg_id", event.get("ts", "")),
                    platform=self.PLATFORM,
                    user_id=event.get("user", ""),
                    chat_id=event.get("channel", ""),
                    text=text,
                    timestamp=datetime.now(timezone.utc),
                    message_type=(
                        MessageType.COMMAND if text.startswith("/") else MessageType.TEXT
                    ),
                    raw_data=event,
                )
                await message_bus.publish_inbound(msg)

    async def stop(self):
        """停止 Slack Bot"""
        self._running = False
        if self._socket_client:
            await self._socket_client.disconnect()
        if self._task:
            self._task.cancel()
        logger.info("[Slack] Channel stopped")

    async def send(self, msg: OutboundMessage) -> bool:
        """發送訊息"""
        if not self._web_client:
            return False

        try:
            await self._web_client.chat_postMessage(
                channel=msg.chat_id,
                text=msg.text,
            )
            return True
        except Exception as e:
            logger.error(f"[Slack] Send failed: {e}")
            return False

    async def listen(self) -> AsyncIterator[InboundMessage]:
        """Socket Mode 由 _handle_event 處理"""
        while self._running:
            await asyncio.sleep(1)
            if False:
                yield  # type: ignore

    async def health_check(self) -> ChannelStatus:
        """健康檢查"""
        if not self._web_client:
            return ChannelStatus(
                platform=self.PLATFORM,
                is_connected=False,
                error="Client not initialized",
            )

        try:
            result = await self._web_client.auth_test()
            return ChannelStatus(
                platform=self.PLATFORM,
                is_connected=True,
                last_heartbeat=datetime.now(timezone.utc),
                stats={
                    "bot_id": result.get("bot_id"),
                    "team": result.get("team"),
                },
            )
        except Exception as e:
            return ChannelStatus(
                platform=self.PLATFORM,
                is_connected=False,
                error=str(e),
            )
