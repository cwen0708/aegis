"""
OneStack 連接器
可選功能：連接 OneStack 雲端服務，提供跨設備記憶同步和任務調度

環境變數：
- ONESTACK_ENABLED: 是否啟用（預設 false）
- ONESTACK_SUPABASE_URL: OneStack Supabase URL
- ONESTACK_SUPABASE_ANON_KEY: OneStack Supabase Anon Key（不再需要 service_role）
- ONESTACK_DEVICE_NAME: 設備名稱（如 "辦公室1"，預設 "Aegis"）

自動管理（不需手動設定）：
- device_id: 首次啟動自動註冊，存在 .aegis/onestack_device.json
- device_token: 註冊時由 Supabase 產生，存在同一檔案
"""
import os
import time
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

# 配置
ONESTACK_ENABLED = os.getenv("ONESTACK_ENABLED", "false").lower() == "true"
# OneStack Supabase 預設值（所有 Aegis 實例共用同一個）
_DEFAULT_URL = "https://avioqoteujivjkpnvyyo.supabase.co"
_DEFAULT_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImF2aW9xb3RldWppdmprcG52eXlvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjY3Mjk1MzYsImV4cCI6MjA4MjMwNTUzNn0.PcoN9eQIJwK3cgMoWls-N9NObzoWDR_JWJH_ULVmTO4"

ONESTACK_SUPABASE_URL = os.getenv("ONESTACK_SUPABASE_URL", _DEFAULT_URL)
ONESTACK_SUPABASE_ANON_KEY = os.getenv("ONESTACK_SUPABASE_ANON_KEY", _DEFAULT_KEY)
# 向後相容：舊 env var 名稱
if ONESTACK_SUPABASE_ANON_KEY == _DEFAULT_KEY:
    env_key = os.getenv("ONESTACK_SUPABASE_KEY", "")
    if env_key:
        ONESTACK_SUPABASE_ANON_KEY = env_key
ONESTACK_DEVICE_NAME = os.getenv("ONESTACK_DEVICE_NAME", "Aegis")
# 預設裝置認證（從 OneStack 設定頁取得）
ONESTACK_DEVICE_ID = os.getenv("ONESTACK_DEVICE_ID", "")
ONESTACK_DEVICE_TOKEN = os.getenv("ONESTACK_DEVICE_TOKEN", "")

# 裝置認證檔案路徑
DEVICE_CREDENTIALS_FILE = Path(__file__).parent.parent.parent / ".aegis" / "onestack_device.json"

# 心跳間隔（秒）
HEARTBEAT_INTERVAL = 60
# 任務輪詢間隔（秒）— 未來改 Realtime 後可移除
POLL_INTERVAL = 15


class OneStackConnector:
    """OneStack 連接器（anon key + device_token 認證）"""

    def __init__(self):
        self.enabled = ONESTACK_ENABLED
        self.supabase_url = ONESTACK_SUPABASE_URL
        self.supabase_key = ONESTACK_SUPABASE_ANON_KEY
        self.device_name = ONESTACK_DEVICE_NAME
        self.device_id: Optional[str] = None
        self.device_token: Optional[str] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._catalog_task: Optional[asyncio.Task] = None
        self._email_digest_task: Optional[asyncio.Task] = None
        self._email_digest_interval_hours: int = 6
        self._task_callback = None  # 外部註冊的任務回調

        # 認證來源：env / file / auto
        self._credentials_source: Optional[str] = None

        # 優先順序：Env Vars > 本地檔案
        if ONESTACK_DEVICE_ID and ONESTACK_DEVICE_TOKEN:
            self.device_id = ONESTACK_DEVICE_ID
            self.device_token = ONESTACK_DEVICE_TOKEN
            self._credentials_source = "env"
        else:
            self._load_device_credentials()
            self._credentials_source = "file" if self.device_id else None

        # 有 credentials 就自動啟用（不需要 ONESTACK_ENABLED=true）
        if self.device_id and self.device_token:
            self.enabled = True
            logger.info(f"[OneStack] Connector initialized: {self.device_name} ({self.device_id[:8]}...) [source={self._credentials_source}]")
        elif self.enabled:
            logger.info(f"[OneStack] Connector enabled but no credentials (等待配對)")
        else:
            logger.debug("[OneStack] Connector disabled")

    # ─── 裝置認證管理 ───

    def _load_device_credentials(self):
        """從本地檔案載入裝置認證"""
        if DEVICE_CREDENTIALS_FILE.exists():
            try:
                data = json.loads(DEVICE_CREDENTIALS_FILE.read_text(encoding="utf-8"))
                self.device_id = data.get("device_id")
                self.device_token = data.get("device_token")
                if self.device_id and self.device_token:
                    logger.debug(f"[OneStack] Loaded device credentials: {self.device_id[:8]}...")
            except Exception as e:
                logger.warning(f"[OneStack] Failed to load credentials: {e}")

    def _save_device_credentials(self):
        """儲存裝置認證到本地檔案"""
        try:
            DEVICE_CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
            DEVICE_CREDENTIALS_FILE.write_text(
                json.dumps({
                    "device_id": self.device_id,
                    "device_token": self.device_token,
                    "device_name": self.device_name,
                    "supabase_url": self.supabase_url,
                    "registered_at": datetime.now(timezone.utc).isoformat(),
                }, indent=2),
                encoding="utf-8",
            )
            logger.info(f"[OneStack] Device credentials saved to {DEVICE_CREDENTIALS_FILE}")
        except Exception as e:
            logger.error(f"[OneStack] Failed to save credentials: {e}")

    # ─── HTTP 請求 ───

    def _make_headers(self, prefer: str = "return=representation") -> Dict[str, str]:
        """建立 HTTP headers（含 device 認證）"""
        headers = {
            "apikey": self.supabase_key,
            "Authorization": f"Bearer {self.supabase_key}",
            "Content-Type": "application/json",
            "Prefer": prefer,
        }
        # 裝置認證 headers（用於 RLS policy 驗證）
        if self.device_id:
            headers["x-device-id"] = self.device_id
        if self.device_token:
            headers["x-device-token"] = self.device_token
        return headers

    async def _request(
        self,
        method: str,
        table: str,
        params: Optional[Dict] = None,
        json_data: Optional[Any] = None,
        prefer_override: Optional[str] = None,
    ) -> Optional[Any]:
        """發送請求到 Supabase REST API"""
        import httpx

        url = f"{self.supabase_url}/rest/v1/{table}"
        prefer = prefer_override or ("return=minimal" if method in ["PATCH", "DELETE"] else "return=representation")
        headers = self._make_headers(prefer)

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

    async def _rpc(self, function_name: str, params: Dict) -> Optional[Any]:
        """呼叫 Supabase RPC 函式"""
        import httpx

        url = f"{self.supabase_url}/rest/v1/rpc/{function_name}"
        headers = self._make_headers()

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, headers=headers, json=params)
                if resp.status_code >= 400:
                    logger.error(f"[OneStack] RPC {function_name} failed: {resp.status_code} {resp.text}")
                    return None
                return resp.json() if resp.text else {}
        except Exception as e:
            logger.error(f"[OneStack] RPC error: {e}")
            return None

    # ─── 裝置註冊 ───

    async def register_device(self):
        """首次啟動時自動註冊裝置，取得 device_id + device_token"""
        if not self.enabled:
            return

        # 已有認證，驗證是否有效
        if self.device_id and self.device_token:
            result = await self._request(
                "GET",
                "cli_devices",
                params={"id": f"eq.{self.device_id}", "select": "id,device_name"}
            )
            if result and len(result) > 0:
                logger.info(f"[OneStack] Device verified: {self.device_id[:8]}... (source: {self._credentials_source})")
                return
            else:
                if self._credentials_source == "env":
                    # Env var 指定的裝置不存在 → 致命錯誤
                    logger.error("[OneStack] Env var device credentials invalid! Check ONESTACK_DEVICE_ID/TOKEN")
                    self.enabled = False
                    return
                logger.warning("[OneStack] Saved credentials invalid, re-registering...")

        # 自動註冊（僅 file/auto 來源）
        metadata = self._get_metadata()
        result = await self._rpc("register_device", {
            "p_device_name": self.device_name,
            "p_metadata": metadata,
        })

        if result and isinstance(result, dict):
            self.device_id = result.get("device_id")
            self.device_token = result.get("device_token")
            if self.device_id and self.device_token:
                self._credentials_source = "auto"
                self._save_device_credentials()
                logger.info(f"[OneStack] Device registered: {self.device_id[:8]}... ({self.device_name})")
            else:
                logger.error(f"[OneStack] Registration returned unexpected data: {result}")
                self.enabled = False
        else:
            logger.error("[OneStack] Device registration failed")
            self.enabled = False

    # ─── 元資料 ───

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

    # ─── 心跳 ───

    async def send_heartbeat(self):
        """發送心跳到 OneStack cli_devices 表"""
        if not self.enabled or not self.device_id:
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

    # ─── 目錄同步（成員 + 專案 → Supabase） ───

    CATALOG_SYNC_INTERVAL = 300  # 5 分鐘

    async def sync_catalog(self):
        """全量同步成員 + 專案目錄到 OneStack Supabase"""
        if not self.enabled or not self.device_id:
            return
        try:
            await self._sync_members()
            await self._sync_projects()
            logger.debug("[OneStack] Catalog synced")
        except Exception as e:
            logger.error(f"[OneStack] Catalog sync error: {e}")

    async def _sync_members(self):
        """UPSERT 成員列表"""
        from sqlmodel import Session, select
        from app.database import engine
        from app.models.core import Member

        with Session(engine) as session:
            members = session.exec(select(Member)).all()

        now = datetime.now(timezone.utc).isoformat()
        rows = [
            {
                "device_id": self.device_id,
                "aegis_member_id": m.id,
                "name": m.name,
                "slug": m.slug,
                "avatar": m.avatar or "",
                "role": m.role or "",
                "description": m.description or "",
                "portrait_url": m.portrait or "",
                "sprite_sheet_url": m.sprite_sheet or "",
                "sprite_scale": m.sprite_scale or 1.0,
                "quick_actions": [],
                "synced_at": now,
            }
            for m in members
        ]

        if rows:
            await self._request(
                "POST",
                "aegis_members?on_conflict=device_id,aegis_member_id",
                json_data=rows,
                prefer_override="resolution=merge-duplicates,return=minimal",
            )

        # 刪除已移除的成員
        aegis_ids = [m.id for m in members]
        if aegis_ids:
            id_list = ",".join(str(i) for i in aegis_ids)
            await self._request(
                "DELETE",
                "aegis_members",
                params={
                    "device_id": f"eq.{self.device_id}",
                    "aegis_member_id": f"not.in.({id_list})",
                },
            )

    async def _sync_projects(self):
        """UPSERT 專案列表"""
        from sqlmodel import Session, select
        from app.database import engine
        from app.models.core import Project, StageList, Member

        with Session(engine) as session:
            projects = session.exec(
                select(Project).where(Project.is_active == True)
            ).all()

            now = datetime.now(timezone.utc).isoformat()
            rows = []
            for p in projects:
                stages = session.exec(
                    select(StageList)
                    .where(StageList.project_id == p.id)
                    .order_by(StageList.position)
                ).all()
                default_slug = ""
                if p.default_member_id:
                    dm = session.get(Member, p.default_member_id)
                    if dm:
                        default_slug = dm.slug
                rows.append({
                    "device_id": self.device_id,
                    "aegis_project_id": p.id,
                    "name": p.name,
                    "is_active": p.is_active,
                    "is_system": p.is_system,
                    "default_member_slug": default_slug,
                    "stage_names": [s.name for s in stages],
                    "synced_at": now,
                })

        if rows:
            await self._request(
                "POST",
                "aegis_projects?on_conflict=device_id,aegis_project_id",
                json_data=rows,
                prefer_override="resolution=merge-duplicates,return=minimal",
            )

        # 刪除已移除的專案
        aegis_ids = [r["aegis_project_id"] for r in rows]
        if aegis_ids:
            id_list = ",".join(str(i) for i in aegis_ids)
            await self._request(
                "DELETE",
                "aegis_projects",
                params={
                    "device_id": f"eq.{self.device_id}",
                    "aegis_project_id": f"not.in.({id_list})",
                },
            )

    async def _catalog_sync_loop(self):
        """目錄同步循環（啟動立即一次，之後每 5 分鐘）"""
        await asyncio.sleep(5)  # 等 DB 初始化完
        await self.sync_catalog()
        while True:
            await asyncio.sleep(self.CATALOG_SYNC_INTERVAL)
            try:
                await self.sync_catalog()
            except Exception as e:
                logger.error(f"[OneStack] Catalog sync loop error: {e}")

    def start_catalog_sync(self):
        """啟動目錄同步任務"""
        if not self.enabled:
            return
        if self._catalog_task is None or self._catalog_task.done():
            self._catalog_task = asyncio.create_task(self._catalog_sync_loop())
            logger.info("[OneStack] Catalog sync started (every 5min)")

    def stop_catalog_sync(self):
        """停止目錄同步任務"""
        if self._catalog_task and not self._catalog_task.done():
            self._catalog_task.cancel()
            logger.info("[OneStack] Catalog sync stopped")

    # ─── 任務輪詢（未來可改 Realtime） ───

    async def poll_tasks(self) -> List[Dict]:
        """從 OneStack 取得待處理任務"""
        if not self.enabled or not self.device_id:
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

        return result if isinstance(result, list) else []

    def on_task(self, callback):
        """註冊任務回調（收到新任務時觸發）"""
        self._task_callback = callback

    async def _poll_loop(self):
        """任務輪詢循環"""
        while True:
            try:
                tasks = await self.poll_tasks()
                if tasks and self._task_callback:
                    for task in tasks:
                        try:
                            await self._task_callback(task)
                        except Exception as e:
                            logger.error(f"[OneStack] Task callback error: {e}")
            except Exception as e:
                logger.error(f"[OneStack] Poll error: {e}")
            await asyncio.sleep(POLL_INTERVAL)

    def start_polling(self):
        """啟動任務輪詢"""
        if not self.enabled:
            return
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._poll_loop())
            logger.info(f"[OneStack] Task polling started (every {POLL_INTERVAL}s)")

    def stop_polling(self):
        """停止任務輪詢"""
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            logger.info("[OneStack] Task polling stopped")

    # ─── 任務狀態更新 ───

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

        data: Dict[str, Any] = {"status": status}

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

    # ─── 任務完成回報 ───

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

        import re
        from sqlmodel import Session as DBSession
        from app.database import engine
        from app.models.core import CardIndex, Project
        from app.core.card_file import card_file_path

        # 讀取 card metadata
        onestack_task_id = None
        card_title = "Task"

        with DBSession(engine) as session:
            card = session.get(CardIndex, card_id)
            if not card:
                return
            card_title = card.title or card_title

            project = session.get(Project, card.project_id) if card else None
            if not project or not project.path:
                return

        # 從 MD 檔讀 onestack_task_id（寫在 HTML comment 中）
        md_path = card_file_path(project.path, card_id)
        if md_path.exists():
            try:
                text = md_path.read_text(encoding="utf-8")
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
        task_title = card_title
        if task_data and isinstance(task_data, list) and len(task_data) > 0:
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

    # ─── 記憶同步 ───

    async def sync_memory(self, member_slug: str, content: str, memory_type: str = "short_term"):
        """同步成員記憶到 OneStack"""
        if not self.enabled:
            return

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

    # ─── 每日統計 ───

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

    # ─── Email 摘要同步 ───

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

    # ─── Aegis Stream（寫入執行輸出到 aegis_stream） ───

    async def stream_event(
        self,
        card_id: int,
        event_type: str,
        content: str,
        member_slug: Optional[str] = None,
        metadata: Optional[Dict] = None,
        chat_id: Optional[str] = None,
    ):
        """寫入一筆執行事件到 aegis_stream（OneStack 前端 Realtime 訂閱）"""
        if not self.enabled or not self.device_id:
            return

        # 需要 owner_id — 從 cli_devices 取得（快取）
        owner_id = await self._get_owner_id()
        if not owner_id:
            return

        data: Dict[str, Any] = {
            "owner_id": owner_id,
            "device_id": self.device_id,
            "card_id": card_id,
            "member_slug": member_slug,
            "event_type": event_type,
            "content": content[:5000],
            "metadata": metadata or {},
        }
        if chat_id:
            data["chat_id"] = chat_id

        await self._request("POST", "aegis_stream", json_data=data)

    _cached_owner_id: Optional[str] = None

    async def _get_owner_id(self) -> Optional[str]:
        """從 cli_devices 取得 owner_id（快取）"""
        if self._cached_owner_id:
            return self._cached_owner_id

        result = await self._request(
            "GET",
            "cli_devices",
            params={
                "id": f"eq.{self.device_id}",
                "select": "owner_id",
            }
        )
        if result and isinstance(result, list) and len(result) > 0:
            self._cached_owner_id = result[0].get("owner_id")
        return self._cached_owner_id

    async def stream_status(self, card_id: int, status: str, member_slug: Optional[str] = None, chat_id: Optional[str] = None):
        """快捷：寫入狀態事件"""
        await self.stream_event(card_id, "status", status, member_slug, chat_id=chat_id)

    async def stream_output(self, card_id: int, content: str, member_slug: Optional[str] = None, chat_id: Optional[str] = None):
        """快捷：寫入輸出事件"""
        await self.stream_event(card_id, "output", content, member_slug, chat_id=chat_id)

    async def stream_result(self, card_id: int, content: str, member_slug: Optional[str] = None, metadata: Optional[Dict] = None, chat_id: Optional[str] = None):
        """快捷：寫入結果事件"""
        await self.stream_event(card_id, "result", content, member_slug, metadata, chat_id=chat_id)

    # ─── Aegis Commands（輪詢 aegis_commands） ───

    async def poll_commands(self) -> List[Dict]:
        """從 aegis_commands 取得待處理指令"""
        if not self.enabled or not self.device_id:
            return []

        result = await self._request(
            "GET",
            "aegis_commands",
            params={
                "device_id": f"eq.{self.device_id}",
                "status": "eq.pending",
                "order": "created_at.asc",
                "limit": "10",
            }
        )
        return result if isinstance(result, list) else []

    async def update_command_status(
        self, command_id: int, status: str, result: Optional[Dict] = None
    ):
        """更新指令狀態"""
        if not self.enabled:
            return

        data: Dict[str, Any] = {
            "status": status,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        if result:
            data["result"] = result

        await self._request(
            "PATCH",
            "aegis_commands",
            params={"id": f"eq.{command_id}"},
            json_data=data
        )

    _command_callback = None

    def on_command(self, callback):
        """註冊指令回調"""
        self._command_callback = callback

    async def _command_poll_loop(self):
        """aegis_commands 輪詢循環（10 秒）"""
        while True:
            try:
                commands = await self.poll_commands()
                for cmd in commands:
                    cmd_id = cmd.get("id")
                    cmd_type = cmd.get("command_type")
                    payload = cmd.get("payload", {})

                    logger.info(f"[OneStack] Command received: {cmd_type} (id={cmd_id})")

                    # 標記為 processing
                    await self.update_command_status(cmd_id, "processing")

                    try:
                        if self._command_callback:
                            result = await self._command_callback(cmd_type, payload)
                            await self.update_command_status(cmd_id, "completed", result=result)
                        else:
                            await self.update_command_status(
                                cmd_id, "failed",
                                result={"error": "No command handler registered"}
                            )
                    except Exception as e:
                        logger.error(f"[OneStack] Command {cmd_id} failed: {e}")
                        await self.update_command_status(
                            cmd_id, "failed",
                            result={"error": str(e)[:500]}
                        )
            except Exception as e:
                logger.error(f"[OneStack] Command poll error: {e}")
            await asyncio.sleep(10)

    _command_poll_task: Optional[asyncio.Task] = None

    def start_command_polling(self):
        """啟動 aegis_commands 輪詢"""
        if not self.enabled:
            return
        if self._command_poll_task is None or self._command_poll_task.done():
            self._command_poll_task = asyncio.create_task(self._command_poll_loop())
            logger.info("[OneStack] Command polling started (every 10s)")

    def stop_command_polling(self):
        """停止 aegis_commands 輪詢"""
        if self._command_poll_task and not self._command_poll_task.done():
            self._command_poll_task.cancel()
            logger.info("[OneStack] Command polling stopped")

    # ─── 離線 ───

    async def set_offline(self):
        """設定設備為離線狀態"""
        if not self.enabled or not self.device_id:
            return

        await self._request(
            "PATCH",
            "cli_devices",
            params={"id": f"eq.{self.device_id}"},
            json_data={"status": "offline"}
        )
        logger.info(f"[OneStack] Device set to offline: {self.device_name}")


# 全域實例
connector = OneStackConnector()


async def _handle_onestack_task(task: Dict[str, Any]):
    """
    處理從 OneStack 輪詢到的任務：建立 Aegis 卡片

    task 結構（來自 cli_tasks）：
    - id: UUID
    - task_type: str
    - payload: {title, description, project_name, member_slug, ...}
    - owner_id: UUID
    """
    task_id = task.get("id", "")
    payload = task.get("payload", {}) or {}
    title = payload.get("title") or task.get("title") or "OneStack Task"
    description = payload.get("description") or task.get("description") or ""
    project_name = payload.get("project_name") or task.get("project_name")
    member_slug = payload.get("member_slug") or task.get("member_slug")

    logger.info(f"[OneStack] Processing task: {task_id[:8]}... - {title}")

    # 標記為 processing
    await connector.update_task_status(task_id, "processing")

    # 建立 Aegis 卡片
    try:
        from sqlmodel import Session as _Ses
        from app.database import engine as _eng
        from app.api.onestack import create_card_from_onestack_task

        with _Ses(_eng) as session:
            result = create_card_from_onestack_task(
                session=session,
                task_id=task_id,
                title=title,
                description=description,
                project_name=project_name,
                member_slug=member_slug,
            )

        if result.get("ok"):
            logger.info(
                f"[OneStack] Card created: #{result['card_id']} "
                f"in {result['project']}/{result['stage']}"
            )
        else:
            error = result.get("error", "Unknown error")
            logger.error(f"[OneStack] Failed to create card: {error}")
            await connector.update_task_status(
                task_id, "failed", error_message=error
            )

    except Exception as e:
        logger.error(f"[OneStack] Task processing error: {e}")
        await connector.update_task_status(
            task_id, "failed", error_message=str(e)[:500]
        )


async def _build_chat_history(chat_id: str, max_rounds: int = 5) -> str:
    """從 aegis_stream 撈對話歷史（用戶問題 + AI 回應），回傳 Markdown 區塊"""
    STATUS_WORDS = {"completed", "task_started", "task_completed", "task_failed", "running", "pending"}
    try:
        # 撈最近的 result 和用戶訊息（output 含 [用戶] 前綴）
        history = await connector._request(
            "GET", "aegis_stream",
            params={
                "device_id": f"eq.{connector.device_id}",
                "chat_id": f"eq.{chat_id}",
                "event_type": "in.(result,output)",
                "order": "created_at.desc",
                "limit": str(max_rounds * 3),  # 多撈一些，過濾後取 max_rounds 輪
            }
        )
        if not history or not isinstance(history, list):
            return ""

        # 組成對話格式（從舊到新）
        pairs = []
        for h in reversed(history):
            c = h.get("content", "").strip()
            if not c or c in STATUS_WORDS:
                continue
            if c.startswith("{"):  # 原始 JSON，跳過
                continue
            if c.startswith("[用戶]"):
                pairs.append(("user", c[4:].strip()))
            elif h.get("event_type") == "result":
                pairs.append(("assistant", c[:500]))

        if not pairs:
            return ""

        # 只取最近 max_rounds 輪
        lines = []
        for role, text in pairs[-(max_rounds * 2):]:
            if role == "user":
                lines.append(f"**用戶**：{text}")
            else:
                lines.append(f"**AI**：{text}")

        return "## 對話歷史\n\n" + "\n\n".join(lines) + "\n\n---\n\n"

    except Exception as e:
        logger.debug(f"[OneStack] Failed to load history: {e}")
        return ""


async def _build_chat_card_content(chat_id: str, message: str, max_rounds: int = 5) -> str:
    """組合 chat 卡片的完整 content（歷史 + 用戶訊息）"""
    history = await _build_chat_history(chat_id, max_rounds)
    return f"<!-- chat_id: {chat_id} -->\n{history}## 用戶訊息\n\n{message}"


async def _handle_aegis_command(command_type: str, payload: Dict) -> Dict:
    """處理從 OneStack aegis_commands 收到的指令"""
    if command_type == "create_card":
        from sqlmodel import Session as _Ses
        from app.database import engine as _eng
        from app.api.onestack import create_card_from_onestack_task

        member_slug = payload.get("member_slug")
        title = payload.get("title", "OneStack 任務")
        content = payload.get("content", "")

        with _Ses(_eng) as session:
            result = create_card_from_onestack_task(
                session=session,
                task_id="",
                title=title,
                description=content,
                member_slug=member_slug,
            )
        return result

    elif command_type == "chat":
        # 即時對話：建一張 [chat] 卡片，由 Worker 統一執行
        member_slug = payload.get("member_slug", "aegis")
        message = payload.get("message", "")
        chat_id = payload.get("chat_id", f"os:{member_slug}")
        logger.info(f"[OneStack] Chat → card: {member_slug} chat_id={chat_id}")

        try:
            from sqlmodel import Session as _Ses, select
            from app.database import engine as _eng
            from app.models.core import Member, StageList, CardIndex, Project
            from app.core.card_file import CardData, write_card, card_file_path

            with _Ses(_eng) as session:
                member = session.exec(select(Member).where(Member.slug == member_slug)).first()
                if not member:
                    member = session.exec(select(Member).where(Member.slug == "aegis")).first()

                inbox = session.exec(
                    select(StageList).where(
                        StageList.project_id == 1,
                        StageList.member_id == member.id,
                        StageList.is_ai_stage == True,
                    )
                ).first()

                if not inbox:
                    return {"ok": False, "error": f"No inbox for {member_slug}"}

                project = session.exec(select(Project).where(Project.id == 1)).first()
                project_path = project.path if project else "/home/cwen0708/projects/Aegis"

                # 建卡片
                max_id = session.exec(select(CardIndex.card_id).order_by(CardIndex.card_id.desc())).first() or 0
                card_id = max_id + 1

                # 組合卡片 content（歷史 + 用戶訊息）
                content = await _build_chat_card_content(chat_id, message)
                card_data = CardData(
                    id=card_id,
                    list_id=inbox.id,
                    title=f"[chat] {member_slug}: {message[:30]}",
                    description=None,
                    content=content,
                    status="pending",
                )

                fp = card_file_path(project_path, card_id)
                fp.parent.mkdir(parents=True, exist_ok=True)
                write_card(fp, card_data)

                # 寫索引
                idx = CardIndex(
                    card_id=card_id,
                    project_id=1,
                    list_id=inbox.id,
                    title=card_data.title,
                    status="pending",
                    file_path=str(fp),
                )
                session.add(idx)
                session.commit()

            # 寫 stream: 用戶訊息（供歷史記憶用）
            await connector.stream_event(card_id, "output", f"[用戶] {message}", member_slug, chat_id=chat_id)
            # 寫 stream: 已接收
            await connector.stream_event(card_id, "status", "pending", member_slug, chat_id=chat_id)

            return {"ok": True, "card_id": card_id, "message": "Chat card created"}

        except Exception as e:
            logger.error(f"[OneStack] Chat card creation failed: {e}")
            await connector.stream_event(0, "error", str(e)[:500], member_slug, chat_id=chat_id)
            return {"ok": False, "error": str(e)[:500]}

    elif command_type == "cancel":
        card_id = payload.get("card_id")
        if card_id:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(f"http://127.0.0.1:8899/api/v1/cards/{card_id}/abort")
                return {"ok": resp.status_code < 400}
        return {"ok": False, "error": "Missing card_id"}

    elif command_type == "sync":
        return {"ok": True, "status": "online"}

    else:
        return {"ok": False, "error": f"Unknown command: {command_type}"}


async def start_onestack_connector():
    """啟動 OneStack 連接器（供 main.py 呼叫）"""
    if connector.enabled:
        await connector.register_device()
        connector.start_heartbeat()

        # 註冊 cli_tasks 回調 + 啟動輪詢（Phase 1 舊機制）
        connector.on_task(_handle_onestack_task)
        connector.start_polling()

        # 註冊 aegis_commands 回調 + 啟動輪詢（新機制）
        connector.on_command(_handle_aegis_command)
        connector.start_command_polling()

        # 啟動目錄同步（成員 + 專案 → Supabase）
        connector.start_catalog_sync()

        # 讀取 Email digest 設定
        try:
            from sqlmodel import Session as _Ses
            from app.database import engine as _eng
            from app.models.core import SystemSetting as _SS
            with _Ses(_eng) as _s:
                setting = _s.get(_SS, "channel_email")
                if setting:
                    cfg = json.loads(setting.value)
                    if cfg.get("onestack_digest_enabled"):
                        connector._email_digest_interval_hours = cfg.get("onestack_digest_interval_hours", 6)
                        connector.start_email_digest()
        except Exception as e:
            logger.debug(f"[OneStack] Email digest config not loaded: {e}")


async def stop_onestack_connector():
    """停止 OneStack 連接器"""
    if connector.enabled:
        connector.stop_command_polling()
        connector.stop_email_digest()
        connector.stop_polling()
        connector.stop_heartbeat()
        await connector.set_offline()
