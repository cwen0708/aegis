"""
OneStack 連接器
可選功能：連接 OneStack 雲端服務，提供跨設備記憶同步和任務調度

環境變數：
- ONESTACK_ENABLED: 是否啟用（預設 false）
- ONESTACK_SUPABASE_URL: OneStack Supabase URL
- ONESTACK_SUPABASE_KEY: OneStack Supabase Service Role Key
- ONESTACK_DEVICE_ID: 此 Aegis 實例的設備 ID
- ONESTACK_DEVICE_NAME: 設備名稱（如 "辦公室1"）
"""
import os
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

# 配置
ONESTACK_ENABLED = os.getenv("ONESTACK_ENABLED", "false").lower() == "true"
ONESTACK_SUPABASE_URL = os.getenv("ONESTACK_SUPABASE_URL", "")
ONESTACK_SUPABASE_KEY = os.getenv("ONESTACK_SUPABASE_KEY", "")
ONESTACK_DEVICE_ID = os.getenv("ONESTACK_DEVICE_ID", "")
ONESTACK_DEVICE_NAME = os.getenv("ONESTACK_DEVICE_NAME", "Aegis")

# 心跳間隔（秒）
HEARTBEAT_INTERVAL = 60


class OneStackConnector:
    """OneStack 連接器"""

    def __init__(self):
        self.enabled = ONESTACK_ENABLED
        self.supabase_url = ONESTACK_SUPABASE_URL
        self.supabase_key = ONESTACK_SUPABASE_KEY
        self.device_id = ONESTACK_DEVICE_ID
        self.device_name = ONESTACK_DEVICE_NAME
        self._heartbeat_task: Optional[asyncio.Task] = None

        if self.enabled:
            if not self.supabase_url or not self.supabase_key:
                logger.warning("[OneStack] Enabled but missing SUPABASE_URL or SUPABASE_KEY")
                self.enabled = False
            elif not self.device_id:
                logger.warning("[OneStack] Enabled but missing DEVICE_ID")
                self.enabled = False
            else:
                logger.info(f"[OneStack] Connector initialized for device: {self.device_name}")

    async def _request(
        self,
        method: str,
        table: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None
    ) -> Optional[Dict]:
        """發送請求到 Supabase REST API"""
        import httpx

        url = f"{self.supabase_url}/rest/v1/{table}"
        headers = {
            "apikey": self.supabase_key,
            "Authorization": f"Bearer {self.supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal" if method in ["PATCH", "DELETE"] else "return=representation",
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                if method == "GET":
                    resp = await client.get(url, headers=headers, params=params)
                elif method == "POST":
                    resp = await client.post(url, headers=headers, json=json_data)
                elif method == "PATCH":
                    resp = await client.patch(url, headers=headers, params=params, json=json_data)
                elif method == "DELETE":
                    resp = await client.delete(url, headers=headers, params=params)
                else:
                    return None

                if resp.status_code >= 400:
                    logger.error(f"[OneStack] {method} {table} failed: {resp.status_code} {resp.text}")
                    return None

                if resp.status_code == 204 or not resp.text:
                    return {}

                return resp.json()

        except Exception as e:
            logger.error(f"[OneStack] Request error: {e}")
            return None

    def _get_metadata(self) -> Dict[str, Any]:
        """取得設備元資料"""
        from app.core.telemetry import get_system_metrics

        # 讀取版本
        version = "unknown"
        version_file = Path(__file__).parent.parent.parent / "VERSION"
        if version_file.exists():
            version = version_file.read_text().strip()

        # 取得運行狀態
        try:
            from sqlmodel import Session, select
            from app.database import engine
            from app.models.core import CardIndex, SystemSetting

            with Session(engine) as session:
                running_count = len(list(session.exec(
                    select(CardIndex).where(CardIndex.status == "running")
                ).all()))

                max_ws_setting = session.get(SystemSetting, "max_workstations")
                max_workstations = int(max_ws_setting.value) if max_ws_setting else 3
        except Exception:
            running_count = 0
            max_workstations = 3

        # 系統指標
        try:
            metrics = get_system_metrics()
        except Exception:
            metrics = {"cpu_percent": 0, "memory_percent": 0}

        return {
            "type": "aegis",
            "version": version,
            "providers": ["claude", "gemini"],
            "max_workstations": max_workstations,
            "current_workstations": running_count,
            "cpu_percent": metrics.get("cpu_percent", 0),
            "memory_percent": metrics.get("memory_percent", 0),
        }

    async def send_heartbeat(self):
        """發送心跳到 OneStack cli_devices 表"""
        if not self.enabled:
            return

        metadata = self._get_metadata()

        result = await self._request(
            "PATCH",
            "cli_devices",
            params={"id": f"eq.{self.device_id}"},
            json_data={
                "status": "online",
                "last_heartbeat": datetime.now(timezone.utc).isoformat(),
                "metadata": metadata,
            }
        )

        if result is not None:
            logger.debug(f"[OneStack] Heartbeat sent: {self.device_name}")

    async def register_device(self):
        """註冊設備（首次啟動時）"""
        if not self.enabled:
            return

        # 檢查設備是否存在
        result = await self._request(
            "GET",
            "cli_devices",
            params={"id": f"eq.{self.device_id}", "select": "id"}
        )

        if result and len(result) > 0:
            logger.info(f"[OneStack] Device already registered: {self.device_id}")
            return

        # 註冊新設備
        metadata = self._get_metadata()
        endpoint = os.getenv("AEGIS_PUBLIC_URL", "http://localhost:8899")

        result = await self._request(
            "POST",
            "cli_devices",
            json_data={
                "id": self.device_id,
                "device_name": self.device_name,
                "endpoint": endpoint,
                "status": "online",
                "last_heartbeat": datetime.now(timezone.utc).isoformat(),
                "metadata": metadata,
            }
        )

        if result is not None:
            logger.info(f"[OneStack] Device registered: {self.device_name}")

    async def poll_tasks(self) -> List[Dict]:
        """從 OneStack 取得待處理任務"""
        if not self.enabled:
            return []

        result = await self._request(
            "GET",
            "cli_tasks",
            params={
                "device_id": f"eq.{self.device_id}",
                "status": "eq.pending",
                "order": "created_at.asc",
                "limit": "5",
            }
        )

        return result if result else []

    async def update_task_status(
        self,
        task_id: str,
        status: str,
        result: Optional[Dict] = None,
        error_message: Optional[str] = None
    ):
        """更新任務狀態"""
        if not self.enabled:
            return

        data = {
            "status": status,
        }

        if status == "processing":
            data["started_at"] = datetime.now(timezone.utc).isoformat()
        elif status in ["completed", "failed"]:
            data["completed_at"] = datetime.now(timezone.utc).isoformat()

        if result:
            data["result"] = result
        if error_message:
            data["error_message"] = error_message

        await self._request(
            "PATCH",
            "cli_tasks",
            params={"id": f"eq.{task_id}"},
            json_data=data
        )

    async def sync_memory(self, member_slug: str, content: str, memory_type: str = "short_term"):
        """同步成員記憶到 OneStack"""
        if not self.enabled:
            return

        # 使用 ai_suggestions 表儲存記憶（或可另建表）
        await self._request(
            "POST",
            "ai_suggestions",
            json_data={
                "device_id": self.device_id,
                "suggestion_type": "insight",
                "title": f"Memory: {member_slug} ({memory_type})",
                "content": content,
                "priority": "low",
                "metadata": {
                    "source": "aegis_memory",
                    "member_slug": member_slug,
                    "memory_type": memory_type,
                }
            }
        )

    async def sync_daily_stats(self, stats: Dict[str, Any]):
        """同步每日統計"""
        if not self.enabled:
            return

        await self._request(
            "POST",
            "cli_device_daily_stats",
            json_data={
                "device_id": self.device_id,
                "date": datetime.now(timezone.utc).date().isoformat(),
                **stats
            }
        )

    async def set_offline(self):
        """設定設備為離線狀態"""
        if not self.enabled:
            return

        await self._request(
            "PATCH",
            "cli_devices",
            params={"id": f"eq.{self.device_id}"},
            json_data={"status": "offline"}
        )
        logger.info(f"[OneStack] Device set to offline: {self.device_name}")

    async def _heartbeat_loop(self):
        """心跳循環"""
        while True:
            try:
                await self.send_heartbeat()
            except Exception as e:
                logger.error(f"[OneStack] Heartbeat error: {e}")
            await asyncio.sleep(HEARTBEAT_INTERVAL)

    def start_heartbeat(self):
        """啟動心跳任務"""
        if not self.enabled:
            return

        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            logger.info("[OneStack] Heartbeat started")

    def stop_heartbeat(self):
        """停止心跳任務"""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            logger.info("[OneStack] Heartbeat stopped")


# 全域實例
connector = OneStackConnector()


async def start_onestack_connector():
    """啟動 OneStack 連接器（供 main.py 呼叫）"""
    if connector.enabled:
        await connector.register_device()
        connector.start_heartbeat()


async def stop_onestack_connector():
    """停止 OneStack 連接器"""
    if connector.enabled:
        connector.stop_heartbeat()
        await connector.set_offline()
