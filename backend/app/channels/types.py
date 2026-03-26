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
    PHOTO = "photo"
    VOICE = "voice"
    AUDIO = "audio"
    DOCUMENT = "document"


class ParseMode(str, Enum):
    """文字解析模式"""
    PLAIN = "plain"
    MARKDOWN = "markdown"
    HTML = "html"


@dataclass
class Button:
    """互動按鈕（URL 或 callback 二選一）"""
    text: str
    callback_data: str = ""
    url: str = ""


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

    # 多模態支援
    media_type: Optional[str] = None   # "photo" | "voice" | "audio" | "document"
    media_path: Optional[str] = None   # 下載到本地的暫存路徑
    media_mime: Optional[str] = None   # MIME type（如 image/jpeg）
    caption: Optional[str] = None      # 圖片/檔案附帶的說明文字


@dataclass
class Attachment:
    """發送附件（圖片/檔案）"""
    type: str          # "photo" | "document" | "audio" | "voice"
    path: str          # 本地檔案路徑
    caption: str = ""  # 附帶說明


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

    # LINE Reply API token（免費，不計配額）
    reply_token: Optional[str] = None

    # 多模態附件
    attachments: list[Attachment] = field(default_factory=list)


@dataclass
class ChannelStatus:
    """頻道狀態"""
    platform: str
    is_connected: bool
    last_heartbeat: Optional[datetime] = None
    error: Optional[str] = None
    stats: dict = field(default_factory=dict)
