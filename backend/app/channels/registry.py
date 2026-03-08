"""
頻道註冊表 — Factory Pattern 實作

參考: PicoClaw channel registry 設計
"""
from typing import Type
from .base import ChannelBase
import logging

logger = logging.getLogger(__name__)

# 全域註冊表
_CHANNEL_REGISTRY: dict[str, Type[ChannelBase]] = {}


def register_channel(name: str):
    """
    裝飾器：註冊頻道類別

    Usage:
        @register_channel("telegram")
        class TelegramChannel(ChannelBase):
            ...
    """
    def decorator(cls: Type[ChannelBase]):
        _CHANNEL_REGISTRY[name] = cls
        cls.PLATFORM = name
        logger.info(f"Channel registered: {name}")
        return cls
    return decorator


def create_channel(name: str, **config) -> ChannelBase:
    """
    工廠函數：建立頻道實例

    Args:
        name: 頻道名稱 (telegram/line/discord)
        **config: 頻道配置參數

    Returns:
        頻道實例

    Raises:
        ValueError: 未知的頻道名稱
    """
    if name not in _CHANNEL_REGISTRY:
        available = ", ".join(_CHANNEL_REGISTRY.keys()) or "(none)"
        raise ValueError(f"Unknown channel: {name}. Available: {available}")
    return _CHANNEL_REGISTRY[name](**config)


def list_channels() -> list[str]:
    """列出所有已註冊頻道"""
    return list(_CHANNEL_REGISTRY.keys())


def get_channel_class(name: str) -> Type[ChannelBase] | None:
    """取得頻道類別（不建立實例）"""
    return _CHANNEL_REGISTRY.get(name)
