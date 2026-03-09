"""
頻道抽象基類 — 定義所有頻道適配器必須實作的介面

參考: ZeroClaw Channel trait 設計
"""
from abc import ABC, abstractmethod
from typing import AsyncIterator
from .types import InboundMessage, OutboundMessage, ChannelStatus


class ChannelBase(ABC):
    """
    頻道抽象基類

    職責：
    - 平台連線管理 (start/stop)
    - 訊息格式翻譯 (平台格式 ↔ 統一格式)
    - 健康檢查

    不負責：
    - 命令解析（由 Router 處理）
    - 業務邏輯（由 Handler 處理）
    """

    PLATFORM: str = "unknown"

    @abstractmethod
    async def start(self) -> None:
        """
        啟動頻道連線

        實作須：
        - 初始化平台 SDK
        - 建立連線 (polling/webhook/gateway)
        - 開始監聽訊息
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """
        停止頻道

        實作須：
        - 優雅關閉連線
        - 清理資源
        - 取消背景任務
        """
        pass

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> str | bool:
        """
        發送訊息到平台

        Args:
            msg: 統一格式的外發訊息
                 - 若 edit_message_id 有值，則編輯該訊息

        Returns:
            成功時返回 message_id (str)，失敗返回 False

        實作須：
        - 將 OutboundMessage 翻譯為平台原生格式
        - 處理發送失敗（記錄日誌，不拋例外）
        - 支援 edit_message_id 欄位（編輯訊息）
        """
        pass

    @abstractmethod
    async def listen(self) -> AsyncIterator[InboundMessage]:
        """
        監聽平台訊息（可選實作）

        Yields:
            統一格式的入站訊息

        注意：
        - Polling 模式：此方法可用 async for 迭代
        - Webhook 模式：此方法可能為空實作（訊息由 webhook 端點處理）
        """
        pass

    @abstractmethod
    async def health_check(self) -> ChannelStatus:
        """
        健康檢查

        Returns:
            頻道狀態（連線狀態、錯誤訊息、統計資料）
        """
        pass
