from dotenv import load_dotenv
load_dotenv()  # 載入 .env 檔案

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import asyncio
import logging
from pathlib import Path
from app.database import init_db
from app.api import routes, webhooks, files
from app.core.telemetry import get_system_metrics
# start_poller 已移到獨立的 worker.py 程序
from app.core.cron_poller import start_cron_poller
from app.core.usage_poller import start_usage_poller
from app.core.ws_manager import websocket_clients, periodic_broadcast, broadcast_message
from app.core.card_watcher import start_card_watcher, stop_card_watcher
from app.core.card_index import rebuild_index
from app.core.card_file import read_card, write_card
from app.core.onestack_connector import start_onestack_connector, stop_onestack_connector
from app.core.auth import verify_session_token, AEGIS_API_KEY
from app.models.core import CardIndex, Project
from app.channels import channel_manager
from starlette.requests import Request
from starlette.responses import JSONResponse
import os
import time
import secrets

logger = logging.getLogger(__name__)


async def _register_channels_from_config():
    """從資料庫讀取頻道設定並註冊（環境變數為備援）"""
    import json
    from app.database import engine
    from app.models.core import SystemSetting
    from sqlmodel import Session as DBSession

    # 讀取 DB 中的頻道設定
    channel_configs = {}
    with DBSession(engine) as session:
        for key in ["channel_telegram", "channel_line", "channel_discord",
                    "channel_slack", "channel_wecom", "channel_feishu",
                    "channel_email"]:
            setting = session.get(SystemSetting, key)
            if setting:
                try:
                    channel_configs[key] = json.loads(setting.value)
                except:
                    pass

    # 每個頻道獨立 try/except，缺少依賴不影響其他頻道和啟動

    # Telegram: DB 優先，env 備援
    try:
        tg_config = channel_configs.get("channel_telegram", {})
        tg_token = tg_config.get("bot_token") or os.getenv("TELEGRAM_BOT_TOKEN")
        if tg_config.get("enabled") or (not tg_config and tg_token):
            if tg_token:
                from app.channels.adapters.telegram import TelegramChannel
                channel_manager.register(TelegramChannel(tg_token))
                logger.info("Telegram channel registered")
    except ImportError as e:
        logger.warning(f"Telegram adapter unavailable: {e}")

    # LINE: DB 優先，env 備援
    try:
        line_config = channel_configs.get("channel_line", {})
        line_secret = line_config.get("channel_secret") or os.getenv("LINE_CHANNEL_SECRET")
        line_token = line_config.get("access_token") or os.getenv("LINE_ACCESS_TOKEN")
        if line_config.get("enabled") or (not line_config and line_secret and line_token):
            if line_secret and line_token:
                from app.channels.adapters.line import LineChannel
                channel_manager.register(LineChannel(
                    channel_secret=line_secret,
                    access_token=line_token,
                ))
                logger.info("LINE channel registered")
    except ImportError as e:
        logger.warning(f"LINE adapter unavailable: {e}")

    # Discord: DB 優先，env 備援
    try:
        discord_config = channel_configs.get("channel_discord", {})
        discord_token = discord_config.get("bot_token") or os.getenv("DISCORD_BOT_TOKEN")
        if discord_config.get("enabled") or (not discord_config and discord_token):
            if discord_token:
                from app.channels.adapters.discord import DiscordChannel
                channel_manager.register(DiscordChannel(discord_token))
                logger.info("Discord channel registered")
    except ImportError as e:
        logger.warning(f"Discord adapter unavailable: {e}")

    # Slack: DB 優先，env 備援
    try:
        slack_config = channel_configs.get("channel_slack", {})
        slack_bot = slack_config.get("bot_token") or os.getenv("SLACK_BOT_TOKEN")
        slack_app = slack_config.get("app_token") or os.getenv("SLACK_APP_TOKEN")
        if slack_config.get("enabled") or (not slack_config and slack_bot and slack_app):
            if slack_bot and slack_app:
                from app.channels.adapters.slack import SlackChannel
                channel_manager.register(SlackChannel(
                    bot_token=slack_bot,
                    app_token=slack_app,
                ))
                logger.info("Slack channel registered")
    except ImportError as e:
        logger.warning(f"Slack adapter unavailable: {e}")

    # WeCom: DB 優先，env 備援
    try:
        wecom_config = channel_configs.get("channel_wecom", {})
        wecom_id = wecom_config.get("corp_id") or os.getenv("WECOM_CORP_ID")
        wecom_secret = wecom_config.get("corp_secret") or os.getenv("WECOM_CORP_SECRET")
        wecom_agent = wecom_config.get("agent_id") or os.getenv("WECOM_AGENT_ID", "0")
        if wecom_config.get("enabled") or (not wecom_config and wecom_id and wecom_secret):
            if wecom_id and wecom_secret:
                from app.channels.adapters.wecom import WeComChannel
                channel_manager.register(WeComChannel(
                    corp_id=wecom_id,
                    corp_secret=wecom_secret,
                    agent_id=int(wecom_agent) if wecom_agent else 0,
                ))
                logger.info("WeCom channel registered")
    except ImportError as e:
        logger.warning(f"WeCom adapter unavailable: {e}")

    # Feishu: DB 優先，env 備援
    try:
        feishu_config = channel_configs.get("channel_feishu", {})
        feishu_id = feishu_config.get("app_id") or os.getenv("FEISHU_APP_ID")
        feishu_secret = feishu_config.get("app_secret") or os.getenv("FEISHU_APP_SECRET")
        feishu_lark = feishu_config.get("is_lark") or os.getenv("FEISHU_IS_LARK", "").lower() == "true"
        if feishu_config.get("enabled") or (not feishu_config and feishu_id and feishu_secret):
            if feishu_id and feishu_secret:
                from app.channels.adapters.feishu import FeishuChannel
                channel_manager.register(FeishuChannel(
                    app_id=feishu_id,
                    app_secret=feishu_secret,
                    is_lark=bool(feishu_lark),
                ))
                logger.info("Feishu channel registered")
    except ImportError as e:
        logger.warning(f"Feishu adapter unavailable: {e}")

    # Email: DB 設定（無 env 備援，IMAP 憑證必須存在 DB）
    try:
        email_config = channel_configs.get("channel_email", {})
        if email_config.get("enabled") and email_config.get("imap_host"):
            from app.channels.adapters.email import EmailChannel
            channel_manager.register(EmailChannel(
                imap_host=email_config["imap_host"],
                imap_port=email_config.get("imap_port", 993),
                imap_user=email_config.get("imap_user", ""),
                imap_pass=email_config.get("imap_pass", ""),
                imap_use_ssl=email_config.get("imap_use_ssl", True),
                smtp_host=email_config.get("smtp_host", ""),
                smtp_port=email_config.get("smtp_port", 587),
                smtp_user=email_config.get("smtp_user", ""),
                smtp_pass=email_config.get("smtp_pass", ""),
                smtp_use_tls=email_config.get("smtp_use_tls", True),
                smtp_use_ssl=email_config.get("smtp_use_ssl", False),
                poll_interval=email_config.get("poll_interval", 60),
                mark_seen=email_config.get("mark_seen", True),
                max_body_chars=email_config.get("max_body_chars", 5000),
                auto_reply_enabled=email_config.get("auto_reply_enabled", False),
                sender_allowlist=email_config.get("sender_allowlist", []),
                folders=email_config.get("folders", ["INBOX"]),
                ai_classify_enabled=email_config.get("ai_classify_enabled", True),
            ))
            logger.info("Email channel registered")
    except ImportError as e:
        logger.warning(f"Email adapter unavailable: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 啟動時初始化資料庫
    init_db()

    # 更新系統版本號
    try:
        from app.database import engine
        from app.models.core import SystemSetting
        from sqlmodel import Session as DBSession
        version_file = Path(__file__).parent.parent / "VERSION"
        if version_file.exists():
            version = version_file.read_text().strip()
            with DBSession(engine) as session:
                setting = session.get(SystemSetting, "app_version")
                if setting:
                    setting.value = version
                else:
                    setting = SystemSetting(key="app_version", value=version)
                session.add(setting)
                session.commit()
            logger.info(f"Aegis version: {version}")
    except Exception as e:
        logger.warning(f"Failed to update app_version: {e}")

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

    # 清除更新狀態（服務重啟後重置）
    try:
        from app.database import engine as _engine
        from app.models.core import SystemSetting
        from sqlmodel import Session as _Session

        with _Session(_engine) as session:
            for key in ["update_stage", "update_progress", "update_message", "update_error", "update_is_updating"]:
                setting = session.get(SystemSetting, key)
                if setting:
                    if key == "update_stage":
                        setting.value = "idle"
                    elif key in ("update_progress",):
                        setting.value = "0"
                    elif key == "update_is_updating":
                        setting.value = "false"
                    else:
                        setting.value = ""
                    session.add(setting)
            session.commit()
    except Exception as e:
        logger.warning(f"Failed to clear update status: {e}")

    # 同步系統排程（更新檢查、記憶清理等）
    try:
        from seed import _sync_system_cron_jobs
        from app.database import engine as _engine
        from sqlmodel import Session as _Session

        with _Session(_engine) as session:
            _sync_system_cron_jobs(session)
    except Exception as e:
        logger.warning(f"Failed to sync system cron jobs: {e}")

    # 注意：AI Task Poller 已移到獨立的 worker.py 程序
    # 透過 dev.bat 啟動，避免阻塞 FastAPI event loop

    # 啟動本地 Cron Job Poller
    cron_poller_task = asyncio.create_task(start_cron_poller())

    # 啟動 WebSocket 定期廣播
    ws_broadcast_task = asyncio.create_task(periodic_broadcast())

    # 啟動用量排程器（每 300 秒更新一次帳號用量）
    usage_poller_task = asyncio.create_task(start_usage_poller())

    # 啟動 MD 卡片檔案監視器（偵測外部編輯）
    await start_card_watcher()

    # 啟動多頻道通訊（從 DB 讀取設定，環境變數為備援）
    await _register_channels_from_config()
    await channel_manager.start_all()

    # 啟動 OneStack 連接器（可選，環境變數控制）
    await start_onestack_connector()

    yield

    # Cleanup
    await stop_onestack_connector()
    await channel_manager.stop_all()
    await stop_card_watcher()
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
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8888", "http://127.0.0.1:8888"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# Auth Middleware — 保護所有寫入 API
# ==========================================
# 豁免路徑（不需要 token 驗證）
_AUTH_EXEMPT_PREFIXES = (
    "/api/v1/auth/",        # 登入流程
    "/api/v1/internal/",    # worker 內部通訊
    "/api/v1/webhooks/",    # 平台簽名驗證
    "/api/v1/node/",        # API key 驗證
)

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # 1. GET/HEAD/OPTIONS → 放行（唯讀）
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return await call_next(request)

    path = request.url.path

    # 2. 非 API 路徑 → 放行（靜態檔案等）
    if not path.startswith("/api/"):
        return await call_next(request)

    # 3. 豁免路徑 → 放行
    for prefix in _AUTH_EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return await call_next(request)

    # 4. /health → 放行
    if path == "/health":
        return await call_next(request)

    # 5. 來自 localhost 的請求（worker 進程）→ 放行
    client_host = request.client.host if request.client else ""
    if client_host in ("127.0.0.1", "::1", "localhost"):
        return await call_next(request)

    # 6. 驗證 Authorization: Bearer token
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if verify_session_token(token):
            return await call_next(request)

    # 7. 驗證 X-API-Key（用於外部 API 整合）
    api_key = request.headers.get("x-api-key", "")
    if api_key and AEGIS_API_KEY and secrets.compare_digest(api_key, AEGIS_API_KEY):
        return await call_next(request)

    # 8. 不符合以上 → 401
    return JSONResponse(
        status_code=401,
        content={"detail": "Authentication required"}
    )


# 提供 uploads 靜態檔案（立繪等）
uploads_dir = Path(__file__).parent.parent / "uploads"
uploads_dir.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")

# 註冊 API 路由
app.include_router(routes.router, prefix="/api/v1")
app.include_router(webhooks.router, prefix="/api/v1")
app.include_router(files.router, prefix="/api/v1")

# ==========================================
# SPA Frontend (serve from frontend/dist)
# ==========================================
_frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"

if _frontend_dist.exists() and (_frontend_dist / "index.html").exists():
    # Serve static assets (js, css, images, etc.)
    app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="frontend-assets")

    @app.get("/")
    def serve_spa_root():
        return FileResponse(str(_frontend_dist / "index.html"))
else:
    @app.get("/")
    def read_root():
        return {"message": "Welcome to Aegis API", "hint": "Run 'npm run build' in frontend/ to enable the dashboard"}

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


# ==========================================
# SPA Catch-All (must be last)
# ==========================================
if _frontend_dist.exists() and (_frontend_dist / "index.html").exists():
    @app.get("/{full_path:path}")
    def serve_spa_catchall(full_path: str):
        """Serve index.html for any unmatched route (Vue Router history mode)"""
        # API 路由不走 SPA fallback
        if full_path.startswith("api/"):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        # Try to serve as a static file first (e.g. favicon.ico, robots.txt)
        file_path = (_frontend_dist / full_path).resolve()
        if file_path.is_relative_to(_frontend_dist.resolve()) and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_frontend_dist / "index.html"))
