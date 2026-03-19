from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import Optional
from pydantic import BaseModel
from datetime import datetime
from app.database import get_session
from app.models.core import Project, StageList, CardIndex, SystemSetting, Account, Member
from app.core.card_file import CardData, write_card, card_file_path
from app.core.card_index import sync_card_to_index, next_card_id
from app.core.auth import require_api_key
from pathlib import Path
import os

router = APIRouter(tags=["onestack"])


# ==========================================
# OneStack Node API（供 OneStack 查詢/派發任務）
# ==========================================


class NodeTaskPayload(BaseModel):
    """OneStack 派發的任務"""
    task_id: str
    title: str
    description: str
    project_name: Optional[str] = None
    member_slug: Optional[str] = None
    priority: int = 0


@router.get("/node/info")
def get_node_info(
    session: Session = Depends(get_session),
    _: bool = Depends(require_api_key)
):
    """
    取得節點資訊（供 OneStack 查詢）

    返回此 Aegis 實例的狀態、版本、工作台使用情況等
    """
    # 讀取版本
    version = "unknown"
    version_file = Path(__file__).parent.parent.parent / "VERSION"
    if version_file.exists():
        version = version_file.read_text().strip()

    # 取得 OneStack 連接資訊
    onestack_device_id = os.getenv("ONESTACK_DEVICE_ID", "")
    onestack_device_name = os.getenv("ONESTACK_DEVICE_NAME", "Aegis")

    # 工作台狀態
    max_ws_setting = session.get(SystemSetting, "max_workstations")
    max_workstations = int(max_ws_setting.value) if max_ws_setting else 3

    # 統計 running 卡片數量
    running_count = len(list(session.exec(
        select(CardIndex).where(CardIndex.status == "running")
    ).all()))

    # 可用的 AI 提供者
    providers = []
    accounts = session.exec(select(Account)).all()
    for acc in accounts:
        if acc.provider not in providers:
            providers.append(acc.provider)

    # 專案列表
    projects = session.exec(
        select(Project).where(Project.is_active == True)
    ).all()
    project_list = [{"id": p.id, "name": p.name, "path": p.path} for p in projects]

    return {
        "device_id": onestack_device_id,
        "device_name": onestack_device_name,
        "version": version,
        "status": "online",
        "workstations": {
            "used": running_count,
            "total": max_workstations,
        },
        "providers": providers,
        "projects": project_list,
    }


class NodePairPayload(BaseModel):
    """配對碼連線請求"""
    supabase_url: str
    supabase_anon_key: str
    pairing_code: str
    device_name: Optional[str] = None


@router.post("/node/pair")
async def pair_with_onestack(payload: NodePairPayload):
    """
    用配對碼連線到 OneStack

    1. 呼叫 OneStack Supabase RPC claim_device_by_code
    2. 取得 device_id + device_token
    3. 儲存設定到本地 + 熱啟動 connector
    """
    import httpx

    url = f"{payload.supabase_url}/rest/v1/rpc/claim_device_by_code"
    headers = {
        "apikey": payload.supabase_anon_key,
        "Authorization": f"Bearer {payload.supabase_anon_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=headers, json={
                "p_code": payload.pairing_code.strip().upper()
            })
            if resp.status_code >= 400:
                detail = resp.text
                try:
                    detail = resp.json().get("message", detail)
                except Exception:
                    pass
                raise HTTPException(status_code=400, detail=f"Pairing failed: {detail}")
            result = resp.json()
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach OneStack: {e}")

    device_id = result.get("device_id")
    device_token = result.get("device_token")
    if not device_id or not device_token:
        raise HTTPException(status_code=400, detail="Unexpected response from OneStack")

    # 儲存設定到本地
    from app.core.onestack_connector import connector, DEVICE_CREDENTIALS_FILE, start_onestack_connector
    import json as _json

    connector.supabase_url = payload.supabase_url
    connector.supabase_key = payload.supabase_anon_key
    connector.device_id = device_id
    connector.device_token = device_token
    connector.device_name = payload.device_name or result.get("device_name", "Aegis")
    connector.enabled = True
    connector._credentials_source = "paired"

    # 儲存到認證檔案
    DEVICE_CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    DEVICE_CREDENTIALS_FILE.write_text(
        _json.dumps({
            "device_id": device_id,
            "device_token": device_token,
            "device_name": connector.device_name,
            "supabase_url": payload.supabase_url,
            "supabase_anon_key": payload.supabase_anon_key,
            "paired_at": datetime.now().isoformat(),
        }, indent=2),
        encoding="utf-8",
    )

    # 同時寫入 .env（重啟後仍有效）
    env_path = Path(__file__).parent.parent.parent / ".env"
    env_lines = []
    if env_path.exists():
        env_lines = env_path.read_text(encoding="utf-8").splitlines()

    onestack_vars = {
        "ONESTACK_ENABLED": "true",
        "ONESTACK_SUPABASE_URL": payload.supabase_url,
        "ONESTACK_SUPABASE_ANON_KEY": payload.supabase_anon_key,
        "ONESTACK_DEVICE_ID": device_id,
        "ONESTACK_DEVICE_TOKEN": device_token,
        "ONESTACK_DEVICE_NAME": connector.device_name,
    }
    env_lines = [l for l in env_lines if not l.startswith("ONESTACK_")]
    env_lines.extend([f"{k}={v}" for k, v in onestack_vars.items()])
    env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")

    # 熱啟動 connector
    import asyncio
    asyncio.create_task(start_onestack_connector())

    return {
        "ok": True,
        "device_id": device_id,
        "device_name": connector.device_name,
        "message": "Paired successfully. OneStack connector started.",
    }


@router.get("/node/pair/status")
def get_pair_status():
    """取得目前 OneStack 連線狀態"""
    from app.core.onestack_connector import connector
    return {
        "enabled": connector.enabled,
        "device_id": connector.device_id,
        "device_name": connector.device_name,
        "supabase_url": connector.supabase_url or None,
        "supabase_anon_key": connector.supabase_key or None,
        "connected": connector.enabled and connector.device_id is not None,
    }


def create_card_from_onestack_task(
    session: Session,
    task_id: str,
    title: str,
    description: str,
    project_name: Optional[str] = None,
    member_slug: Optional[str] = None,
) -> dict:
    """
    從 OneStack 任務建立 Aegis 卡片（共用邏輯）

    供 /node/task API 和 Supabase polling callback 共用。
    回傳 {"ok": True, "card_id": ..., "project": ..., "stage": ...}
    失敗時回傳 {"ok": False, "error": ...}
    """
    # 找到 AEGIS 系統專案及其 OneStack 列表
    aegis_project = session.exec(
        select(Project).where(Project.is_system == True)
    ).first()

    if not aegis_project:
        return {"ok": False, "error": "AEGIS system project not found"}

    stage_list = session.exec(
        select(StageList).where(
            StageList.project_id == aegis_project.id,
            StageList.name == "Inbound",
        )
    ).first()

    if not stage_list:
        return {"ok": False, "error": "Inbound stage list not found"}

    # 找到目標專案（用於工作目錄）
    project = aegis_project
    if project_name:
        target = session.exec(
            select(Project).where(
                Project.name == project_name,
                Project.is_active == True
            )
        ).first()
        if target:
            project = target

    # 找到目標成員
    member = None
    if member_slug:
        member = session.exec(
            select(Member).where(Member.slug == member_slug)
        ).first()

    member_id = None
    if member:
        member_id = member.id
    elif project.default_member_id:
        member_id = project.default_member_id
    else:
        first_member = session.exec(select(Member)).first()
        if first_member:
            member_id = first_member.id

    # 建立卡片
    card_id = next_card_id(session)

    body_lines = [description]
    body_lines.append(f"\n\n<!-- onestack_task_id: {task_id} -->")
    if project_name and project != aegis_project:
        body_lines.append(f"<!-- project_path: {project.path} -->")
    if member_slug:
        body_lines.append(f"<!-- member_slug: {member_slug} -->")

    card_data = CardData(
        id=card_id,
        list_id=stage_list.id,
        title=title,
        description=description[:200] if description else None,
        content="\n".join(body_lines),
        status="pending",
    )

    fpath = card_file_path(aegis_project.path, card_id)
    write_card(fpath, card_data)
    sync_card_to_index(session, card_data, aegis_project.id, str(fpath))
    session.commit()

    return {
        "ok": True,
        "card_id": card_id,
        "project": project.name,
        "stage": stage_list.name,
    }


@router.get("/node/projects")
def get_node_projects(
    session: Session = Depends(get_session),
    _: bool = Depends(require_api_key)
):
    """取得可用專案清單（供 OneStack 繫結用）"""
    projects = session.exec(
        select(Project).where(Project.is_active == True)
    ).all()

    return {
        "projects": [
            {
                "id": p.id,
                "name": p.name,
                "path": p.path,
                "stages": [
                    {"id": s.id, "name": s.name, "position": s.position}
                    for s in sorted(
                        session.exec(
                            select(StageList).where(StageList.project_id == p.id)
                        ).all(),
                        key=lambda s: s.position
                    )
                ],
            }
            for p in projects
        ]
    }


class BindProjectPayload(BaseModel):
    onestack_project_id: str
    aegis_project_id: Optional[int] = None  # None = 自動建立新專案


@router.post("/node/bind-project")
def bind_project(
    payload: BindProjectPayload,
    session: Session = Depends(get_session),
    _: bool = Depends(require_api_key)
):
    """
    繫結 OneStack 專案到 Aegis 專案

    若 aegis_project_id 為 None，則回傳可用專案清單讓前端選擇。
    """
    if payload.aegis_project_id is None:
        # 回傳可用專案清單
        projects = session.exec(
            select(Project).where(Project.is_active == True)
        ).all()
        return {
            "ok": False,
            "action": "select_project",
            "projects": [
                {"id": p.id, "name": p.name, "path": p.path}
                for p in projects
            ],
        }

    # 驗證 Aegis 專案存在
    project = session.get(Project, payload.aegis_project_id)
    if not project or not project.is_active:
        raise HTTPException(status_code=404, detail="Aegis project not found")

    # 取得 stages
    stages = session.exec(
        select(StageList).where(StageList.project_id == project.id)
        .order_by(StageList.position)
    ).all()

    return {
        "ok": True,
        "aegis_project_id": project.id,
        "aegis_project_name": project.name,
        "stages": [
            {"id": s.id, "name": s.name, "position": s.position}
            for s in stages
        ],
    }


@router.post("/node/task")
async def receive_node_task(
    payload: NodeTaskPayload,
    session: Session = Depends(get_session),
    _: bool = Depends(require_api_key)
):
    """接收 OneStack 派發的任務（直連 API）"""
    result = create_card_from_onestack_task(
        session=session,
        task_id=payload.task_id,
        title=payload.title,
        description=payload.description,
        project_name=payload.project_name,
        member_slug=payload.member_slug,
    )
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result
