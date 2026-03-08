"""
企業微信（WeCom）頻道適配器

使用企業微信 API (Webhook 接收 + 主動推送)
"""
import httpx
import hashlib
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


@register_channel("wecom")
class WeComChannel(ChannelBase):
    """
    企業微信頻道適配器

    使用 Webhook 接收訊息 + 主動推送 API
    需要在企業微信管理後台建立應用
    """

    PLATFORM = "wecom"
    API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"

    def __init__(self, corp_id: str, corp_secret: str, agent_id: int, token: str = "", aes_key: str = ""):
        """
        Args:
            corp_id: 企業 ID
            corp_secret: 應用 Secret
            agent_id: 應用 AgentId
            token: 接收訊息的 Token（用於驗證）
            aes_key: 接收訊息的 EncodingAESKey
        """
        self.corp_id = corp_id
        self.corp_secret = corp_secret
        self.agent_id = agent_id
        self.token = token
        self.aes_key = aes_key
        self._access_token: str = ""
        self._token_expires: float = 0
        self._running = False
        self._client: httpx.AsyncClient | None = None

    async def start(self):
        """初始化 HTTP Client 並取得 Access Token"""
        self._running = True
        self._client = httpx.AsyncClient(timeout=30)
        await self._refresh_token()
        logger.info("[WeCom] Channel started")

    async def _refresh_token(self):
        """刷新 Access Token"""
        if not self._client:
            return

        try:
            resp = await self._client.get(
                f"{self.API_BASE}/gettoken",
                params={
                    "corpid": self.corp_id,
                    "corpsecret": self.corp_secret,
                }
            )
            data = resp.json()
            if data.get("errcode") == 0:
                self._access_token = data["access_token"]
                self._token_expires = time.time() + data.get("expires_in", 7200) - 300
                logger.debug("[WeCom] Token refreshed")
            else:
                logger.error(f"[WeCom] Token refresh failed: {data}")
        except Exception as e:
            logger.error(f"[WeCom] Token refresh error: {e}")

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
        logger.info("[WeCom] Channel stopped")

    async def handle_webhook(self, msg_signature: str, timestamp: str, nonce: str, body: str) -> int:
        """
        處理企業微信 Webhook（由 FastAPI route 調用）

        Args:
            msg_signature: 訊息簽名
            timestamp: 時間戳
            nonce: 隨機數
            body: 請求 Body（XML 格式）

        Returns:
            處理的事件數量
        """
        # TODO: 實作訊息解密和驗證
        # 需要用 WXBizMsgCrypt 解密
        logger.info(f"[WeCom] Webhook received (not implemented)")
        return 0

    async def send(self, msg: OutboundMessage) -> bool:
        """發送訊息"""
        if not self._client:
            return False

        await self._ensure_token()

        try:
            resp = await self._client.post(
                f"{self.API_BASE}/message/send",
                params={"access_token": self._access_token},
                json={
                    "touser": msg.chat_id,
                    "msgtype": "text",
                    "agentid": self.agent_id,
                    "text": {"content": msg.text},
                }
            )
            data = resp.json()
            if data.get("errcode") == 0:
                return True
            else:
                logger.error(f"[WeCom] Send failed: {data}")
                return False
        except Exception as e:
            logger.error(f"[WeCom] Send error: {e}")
            return False

    async def listen(self) -> AsyncIterator[InboundMessage]:
        """Webhook 模式不需要此方法"""
        while self._running:
            await asyncio.sleep(1)
            if False:
                yield  # type: ignore

    async def health_check(self) -> ChannelStatus:
        """健康檢查"""
        if not self._client or not self._access_token:
            return ChannelStatus(
                platform=self.PLATFORM,
                is_connected=False,
                error="Not initialized",
            )

        return ChannelStatus(
            platform=self.PLATFORM,
            is_connected=True,
            last_heartbeat=datetime.now(timezone.utc),
            stats={
                "corp_id": self.corp_id,
                "agent_id": self.agent_id,
            },
        )
