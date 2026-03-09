"""WebSocket 管理器：客戶端追蹤 + 廣播"""
import asyncio
import json
import time
import logging
from typing import Any, Dict, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# 全域 WebSocket 客戶端集合
websocket_clients: Set[WebSocket] = set()


async def broadcast_message(data: dict):
    """廣播訊息給所有連線的 WebSocket 客戶端"""
    if not websocket_clients:
        return
    dead = set()
    payload = json.dumps(data, default=str)
    for ws in websocket_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    websocket_clients.difference_update(dead)


async def broadcast_event(event_type: str, payload: Dict[str, Any] = None):
    """廣播特定事件"""
    await broadcast_message({
        "type": event_type,
        "data": payload or {},
        "timestamp": time.time()
    })


async def periodic_broadcast():
    """定期廣播系統狀態 + 運行中任務（每 5 秒）"""
    from app.core.telemetry import get_system_metrics
    from sqlmodel import Session, select
    from app.database import engine
    from app.models.core import CardIndex, StageList, Project, SystemSetting

    while True:
        await asyncio.sleep(5)
        if not websocket_clients:
            continue

        try:
            # 從 DB 查詢運行中任務
            tasks_data = []
            with Session(engine) as session:
                stmt = select(CardIndex).where(CardIndex.status == "running")
                running_cards = list(session.exec(stmt).all())

                for idx in running_cards:
                    project = session.get(Project, idx.project_id)
                    stage_list = session.get(StageList, idx.list_id)
                    tasks_data.append({
                        "task_id": idx.card_id,
                        "project": project.name if project else "",
                        "card_title": idx.title,
                        "started_at": idx.updated_at.timestamp() if idx.updated_at else 0,
                        "pid": None,  # Worker 獨立程序，無法追蹤 PID
                        "provider": "",  # 可從 stage_list 推斷
                        "member_id": idx.member_id,
                    })

                # 讀取最大工作台數
                max_ws_setting = session.get(SystemSetting, "max_workstations")
                max_workstations = int(max_ws_setting.value) if max_ws_setting else 3

            await broadcast_message({
                "type": "running_tasks_update",
                "data": tasks_data,
                "timestamp": time.time()
            })

            # 系統指標
            metrics = get_system_metrics()
            await broadcast_message({
                "type": "system_info_update",
                "data": {
                    "cpu_percent": metrics["cpu_percent"],
                    "mem_percent": metrics["memory_percent"],
                    "mem_available_gb": metrics["memory_available_gb"],
                    "is_paused": False,  # Worker 獨立程序，暫停邏輯待實作
                    "workstations_used": len(tasks_data),
                    "workstations_total": max_workstations,
                },
                "timestamp": time.time()
            })
        except Exception as e:
            logger.error(f"[WS Broadcast Error] {e}")
