from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import logging
from app.database import init_db
from app.api import routes
from app.core.telemetry import get_system_metrics
from app.core.poller import start_poller
from app.core.cron_poller import start_cron_poller
from app.core.usage_poller import start_usage_poller
from app.core.ws_manager import websocket_clients, periodic_broadcast, broadcast_message
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

    # 啟動背景的 AI Task Poller
    poller_task = asyncio.create_task(start_poller())

    # 啟動本地 Cron Job Poller
    cron_poller_task = asyncio.create_task(start_cron_poller())

    # 啟動 WebSocket 定期廣播
    ws_broadcast_task = asyncio.create_task(periodic_broadcast())

    # 啟動用量排程器（每 120 秒更新一次帳號用量）
    usage_poller_task = asyncio.create_task(start_usage_poller())

    yield

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
