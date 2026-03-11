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
        self._email_digest_task: Optional[asyncio.Task] = None
        self._email_digest_interval_hours: int = 6

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

    # ===== Task Completion Report =====

    async def report_task_completion(
        self,
        card_id: int,
        output: str,
        status: str,
        duration_ms: int = 0,
        cost_usd: float = 0,
    ):
        """Card 完成時，檢查是否來自 OneStack，回報結果到 cli_tasks + ai_suggestions"""
        if not self.enabled:
            return

        import json as _json
        from sqlmodel import Session as DBSession
        from app.database import engine
        from app.models.core import CardIndex

        # 讀取 card 的 metadata
        onestack_task_id = None
        card_title = "Task"

        with DBSession(engine) as session:
            card = session.get(CardIndex, card_id)
            if not card:
                return
            card_title = card.title or card_title

            # CardIndex 可能沒有 metadata，從 tags_json 或其他欄位找
            # 實際 onestack_task_id 存在卡片建立時的 metadata 中
            # 由 /node/task 端點設定在 card 的 description 或 tags

        # 從 MD 檔讀 onestack_task_id（寫在 HTML comment 中）
        import re
        from app.models.core import Project
        from app.core.card_file import card_file_path

        with DBSession(engine) as session:
            project = session.get(Project, card.project_id) if card else None
            if not project or not project.path:
                return

        md_path = card_file_path(project.path, card_id)
        if md_path.exists():
            try:
                text = md_path.read_text(encoding="utf-8")
                # 從 HTML comment 中提取 onestack_task_id
                match = re.search(r'<!--\s*onestack_task_id:\s*(\S+)\s*-->', text)
                if match:
                    onestack_task_id = match.group(1)
            except Exception as e:
                logger.debug(f"[OneStack] Failed to parse card: {e}")

        if not onestack_task_id:
            return

        logger.info(f"[OneStack] Reporting task completion: {onestack_task_id}")

        # 1. 更新 cli_tasks 狀態
        task_status = "completed" if status == "success" else "failed"
        result_data = {
            "output": output[:5000] if output else "",
            "duration_ms": duration_ms,
            "cost_usd": cost_usd,
            "card_id": card_id,
        }
        error_msg = output[:1000] if status != "success" and output else None

        await self.update_task_status(
            onestack_task_id,
            task_status,
            result=result_data,
            error_message=error_msg,
        )

        # 2. 查 owner_id 並寫入 ai_suggestions
        task_data = await self._request(
            "GET",
            "cli_tasks",
            params={"id": f"eq.{onestack_task_id}", "select": "owner_id,title"}
        )

        owner_id = None
        if task_data and len(task_data) > 0:
            owner_id = task_data[0].get("owner_id")
            task_title = task_data[0].get("title") or card_title

        if owner_id:
            summary = output[:2000] if output else "（無輸出）"
            icon = "✓" if task_status == "completed" else "✗"
            await self._request(
                "POST",
                "ai_suggestions",
                json_data={
                    "owner_id": owner_id,
                    "device_id": self.device_id,
                    "suggestion_type": "task_result",
                    "title": f"{icon} {task_title}",
                    "content": summary,
                    "priority": "medium",
                    "source_task_id": onestack_task_id,
                    "metadata": {
                        "source": "aegis",
                        "card_id": card_id,
                        "status": task_status,
                        "duration_ms": duration_ms,
                        "cost_usd": cost_usd,
                    },
                }
            )
            logger.info(f"[OneStack] Task result reported: {task_title} ({task_status})")

    # ===== Email Digest Sync =====

    async def sync_email_digest(self):
        """批次同步未同步的高價值 email 到 OneStack ai_suggestions 表"""
        if not self.enabled:
            return

        from sqlmodel import Session as DBSession, select
        from app.database import engine
        from app.models.core import EmailMessage

        with DBSession(engine) as session:
            emails = session.exec(
                select(EmailMessage).where(
                    EmailMessage.is_processed == True,
                    EmailMessage.is_synced_to_onestack == False,
                    EmailMessage.category == "actionable",
                )
            ).all()

            if not emails:
                return

            synced_ids = []
            for email_msg in emails:
                result = await self._request(
                    "POST",
                    "ai_suggestions",
                    json_data={
                        "device_id": self.device_id,
                        "suggestion_type": "email_digest",
                        "title": f"[Email] {email_msg.subject[:80]}",
                        "content": (
                            f"From: {email_msg.from_name} <{email_msg.from_address}>\n"
                            f"Summary: {email_msg.summary}\n"
                            f"Action: {email_msg.suggested_action}"
                        ),
                        "priority": "high" if email_msg.urgency == "high" else "medium",
                        "metadata": {
                            "source": "aegis_email",
                            "email_message_id": email_msg.id,
                            "from_address": email_msg.from_address,
                            "subject": email_msg.subject,
                            "date": str(email_msg.date or ""),
                        },
                    }
                )
                if result is not None:
                    synced_ids.append(email_msg.id)

            # 標記已同步
            if synced_ids:
                for eid in synced_ids:
                    em = session.get(EmailMessage, eid)
                    if em:
                        em.is_synced_to_onestack = True
                session.commit()

            logger.info(f"[OneStack] Email digest synced: {len(synced_ids)} emails")

    async def _email_digest_loop(self):
        """定時 Email 摘要同步循環"""
        interval = self._email_digest_interval_hours * 3600
        while True:
            try:
                await asyncio.sleep(interval)
                await self.sync_email_digest()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[OneStack] Email digest error: {e}")

    def start_email_digest(self):
        """啟動 Email 摘要同步"""
        if not self.enabled:
            return
        if self._email_digest_task is None or self._email_digest_task.done():
            self._email_digest_task = asyncio.create_task(self._email_digest_loop())
            logger.info(f"[OneStack] Email digest started (every {self._email_digest_interval_hours}h)")

    def stop_email_digest(self):
        """停止 Email 摘要同步"""
        if self._email_digest_task and not self._email_digest_task.done():
            self._email_digest_task.cancel()
            logger.info("[OneStack] Email digest stopped")

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

        # 讀取 Email digest 設定
        try:
            import json as _json
            from sqlmodel import Session as _Ses
            from app.database import engine as _eng
            from app.models.core import SystemSetting as _SS
            with _Ses(_eng) as _s:
                setting = _s.get(_SS, "channel_email")
                if setting:
                    cfg = _json.loads(setting.value)
                    if cfg.get("onestack_digest_enabled"):
                        connector._email_digest_interval_hours = cfg.get("onestack_digest_interval_hours", 6)
                        connector.start_email_digest()
        except Exception as e:
            logger.debug(f"[OneStack] Email digest config not loaded: {e}")


async def stop_onestack_connector():
    """停止 OneStack 連接器"""
    if connector.enabled:
        connector.stop_email_digest()
        connector.stop_heartbeat()
        await connector.set_offline()
