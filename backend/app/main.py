from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import asyncio
import logging
from pathlib import Path
from app.database import init_db
from app.api import routes
from app.core.telemetry import get_system_metrics
from app.core.poller import start_poller
from app.core.cron_poller import start_cron_poller
from app.core.usage_poller import start_usage_poller
from app.core.ws_manager import websocket_clients, periodic_broadcast, broadcast_message
from app.core.card_watcher import start_card_watcher, stop_card_watcher
from app.core.card_index import rebuild_index
from app.core.card_file import read_card, write_card
from app.models.core import CardIndex, Project
from app.channels import channel_manager
import os
import time

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 啟動時初始化資料庫
    init_db()

    # 從 DB 讀取工作台數量設定
    try:
        from app.database import engine
        from app.models.core import SystemSetting
        from sqlmodel import Session as DBSession
        from app.core.runner import update_max_workstations
        with DBSession(engine) as session:
            setting = session.get(SystemSetting, "max_workstations")
            if not setting:
                setting = session.get(SystemSetting, "max_concurrent_agents")
            if setting:
                update_max_workstations(int(setting.value))
    except Exception as e:
        logger.warning(f"Failed to load max_workstations from DB: {e}")

    # 自動偵測本機已登入的 CLI 帳號，同步到 Account 表
    try:
        from app.database import engine as _eng
        from sqlmodel import Session as _Ses, select as _sel
        from app.models.core import Account
        import json as _json

        with _Ses(_eng) as session:
            # Claude profiles
            claude_profiles_dir = Path.home() / ".claude-profiles"
            claude_creds = Path.home() / ".claude" / ".credentials.json"

            if claude_profiles_dir.exists():
                for f in sorted(claude_profiles_dir.glob("*.json")):
                    cred_file = f.name
                    existing = session.exec(
                        _sel(Account).where(Account.provider == "claude", Account.credential_file == cred_file)
                    ).first()
                    if not existing:
                        try:
                            data = _json.loads(f.read_text(encoding="utf-8"))
                            sub = data.get("claudeAiOauth", {}).get("subscriptionType", "")
                        except Exception:
                            sub = ""
                        session.add(Account(provider="claude", name=f.stem, credential_file=cred_file, subscription=sub))
                        logger.info(f"Auto-registered Claude account: {f.stem}")
            elif claude_creds.exists():
                existing = session.exec(
                    _sel(Account).where(Account.provider == "claude", Account.credential_file == "default")
                ).first()
                if not existing:
                    try:
                        data = _json.loads(claude_creds.read_text(encoding="utf-8"))
                        sub = data.get("claudeAiOauth", {}).get("subscriptionType", "")
                    except Exception:
                        sub = ""
                    session.add(Account(provider="claude", name="default", credential_file="default", subscription=sub))
                    logger.info("Auto-registered Claude default account")

            # Gemini — 檢查 oauth_creds.json 或 google_accounts.json
            gemini_dir = Path.home() / ".gemini"
            gemini_oauth = gemini_dir / "oauth_creds.json"
            gemini_accounts_file = gemini_dir / "google_accounts.json"
            gemini_email = ""
            if gemini_accounts_file.exists():
                try:
                    acc = _json.loads(gemini_accounts_file.read_text(encoding="utf-8"))
                    gemini_email = acc.get("active", "") if isinstance(acc, dict) else ""
                except Exception:
                    pass
            if gemini_oauth.exists():
                existing = session.exec(
                    _sel(Account).where(Account.provider == "gemini")
                ).first()
                if not existing:
                    session.add(Account(provider="gemini", name="Gemini CLI", credential_file="oauth_creds.json", subscription="ai-pro", email=gemini_email))
                    logger.info(f"Auto-registered Gemini account: {gemini_email or 'oauth'}")

            session.commit()
    except Exception as e:
        logger.warning(f"Failed to auto-detect CLI accounts: {e}")

    # Rebuild CardIndex from MD files for all active projects
    try:
        from app.database import engine as _engine
        from sqlmodel import Session as _Session, select as _select
        with _Session(_engine) as session:
            projects = session.exec(
                _select(Project).where(Project.is_active == True)
            ).all()
            for project in projects:
                count = rebuild_index(session, project.id, project.path)
                if count > 0:
                    logger.info(f"Rebuilt index for {project.name}: {count} cards")
            session.commit()

        # Detect orphaned 'running' cards (no matching process)
        with _Session(_engine) as session:
            from app.core.runner import running_tasks
            orphans = session.exec(
                _select(CardIndex).where(CardIndex.status == "running")
            ).all()
            for idx in orphans:
                if idx.card_id not in running_tasks:
                    # Reset to failed — no process is running for this card
                    idx.status = "failed"
                    session.add(idx)
                    # Also update the MD file
                    try:
                        fpath = Path(idx.file_path)
                        if fpath.exists():
                            card = read_card(fpath)
                            card.status = "failed"
                            card.content += "\n\n### System Reset\nOrphaned running status detected on startup. Reset to failed."
                            write_card(fpath, card)
                    except Exception as e:
                        logger.warning(f"Failed to update orphaned card {idx.card_id} MD file: {e}")
                    logger.warning(f"Reset orphaned running card {idx.card_id}: {idx.title}")
            session.commit()
    except Exception as e:
        logger.warning(f"Failed to rebuild card index on startup: {e}")

    # 啟動背景的 AI Task Poller
    poller_task = asyncio.create_task(start_poller())

    # 啟動本地 Cron Job Poller
    cron_poller_task = asyncio.create_task(start_cron_poller())

    # 啟動 WebSocket 定期廣播
    ws_broadcast_task = asyncio.create_task(periodic_broadcast())

    # 啟動用量排程器（每 120 秒更新一次帳號用量）
    usage_poller_task = asyncio.create_task(start_usage_poller())

    # 啟動 MD 卡片檔案監視器（偵測外部編輯）
    await start_card_watcher()

    # 啟動多頻道通訊（如有設定 Bot Token）
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        from app.channels.adapters.telegram import TelegramChannel
        channel_manager.register(TelegramChannel(os.getenv("TELEGRAM_BOT_TOKEN")))
        logger.info("Telegram channel registered")
    await channel_manager.start_all()

    yield

    await channel_manager.stop_all()
    await stop_card_watcher()
    poller_task.cancel()
    cron_poller_task.cancel()
    ws_broadcast_task.cancel()
    usage_poller_task.cancel()

app = FastAPI(
    title="Aegis API",
    description="AI Engineering Grid & Intelligence System",
    version="0.2.0",
    lifespan=lifespan
)

# 加入 CORS Middleware 允許前端呼叫
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 提供 uploads 靜態檔案（立繪等）
uploads_dir = Path(__file__).parent.parent / "uploads"
uploads_dir.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")

# 註冊 API 路由
app.include_router(routes.router, prefix="/api/v1")

@app.get("/")
def read_root():
    return {"message": "Welcome to Aegis API"}

@app.get("/health")
def health_check():
    return {"status": "ok", "db": "local.db active"}

@app.get("/api/v1/system/metrics")
def read_system_metrics():
    """獲取系統即時硬體資源狀態"""
    return get_system_metrics()


# ==========================================
# WebSocket Endpoint
# ==========================================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    websocket_clients.add(websocket)
    logger.info(f"[WS] Client connected. Total: {len(websocket_clients)}")

    # 發送初始狀態
    try:
        import app.core.runner as _runner
        from app.core.poller import is_paused

        tasks_data = []
        for tid, info in list(_runner.running_tasks.items()):
            tasks_data.append({
                "task_id": info["task_id"],
                "project": info.get("project", ""),
                "card_title": info.get("card_title", ""),
                "started_at": info.get("started_at", 0),
                "pid": info.get("pid"),
                "provider": info.get("provider", ""),
                "member_id": info.get("member_id"),
            })

        await broadcast_message({
            "type": "running_tasks_update",
            "data": tasks_data,
            "timestamp": time.time()
        })

        metrics = get_system_metrics()
        await broadcast_message({
            "type": "system_info_update",
            "data": {
                "cpu_percent": metrics["cpu_percent"],
                "mem_percent": metrics["memory_percent"],
                "mem_available_gb": metrics["memory_available_gb"],
                "is_paused": is_paused,
                "workstations_used": len(_runner.running_tasks),
                "workstations_total": _runner.MAX_WORKSTATIONS,
            },
            "timestamp": time.time()
        })
    except Exception as e:
        logger.error(f"[WS] Failed to send initial state: {e}")

    # 保持連線
    try:
        while True:
            # 等待客戶端消息（心跳）
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        websocket_clients.discard(websocket)
        logger.info(f"[WS] Client disconnected. Total: {len(websocket_clients)}")
