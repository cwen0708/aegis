"""
統一 HTTP 客戶端 — 內部 API 呼叫
避免各模組重複建立 urllib/httpx 連線
"""
import json
import logging
import threading
import urllib.request
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

API_BASE = "http://127.0.0.1:8899/api/v1"


class InternalAPI:
    """同步呼叫 127.0.0.1:8899 內部 API（適用 Worker thread）"""

    @staticmethod
    def post(path: str, data: dict, timeout: int = 5) -> Optional[dict]:
        """POST JSON，回傳 response dict 或 None"""
        try:
            body = json.dumps(data).encode("utf-8")
            req = urllib.request.Request(
                f"{API_BASE}/{path.lstrip('/')}",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=timeout)
            return json.loads(resp.read())
        except Exception as e:
            logger.warning("[InternalAPI] POST %s failed: %s", path, e)
            return None

    @staticmethod
    def broadcast_log(card_id: int, line: str, structured_data: Optional[Dict[str, Any]] = None) -> None:
        """Worker 廣播 task log 到 FastAPI（WS + OneStack 轉發）"""
        payload = {"card_id": card_id, "line": line}
        if structured_data is not None:
            payload["structured_data"] = structured_data
        InternalAPI.post("internal/broadcast-log", payload)

    @staticmethod
    def broadcast_event(event_type: str, payload: dict):
        """Worker 廣播 WS 事件"""
        InternalAPI.post("internal/broadcast-event", {"event": event_type, "payload": payload})

    @staticmethod
    def channel_send(platform: str, chat_id: str, text: str, edit_message_id: str = None):
        """發送/編輯 channel 訊息（同步，適用 Worker thread）"""
        data = {"platform": platform, "chat_id": chat_id, "text": text}
        if edit_message_id:
            data["edit_message_id"] = edit_message_id
        InternalAPI.post("internal/channel-send", data, timeout=10)

    @staticmethod
    def channel_send_file(platform: str, chat_id: str, file_path: str, caption: str = ""):
        """發送檔案到 channel（同步，適用 Worker thread / Hook）"""
        data = {"platform": platform, "chat_id": chat_id, "file_path": file_path, "caption": caption}
        InternalAPI.post("internal/channel-send-file", data, timeout=30)

    @staticmethod
    def channel_send_async(platform: str, chat_id: str, text: str, edit_message_id: str = None):
        """非阻塞發送（用 thread，適用 Runner stdout 讀取迴圈）"""
        threading.Thread(
            target=InternalAPI.channel_send,
            args=(platform, chat_id, text, edit_message_id),
            daemon=True,
        ).start()


class InternalAPIAsync:
    """非同步呼叫內部 API（適用 FastAPI / chat_handler）"""

    @staticmethod
    async def channel_send(platform: str, chat_id: str, text: str, edit_message_id: str = None):
        """非同步發送/編輯 channel 訊息"""
        try:
            import httpx
            data = {"platform": platform, "chat_id": chat_id, "text": text}
            if edit_message_id:
                data["edit_message_id"] = edit_message_id
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(f"{API_BASE}/internal/channel-send", json=data)
        except Exception as e:
            logger.warning("[InternalAPIAsync] channel_send failed: %s", e)
