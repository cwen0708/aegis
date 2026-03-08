"""
Discord 頻道適配器

使用 discord.py (Gateway/WebSocket 模式)
"""
import discord
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


@register_channel("discord")
class DiscordChannel(ChannelBase):
    """
    Discord 頻道適配器

    使用 Gateway 模式（WebSocket 長連線）
    需要在 Discord Developer Portal 建立 Bot 並取得 Token
    需要啟用 Message Content Intent
    """

    PLATFORM = "discord"

    def __init__(self, token: str, command_prefix: str = "/"):
        """
        Args:
            token: Discord Bot Token
            command_prefix: 命令前綴（預設 /）
        """
        self.token = token
        self.command_prefix = command_prefix
        self._running = False
        self._task: asyncio.Task | None = None

        # 設定 Intents
        intents = discord.Intents.default()
        intents.message_content = True  # 需要在 Developer Portal 啟用

        self.client = discord.Client(intents=intents)
        self._setup_handlers()

    def _setup_handlers(self):
        """設定事件處理器"""

        @self.client.event
        async def on_ready():
            logger.info(f"[Discord] Bot ready: {self.client.user}")

        @self.client.event
        async def on_message(message: discord.Message):
            # 忽略 Bot 自己的訊息
            if message.author.bot:
                return

            # 翻譯為統一格式
            msg = InboundMessage(
                id=str(message.id),
                platform=self.PLATFORM,
                user_id=str(message.author.id),
                chat_id=str(message.channel.id),
                text=message.content,
                timestamp=datetime.now(timezone.utc),
                message_type=(
                    MessageType.COMMAND
                    if message.content.startswith(self.command_prefix)
                    else MessageType.TEXT
                ),
                user_name=message.author.display_name,
                raw_data={
                    "guild_id": str(message.guild.id) if message.guild else None,
                    "channel_name": getattr(message.channel, "name", None),
                },
            )
            await message_bus.publish_inbound(msg)

    async def start(self):
        """啟動 Discord Bot（背景執行）"""
        self._running = True
        self._task = asyncio.create_task(self._run_bot())

        # 等待連線建立（最多 30 秒）
        for _ in range(60):
            if self.client.is_ready():
                break
            await asyncio.sleep(0.5)

        logger.info("[Discord] Channel started")

    async def _run_bot(self):
        """Bot 執行循環"""
        try:
            await self.client.start(self.token)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[Discord] Bot error: {e}")

    async def stop(self):
        """停止 Discord Bot"""
        self._running = False
        await self.client.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[Discord] Channel stopped")

    async def send(self, msg: OutboundMessage) -> bool:
        """發送訊息到指定頻道"""
        try:
            channel = self.client.get_channel(int(msg.chat_id))
            if channel and hasattr(channel, "send"):
                await channel.send(msg.text)
                return True
            else:
                logger.warning(f"[Discord] Channel not found: {msg.chat_id}")
                return False
        except Exception as e:
            logger.error(f"[Discord] Send failed: {e}")
            return False

    async def listen(self) -> AsyncIterator[InboundMessage]:
        """Gateway 模式由 on_message 處理"""
        while self._running:
            await asyncio.sleep(1)
            if False:
                yield  # type: ignore

    async def health_check(self) -> ChannelStatus:
        """健康檢查"""
        if not self.client.is_ready():
            return ChannelStatus(
                platform=self.PLATFORM,
                is_connected=False,
                error="Client not ready",
            )

        return ChannelStatus(
            platform=self.PLATFORM,
            is_connected=True,
            last_heartbeat=datetime.now(timezone.utc),
            stats={
                "bot_id": self.client.user.id if self.client.user else None,
                "bot_name": self.client.user.name if self.client.user else None,
                "guilds": len(self.client.guilds),
            },
        )
