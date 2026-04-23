"""
ChannelManager per-channel 啟停測試 (P2-MA-12 step 1)

驗證 start_channel() / stop_channel() 行為：
- 只影響指定 channel，其他 channel 不受波及
- 未知 channel 回 False（不拋例外）
- 已 running 再 start 具有冪等性
- stop 會清掉對應 outbound task
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.channels.manager import ChannelManager
from app.channels.types import ChannelStatus


def _make_fake_channel(platform: str):
    """建立假的 ChannelBase — 只需要滿足 manager 用到的方法"""
    channel = MagicMock()
    channel.PLATFORM = platform
    channel.start = AsyncMock(return_value=None)
    channel.stop = AsyncMock(return_value=None)
    channel.send = AsyncMock(return_value=True)
    channel.health_check = AsyncMock(
        return_value=ChannelStatus(platform=platform, is_connected=True)
    )
    return channel


@pytest.fixture
async def manager_with_channels(monkeypatch):
    """建立已註冊 telegram + line 兩個假頻道的 manager（尚未 start_all）"""
    # 避免真的啟動 bus/router
    from app.channels import manager as manager_module

    async def _idle_consume(*args, **kwargs):
        # 保留 yield 點，讓 outbound_loop 能被 cancel
        await asyncio.sleep(0.01)
        return None

    fake_bus = MagicMock()
    fake_bus.start = AsyncMock()
    fake_bus.stop = AsyncMock()
    fake_bus.consume_outbound = AsyncMock(side_effect=_idle_consume)
    fake_bus.publish_outbound = AsyncMock()
    monkeypatch.setattr(manager_module, "message_bus", fake_bus)

    fake_router = MagicMock()
    fake_router.start = AsyncMock()
    fake_router.stop = AsyncMock()
    monkeypatch.setattr(manager_module, "message_router", fake_router)

    manager = ChannelManager()
    manager.register(_make_fake_channel("telegram"))
    manager.register(_make_fake_channel("line"))
    # 模擬 start_all 後的狀態（_running = True，但不真的啟動所有 channel）
    manager._running = True
    yield manager
    # 清理：取消殘留 outbound tasks
    for task in list(manager._outbound_tasks.values()):
        task.cancel()
    for task in list(manager._outbound_tasks.values()):
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


@pytest.mark.asyncio
async def test_start_channel_by_name(manager_with_channels):
    """start_channel("telegram") 只啟動該頻道，line 不受影響"""
    m = manager_with_channels
    result = await m.start_channel("telegram")

    assert result is True
    m.channels["telegram"].start.assert_awaited_once()
    m.channels["line"].start.assert_not_called()
    assert "telegram" in m._outbound_tasks
    assert "line" not in m._outbound_tasks


@pytest.mark.asyncio
async def test_stop_channel_by_name(manager_with_channels):
    """stop_channel 只停指定頻道；其他 channel 的 outbound task 仍存在"""
    m = manager_with_channels
    # 先把兩個都啟動
    await m.start_channel("telegram")
    await m.start_channel("line")
    assert "telegram" in m._outbound_tasks
    assert "line" in m._outbound_tasks

    # 只停 telegram
    result = await m.stop_channel("telegram")

    assert result is True
    m.channels["telegram"].stop.assert_awaited_once()
    m.channels["line"].stop.assert_not_called()
    assert "telegram" not in m._outbound_tasks
    assert "line" in m._outbound_tasks


@pytest.mark.asyncio
async def test_start_channel_unknown(manager_with_channels):
    """未註冊的 channel 回 False（不拋例外）"""
    m = manager_with_channels
    result = await m.start_channel("not_exist")

    assert result is False
    assert "not_exist" not in m._outbound_tasks


@pytest.mark.asyncio
async def test_start_channel_idempotent(manager_with_channels):
    """已有 outbound task 再 start 不會重複建 task"""
    m = manager_with_channels
    await m.start_channel("telegram")
    first_task = m._outbound_tasks["telegram"]

    result = await m.start_channel("telegram")

    assert result is True
    # 同一個 task，沒有重建
    assert m._outbound_tasks["telegram"] is first_task
    # channel.start() 只被呼叫一次
    assert m.channels["telegram"].start.await_count == 1


@pytest.mark.asyncio
async def test_stop_channel_cleans_outbound_task(manager_with_channels):
    """stop_channel 後 _outbound_tasks[name] 被 cancel 並 pop"""
    m = manager_with_channels
    await m.start_channel("telegram")
    task = m._outbound_tasks["telegram"]

    await m.stop_channel("telegram")

    assert "telegram" not in m._outbound_tasks
    assert task.cancelled() or task.done()
