"""
飛書（Feishu/Lark）頻道適配器

使用飛書開放平台 API (WebSocket 長連線)
"""
import httpx
import time
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


@register_channel("feishu")
class FeishuChannel(ChannelBase):
    """
    飛書頻道適配器

    支援國內飛書和國際版 Lark
    使用 Webhook 接收 + 主動推送 API
    """

    PLATFORM = "feishu"

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        is_lark: bool = False,
        verification_token: str = "",
        encrypt_key: str = "",
    ):
        """
        Args:
            app_id: 應用 App ID
            app_secret: 應用 App Secret
            is_lark: 是否為國際版 Lark
            verification_token: 事件訂閱驗證 Token
            encrypt_key: 事件訂閱加密 Key
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self.verification_token = verification_token
        self.encrypt_key = encrypt_key

        # API 端點
        if is_lark:
            self.api_base = "https://open.larksuite.com/open-apis"
        else:
            self.api_base = "https://open.feishu.cn/open-apis"

        self._tenant_token: str = ""
        self._token_expires: float = 0
        self._running = False
        self._client: httpx.AsyncClient | None = None

    async def start(self):
        """初始化 HTTP Client 並取得 Tenant Token"""
        self._running = True
        self._client = httpx.AsyncClient(timeout=30)
        await self._refresh_token()
        logger.info(f"[Feishu] Channel started")

    async def _refresh_token(self):
        """刷新 Tenant Access Token"""
        if not self._client:
            return

        try:
            resp = await self._client.post(
                f"{self.api_base}/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": self.app_id,
                    "app_secret": self.app_secret,
                }
            )
            data = resp.json()
            if data.get("code") == 0:
                self._tenant_token = data["tenant_access_token"]
                self._token_expires = time.time() + data.get("expire", 7200) - 300
                logger.debug("[Feishu] Token refreshed")
            else:
                logger.error(f"[Feishu] Token refresh failed: {data}")
        except Exception as e:
            logger.error(f"[Feishu] Token refresh error: {e}")

    async def _ensure_token(self):
        """確保 Token 有效"""
        if time.time() > self._token_expires:
            await self._refresh_token()

    async def stop(self):
        """關閉 HTTP Client"""
        self._running = False
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("[Feishu] Channel stopped")

    async def handle_webhook(self, body: dict) -> dict:
        """
        處理飛書 Webhook（由 FastAPI route 調用）

        Args:
            body: 請求 Body（JSON）

        Returns:
            回應內容（用於 URL 驗證等）
        """
        # URL 驗證挑戰
        if "challenge" in body:
            return {"challenge": body["challenge"]}

        # 事件處理
        event = body.get("event", {})
        header = body.get("header", {})

        if header.get("event_type") == "im.message.receive_v1":
            message = event.get("message", {})
            sender = event.get("sender", {})

            # 解析訊息內容（可能是 JSON 格式）
            content = message.get("content", "{}")
            try:
                import json
                content_obj = json.loads(content)
                text = content_obj.get("text", "")
            except:
                text = content

            msg = InboundMessage(
                id=message.get("message_id", ""),
                platform=self.PLATFORM,
                user_id=sender.get("sender_id", {}).get("user_id", ""),
                chat_id=message.get("chat_id", ""),
                text=text,
                timestamp=datetime.now(timezone.utc),
                message_type=(
                    MessageType.COMMAND if text.startswith("/") else MessageType.TEXT
                ),
                raw_data=body,
            )
            await message_bus.publish_inbound(msg)

        return {}

    async def send(self, msg: OutboundMessage) -> bool:
        """發送訊息"""
        if not self._client:
            return False

        await self._ensure_token()

        try:
            resp = await self._client.post(
                f"{self.api_base}/im/v1/messages",
                params={"receive_id_type": "chat_id"},
                headers={"Authorization": f"Bearer {self._tenant_token}"},
                json={
                    "receive_id": msg.chat_id,
                    "msg_type": "text",
                    "content": f'{{"text": "{msg.text}"}}',
                }
            )
            data = resp.json()
            if data.get("code") == 0:
                return True
            else:
                logger.error(f"[Feishu] Send failed: {data}")
                return False
        except Exception as e:
            logger.error(f"[Feishu] Send error: {e}")
            return False

    async def listen(self) -> AsyncIterator[InboundMessage]:
        """Webhook 模式不需要此方法"""
        while self._running:
            await asyncio.sleep(1)
            if False:
                yield  # type: ignore

    async def health_check(self) -> ChannelStatus:
        """健康檢查"""
        if not self._client or not self._tenant_token:
            return ChannelStatus(
                platform=self.PLATFORM,
                is_connected=False,
                error="Not initialized",
            )

        return ChannelStatus(
            platform=self.PLATFORM,
            is_connected=True,
            last_heartbeat=datetime.now(timezone.utc),
            stats={"app_id": self.app_id},
        )
