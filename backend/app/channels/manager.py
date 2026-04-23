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

    @property
    def _channels(self) -> list[ChannelBase]:
        """取得所有頻道實例（供 webhook 使用）"""
        return list(self.channels.values())

    async def start_channel(self, name: str) -> bool:
        """
        啟動單一已註冊頻道

        Args:
            name: 頻道名稱（對應 ChannelBase.PLATFORM）

        Returns:
            True 代表成功啟動或已在運行；False 代表未知 channel
        """
        channel = self.channels.get(name)
        if channel is None:
            logger.warning(f"[Manager] start_channel: unknown channel '{name}'")
            return False

        # 已有 outbound task 視為已啟動，冪等 no-op
        existing = self._outbound_tasks.get(name)
        if existing and not existing.done():
            logger.info(f"[Manager] start_channel: '{name}' already running, skip")
            return True

        # 確保 _running 為 True，outbound loop 才不會立即結束
        self._running = True

        try:
            await channel.start()
            self._outbound_tasks[name] = asyncio.create_task(
                self._outbound_loop(channel)
            )
            logger.info(f"[Manager] Channel started: {name}")
            return True
        except Exception as e:
            logger.error(f"[Manager] Failed to start {name}: {e}")
            return False

    async def stop_channel(self, name: str) -> bool:
        """
        停止單一頻道（cancel outbound task、呼叫 channel.stop()）

        Args:
            name: 頻道名稱

        Returns:
            True 代表成功停止；False 代表未知 channel
        """
        channel = self.channels.get(name)
        if channel is None:
            logger.warning(f"[Manager] stop_channel: unknown channel '{name}'")
            return False

        # 先取消 outbound task
        task = self._outbound_tasks.pop(name, None)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"[Manager] outbound task for '{name}' ended with: {e}")

        try:
            await channel.stop()
            logger.info(f"[Manager] Channel stopped: {name}")
            return True
        except Exception as e:
            logger.error(f"[Manager] Failed to stop {name}: {e}")
            return False

    async def restart_all(self):
        """重啟所有頻道（停止 → 清空 → 重新載入 → 啟動）"""
        logger.info("[Manager] Restarting all channels...")

        # 停止現有頻道
        await self.stop_all()

        # 清空頻道列表
        self.channels.clear()
        self._outbound_tasks.clear()

        # 重新載入設定並註冊頻道（延遲 import 避免循環引用）
        from app.main import _register_channels_from_config
        await _register_channels_from_config()

        # 重新啟動
        await self.start_all()

        logger.info(f"[Manager] Restart complete, {len(self.channels)} channels active")
        return len(self.channels)


# 全域 Manager 實例
channel_manager = ChannelManager()
