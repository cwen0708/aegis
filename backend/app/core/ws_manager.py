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
    import app.core.runner as runner_module
    from app.core.telemetry import get_system_metrics
    import app.core.poller as poller_module

    while True:
        await asyncio.sleep(5)
        if not websocket_clients:
            continue

        try:
            # 運行中任務
            tasks_data = []
            for tid, info in list(runner_module.running_tasks.items()):
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

            # 系統指標
            metrics = get_system_metrics()
            await broadcast_message({
                "type": "system_info_update",
                "data": {
                    "cpu_percent": metrics["cpu_percent"],
                    "mem_percent": metrics["memory_percent"],
                    "mem_available_gb": metrics["memory_available_gb"],
                    "is_paused": poller_module.is_paused,
                    "workstations_used": len(runner_module.running_tasks),
                    "workstations_total": runner_module.MAX_WORKSTATIONS,
                },
                "timestamp": time.time()
            })
        except Exception as e:
            logger.error(f"[WS Broadcast Error] {e}")
