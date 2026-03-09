from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlmodel import Session, select
from sqlalchemy import func as sa_func
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, timezone
from app.database import get_session
from app.models.core import Project, Card, StageList, CronJob, SystemSetting, Account, Member, MemberAccount, TaskLog, CardIndex
from typing import Any
from app.core.runner import running_tasks, abort_task
import app.core.runner as runner_module
from app.core.usage_poller import get_cached_claude_usage, get_cached_gemini_usage, get_last_updated
# Worker 程序獨立執行，暫停狀態改用 DB SystemSetting "worker_paused"
import app.core.cron_poller as cron_module
from app.core.ws_manager import websocket_clients
from app.core.card_file import CardData, read_card as read_card_md, write_card, card_file_path
from app.core.card_index import sync_card_to_index, remove_card_from_index, query_board, next_card_id, rebuild_index
import asyncio
import subprocess
import time as time_module
import json as json_module
import os
import uuid
from pathlib import Path

# 確保上傳目錄存在
UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads" / "portraits"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

router = APIRouter()

# ==========================================
# Per-card lock manager (for async endpoints)
# ==========================================
_card_locks: dict[int, asyncio.Lock] = {}

def get_card_lock(card_id: int) -> asyncio.Lock:
    return _card_locks.setdefault(card_id, asyncio.Lock())


def _get_project_for_list(session: Session, list_id: int):
    """Get Project from a list_id. Returns (project, stage_list) or raises 404."""
    sl = session.get(StageList, list_id)
    if not sl:
        raise HTTPException(status_code=404, detail="List not found")
    project = session.get(Project, sl.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project, sl


def _get_member_primary_provider(member_id: int, session: Session) -> str:
    """從成員的主帳號（priority 最低）取得 provider"""
    binding = session.exec(
        select(MemberAccount)
        .where(MemberAccount.member_id == member_id)
        .order_by(MemberAccount.priority)
    ).first()
    if binding:
        account = session.get(Account, binding.account_id)
        if account:
            return account.provider
    return ""

# ==========================================
# Response Models
# ==========================================
class CardResponse(BaseModel):
    id: int
    list_id: int
    title: str
    description: Optional[str]
    status: str
    created_at: datetime

class MemberBrief(BaseModel):
    id: int
    name: str
    avatar: str = ""
    provider: str = ""  # 從主帳號推導

class StageListResponse(BaseModel):
    id: int
    project_id: int
    name: str
    position: int
    member_id: Optional[int] = None
    member: Optional[MemberBrief] = None
    cards: List[CardResponse] = []
    # 階段配置
    stage_type: str = "auto_process"
    system_instruction: Optional[str] = None
    prompt_template: Optional[str] = None
    is_ai_stage: bool = True

# ==========================================
# Project Schemas
# ==========================================
class ProjectCreate(BaseModel):
    name: str
    path: str
    deploy_type: str = "none"
    default_provider: str = "auto"


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    path: Optional[str] = None
    is_active: Optional[bool] = None
    deploy_type: Optional[str] = None
    default_provider: Optional[str] = None


# ==========================================
# Project Routes
# ==========================================
@router.get("/projects/", response_model=List[Project])
def read_projects(session: Session = Depends(get_session)):
    # 回傳所有專案，讓前端可以顯示停用狀態
    projects = session.exec(select(Project)).all()
    return projects

@router.post("/projects/", response_model=Project)
def create_project(data: ProjectCreate, session: Session = Depends(get_session)):
    """建立新專案，自動建立 cards 目錄和預設 StageList"""
    # 1. 路徑驗證與建立
    project_path = Path(data.path)
    if not project_path.exists():
        try:
            project_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"無法建立路徑: {e}")

    # 2. 建立 cards 子目錄
    cards_dir = project_path / "cards"
    cards_dir.mkdir(exist_ok=True)

    # 3. 建立專案
    project = Project(
        name=data.name,
        path=str(project_path),
        deploy_type=data.deploy_type,
        default_provider=data.default_provider,
    )
    session.add(project)
    session.commit()
    session.refresh(project)

    # 4. 建立預設 StageList（含階段配置）
    stages_config = [
        ("Backlog", "manual", False),
        ("Planning", "auto_process", True),
        ("Developing", "auto_process", True),
        ("Verifying", "auto_review", True),
        ("Done", "terminal", False),
        ("Aborted", "terminal", False),
    ]
    for idx, (name, stage_type, is_ai) in enumerate(stages_config):
        sl = StageList(
            project_id=project.id,
            name=name,
            position=idx,
            stage_type=stage_type,
            is_ai_stage=is_ai,
        )
        session.add(sl)
    session.commit()

    return project

@router.patch("/projects/{project_id}", response_model=Project)
def update_project(project_id: int, update_data: ProjectUpdate, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    # 系統專案禁止改名
    if project.is_system and update_data.name is not None:
        raise HTTPException(status_code=403, detail="無法修改系統專案名稱")
    if update_data.name is not None:
        project.name = update_data.name
    if update_data.path is not None:
        new_path = Path(update_data.path)
        if not new_path.exists():
            raise HTTPException(status_code=400, detail="路徑不存在")
        project.path = str(new_path)
    if update_data.is_active is not None:
        project.is_active = update_data.is_active
    if update_data.deploy_type is not None:
        project.deploy_type = update_data.deploy_type
    if update_data.default_provider is not None:
        project.default_provider = update_data.default_provider
    session.add(project)
    session.commit()
    session.refresh(project)
    return project

@router.get("/projects/{project_id}/board", response_model=List[StageListResponse])
def read_project_board(project_id: int, session: Session = Depends(get_session)):
    """一次抓取整個看板所需的資料：列表與其中的卡片（MD-driven via CardIndex）"""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    lists = session.exec(
        select(StageList).where(StageList.project_id == project_id).order_by(StageList.position)
    ).all()

    # Query all cards for this project from the index
    card_indices = query_board(session, project_id)
    # Group by list_id
    cards_by_list: dict[int, list[CardIndex]] = {}
    for ci in card_indices:
        cards_by_list.setdefault(ci.list_id, []).append(ci)
    # Sort each group by created_at desc
    for lst in cards_by_list.values():
        lst.sort(key=lambda c: c.created_at, reverse=True)

    result = []
    for l in lists:
        member_brief = None
        if l.member_id:
            m = session.get(Member, l.member_id)
            if m:
                member_brief = MemberBrief(id=m.id, name=m.name, avatar=m.avatar, provider=_get_member_primary_provider(m.id, session))
        list_cards = cards_by_list.get(l.id, [])
        result.append(StageListResponse(
            id=l.id,
            project_id=l.project_id,
            name=l.name,
            position=l.position,
            member_id=l.member_id,
            member=member_brief,
            cards=[CardResponse(
                id=ci.card_id, list_id=ci.list_id, title=ci.title,
                description=ci.description, status=ci.status, created_at=ci.created_at
            ) for ci in list_cards],
            # 階段配置
            stage_type=l.stage_type,
            system_instruction=l.system_instruction,
            prompt_template=l.prompt_template,
            is_ai_stage=l.is_ai_stage,
        ))
    return result

# ==========================================
# StageList Routes
# ==========================================
class StageListUpdateRequest(BaseModel):
    member_id: Optional[int] = None  # null = 使用預設路由
    # 階段行為配置
    stage_type: Optional[str] = None  # manual, auto_process, auto_review, terminal
    system_instruction: Optional[str] = None
    prompt_template: Optional[str] = None
    is_ai_stage: Optional[bool] = None


@router.patch("/lists/{list_id}")
def update_stage_list(list_id: int, data: StageListUpdateRequest, session: Session = Depends(get_session)):
    stage_list = session.get(StageList, list_id)
    if not stage_list:
        raise HTTPException(status_code=404, detail="StageList not found")

    # 更新成員指派
    if data.member_id is not None:
        stage_list.member_id = data.member_id if data.member_id != 0 else None

    # 更新階段配置
    if data.stage_type is not None:
        stage_list.stage_type = data.stage_type
    if data.system_instruction is not None:
        stage_list.system_instruction = data.system_instruction if data.system_instruction else None
    if data.prompt_template is not None:
        stage_list.prompt_template = data.prompt_template if data.prompt_template else None
    if data.is_ai_stage is not None:
        stage_list.is_ai_stage = data.is_ai_stage

    session.add(stage_list)
    session.commit()
    session.refresh(stage_list)

    # 回傳完整資訊
    member_brief = None
    if stage_list.member_id:
        m = session.get(Member, stage_list.member_id)
        if m:
            member_brief = {"id": m.id, "name": m.name, "avatar": m.avatar, "provider": _get_member_primary_provider(m.id, session)}

    return {
        "ok": True,
        "id": stage_list.id,
        "name": stage_list.name,
        "member_id": stage_list.member_id,
        "member": member_brief,
        "stage_type": stage_list.stage_type,
        "system_instruction": stage_list.system_instruction,
        "prompt_template": stage_list.prompt_template,
        "is_ai_stage": stage_list.is_ai_stage,
    }


# ==========================================
# Card Routes
# ==========================================
@router.get("/cards/", response_model=List[Card])
def read_cards(session: Session = Depends(get_session)):
    cards = session.exec(select(Card)).all()
    return cards

@router.get("/cards/{card_id}", response_model=Card)
def read_card_endpoint(card_id: int, session: Session = Depends(get_session)):
    # Primary: look up CardIndex -> read MD file
    idx = session.get(CardIndex, card_id)
    if idx and idx.file_path and Path(idx.file_path).exists():
        cd = read_card_md(Path(idx.file_path))
        # Return as Card-compatible dict (response_model=Card)
        return Card(
            id=cd.id, list_id=cd.list_id, title=cd.title,
            description=cd.description, content=cd.content,
            status=cd.status, created_at=cd.created_at, updated_at=cd.updated_at,
        )
    # Fallback: old Card table
    card = session.get(Card, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return card

class CardCreateRequest(BaseModel):
    list_id: int
    title: str
    description: Optional[str] = None

@router.post("/cards/", response_model=Card)
def create_card(card_in: CardCreateRequest, session: Session = Depends(get_session)):
    # Resolve project from list_id
    project, sl = _get_project_for_list(session, card_in.list_id)

    # Get next card ID (max of both old Card table and CardIndex)
    new_id = next_card_id(session)
    # Also check old Card table max id（用 SQL 聚合避免全表掃描）
    old_max_id = session.exec(select(sa_func.max(Card.id))).one()
    if old_max_id is not None:
        new_id = max(new_id, old_max_id + 1)

    now = datetime.now(timezone.utc)
    card_data = CardData(
        id=new_id, list_id=card_in.list_id, title=card_in.title,
        description=card_in.description, content="", status="idle",
        tags=[], created_at=now, updated_at=now,
    )

    # Write MD file
    fpath = card_file_path(project.path, new_id)
    fpath.parent.mkdir(parents=True, exist_ok=True)
    write_card(fpath, card_data)

    # Sync to index
    sync_card_to_index(session, card_data, project_id=project.id, file_path=str(fpath))

    # Dual-write: also create old Card ORM record (transition)
    orm_card = Card(
        id=new_id, list_id=card_in.list_id, title=card_in.title,
        description=card_in.description, status="idle",
        created_at=now, updated_at=now,
    )
    session.add(orm_card)
    session.commit()
    session.refresh(orm_card)
    return orm_card

class CardUpdateRequest(BaseModel):
    list_id: Optional[int] = None
    status: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None

@router.patch("/cards/{card_id}", response_model=Card)
def update_card(card_id: int, update_data: CardUpdateRequest, session: Session = Depends(get_session)):
    # Try MD-driven path first
    idx = session.get(CardIndex, card_id)
    now = datetime.now(timezone.utc)

    if idx and idx.file_path and Path(idx.file_path).exists():
        cd = read_card_md(Path(idx.file_path))

        if update_data.list_id is not None:
            cd.list_id = update_data.list_id
            cd.status = "pending"
        if update_data.status is not None:
            cd.status = update_data.status
        if update_data.title is not None:
            cd.title = update_data.title
        if update_data.description is not None:
            cd.description = update_data.description
        if update_data.content is not None:
            cd.content = update_data.content
        cd.updated_at = now

        write_card(Path(idx.file_path), cd)

        # Re-derive project_id from list_id for index sync
        project_id = idx.project_id
        if update_data.list_id is not None:
            sl = session.get(StageList, cd.list_id)
            if sl:
                project_id = sl.project_id
        sync_card_to_index(session, cd, project_id=project_id, file_path=idx.file_path)

    # Dual-write: also update old Card ORM record
    orm_card = session.get(Card, card_id)
    if orm_card:
        if update_data.list_id is not None:
            orm_card.list_id = update_data.list_id
            orm_card.status = "pending"
        if update_data.status is not None:
            orm_card.status = update_data.status
        if update_data.title is not None:
            orm_card.title = update_data.title
        if update_data.description is not None:
            orm_card.description = update_data.description
        if update_data.content is not None:
            orm_card.content = update_data.content
        orm_card.updated_at = now
        session.add(orm_card)

    if not idx and not orm_card:
        raise HTTPException(status_code=404, detail="Card not found")

    session.commit()
    if orm_card:
        session.refresh(orm_card)
        return orm_card

    # Return from MD data if no ORM card
    cd_final = read_card_md(Path(idx.file_path))
    return Card(
        id=cd_final.id, list_id=cd_final.list_id, title=cd_final.title,
        description=cd_final.description, content=cd_final.content,
        status=cd_final.status, created_at=cd_final.created_at, updated_at=cd_final.updated_at,
    )

# ==========================================
# CronJob Routes
# ==========================================
@router.get("/cron-jobs/", response_model=List[CronJob])
def read_cron_jobs(project_id: Optional[int] = None, session: Session = Depends(get_session)):
    # 回傳所有 CronJob，不再過濾 is_enabled
    query = select(CronJob)
    if project_id:
        query = query.where(CronJob.project_id == project_id)
    return session.exec(query).all()


class CronJobUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    cron_expression: Optional[str] = None
    system_instruction: Optional[str] = None
    prompt_template: Optional[str] = None
    is_enabled: Optional[bool] = None

@router.patch("/cron-jobs/{job_id}", response_model=CronJob)
def update_cron_job(job_id: int, update_data: CronJobUpdate, session: Session = Depends(get_session)):
    job = session.get(CronJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="CronJob not found")
    for field in ["name", "description", "cron_expression", "system_instruction", "prompt_template", "is_enabled"]:
        val = getattr(update_data, field)
        if val is not None:
            setattr(job, field, val)
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


# ==========================================
# CronJob Create
# ==========================================
class CronJobCreateRequest(BaseModel):
    project_id: int
    name: str
    description: Optional[str] = None
    cron_expression: str = "0 0 * * *"
    system_instruction: Optional[str] = None
    prompt_template: str = ""

@router.post("/cron-jobs/", response_model=CronJob)
def create_cron_job(data: CronJobCreateRequest, session: Session = Depends(get_session)):
    project = session.get(Project, data.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    job = CronJob(
        project_id=data.project_id,
        name=data.name,
        description=data.description,
        cron_expression=data.cron_expression,
        system_instruction=data.system_instruction,
        prompt_template=data.prompt_template,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


# ==========================================
# Delete Endpoints
# ==========================================
@router.delete("/cards/{card_id}")
def delete_card(card_id: int, session: Session = Depends(get_session)):
    # Check status from index or ORM
    idx = session.get(CardIndex, card_id)
    orm_card = session.get(Card, card_id)

    if not idx and not orm_card:
        raise HTTPException(status_code=404, detail="Card not found")

    status = idx.status if idx else (orm_card.status if orm_card else "idle")
    if status == "running":
        raise HTTPException(status_code=409, detail="Cannot delete a running card")

    # Delete MD file
    if idx and idx.file_path:
        md_path = Path(idx.file_path)
        if md_path.exists():
            md_path.unlink()
        remove_card_from_index(session, card_id)

    # Dual-write: also delete old Card ORM record
    if orm_card:
        session.delete(orm_card)

    session.commit()
    # Clean up lock
    _card_locks.pop(card_id, None)
    return {"ok": True}


@router.delete("/cron-jobs/{job_id}")
def delete_cron_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(CronJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="CronJob not found")
    if job.is_system:
        raise HTTPException(status_code=403, detail="Cannot delete a system cron job")
    session.delete(job)
    session.commit()
    return {"ok": True}


# ==========================================
# Card Trigger / Abort
# ==========================================
@router.post("/cards/{card_id}/trigger")
def trigger_card(card_id: int, session: Session = Depends(get_session)):
    """手動觸發卡片執行（將 status 設為 pending）"""
    idx = session.get(CardIndex, card_id)
    orm_card = session.get(Card, card_id)
    if not idx and not orm_card:
        raise HTTPException(status_code=404, detail="Card not found")

    status = idx.status if idx else (orm_card.status if orm_card else "idle")
    if status == "running":
        raise HTTPException(status_code=409, detail="Card is already running")

    now = datetime.now(timezone.utc)

    # Update MD file + index
    if idx and idx.file_path and Path(idx.file_path).exists():
        cd = read_card_md(Path(idx.file_path))
        cd.status = "pending"
        cd.updated_at = now
        write_card(Path(idx.file_path), cd)
        sync_card_to_index(session, cd, project_id=idx.project_id, file_path=idx.file_path)

    # Dual-write: old Card ORM
    if orm_card:
        orm_card.status = "pending"
        orm_card.updated_at = now
        session.add(orm_card)

    session.commit()
    return {"ok": True, "status": "pending"}


@router.post("/cards/{card_id}/abort")
def abort_card(card_id: int, session: Session = Depends(get_session)):
    """中止執行中的任務"""
    idx = session.get(CardIndex, card_id)
    orm_card = session.get(Card, card_id)
    if not idx and not orm_card:
        raise HTTPException(status_code=404, detail="Card not found")

    killed = abort_task(card_id)
    now = datetime.now(timezone.utc)

    if killed:
        # Update MD file + index
        if idx and idx.file_path and Path(idx.file_path).exists():
            cd = read_card_md(Path(idx.file_path))
            cd.status = "failed"
            cd.content = (cd.content or "") + "\n\n### Aborted\n任務已被手動中止。"
            cd.updated_at = now
            write_card(Path(idx.file_path), cd)
            sync_card_to_index(session, cd, project_id=idx.project_id, file_path=idx.file_path)
        # Dual-write: old Card ORM
        if orm_card:
            orm_card.status = "failed"
            orm_card.content = (orm_card.content or "") + "\n\n### Aborted\n任務已被手動中止。"
            orm_card.updated_at = now
            session.add(orm_card)
        session.commit()
        return {"ok": True, "status": "aborted"}

    # 即使 process 不在 running_tasks，也重設狀態
    status = idx.status if idx else (orm_card.status if orm_card else "idle")
    if status == "running":
        if idx and idx.file_path and Path(idx.file_path).exists():
            cd = read_card_md(Path(idx.file_path))
            cd.status = "failed"
            cd.updated_at = now
            write_card(Path(idx.file_path), cd)
            sync_card_to_index(session, cd, project_id=idx.project_id, file_path=idx.file_path)
        if orm_card:
            orm_card.status = "failed"
            orm_card.updated_at = now
            session.add(orm_card)
        session.commit()
    return {"ok": True, "status": "reset"}


# ==========================================
# Project Delete (with is_system guard)
# ==========================================
@router.delete("/projects/{project_id}")
def delete_project(project_id: int, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.is_system:
        raise HTTPException(status_code=403, detail="Cannot delete a system project")
    # Delete associated stage lists (and their cards from index)
    lists = session.exec(select(StageList).where(StageList.project_id == project_id)).all()
    for l in lists:
        session.delete(l)
    # Remove card index entries for this project
    card_indices = query_board(session, project_id)
    for ci in card_indices:
        if ci.file_path and Path(ci.file_path).exists():
            Path(ci.file_path).unlink()
        remove_card_from_index(session, ci.card_id)
    session.delete(project)
    session.commit()
    return {"ok": True}


# ==========================================
# Project Reindex
# ==========================================
@router.post("/projects/{project_id}/reindex")
def reindex_project(project_id: int, session: Session = Depends(get_session)):
    """Rebuild CardIndex from MD files for a project."""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    count = rebuild_index(session, project_id, project.path)
    session.commit()
    return {"ok": True, "cards_indexed": count}


# ==========================================
# Runner Control (DB-based for Worker process)
# ==========================================
@router.post("/runner/pause")
def pause_runner(session: Session = Depends(get_session)):
    """暫停 Worker（透過 DB 旗標）"""
    setting = session.get(SystemSetting, "worker_paused")
    if setting:
        setting.value = "true"
    else:
        setting = SystemSetting(key="worker_paused", value="true")
        session.add(setting)
    session.commit()
    return {"ok": True, "is_paused": True}


@router.post("/runner/resume")
def resume_runner(session: Session = Depends(get_session)):
    """恢復 Worker（透過 DB 旗標）"""
    setting = session.get(SystemSetting, "worker_paused")
    if setting:
        setting.value = "false"
    else:
        setting = SystemSetting(key="worker_paused", value="false")
        session.add(setting)
    session.commit()
    return {"ok": True, "is_paused": False}


@router.get("/runner/status")
def runner_status(session: Session = Depends(get_session)):
    """從 DB 查詢運行中任務（Worker 獨立程序架構）"""
    from sqlmodel import select

    stmt = select(CardIndex).where(CardIndex.status == "running")
    running_cards = list(session.exec(stmt).all())

    tasks_data = []
    for idx in running_cards:
        project = session.get(Project, idx.project_id)
        tasks_data.append({
            "task_id": idx.card_id,
            "project": project.name if project else "",
            "card_title": idx.title,
            "started_at": idx.updated_at.timestamp() if idx.updated_at else 0,
            "pid": None,  # Worker 獨立程序
            "provider": "",
            "member_id": idx.member_id,
        })

    # 讀取最大工作台數
    max_ws_setting = session.get(SystemSetting, "max_workstations")
    max_workstations = int(max_ws_setting.value) if max_ws_setting else 3

    # 讀取暫停旗標
    paused_setting = session.get(SystemSetting, "worker_paused")
    is_paused = paused_setting and paused_setting.value == "true"

    return {
        "is_paused": is_paused,
        "running_tasks": tasks_data,
        "workstations_used": len(tasks_data),
        "workstations_total": max_workstations,
    }


# ==========================================
# Internal APIs (for Worker process)
# ==========================================
from pydantic import BaseModel

class BroadcastLogRequest(BaseModel):
    card_id: int
    line: str

class BroadcastEventRequest(BaseModel):
    event: str
    payload: dict

@router.post("/internal/broadcast-log")
async def internal_broadcast_log(req: BroadcastLogRequest):
    """Worker 呼叫：廣播任務輸出行"""
    from app.core.ws_manager import broadcast_event
    await broadcast_event("task_log", {"card_id": req.card_id, "line": req.line})
    return {"ok": True}


@router.post("/internal/broadcast-event")
async def internal_broadcast_event(req: BroadcastEventRequest):
    """Worker 呼叫：廣播事件"""
    from app.core.ws_manager import broadcast_event
    await broadcast_event(req.event, req.payload)
    return {"ok": True}


# ==========================================
# Claude Usage
# ==========================================
@router.get("/claude/usage")
def claude_usage():
    """回傳快取的 Claude 帳號用量（由 usage_poller 每 120 秒更新）"""
    return {"accounts": get_cached_claude_usage(), "updated_at": get_last_updated()}


@router.get("/gemini/usage")
def gemini_usage():
    """回傳快取的 Gemini 配額（由 usage_poller 每 120 秒更新）"""
    return {**get_cached_gemini_usage(), "updated_at": get_last_updated()}


# ==========================================
# Service Health
# ==========================================
_services_cache: dict = {"data": None, "ts": 0}
_CACHE_TTL = 10  # seconds


def _check_claude_cli() -> dict:
    info = {"installed": False, "version": None, "authenticated": False, "account": None, "subscription": None}
    try:
        result = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=5, shell=True)
        if result.returncode == 0 and result.stdout.strip():
            info["installed"] = True
            info["version"] = result.stdout.strip()
    except Exception:
        pass

    # Check credentials
    creds_path = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")
    try:
        if os.path.exists(creds_path):
            with open(creds_path, encoding="utf-8") as f:
                creds = json_module.load(f)
            if creds:
                info["authenticated"] = True
    except Exception:
        pass

    # Check profiles for account info
    profiles_dir = os.path.join(os.path.expanduser("~"), ".claude-profiles")
    try:
        if os.path.isdir(profiles_dir):
            for fname in os.listdir(profiles_dir):
                if fname.endswith(".json"):
                    try:
                        with open(os.path.join(profiles_dir, fname), encoding="utf-8") as f:
                            profile = json_module.load(f)
                        info["account"] = fname.replace(".json", "")
                        info["subscription"] = profile.get("subscriptionType", profile.get("subscription_type"))
                    except Exception:
                        pass
                    break
        if not info["account"] and info["authenticated"]:
            info["account"] = "default"
    except Exception:
        pass

    return info


def _check_gemini_cli() -> dict:
    info = {"installed": False, "version": None, "authenticated": False, "account": None}
    try:
        result = subprocess.run(
            ["npm", "list", "-g", "@google/gemini-cli", "--json"],
            capture_output=True, text=True, timeout=5, shell=True
        )
        if result.returncode == 0:
            data = json_module.loads(result.stdout)
            deps = data.get("dependencies", {})
            gemini = deps.get("@google/gemini-cli", {})
            if gemini:
                info["installed"] = True
                info["version"] = gemini.get("version", "unknown")
    except Exception:
        pass

    # Check Google account
    accounts_path = os.path.join(os.path.expanduser("~"), ".gemini", "google_accounts.json")
    try:
        if os.path.exists(accounts_path):
            with open(accounts_path, encoding="utf-8") as f:
                accounts = json_module.load(f)
            if accounts:
                info["authenticated"] = True
                if isinstance(accounts, list) and len(accounts) > 0:
                    first = accounts[0]
                    info["account"] = first.get("email") or first.get("account") or str(first)
                elif isinstance(accounts, dict):
                    info["account"] = next(iter(accounts), None)
    except Exception:
        pass

    # Fallback: check oauth creds
    if not info["authenticated"]:
        oauth_path = os.path.join(os.path.expanduser("~"), ".gemini", "oauth_creds.json")
        try:
            if os.path.exists(oauth_path):
                info["authenticated"] = True
        except Exception:
            pass

    return info


@router.get("/system/services")
def get_services(session: Session = Depends(get_session)):
    """查詢所有服務健康狀態（引擎 + CLI 工具，10 秒快取）"""
    now = time_module.time()
    if _services_cache["data"] and (now - _services_cache["ts"]) < _CACHE_TTL:
        return _services_cache["data"]

    # 讀取 Worker 暫停旗標
    paused_setting = session.get(SystemSetting, "worker_paused")
    worker_paused = paused_setting and paused_setting.value == "true"

    result = {
        "pid": os.getpid(),
        "engines": {
            "task_worker": {
                "status": "paused" if worker_paused else "running",
                "interval_sec": 3,
                "is_paused": worker_paused,
            },
            "cron_poller": {
                "status": "running",
                "interval_sec": 60,
                "paused_projects": list(cron_module.paused_projects),
                "last_check": cron_module.last_check_at,
            },
            "websocket": {
                "status": "running",
                "clients": len(websocket_clients),
            },
        },
        "cli_tools": {
            "claude": _check_claude_cli(),
            "gemini": _check_gemini_cli(),
        },
    }

    _services_cache["data"] = result
    _services_cache["ts"] = now
    return result


# ==========================================
# Cron Poller Control (per-project)
# ==========================================
class CronToggleRequest(BaseModel):
    project_id: int


@router.post("/cron/pause")
def pause_cron(body: CronToggleRequest):
    cron_module.paused_projects.add(body.project_id)
    return {"ok": True, "paused_projects": list(cron_module.paused_projects)}


@router.post("/cron/resume")
def resume_cron(body: CronToggleRequest):
    cron_module.paused_projects.discard(body.project_id)
    return {"ok": True, "paused_projects": list(cron_module.paused_projects)}


# ==========================================
# System Settings
# ==========================================
from app.core.default_office_layout import get_default_office_layout_json

SETTING_DEFAULTS = {
    "timezone": "Asia/Taipei",
    "max_workstations": "3",
    "office_layout": get_default_office_layout_json(),
}


@router.get("/settings")
def get_settings(session: Session = Depends(get_session)):
    """回傳所有設定（合併預設值）"""
    result = dict(SETTING_DEFAULTS)
    db_keys = set()
    rows = session.exec(select(SystemSetting)).all()
    for row in rows:
        result[row.key] = row.value
        db_keys.add(row.key)
    # 向下相容：只在 DB 沒有 max_workstations 時才用舊 key
    if "max_workstations" not in db_keys and "max_concurrent_agents" in db_keys:
        result["max_workstations"] = result["max_concurrent_agents"]
    result.pop("max_concurrent_agents", None)
    return result


@router.put("/settings")
def update_settings(data: dict, session: Session = Depends(get_session)):
    """批次更新設定"""
    for key, value in data.items():
        existing = session.get(SystemSetting, key)
        if existing:
            existing.value = str(value)
            session.add(existing)
        else:
            session.add(SystemSetting(key=key, value=str(value)))
    session.commit()
    # 即時更新工作台數量（驗證為正整數且在合理範圍內）
    if "max_workstations" in data:
        from app.core.runner import update_max_workstations
        try:
            val = int(data["max_workstations"])
            if val < 1 or val > 100:
                raise HTTPException(status_code=400, detail="max_workstations 必須介於 1~100")
            update_max_workstations(val)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="max_workstations 必須為正整數")
    return get_settings(session=session)


# ==========================================
# Auth API
# ==========================================
class AuthVerifyRequest(BaseModel):
    password: str

class AuthChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

@router.post("/auth/verify")
def verify_admin_password(req: AuthVerifyRequest, session: Session = Depends(get_session)):
    """驗證管理員密碼"""
    setting = session.get(SystemSetting, "admin_password")
    stored_password = setting.value if setting else "aegis2026!"
    if req.password == stored_password:
        return {"success": True}
    raise HTTPException(status_code=401, detail="密碼錯誤")

@router.post("/auth/change-password")
def change_admin_password(req: AuthChangePasswordRequest, session: Session = Depends(get_session)):
    """修改管理員密碼"""
    setting = session.get(SystemSetting, "admin_password")
    stored_password = setting.value if setting else "aegis2026!"
    if req.current_password != stored_password:
        raise HTTPException(status_code=401, detail="目前密碼錯誤")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密碼至少需要 6 個字元")
    if setting:
        setting.value = req.new_password
        session.add(setting)
    else:
        session.add(SystemSetting(key="admin_password", value=req.new_password))
    session.commit()
    return {"success": True, "message": "密碼已更新"}


# ==========================================
# 頻道設定 API
# ==========================================
CHANNEL_DEFAULTS = {
    "telegram": {"enabled": False, "bot_token": ""},
    "line": {"enabled": False, "channel_secret": "", "access_token": ""},
    "discord": {"enabled": False, "bot_token": ""},
    "slack": {"enabled": False, "bot_token": "", "app_token": ""},
    "wecom": {"enabled": False, "corp_id": "", "corp_secret": "", "agent_id": ""},
    "feishu": {"enabled": False, "app_id": "", "app_secret": "", "is_lark": False},
}


@router.get("/channels")
def get_channel_configs(session: Session = Depends(get_session)):
    """取得所有頻道設定"""
    result = {}
    for channel_name, defaults in CHANNEL_DEFAULTS.items():
        key = f"channel_{channel_name}"
        setting = session.get(SystemSetting, key)
        if setting:
            try:
                config = json_module.loads(setting.value)
                # 合併預設值（確保新欄位存在）
                result[channel_name] = {**defaults, **config}
            except:
                result[channel_name] = dict(defaults)
        else:
            result[channel_name] = dict(defaults)
    return result


@router.put("/channels/{channel_name}")
def update_channel_config(
    channel_name: str,
    config: dict,
    session: Session = Depends(get_session)
):
    """更新單一頻道設定"""
    if channel_name not in CHANNEL_DEFAULTS:
        raise HTTPException(status_code=400, detail=f"Unknown channel: {channel_name}")

    key = f"channel_{channel_name}"
    existing = session.get(SystemSetting, key)
    config_json = json_module.dumps(config, ensure_ascii=False)

    if existing:
        existing.value = config_json
        session.add(existing)
    else:
        session.add(SystemSetting(key=key, value=config_json))
    session.commit()

    return {"status": "ok", "channel": channel_name, "config": config}


@router.get("/channels/status")
async def get_channel_status():
    """取得所有頻道的即時狀態"""
    from app.channels import channel_manager
    statuses = await channel_manager.health_check_all()
    return {
        "channels": [
            {
                "platform": s.platform,
                "connected": s.is_connected,
                "error": s.error,
                "last_heartbeat": s.last_heartbeat.isoformat() if s.last_heartbeat else None,
                "stats": s.stats,
            }
            for s in statuses.values()
        ]
    }


@router.post("/channels/restart")
async def restart_channels():
    """重啟所有頻道（套用新設定）"""
    from app.channels import channel_manager
    try:
        count = await channel_manager.restart_all()
        return {"status": "ok", "message": f"已重啟 {count} 個頻道", "active_channels": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# Account CRUD (多帳號管理)
# ==========================================
from app.core.account_manager import (
    capture_current_credential, activate_account,
    get_account_email, get_subscription_type,
    get_member_with_accounts, select_best_account,
    start_gcloud_auth, complete_gcloud_auth, cancel_gcloud_auth, check_gcloud_status,
)


class AccountCreateRequest(BaseModel):
    provider: str  # "claude" | "gemini"
    name: str


@router.get("/accounts")
def list_accounts(session: Session = Depends(get_session)):
    """列出所有帳號"""
    accounts = session.exec(select(Account).order_by(Account.provider, Account.id)).all()
    return [a.model_dump() for a in accounts]


@router.post("/accounts")
def create_account(data: AccountCreateRequest, session: Session = Depends(get_session)):
    """從目前 CLI 登入狀態新增帳號"""
    import re, time as _t
    # 自動產生 profile name: provider-name-timestamp
    safe_name = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff]', '-', data.name).strip('-').lower()
    profile_name = f"{data.provider}-{safe_name}-{int(_t.time())}"
    filename = capture_current_credential(data.provider, profile_name)
    if not filename:
        raise HTTPException(status_code=400, detail=f"找不到 {data.provider} 的登入憑證")

    email = get_account_email(data.provider, filename)
    subscription = get_subscription_type(data.provider, filename)

    account = Account(
        provider=data.provider,
        name=data.name,
        credential_file=filename,
        subscription=subscription,
        email=email,
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    return account.model_dump()


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int, session: Session = Depends(get_session)):
    account = session.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    # 刪除所有綁定
    bindings = session.exec(select(MemberAccount).where(MemberAccount.account_id == account_id)).all()
    for b in bindings:
        session.delete(b)
    session.delete(account)
    session.commit()
    return {"ok": True}


class AccountUpdateRequest(BaseModel):
    name: Optional[str] = None
    is_healthy: Optional[bool] = None


@router.patch("/accounts/{account_id}")
def update_account(account_id: int, data: AccountUpdateRequest, session: Session = Depends(get_session)):
    account = session.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if data.name is not None:
        account.name = data.name
    if data.is_healthy is not None:
        account.is_healthy = data.is_healthy
    session.add(account)
    session.commit()
    session.refresh(account)
    return account.model_dump()


# ==========================================
# Member CRUD
# ==========================================
class MemberCreateRequest(BaseModel):
    name: str
    avatar: str = ""
    role: str = ""
    description: str = ""


@router.get("/members")
def list_members(session: Session = Depends(get_session)):
    """列出所有成員 + 綁定帳號"""
    members = session.exec(select(Member).order_by(Member.id)).all()
    result = []
    for m in members:
        bindings = session.exec(
            select(MemberAccount)
            .where(MemberAccount.member_id == m.id)
            .order_by(MemberAccount.priority)
        ).all()
        accounts = []
        primary_provider = ""
        for b in bindings:
            acc = session.get(Account, b.account_id)
            if acc:
                if not primary_provider:
                    primary_provider = acc.provider
                accounts.append({
                    "account_id": acc.id,
                    "priority": b.priority,
                    "model": b.model,
                    "name": acc.name,
                    "provider": acc.provider,
                    "subscription": acc.subscription,
                    "is_healthy": acc.is_healthy,
                })
        result.append({
            **m.model_dump(),
            "provider": primary_provider,
            "accounts": accounts,
        })
    return result


@router.post("/members")
def create_member(data: MemberCreateRequest, session: Session = Depends(get_session)):
    member = Member(**data.model_dump())
    session.add(member)
    session.commit()
    session.refresh(member)
    return member.model_dump()


class MemberUpdateRequest(BaseModel):
    name: Optional[str] = None
    avatar: Optional[str] = None
    role: Optional[str] = None
    description: Optional[str] = None
    sprite_index: Optional[int] = None
    portrait: Optional[str] = None


@router.put("/members/{member_id}")
def update_member(member_id: int, data: MemberUpdateRequest, session: Session = Depends(get_session)):
    member = session.get(Member, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    for field, val in data.model_dump(exclude_unset=True).items():
        setattr(member, field, val)
    session.add(member)
    session.commit()
    session.refresh(member)
    return member.model_dump()


@router.delete("/members/{member_id}")
def delete_member(member_id: int, session: Session = Depends(get_session)):
    member = session.get(Member, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    bindings = session.exec(select(MemberAccount).where(MemberAccount.member_id == member_id)).all()
    for b in bindings:
        session.delete(b)
    session.delete(member)
    session.commit()
    return {"ok": True}


# ==========================================
# Member-Account Binding
# ==========================================
class BindAccountRequest(BaseModel):
    account_id: int
    priority: int = 0
    model: str = ""


@router.post("/members/{member_id}/accounts")
def bind_account(member_id: int, data: BindAccountRequest, session: Session = Depends(get_session)):
    """綁定帳號到成員"""
    member = session.get(Member, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    account = session.get(Account, data.account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    # 檢查是否已綁定
    existing = session.exec(
        select(MemberAccount)
        .where(MemberAccount.member_id == member_id, MemberAccount.account_id == data.account_id)
    ).first()
    if existing:
        existing.priority = data.priority
        existing.model = data.model
        session.add(existing)
    else:
        session.add(MemberAccount(member_id=member_id, account_id=data.account_id, priority=data.priority, model=data.model))
    session.commit()
    return {"ok": True}


@router.delete("/members/{member_id}/accounts/{account_id}")
def unbind_account(member_id: int, account_id: int, session: Session = Depends(get_session)):
    """解綁帳號"""
    binding = session.exec(
        select(MemberAccount)
        .where(MemberAccount.member_id == member_id, MemberAccount.account_id == account_id)
    ).first()
    if not binding:
        raise HTTPException(status_code=404, detail="Binding not found")
    session.delete(binding)
    session.commit()
    return {"ok": True}


# ==========================================
# Task Stats
# ==========================================
@router.get("/task-stats")
def task_stats(session: Session = Depends(get_session)):
    """任務統計：token 用量、任務數、費用（使用 SQL 聚合避免全表載入）"""
    from sqlalchemy import func, case

    # 單次 SQL 聚合查詢取得總計數據
    row = session.exec(
        select(
            func.count(TaskLog.id).label("total"),
            func.sum(case((TaskLog.status == "success", 1), else_=0)).label("success"),
            func.sum(case((TaskLog.status.in_(["error", "timeout"]), 1), else_=0)).label("failed"),
            func.coalesce(func.sum(TaskLog.input_tokens), 0).label("input"),
            func.coalesce(func.sum(TaskLog.output_tokens), 0).label("output"),
            func.coalesce(func.sum(TaskLog.cache_read_tokens), 0).label("cache_read"),
            func.coalesce(func.sum(TaskLog.cache_creation_tokens), 0).label("cache_create"),
            func.coalesce(func.sum(TaskLog.cost_usd), 0).label("cost"),
            func.coalesce(func.sum(TaskLog.duration_ms), 0).label("duration"),
        )
    ).one()

    # 按 provider 分組（SQL 聚合）
    provider_rows = session.exec(
        select(
            func.coalesce(TaskLog.provider, "unknown"),
            func.count(TaskLog.id),
            func.coalesce(func.sum(TaskLog.input_tokens), 0),
            func.coalesce(func.sum(TaskLog.output_tokens), 0),
            func.coalesce(func.sum(TaskLog.cost_usd), 0),
        ).group_by(func.coalesce(TaskLog.provider, "unknown"))
    ).all()
    by_provider = {
        p: {"tasks": int(cnt), "input_tokens": int(inp), "output_tokens": int(out), "cost_usd": float(cost)}
        for p, cnt, inp, out, cost in provider_rows
    }

    # 最近 10 筆
    recent = session.exec(select(TaskLog).order_by(TaskLog.id.desc()).limit(10)).all()

    return {
        "total_tasks": int(row[0]),
        "success_tasks": int(row[1] or 0),
        "failed_tasks": int(row[2] or 0),
        "total_input_tokens": int(row[3]),
        "total_output_tokens": int(row[4]),
        "total_cache_read_tokens": int(row[5]),
        "total_cache_creation_tokens": int(row[6]),
        "total_cost_usd": float(row[7]),
        "total_duration_ms": int(row[8]),
        "by_provider": by_provider,
        "recent": [l.model_dump() for l in recent],
    }


# ==========================================
# Member Task History
# ==========================================
@router.get("/members/{member_id}/history")
def get_member_history(member_id: int, limit: int = 10, session: Session = Depends(get_session)):
    """取得角色的任務執行歷史"""
    logs = session.exec(
        select(TaskLog)
        .where(TaskLog.member_id == member_id)
        .order_by(TaskLog.created_at.desc())
        .limit(limit)
    ).all()
    return [l.model_dump() for l in logs]


# ==========================================
# Member Portrait Upload
# ==========================================
@router.post("/members/{member_id}/portrait")
async def upload_portrait(member_id: int, file: UploadFile = File(...), session: Session = Depends(get_session)):
    """上傳成員立繪圖片"""
    member = session.get(Member, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    # 檢查檔案類型
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    # 產生唯一檔名
    ext = Path(file.filename).suffix if file.filename else ".png"
    filename = f"{member_id}_{uuid.uuid4().hex[:8]}{ext}"
    filepath = UPLOAD_DIR / filename

    # 刪除舊立繪
    if member.portrait:
        old_path = UPLOAD_DIR / Path(member.portrait).name
        if old_path.exists():
            old_path.unlink()

    # 儲存新檔案（限制 10MB）
    MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB
    content = await file.read(MAX_UPLOAD_SIZE + 1)
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="檔案大小超過 10MB 限制")
    with open(filepath, "wb") as f:
        f.write(content)

    # 更新資料庫
    member.portrait = f"/api/v1/portraits/{filename}"
    session.add(member)
    session.commit()

    return {"portrait": member.portrait}


@router.get("/portraits/{filename}")
async def get_portrait(filename: str):
    """取得立繪圖片（含快取標頭）"""
    filepath = UPLOAD_DIR / filename
    # 防止路徑穿越攻擊
    if not filepath.resolve().is_relative_to(UPLOAD_DIR.resolve()):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Portrait not found")
    # 檔名含 hash，可長期快取（1 年）
    return FileResponse(
        filepath,
        headers={"Cache-Control": "public, max-age=31536000, immutable"}
    )


# ==========================================
# AI Portrait Generation
# ==========================================
@router.post("/members/{member_id}/generate-portrait")
async def generate_portrait_api(member_id: int, file: UploadFile = File(...), session: Session = Depends(get_session)):
    """使用 AI 生成成員立繪"""
    from app.core.portrait_generator import generate_member_portrait

    member = session.get(Member, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    # 檢查檔案類型
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    # 取得 Gemini API Key
    api_key_setting = session.get(SystemSetting, "gemini_api_key")
    if not api_key_setting or not api_key_setting.value:
        raise HTTPException(status_code=400, detail="請先在設定頁面設定 Gemini API Key")

    try:
        # 讀取照片
        photo_bytes = await file.read()

        # 生成立繪
        png_bytes, description = generate_member_portrait(
            photo_bytes,
            member.name,
            api_key_setting.value
        )

        # 儲存 PNG
        filename = f"{member_id}_{uuid.uuid4().hex[:8]}.png"
        filepath = UPLOAD_DIR / filename

        # 刪除舊立繪
        if member.portrait:
            old_name = Path(member.portrait).name
            old_path = UPLOAD_DIR / old_name
            if old_path.exists():
                old_path.unlink()

        with open(filepath, "wb") as f:
            f.write(png_bytes)

        # 更新資料庫
        member.portrait = f"/api/v1/portraits/{filename}"
        session.add(member)
        session.commit()

        return {
            "portrait": member.portrait,
            "description": description
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成失敗：{str(e)}")


# ==========================================
# Guided CLI Login (引導式 CLI 登入)
# ==========================================
@router.get("/gcloud/status")
def get_gcloud_status():
    """檢查 gcloud CLI 狀態"""
    return check_gcloud_status()


@router.post("/gcloud/auth/init")
def init_gcloud_auth():
    """啟動 gcloud 引導式登入，回傳授權 URL"""
    try:
        session_id, auth_url = start_gcloud_auth()
        return {
            "session_id": session_id,
            "auth_url": auth_url,
            "instructions": [
                "1. 在您的瀏覽器開啟上方的授權網址",
                "2. 使用 Google 帳號登入並授權存取",
                "3. 複製 Google 給您的授權碼",
                "4. 將授權碼貼到下方輸入框完成登入",
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class GcloudAuthCompleteRequest(BaseModel):
    session_id: str
    auth_code: str


@router.post("/gcloud/auth/complete")
def complete_gcloud_auth_api(data: GcloudAuthCompleteRequest, session: Session = Depends(get_session)):
    """完成 gcloud 引導式登入，並自動建立 Gemini 帳號"""
    try:
        success = complete_gcloud_auth(data.session_id, data.auth_code)
        if not success:
            raise HTTPException(status_code=400, detail="登入失敗")

        # 取得認證的 email
        status = check_gcloud_status()
        email = status.get("account", "")
        if not email:
            return {"ok": True, "message": "登入成功，但無法取得帳號資訊"}

        # 檢查是否已存在此 email 的 Gemini 帳號
        existing = session.exec(
            select(Account).where(Account.provider == "gemini", Account.email == email)
        ).first()

        if existing:
            # 更新健康狀態
            existing.is_healthy = True
            session.add(existing)
            session.commit()
            return {"ok": True, "message": f"帳號 {email} 已更新", "account_id": existing.id}

        # 建立新的 Gemini 帳號
        # credential_file 指向 gcloud 的 application_default_credentials
        new_account = Account(
            provider="gemini",
            name=email.split("@")[0],  # 用 email 前綴當名稱
            credential_file="application_default_credentials.json",
            subscription="gcloud",
            email=email,
            is_healthy=True,
        )
        session.add(new_account)
        session.commit()
        session.refresh(new_account)

        return {"ok": True, "message": f"已建立 Gemini 帳號：{email}", "account_id": new_account.id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class GcloudAuthCancelRequest(BaseModel):
    session_id: str


@router.post("/gcloud/auth/cancel")
def cancel_gcloud_auth_api(data: GcloudAuthCancelRequest):
    """取消 gcloud 引導式登入"""
    cancel_gcloud_auth(data.session_id)
    return {"ok": True}


# ==========================================
# CLI Management
# ==========================================
@router.get("/cli/status")
def get_cli_status():
    """檢查 AI CLI 工具安裝狀態"""
    import shutil

    result = {
        "claude": {"installed": False, "version": None, "path": None},
        "gemini": {"installed": False, "version": None, "path": None},
        "codex": {"installed": False, "version": None, "path": None},
        "ollama": {"installed": False, "version": None, "path": None},
    }

    # 檢查 Claude CLI（使用跨平台的 shutil.which）
    try:
        claude_path = shutil.which("claude")
        if claude_path:
            result["claude"]["installed"] = True
            result["claude"]["path"] = claude_path
            # 取得版本
            ver_result = subprocess.run(
                ["claude", "--version"], capture_output=True, text=True, timeout=10
            )
            if ver_result.returncode == 0:
                result["claude"]["version"] = ver_result.stdout.strip().split("\n")[0]
    except Exception:
        pass

    # 檢查 Gemini CLI（Windows 的 .cmd 需要 shell=True）
    try:
        gemini_path = shutil.which("gemini")
        if gemini_path:
            result["gemini"]["installed"] = True
            result["gemini"]["path"] = gemini_path
            # 取得版本（Windows .cmd 需要 shell=True）
            ver_result = subprocess.run(
                "gemini --version", shell=True, capture_output=True, text=True, timeout=10
            )
            if ver_result.returncode == 0:
                result["gemini"]["version"] = ver_result.stdout.strip().split("\n")[0]
    except Exception:
        pass

    # 檢查 Codex CLI (OpenAI)
    try:
        codex_path = shutil.which("codex")
        if codex_path:
            result["codex"]["installed"] = True
            result["codex"]["path"] = codex_path
            # 取得版本（Windows .cmd 需要 shell=True）
            ver_result = subprocess.run(
                "codex --version", shell=True, capture_output=True, text=True, timeout=10
            )
            if ver_result.returncode == 0:
                result["codex"]["version"] = ver_result.stdout.strip().split("\n")[0]
    except Exception:
        pass

    # 檢查 Ollama CLI
    try:
        ollama_path = shutil.which("ollama")
        if ollama_path:
            result["ollama"]["installed"] = True
            result["ollama"]["path"] = ollama_path
            # 取得版本
            ver_result = subprocess.run(
                ["ollama", "--version"], capture_output=True, text=True, timeout=10
            )
            if ver_result.returncode == 0:
                # ollama version is 0.9.0
                result["ollama"]["version"] = ver_result.stdout.strip().split("\n")[0]
    except Exception:
        pass

    return result


@router.post("/cli/claude/install")
def install_claude_cli():
    """安裝 Claude CLI"""
    import platform
    try:
        # Windows 不需要 sudo，Linux 需要
        if platform.system() == "Windows":
            cmd = "npm install -g @anthropic-ai/claude-code"
        else:
            cmd = "sudo -n npm install -g @anthropic-ai/claude-code"

        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            return {"ok": True, "message": "Claude CLI 安裝成功", "output": result.stdout}
        else:
            raise HTTPException(status_code=500, detail=f"安裝失敗: {result.stderr}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="安裝超時")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cli/gemini/install")
def install_gemini_cli():
    """安裝 Gemini CLI"""
    import platform
    try:
        # Windows 不需要 sudo，Linux 需要
        if platform.system() == "Windows":
            cmd = "npm install -g @google/gemini-cli"
        else:
            cmd = "sudo -n npm install -g @google/gemini-cli"

        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            return {"ok": True, "message": "Gemini CLI 安裝成功", "output": result.stdout}
        else:
            raise HTTPException(status_code=500, detail=f"安裝失敗: {result.stderr}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="安裝超時")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cli/codex/install")
def install_codex_cli():
    """安裝 Codex CLI (OpenAI)"""
    import platform
    try:
        # Windows 不需要 sudo，Linux 需要
        if platform.system() == "Windows":
            cmd = "npm install -g @openai/codex"
        else:
            cmd = "sudo -n npm install -g @openai/codex"

        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            return {"ok": True, "message": "Codex CLI 安裝成功", "output": result.stdout}
        else:
            raise HTTPException(status_code=500, detail=f"安裝失敗: {result.stderr}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="安裝超時")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ollama/models")
def get_ollama_models():
    """取得 Ollama 已下載的模型列表"""
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return {"models": [], "error": "Ollama 未安裝或未啟動"}

        # 解析輸出格式：NAME    ID    SIZE    MODIFIED
        lines = result.stdout.strip().split("\n")
        models = []
        for line in lines[1:]:  # 跳過標題行
            parts = line.split()
            if parts:
                models.append({
                    "name": parts[0],
                    "id": parts[1] if len(parts) > 1 else "",
                    "size": parts[2] if len(parts) > 2 else "",
                })
        return {"models": models}
    except FileNotFoundError:
        return {"models": [], "error": "Ollama 未安裝"}
    except subprocess.TimeoutExpired:
        return {"models": [], "error": "查詢超時"}
    except Exception as e:
        return {"models": [], "error": str(e)}
