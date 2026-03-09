"""
統一訊息格式 — 平台無關的訊息定義

參考: Nanobot InboundMessage/OutboundMessage 設計
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum


class MessageType(str, Enum):
    """訊息類型"""
    TEXT = "text"
    COMMAND = "command"
    CALLBACK = "callback"  # 按鈕回調
    FILE = "file"


class ParseMode(str, Enum):
    """文字解析模式"""
    PLAIN = "plain"
    MARKDOWN = "markdown"
    HTML = "html"


@dataclass
class Button:
    """互動按鈕"""
    text: str
    callback_data: str


@dataclass
class InboundMessage:
    """
    來自任何頻道的訊息（統一格式）

    頻道適配器負責將平台原生格式轉換為此格式
    """
    id: str                          # 訊息 ID
    platform: str                    # telegram / line / discord
    user_id: str                     # 平台用戶 ID
    chat_id: str                     # 聊天室 ID
    text: str                        # 訊息內容
    timestamp: datetime
    message_type: MessageType = MessageType.TEXT
    reply_to_id: Optional[str] = None
    user_name: Optional[str] = None  # 顯示名稱
    raw_data: dict = field(default_factory=dict)  # 原始資料備查


@dataclass
class OutboundMessage:
    """
    發送到任何頻道的訊息（統一格式）

    Router 產生此格式，頻道適配器負責轉換為平台原生格式
    """
    chat_id: str
    text: str
    platform: Optional[str] = None   # None = 廣播到來源平台
    parse_mode: ParseMode = ParseMode.MARKDOWN
    reply_to_id: Optional[str] = None
    buttons: list[list[Button]] = field(default_factory=list)

    # 用於任務通知
    task_id: Optional[str] = None
    card_id: Optional[int] = None

    # 用於編輯訊息（先回再更新）
    edit_message_id: Optional[str] = None


@dataclass
class ChannelStatus:
    """頻道狀態"""
    platform: str
    is_connected: bool
    last_heartbeat: Optional[datetime] = None
    error: Optional[str] = None
    stats: dict = field(default_factory=dict)
