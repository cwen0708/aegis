"""
Aegis 多頻道通訊模組

架構：
    Channels → Message Bus → Router → Core

Usage:
    from app.channels import channel_manager
    from app.channels.adapters.telegram import TelegramChannel

    channel_manager.register(TelegramChannel(token="..."))
    await channel_manager.start_all()
"""

from .types import (
    InboundMessage,
    OutboundMessage,
    ChannelStatus,
    MessageType,
    ParseMode,
    Button,
)
from .base import ChannelBase
from .registry import register_channel, create_channel, list_channels
from .bus import message_bus, MessageBus
from .router import message_router, MessageRouter
from .manager import channel_manager, ChannelManager

__all__ = [
    "InboundMessage",
    "OutboundMessage",
    "ChannelStatus",
    "MessageType",
    "ParseMode",
    "Button",
    "ChannelBase",
    "register_channel",
    "create_channel",
    "list_channels",
    "message_bus",
    "MessageBus",
    "message_router",
    "MessageRouter",
    "channel_manager",
    "ChannelManager",
]
