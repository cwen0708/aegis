"""
頻道管理器 — 統一管理所有頻道的生命週期
"""
import asyncio
from typing import Optional
from .base import ChannelBase
from .bus import message_bus
from .router import message_router
from .types import ChannelStatus, OutboundMessage
import logging

logger = logging.getLogger(__name__)


class ChannelManager:
    """
    頻道管理器

    職責：
    - 註冊和管理頻道實例
    - 啟動/停止所有頻道
    - 健康檢查
    - 廣播訊息
    """

    def __init__(self):
        self.channels: dict[str, ChannelBase] = {}
        self._outbound_tasks: dict[str, asyncio.Task] = {}
        self._running = False

    def register(self, channel: ChannelBase):
        """
        註冊頻道實例

        Args:
            channel: 頻道實例（已配置）
        """
        self.channels[channel.PLATFORM] = channel
        logger.info(f"[Manager] Channel registered: {channel.PLATFORM}")

    async def start_all(self):
        """啟動所有頻道 + Bus + Router"""
        self._running = True

        # 先啟動 Bus
        await message_bus.start()

        # 再啟動 Router
        await message_router.start()

        # 最後啟動各頻道
        for name, channel in self.channels.items():
            try:
                await channel.start()
                # 啟動該頻道的 outbound 發送循環
                self._outbound_tasks[name] = asyncio.create_task(
                    self._outbound_loop(channel)
                )
                logger.info(f"[Manager] Channel started: {name}")
            except Exception as e:
                logger.error(f"[Manager] Failed to start {name}: {e}")

        logger.info(f"[Manager] All channels started ({len(self.channels)} total)")

    async def stop_all(self):
        """停止所有頻道 + Router + Bus"""
        self._running = False

        # 先停止 outbound 循環
        for name, task in self._outbound_tasks.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # 停止各頻道
        for name, channel in self.channels.items():
            try:
                await channel.stop()
                logger.info(f"[Manager] Channel stopped: {name}")
            except Exception as e:
                logger.error(f"[Manager] Failed to stop {name}: {e}")

        # 停止 Router
        await message_router.stop()

        # 最後停止 Bus
        await message_bus.stop()

        logger.info("[Manager] All channels stopped")

    async def _outbound_loop(self, channel: ChannelBase):
        """
        Outbound 發送循環（每個頻道一個）

        從 Bus 取訊息，發送到對應平台
        """
        while self._running:
            try:
                msg = await message_bus.consume_outbound(timeout=1.0)
                if not msg:
                    continue

                # 判斷是否發送到此頻道
                if msg.platform and msg.platform != channel.PLATFORM:
                    # 不是給這個頻道的，放回 queue
                    await message_bus.publish_outbound(msg)
                    await asyncio.sleep(0.1)  # 避免忙等
                    continue

                # 發送
                success = await channel.send(msg)
                if not success:
                    logger.warning(f"[Manager] Send failed: {channel.PLATFORM}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Manager] Outbound loop error: {e}")

    async def health_check_all(self) -> dict[str, ChannelStatus]:
        """所有頻道健康檢查"""
        results = {}
        for name, channel in self.channels.items():
            try:
                results[name] = await channel.health_check()
            except Exception as e:
                results[name] = ChannelStatus(
                    platform=name,
                    is_connected=False,
                    error=str(e),
                )
        return results

    async def broadcast(self, text: str, exclude: list[str] | None = None):
        """
        廣播訊息到所有頻道

        Args:
            text: 訊息文字
            exclude: 排除的頻道列表
        """
        exclude = exclude or []
        # TODO: 從 ChannelBinding 取得所有已綁定用戶
        # 目前只是示範架構
        logger.info(f"[Manager] Broadcast: {text[:50]}... (not implemented)")

    def get_channel(self, name: str) -> Optional[ChannelBase]:
        """取得頻道實例"""
        return self.channels.get(name)

    @property
    def active_channels(self) -> list[str]:
        """取得所有活躍頻道名稱"""
        return list(self.channels.keys())


# 全域 Manager 實例
channel_manager = ChannelManager()
