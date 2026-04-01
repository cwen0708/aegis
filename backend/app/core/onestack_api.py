"""
OneStack API 二級封裝
統一 Supabase REST filter 模式，減少 onestack_connector.py 中的重複程式碼

所有 helper 接受 connector 的 _request 方法作為底層呼叫，
不直接依賴 connector 實例，方便測試。
"""
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Callable, Awaitable

# type alias：_request 簽名
RequestFn = Callable[..., Awaitable[Optional[Any]]]


# ─── 內部 helpers ───

async def _patch_by_id(
    request_fn: RequestFn,
    table: str,
    row_id: Any,
    data: Dict[str, Any],
) -> Optional[Any]:
    """統一 PATCH by id 模式"""
    return await request_fn(
        "PATCH",
        table,
        params={"id": f"eq.{row_id}"},
        json_data=data,
    )


async def _query_pending(
    request_fn: RequestFn,
    table: str,
    device_id: str,
    limit: int = 10,
) -> List[Dict]:
    """統一 pending poll 模式（status=pending, order by created_at asc）"""
    result = await request_fn(
        "GET",
        table,
        params={
            "device_id": f"eq.{device_id}",
            "status": "eq.pending",
            "order": "created_at.asc",
            "limit": str(limit),
        },
    )
    return result if isinstance(result, list) else []


async def _upsert(
    request_fn: RequestFn,
    table: str,
    conflict_cols: str,
    rows: List[Dict],
) -> Optional[Any]:
    """統一 upsert 模式（POST with on_conflict）"""
    if not rows:
        return None
    return await request_fn(
        "POST",
        f"{table}?on_conflict={conflict_cols}",
        json_data=rows,
        prefer_override="resolution=merge-duplicates,return=minimal",
    )


# ─── 公開 API ───

async def get_device_info(
    request_fn: RequestFn,
    device_id: str,
    select: str = "id,device_name",
) -> Optional[Dict]:
    """查詢裝置資訊，合併多處 device 查詢"""
    result = await request_fn(
        "GET",
        "cli_devices",
        params={
            "id": f"eq.{device_id}",
            "select": select,
        },
    )
    if result and isinstance(result, list) and len(result) > 0:
        return result[0]
    return None


async def update_task_status(
    request_fn: RequestFn,
    task_id: str,
    status: str,
    result: Optional[Dict] = None,
    error_message: Optional[str] = None,
) -> Optional[Any]:
    """更新 cli_tasks 狀態"""
    data: Dict[str, Any] = {"status": status}

    if status == "processing":
        data["started_at"] = datetime.now(timezone.utc).isoformat()
    elif status in ["completed", "failed"]:
        data["completed_at"] = datetime.now(timezone.utc).isoformat()

    if result:
        data["result"] = result
    if error_message:
        data["error_message"] = error_message

    return await _patch_by_id(request_fn, "cli_tasks", task_id, data)


async def update_command_status(
    request_fn: RequestFn,
    command_id: int,
    status: str,
    result: Optional[Dict] = None,
) -> Optional[Any]:
    """更新 aegis_commands 狀態"""
    data: Dict[str, Any] = {
        "status": status,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    if result:
        data["result"] = result

    return await _patch_by_id(request_fn, "aegis_commands", command_id, data)
