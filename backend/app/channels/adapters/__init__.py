"""頻道適配器"""
# 匯入時自動註冊頻道
from .telegram import TelegramChannel
from .line import LineChannel
from .discord import DiscordChannel
from .slack import SlackChannel
from .wecom import WeComChannel
from .feishu import FeishuChannel

__all__ = [
    "TelegramChannel",
    "LineChannel",
    "DiscordChannel",
    "SlackChannel",
    "WeComChannel",
    "FeishuChannel",
]
