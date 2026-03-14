from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlmodel import Session, select
from sqlalchemy import func as sa_func
from typing import Dict, List, Optional
from pydantic import BaseModel
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from app.database import get_session
from app.models.core import Project, Card, StageList, CronJob, CronLog, SystemSetting, Account, Member, MemberAccount, TaskLog, CardIndex, InviteCode, BotUser, BotUserProject, EmailMessage
from typing import Any
# Worker 負責卡片任務執行，runner.py 只用於 chat/email 即時互動
from app.core.usage_poller import get_cached_claude_usage, get_cached_gemini_usage, get_last_updated
# Worker 程序獨立執行，暫停狀態改用 DB SystemSetting "worker_paused"
import app.core.cron_poller as cron_module
from app.core.ws_manager import websocket_clients
from app.core.card_file import CardData, read_card as read_card_md, write_card, card_file_path
from app.core.card_index import sync_card_to_index, remove_card_from_index, query_board, next_card_id, rebuild_index
from app.core.auth import require_api_key
from croniter import croniter
import asyncio
import subprocess
import time as time_module
import json as json_module
import os
import re
import shutil
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
    description: Optional[str] = None
    position: int
    member_id: Optional[int] = None
    member: Optional[MemberBrief] = None
    cards: List[CardResponse] = []
    # 階段配置
    system_instruction: Optional[str] = None
    prompt_template: Optional[str] = None
    is_ai_stage: bool = True
    is_member_bound: bool = False
    # 完成/失敗動作
    on_success_action: str = "none"
    on_fail_action: str = "none"

# ==========================================
# Project Schemas
# ==========================================
class ProjectCreate(BaseModel):
    name: str
    path: str
    deploy_type: str = "none"
    default_member_id: Optional[int] = None  # 專案預設成員


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    path: Optional[str] = None
    is_active: Optional[bool] = None
    deploy_type: Optional[str] = None
    default_member_id: Optional[int] = None  # 專案預設成員


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
        default_member_id=data.default_member_id,
    )
    session.add(project)
    session.commit()
    session.refresh(project)

    # 4. 建立預設 StageList
    # (name, is_ai, on_success, on_fail, description)
    stages_config = [
        ("Backlog", False, "none", "none", "待處理任務佇列。手動或由排程系統加入卡片，不會自動執行。"),
        ("Scheduled", True, "delete", "none", "排程觸發的臨時任務。由 CronJob 自動建立卡片，執行完成後依動作設定處理（預設刪除）。"),
        ("Planning", True, "none", "none",
         "任務規劃階段。AI 分析需求，拆解為具體步驟，確認技術方案與影響範圍，產出執行計畫後將卡片移至下一階段。"),
        ("Developing", True, "none", "none",
         "開發執行階段。AI 依據規劃方案編寫程式碼、建立或更新測試、提交 commit，完成後將卡片移至驗證階段。"),
        ("Verifying", True, "none", "none",
         "驗證審查階段。AI 執行測試、檢查程式碼品質與安全性、確認功能符合需求，通過後移至 Done，未通過則退回 Developing。"),
        ("Done", False, "none", "none", "已完成。任務已通過驗證，等待人工確認或合併。"),
        ("Aborted", False, "none", "none", "已中止。任務因故取消或多次失敗後放棄。"),
    ]
    for idx, (name, is_ai, on_success, on_fail, desc) in enumerate(stages_config):
        sl = StageList(
            project_id=project.id,
            name=name,
            description=desc,
            position=idx,
            is_ai_stage=is_ai,
            on_success_action=on_success,
            on_fail_action=on_fail,
        )
        session.add(sl)
    session.commit()

    return project

@router.patch("/projects/{project_id}", response_model=Project)
def update_project(project_id: int, update_data: ProjectUpdate, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    # 系統專案禁止改名（名稱未變更時放行）
    if project.is_system and update_data.name is not None and update_data.name != project.name:
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
    if update_data.default_member_id is not None:
        project.default_member_id = update_data.default_member_id if update_data.default_member_id != 0 else None
    session.add(project)
    session.commit()
    session.refresh(project)
    return project

def _ensure_member_inboxes(session: Session, project_id: int):
    """AEGIS 系統專案：為每個成員自動補建綁定收件匣"""
    all_members = session.exec(select(Member)).all()
    if not all_members:
        return
    bound_member_ids = set(
        mid for mid in session.exec(
            select(StageList.member_id).where(
                StageList.project_id == project_id,
                StageList.is_member_bound == True,
            )
        ).all() if mid is not None
    )
    missing = [m for m in all_members if m.id not in bound_member_ids]
    if not missing:
        return
    max_pos = session.exec(
        select(StageList.position).where(StageList.project_id == project_id).order_by(StageList.position.desc())
    ).first()
    pos = (max_pos or 0) + 1
    for m in missing:
        session.add(StageList(
            project_id=project_id,
            name=f"{m.name} 收件匣",
            position=pos,
            member_id=m.id,
            is_ai_stage=True,
            is_member_bound=True,
        ))
        pos += 1
    session.commit()


@router.get("/projects/{project_id}/board", response_model=List[StageListResponse])
def read_project_board(project_id: int, session: Session = Depends(get_session)):
    """一次抓取整個看板所需的資料：列表與其中的卡片（MD-driven via CardIndex）"""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # AEGIS 系統專案：自動補建成員收件匣
    if project.is_system:
        _ensure_member_inboxes(session, project_id)

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
            description=l.description,
            position=l.position,
            member_id=l.member_id,
            member=member_brief,
            cards=[CardResponse(
                id=ci.card_id, list_id=ci.list_id, title=ci.title,
                description=ci.description, status=ci.status, created_at=ci.created_at
            ) for ci in list_cards],
            # 階段配置
            system_instruction=l.system_instruction,
            prompt_template=l.prompt_template,
            is_ai_stage=l.is_ai_stage,
            is_member_bound=l.is_member_bound,
            on_success_action=l.on_success_action,
            on_fail_action=l.on_fail_action,
        ))
    return result

# ==========================================
# StageList Routes
# ==========================================
class StageListUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None  # 階段說明
    position: Optional[int] = None
    member_id: Optional[int] = None  # null = 使用預設路由
    # 階段行為配置
    system_instruction: Optional[str] = None
    prompt_template: Optional[str] = None
    is_ai_stage: Optional[bool] = None
    # 完成/失敗後動作
    on_success_action: Optional[str] = None  # none | move_to:<list_id> | archive | delete
    on_fail_action: Optional[str] = None


@router.patch("/lists/{list_id}")
def update_stage_list(list_id: int, data: StageListUpdateRequest, session: Session = Depends(get_session)):
    stage_list = session.get(StageList, list_id)
    if not stage_list:
        raise HTTPException(status_code=404, detail="StageList not found")

    # 成員綁定列表：禁止變更 member_id
    if stage_list.is_member_bound and data.member_id is not None and data.member_id != stage_list.member_id:
        raise HTTPException(status_code=403, detail="成員綁定列表無法變更成員指派")

    # 更新名稱
    if data.name is not None and data.name.strip():
        stage_list.name = data.name.strip()

    # 更新說明
    if data.description is not None:
        stage_list.description = data.description if data.description.strip() else None

    # 更新位置
    if data.position is not None:
        stage_list.position = data.position

    # 更新成員指派
    if data.member_id is not None:
        stage_list.member_id = data.member_id if data.member_id != 0 else None

    # 更新階段配置
    if data.system_instruction is not None:
        stage_list.system_instruction = data.system_instruction if data.system_instruction else None
    if data.prompt_template is not None:
        stage_list.prompt_template = data.prompt_template if data.prompt_template else None
    if data.is_ai_stage is not None:
        stage_list.is_ai_stage = data.is_ai_stage

    # 更新完成/失敗動作
    if data.on_success_action is not None:
        stage_list.on_success_action = data.on_success_action
    if data.on_fail_action is not None:
        stage_list.on_fail_action = data.on_fail_action

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
        "system_instruction": stage_list.system_instruction,
        "prompt_template": stage_list.prompt_template,
        "is_ai_stage": stage_list.is_ai_stage,
        "description": stage_list.description,
        "on_success_action": stage_list.on_success_action,
        "on_fail_action": stage_list.on_fail_action,
    }


class MemberListCreateRequest(BaseModel):
    member_id: int
    name: Optional[str] = None  # 預設："{member.name} 收件匣"


@router.post("/projects/{project_id}/member-lists")
def create_member_bound_list(project_id: int, data: MemberListCreateRequest, session: Session = Depends(get_session)):
    """建立成員綁定列表（收件匣）"""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    member = session.get(Member, data.member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    # 檢查重複：此專案已有該成員的綁定列表
    existing = session.exec(
        select(StageList).where(
            StageList.project_id == project_id,
            StageList.member_id == data.member_id,
            StageList.is_member_bound == True,
        )
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"{member.name} 已有綁定列表")

    # 計算 position
    max_pos = session.exec(
        select(StageList.position).where(StageList.project_id == project_id).order_by(StageList.position.desc())
    ).first()
    new_position = (max_pos or 0) + 1

    name = data.name.strip() if data.name and data.name.strip() else f"{member.name} 收件匣"

    stage_list = StageList(
        project_id=project_id,
        name=name,
        position=new_position,
        member_id=data.member_id,
        is_ai_stage=True,
        is_member_bound=True,
    )
    session.add(stage_list)
    session.commit()
    session.refresh(stage_list)

    member_brief = MemberBrief(
        id=member.id, name=member.name, avatar=member.avatar,
        provider=_get_member_primary_provider(member.id, session),
    )

    return {
        "ok": True,
        "id": stage_list.id,
        "name": stage_list.name,
        "project_id": stage_list.project_id,
        "position": stage_list.position,
        "member_id": stage_list.member_id,
        "member": member_brief,
        "is_member_bound": True,
    }


class StageListReorderRequest(BaseModel):
    order: list[int]  # list of stage_list IDs in desired order


@router.post("/lists/reorder")
def reorder_stage_lists(data: StageListReorderRequest, session: Session = Depends(get_session)):
    """批次更新 StageList 順序"""
    for idx, list_id in enumerate(data.order):
        stage_list = session.get(StageList, list_id)
        if stage_list:
            stage_list.position = idx
            session.add(stage_list)
    session.commit()
    return {"ok": True}


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
    target_list_id: Optional[int] = None  # 0 = 清除（回到預設 Scheduled）

@router.patch("/cron-jobs/{job_id}", response_model=CronJob)
def update_cron_job(job_id: int, update_data: CronJobUpdate, session: Session = Depends(get_session)):
    job = session.get(CronJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="CronJob not found")
    cron_changed = False
    for field in ["name", "description", "cron_expression", "system_instruction", "prompt_template", "is_enabled"]:
        val = getattr(update_data, field)
        if val is not None:
            if field == "cron_expression" and val != job.cron_expression:
                cron_changed = True
            setattr(job, field, val)
    # 目標列表：0 = 清除，正數 = 設定
    if update_data.target_list_id is not None:
        job.target_list_id = update_data.target_list_id if update_data.target_list_id != 0 else None
    # cron 表達式或啟用狀態改變時，重算下次執行時間
    if cron_changed or (update_data.is_enabled is not None):
        from app.core.cron_poller import _calculate_next_time, _get_system_timezone
        tz_name = _get_system_timezone(session)
        next_time = _calculate_next_time(job.cron_expression, tz_name)
        if next_time:
            job.next_scheduled_at = next_time
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
    target_list_id: Optional[int] = None  # 目標列表，None=Scheduled

@router.post("/cron-jobs/", response_model=CronJob)
def create_cron_job(data: CronJobCreateRequest, session: Session = Depends(get_session)):
    project = session.get(Project, data.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    # 計算下次執行時間（用系統時區解析 cron 表達式）
    next_time = None
    try:
        tz_setting = session.get(SystemSetting, "timezone")
        tz_name = tz_setting.value if tz_setting and tz_setting.value else "Asia/Taipei"
        local_tz = ZoneInfo(tz_name)
        now_local = datetime.now(local_tz)
        cron = croniter(data.cron_expression, now_local)
        next_local = cron.get_next(datetime)
        if next_local.tzinfo is None:
            next_local = next_local.replace(tzinfo=local_tz)
        next_time = next_local.astimezone(timezone.utc)
    except Exception:
        pass
    job = CronJob(
        project_id=data.project_id,
        name=data.name,
        description=data.description,
        cron_expression=data.cron_expression,
        system_instruction=data.system_instruction,
        prompt_template=data.prompt_template,
        target_list_id=data.target_list_id,
        next_scheduled_at=next_time,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


@router.post("/cron-jobs/fix-schedules")
def fix_cron_schedules(session: Session = Depends(get_session)):
    """修復所有排程的 next_scheduled_at（以系統時區重新計算下次執行時間）"""
    from app.core.cron_poller import _calculate_next_time, _get_system_timezone
    tz_name = _get_system_timezone(session)
    jobs = session.exec(select(CronJob).where(CronJob.is_enabled == True)).all()
    fixed_count = 0
    for job in jobs:
        try:
            next_time = _calculate_next_time(job.cron_expression, tz_name)
            if next_time:
                job.next_scheduled_at = next_time
                session.add(job)
                fixed_count += 1
        except Exception as e:
            pass
    session.commit()
    return {"ok": True, "fixed_count": fixed_count}


@router.post("/cron-jobs/{job_id}/trigger")
def trigger_cron_job(job_id: int, session: Session = Depends(get_session)):
    """手動觸發 CronJob，建立待執行卡片"""
    job = session.get(CronJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="CronJob not found")

    from app.core.cron_poller import create_card_for_cron_job
    card_id, error = create_card_for_cron_job(session, job, update_next_time=False)

    if error:
        raise HTTPException(status_code=409, detail=error)

    return {"ok": True, "card_id": card_id, "message": f"已手動觸發「{job.name}」"}


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


@router.delete("/cards/cleanup/duplicates")
def cleanup_duplicate_cards(
    project_id: int,
    dry_run: bool = True,
    session: Session = Depends(get_session)
):
    """清理指定專案的重複卡片（保留每個標題最舊的一張）

    Args:
        project_id: 專案 ID
        dry_run: True=只顯示會刪除的卡片，False=實際刪除
    """
    from sqlmodel import select, func

    # 找出重複的標題
    stmt = (
        select(CardIndex.title, func.min(CardIndex.card_id).label("keep_id"), func.count().label("cnt"))
        .where(CardIndex.project_id == project_id)
        .group_by(CardIndex.title)
        .having(func.count() > 1)
    )
    duplicates = session.exec(stmt).all()

    if not duplicates:
        return {"ok": True, "message": "No duplicates found", "deleted": 0}

    # 收集要刪除的卡片
    cards_to_delete = []
    for title, keep_id, cnt in duplicates:
        # 找出同標題但不是保留的卡片
        dup_cards = session.exec(
            select(CardIndex)
            .where(CardIndex.project_id == project_id)
            .where(CardIndex.title == title)
            .where(CardIndex.card_id != keep_id)
        ).all()
        cards_to_delete.extend(dup_cards)

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "would_delete": len(cards_to_delete),
            "duplicate_titles": len(duplicates),
            "preview": [{"card_id": c.card_id, "title": c.title[:50]} for c in cards_to_delete[:20]]
        }

    # 實際刪除
    deleted_count = 0
    for idx in cards_to_delete:
        if idx.status == "running":
            continue  # 跳過運行中的
        # 刪除 MD 檔案
        if idx.file_path:
            md_path = Path(idx.file_path)
            if md_path.exists():
                md_path.unlink()
        # 刪除 ORM Card
        orm_card = session.get(Card, idx.card_id)
        if orm_card:
            session.delete(orm_card)
        # 刪除 CardIndex
        session.delete(idx)
        _card_locks.pop(idx.card_id, None)
        deleted_count += 1

    session.commit()
    return {"ok": True, "deleted": deleted_count, "duplicate_titles": len(duplicates)}


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


@router.get("/cron-jobs/{job_id}")
def get_cron_job(job_id: int, session: Session = Depends(get_session)):
    """取得單一排程詳情"""
    job = session.get(CronJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="CronJob not found")
    return job


# ==========================================
# TaskLog（任務執行記錄）
# ==========================================
@router.get("/task-logs/")
def list_task_logs(
    member_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    """取得任務執行記錄（可按成員篩選）"""
    query = select(TaskLog)
    count_query = select(sa_func.count()).select_from(TaskLog)
    if member_id is not None:
        query = query.where(TaskLog.member_id == member_id)
        count_query = count_query.where(TaskLog.member_id == member_id)
    logs = session.exec(query.order_by(TaskLog.created_at.desc()).offset(offset).limit(limit)).all()
    total = session.exec(count_query).one()
    return {"items": logs, "total": total}


@router.get("/task-logs/{log_id}")
def get_task_log(log_id: int, session: Session = Depends(get_session)):
    """取得單筆任務執行記錄詳情"""
    log = session.get(TaskLog, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="TaskLog not found")
    return log


@router.get("/cards/{card_id}/broadcast-logs")
def get_card_broadcast_logs(card_id: int, session: Session = Depends(get_session)):
    """取得卡片的廣播記錄（24 小時內）"""
    from app.models.core import BroadcastLog
    logs = session.exec(
        select(BroadcastLog)
        .where(BroadcastLog.card_id == card_id)
        .order_by(BroadcastLog.created_at)
    ).all()
    return [{"line": l.line, "created_at": l.created_at} for l in logs]


# ==========================================
# CronLog（排程執行記錄）
# ==========================================
@router.get("/cron-jobs/{job_id}/logs")
def list_cron_logs(job_id: int, limit: int = 50, offset: int = 0, session: Session = Depends(get_session)):
    """取得特定排程的執行記錄"""
    logs = session.exec(
        select(CronLog)
        .where(CronLog.cron_job_id == job_id)
        .order_by(CronLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    total = session.exec(
        select(sa_func.count()).select_from(CronLog).where(CronLog.cron_job_id == job_id)
    ).one()
    return {"items": logs, "total": total}


@router.get("/cron-logs/{log_id}")
def get_cron_log(log_id: int, session: Session = Depends(get_session)):
    """取得單筆排程執行記錄詳情"""
    log = session.get(CronLog, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="CronLog not found")
    return log


@router.get("/cron-logs/")
def list_all_cron_logs(limit: int = 50, offset: int = 0, project_id: Optional[int] = None, session: Session = Depends(get_session)):
    """取得所有排程執行記錄（可按專案篩選）"""
    query = select(CronLog)
    count_query = select(sa_func.count()).select_from(CronLog)
    if project_id is not None:
        query = query.where(CronLog.project_id == project_id)
        count_query = count_query.where(CronLog.project_id == project_id)
    logs = session.exec(query.order_by(CronLog.created_at.desc()).offset(offset).limit(limit)).all()
    total = session.exec(count_query).one()
    return {"items": logs, "total": total}


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

    now = datetime.now(timezone.utc)

    # Worker 在獨立程序中，此處無法直接 kill 進程
    # 重設卡片狀態為 failed，Worker 下次 poll 不會再撿起
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


@router.post("/cards/{card_id}/archive")
def archive_card(card_id: int, session: Session = Depends(get_session)):
    """封存卡片（從看板隱藏）"""
    idx = session.get(CardIndex, card_id)
    if not idx or not idx.file_path or not Path(idx.file_path).exists():
        raise HTTPException(status_code=404, detail="Card not found")

    # 運行中的卡片不能封存
    if idx.status in ("running", "pending"):
        raise HTTPException(status_code=400, detail="Cannot archive running/pending card")

    cd = read_card_md(Path(idx.file_path))
    cd.is_archived = True
    cd.updated_at = datetime.now(timezone.utc)
    write_card(Path(idx.file_path), cd)
    sync_card_to_index(session, cd, project_id=idx.project_id, file_path=idx.file_path)
    session.commit()
    return {"ok": True}


@router.post("/cards/{card_id}/unarchive")
def unarchive_card(card_id: int, session: Session = Depends(get_session)):
    """取消封存卡片"""
    idx = session.get(CardIndex, card_id)
    if not idx or not idx.file_path or not Path(idx.file_path).exists():
        raise HTTPException(status_code=404, detail="Card not found")

    cd = read_card_md(Path(idx.file_path))
    cd.is_archived = False
    cd.updated_at = datetime.now(timezone.utc)
    write_card(Path(idx.file_path), cd)
    sync_card_to_index(session, cd, project_id=idx.project_id, file_path=idx.file_path)
    session.commit()
    return {"ok": True}


@router.get("/projects/{project_id}/archived")
def list_archived_cards(project_id: int, session: Session = Depends(get_session)):
    """取得專案的封存卡片列表"""
    from app.core.card_index import query_archived
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    cards = query_archived(session, project_id)
    return [
        {
            "id": c.card_id,
            "title": c.title,
            "description": c.description,
            "status": c.status,
            "list_id": c.list_id,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
        }
        for c in cards
    ]


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
# Project Environment Variables
# ==========================================
class EnvVarCreate(BaseModel):
    key: str
    value: str
    is_secret: bool = True
    description: Optional[str] = None

class EnvVarUpdate(BaseModel):
    key: Optional[str] = None
    value: Optional[str] = None
    is_secret: Optional[bool] = None
    description: Optional[str] = None

class EnvVarResponse(BaseModel):
    id: int
    project_id: int
    key: str
    value: str  # masked if is_secret
    is_secret: bool
    description: Optional[str]

@router.get("/projects/{project_id}/env-vars", response_model=List[EnvVarResponse])
def list_env_vars(project_id: int, session: Session = Depends(get_session)):
    from app.models.core import ProjectEnvVar
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    env_vars = session.exec(
        select(ProjectEnvVar).where(ProjectEnvVar.project_id == project_id)
    ).all()
    result = []
    for v in env_vars:
        result.append(EnvVarResponse(
            id=v.id,
            project_id=v.project_id,
            key=v.key,
            value="••••••" if v.is_secret else v.value,
            is_secret=v.is_secret,
            description=v.description,
        ))
    return result

@router.post("/projects/{project_id}/env-vars", response_model=EnvVarResponse)
def create_env_var(project_id: int, data: EnvVarCreate, session: Session = Depends(get_session)):
    from app.models.core import ProjectEnvVar
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    # Check duplicate key
    existing = session.exec(
        select(ProjectEnvVar).where(
            ProjectEnvVar.project_id == project_id,
            ProjectEnvVar.key == data.key,
        )
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Key '{data.key}' already exists")
    env_var = ProjectEnvVar(
        project_id=project_id,
        key=data.key,
        value=data.value,
        is_secret=data.is_secret,
        description=data.description,
    )
    session.add(env_var)
    session.commit()
    session.refresh(env_var)
    return EnvVarResponse(
        id=env_var.id,
        project_id=env_var.project_id,
        key=env_var.key,
        value="••••••" if env_var.is_secret else env_var.value,
        is_secret=env_var.is_secret,
        description=env_var.description,
    )

@router.patch("/projects/{project_id}/env-vars/{var_id}", response_model=EnvVarResponse)
def update_env_var(project_id: int, var_id: int, data: EnvVarUpdate, session: Session = Depends(get_session)):
    from app.models.core import ProjectEnvVar
    env_var = session.get(ProjectEnvVar, var_id)
    if not env_var or env_var.project_id != project_id:
        raise HTTPException(status_code=404, detail="Env var not found")
    if data.key is not None:
        # Check duplicate key
        existing = session.exec(
            select(ProjectEnvVar).where(
                ProjectEnvVar.project_id == project_id,
                ProjectEnvVar.key == data.key,
                ProjectEnvVar.id != var_id,
            )
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Key '{data.key}' already exists")
        env_var.key = data.key
    if data.value is not None:
        env_var.value = data.value
    if data.is_secret is not None:
        env_var.is_secret = data.is_secret
    if data.description is not None:
        env_var.description = data.description
    session.add(env_var)
    session.commit()
    session.refresh(env_var)
    return EnvVarResponse(
        id=env_var.id,
        project_id=env_var.project_id,
        key=env_var.key,
        value="••••••" if env_var.is_secret else env_var.value,
        is_secret=env_var.is_secret,
        description=env_var.description,
    )

@router.delete("/projects/{project_id}/env-vars/{var_id}")
def delete_env_var(project_id: int, var_id: int, session: Session = Depends(get_session)):
    from app.models.core import ProjectEnvVar
    env_var = session.get(ProjectEnvVar, var_id)
    if not env_var or env_var.project_id != project_id:
        raise HTTPException(status_code=404, detail="Env var not found")
    session.delete(env_var)
    session.commit()
    return {"ok": True}


# ==========================================
# Project Remote Control (Claude Code RC)
# ==========================================
# 追蹤運行中的 remote control sessions
# key: project_id, value: { process, bridge_url, name, started_at, pid }
_rc_sessions: Dict[int, Dict[str, Any]] = {}


@router.post("/projects/{project_id}/remote-control")
async def start_remote_control(project_id: int, session: Session = Depends(get_session)):
    """啟動 Claude Code Remote Control session"""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 已有 session 運行中
    existing = _rc_sessions.get(project_id)
    if existing and existing.get("process") and existing["process"].poll() is None:
        return {
            "ok": True,
            "status": "running",
            "bridge_url": existing.get("bridge_url", ""),
            "pid": existing["process"].pid,
            "name": existing.get("name", ""),
        }

    # 啟動 claude rc
    import re as _re
    cmd = ["claude", "rc", "--name", project.name]

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=project.path,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Claude CLI not found")

    # 讀取前幾秒的輸出，解析 bridge URL
    bridge_url = ""
    import threading
    output_lines = []

    def _read_initial():
        for _ in range(50):  # 最多讀 50 行
            line = proc.stdout.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace")
            output_lines.append(decoded)
            # 找 bridge URL
            m = _re.search(r'(https://claude\.ai/code\?bridge=[a-zA-Z0-9_]+)', decoded)
            if m:
                output_lines.append(f"FOUND: {m.group(1)}")
                return m.group(1)
        return ""

    reader = threading.Thread(target=lambda: output_lines.append(_read_initial()))
    reader.start()
    reader.join(timeout=10)

    # 從 output 中找 bridge URL
    for line in output_lines:
        m = _re.search(r'(https://claude\.ai/code\?bridge=[a-zA-Z0-9_]+)', str(line))
        if m:
            bridge_url = m.group(1)
            break

    if proc.poll() is not None:
        # 程序已結束，檢查失敗原因
        full_output = " ".join(str(l) for l in output_lines)
        if "not trusted" in full_output.lower() or "workspace trust" in full_output.lower():
            raise HTTPException(
                status_code=400,
                detail="此專案目錄尚未被 Claude CLI 信任。請先在伺服器上手動執行一次 `claude`，接受 workspace trust 對話框。"
            )
        if "not found" in full_output.lower() or "ENOENT" in full_output:
            raise HTTPException(status_code=500, detail="Claude CLI 未安裝或找不到")
        raise HTTPException(status_code=500, detail=f"Claude RC 啟動失敗：{full_output[:200]}")

    _rc_sessions[project_id] = {
        "process": proc,
        "bridge_url": bridge_url,
        "name": project.name,
        "started_at": time_module.time(),
        "pid": proc.pid,
    }

    return {
        "ok": True,
        "status": "running",
        "bridge_url": bridge_url,
        "pid": proc.pid,
        "name": project.name,
    }


@router.get("/projects/{project_id}/remote-control")
def get_remote_control(project_id: int, session: Session = Depends(get_session)):
    """查詢 Remote Control session 狀態"""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    existing = _rc_sessions.get(project_id)
    if not existing or not existing.get("process"):
        return {"status": "stopped", "bridge_url": "", "pid": None}

    proc = existing["process"]
    if proc.poll() is not None:
        # 已結束
        _rc_sessions.pop(project_id, None)
        return {"status": "stopped", "bridge_url": "", "pid": None}

    return {
        "status": "running",
        "bridge_url": existing.get("bridge_url", ""),
        "pid": proc.pid,
        "name": existing.get("name", ""),
        "uptime_sec": int(time_module.time() - existing.get("started_at", 0)),
    }


@router.delete("/projects/{project_id}/remote-control")
def stop_remote_control(project_id: int, session: Session = Depends(get_session)):
    """停止 Remote Control session"""
    existing = _rc_sessions.pop(project_id, None)
    if not existing or not existing.get("process"):
        return {"ok": True, "status": "already_stopped"}

    proc = existing["process"]
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    return {"ok": True, "status": "stopped"}


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

    # 讀取版本號
    version_setting = session.get(SystemSetting, "app_version")
    app_version = version_setting.value if version_setting else "unknown"

    return {
        "is_paused": is_paused,
        "running_tasks": tasks_data,
        "workstations_used": len(tasks_data),
        "workstations_total": max_workstations,
        "version": app_version,
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

    # 偵測 Worker 獨立程序的 PID
    worker_pid = None
    worker_status = "stopped"
    try:
        import psutil
        for proc in psutil.process_iter(['pid', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline') or []
                cmd_str = ' '.join(cmdline)
                if 'worker.py' in cmd_str and 'python' in cmd_str.lower():
                    worker_pid = proc.info['pid']
                    worker_status = "paused" if worker_paused else "running"
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except ImportError:
        # psutil 不可用時 fallback：假設 systemd 管理，無法偵測 PID
        worker_status = "paused" if worker_paused else "unknown"

    if not worker_pid and not worker_paused:
        worker_status = "stopped"

    result = {
        "pid": os.getpid(),
        "engines": {
            "task_worker": {
                "status": worker_status,
                "pid": worker_pid,
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
    # Mask 敏感 token（只顯示後 4 位）
    for secret_key in ("github_pat",):
        if secret_key in result and result[secret_key]:
            val = result[secret_key]
            result[secret_key] = f"***{val[-4:]}" if len(val) > 4 else "***"
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
    # 工作台數量已寫入 DB，Worker 下次 poll 時會自動讀取
    if "max_workstations" in data:
        try:
            val = int(data["max_workstations"])
            if val < 1 or val > 100:
                raise HTTPException(status_code=400, detail="max_workstations 必須介於 1~100")
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="max_workstations 必須為正整數")
    return get_settings(session=session)


# ==========================================
# GitHub Integration
# ==========================================
class GitHubTokenRequest(BaseModel):
    token: str


@router.post("/github/verify")
def verify_github_token(data: GitHubTokenRequest):
    """驗證 GitHub PAT 有效性"""
    import urllib.request
    req = urllib.request.Request(
        "https://api.github.com/user",
        headers={
            "Authorization": f"Bearer {data.token}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            import json as _json
            user = _json.loads(resp.read().decode("utf-8"))
            return {
                "ok": True,
                "login": user["login"],
                "name": user.get("name", ""),
                "avatar_url": user.get("avatar_url", ""),
            }
    except urllib.error.HTTPError:
        raise HTTPException(status_code=401, detail="GitHub Token 無效")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"無法連線 GitHub API: {e}")


@router.get("/github/status")
def get_github_status(session: Session = Depends(get_session)):
    """取得 GitHub 連線狀態"""
    setting = session.get(SystemSetting, "github_pat")
    if not setting or not setting.value:
        return {"connected": False}

    import urllib.request
    req = urllib.request.Request(
        "https://api.github.com/user",
        headers={
            "Authorization": f"Bearer {setting.value}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            import json as _json
            user = _json.loads(resp.read().decode("utf-8"))
            return {"connected": True, "login": user["login"], "name": user.get("name", "")}
    except Exception:
        return {"connected": False, "error": "Token 已失效"}


# --- GitHub: Parse URL ---
class GitHubParseUrlRequest(BaseModel):
    url: str

@router.post("/github/parse-url")
def parse_github_url(data: GitHubParseUrlRequest):
    """解析 GitHub URL，回傳 owner/repo/clone_url"""
    m = re.match(r"https?://github\.com/([^/]+)/([^/.\s]+?)(?:\.git)?/?$", data.url.strip())
    if not m:
        raise HTTPException(status_code=400, detail="無效的 GitHub URL 格式")
    owner, repo = m.group(1), m.group(2)
    return {
        "owner": owner,
        "repo": repo,
        "full_name": f"{owner}/{repo}",
        "clone_url": f"https://github.com/{owner}/{repo}.git",
        "suggested_name": repo,
    }


# --- GitHub: List Repos ---
@router.get("/github/repos")
def list_github_repos(
    page: int = 1,
    per_page: int = 30,
    search: str = "",
    session: Session = Depends(get_session),
):
    """列出使用者的 GitHub repos（需已儲存 PAT）"""
    setting = session.get(SystemSetting, "github_pat")
    if not setting or not setting.value:
        raise HTTPException(status_code=400, detail="尚未連線 GitHub，請先設定 PAT")

    import httpx

    headers = {
        "Authorization": f"Bearer {setting.value}",
        "Accept": "application/vnd.github+json",
    }

    try:
        if search.strip():
            # 使用 GitHub Search API
            resp = httpx.get(
                "https://api.github.com/search/repositories",
                params={"q": f"{search} user:@me fork:true", "per_page": per_page, "page": page},
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
        else:
            # 列出使用者所有 repos（含 org 的）
            resp = httpx.get(
                "https://api.github.com/user/repos",
                params={"sort": "updated", "per_page": per_page, "page": page, "affiliation": "owner,collaborator,organization_member"},
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            items = resp.json()

        return [
            {
                "full_name": r["full_name"],
                "name": r["name"],
                "clone_url": r["clone_url"],
                "description": r.get("description"),
                "private": r["private"],
                "default_branch": r.get("default_branch", "main"),
            }
            for r in items
        ]
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"GitHub API 錯誤: {e.response.text[:200]}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"無法連線 GitHub API: {e}")


# --- GitHub: Clone ---
class GitHubCloneRequest(BaseModel):
    repo_url: str
    destination: str
    project_name: str
    default_member_id: Optional[int] = None

# 背景 clone 任務狀態
_clone_tasks: dict = {}

@router.post("/github/clone")
async def clone_github_repo(data: GitHubCloneRequest, session: Session = Depends(get_session)):
    """Clone GitHub repo 並建立專案（背景執行）"""
    dest = Path(data.destination)
    if dest.exists():
        raise HTTPException(status_code=400, detail="目標路徑已存在")
    # 確保父目錄存在
    if not dest.parent.exists():
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"無法建立父目錄: {e}")

    # 注入 PAT（私有 repo 需要）
    clone_url = data.repo_url
    setting = session.get(SystemSetting, "github_pat")
    if setting and setting.value:
        clone_url = clone_url.replace("https://github.com/", f"https://{setting.value}@github.com/")

    task_id = str(uuid.uuid4())
    _clone_tasks[task_id] = {"status": "cloning", "message": "正在 clone...", "project_id": None}

    asyncio.create_task(_do_clone(
        task_id=task_id,
        clone_url=clone_url,
        destination=str(dest),
        project_name=data.project_name,
        default_member_id=data.default_member_id,
    ))

    return {"task_id": task_id, "status": "cloning"}


async def _do_clone(task_id: str, clone_url: str, destination: str, project_name: str, default_member_id: Optional[int]):
    """背景 clone 任務"""
    from app.core.ws_manager import broadcast_event
    from app.database import engine

    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth", "1", clone_url, destination,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            err_msg = stderr.decode().strip()
            # 隱藏 PAT
            err_msg = re.sub(r"https://[^@]+@github\.com", "https://***@github.com", err_msg)
            _clone_tasks[task_id] = {"status": "error", "message": f"Clone 失敗: {err_msg}", "project_id": None}
            await broadcast_event("clone_progress", _clone_tasks[task_id] | {"task_id": task_id})
            return

        # Clone 成功，建立專案
        with Session(engine) as session:
            project_path = Path(destination)
            cards_dir = project_path / "cards"
            cards_dir.mkdir(exist_ok=True)

            project = Project(
                name=project_name,
                path=str(project_path),
                deploy_type="none",
                default_member_id=default_member_id,
            )
            session.add(project)
            session.commit()
            session.refresh(project)

            stages_config = [
                ("Backlog", False, "none", "none"),
                ("Scheduled", True, "delete", "none"),
                ("Planning", True, "none", "none"),
                ("Developing", True, "none", "none"),
                ("Verifying", True, "none", "none"),
                ("Done", False, "none", "none"),
                ("Aborted", False, "none", "none"),
            ]
            for idx, (name, is_ai, on_success, on_fail) in enumerate(stages_config):
                sl = StageList(
                    project_id=project.id,
                    name=name,
                    position=idx,
                    is_ai_stage=is_ai,
                    on_success_action=on_success,
                    on_fail_action=on_fail,
                )
                session.add(sl)
            session.commit()

            _clone_tasks[task_id] = {"status": "done", "message": "Clone 完成，專案已建立", "project_id": project.id}

        await broadcast_event("clone_progress", _clone_tasks[task_id] | {"task_id": task_id})

    except Exception as e:
        _clone_tasks[task_id] = {"status": "error", "message": str(e), "project_id": None}
        await broadcast_event("clone_progress", _clone_tasks[task_id] | {"task_id": task_id})


@router.get("/github/clone/{task_id}")
def get_clone_status(task_id: str):
    """查詢 clone 任務狀態"""
    task = _clone_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="找不到此 clone 任務")
    return {"task_id": task_id, **task}


# --- Project Relocate ---
class ProjectRelocateRequest(BaseModel):
    new_path: str

@router.post("/projects/{project_id}/relocate", response_model=Project)
def relocate_project(project_id: int, data: ProjectRelocateRequest, session: Session = Depends(get_session)):
    """搬移專案目錄到新路徑"""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="找不到專案")
    if project.is_system:
        raise HTTPException(status_code=403, detail="無法搬移系統專案")

    old_path = Path(project.path)
    new_path = Path(data.new_path)

    if not new_path.is_absolute():
        raise HTTPException(status_code=400, detail="請提供絕對路徑")
    if str(old_path) == str(new_path):
        raise HTTPException(status_code=400, detail="新路徑與目前相同")
    if new_path.exists():
        raise HTTPException(status_code=400, detail="目標路徑已存在")
    if not new_path.parent.exists():
        try:
            new_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"無法建立父目錄: {e}")

    # 檢查是否有執行中的任務
    running = session.exec(
        select(CardIndex).where(CardIndex.project_id == project_id, CardIndex.status == "running")
    ).first()
    if running:
        raise HTTPException(status_code=409, detail="有任務正在執行，請等待完成後再搬移")

    if old_path.exists():
        try:
            shutil.move(str(old_path), str(new_path))
        except PermissionError:
            raise HTTPException(status_code=400, detail="權限不足，無法搬移目錄")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"搬移失敗: {e}")

    project.path = str(new_path)
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


# ==========================================
# Auth API
# ==========================================
class AuthVerifyRequest(BaseModel):
    password: str

class AuthChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class AuthSetInitialPasswordRequest(BaseModel):
    new_password: str

@router.post("/auth/verify")
def verify_admin_password(req: AuthVerifyRequest, session: Session = Depends(get_session)):
    """驗證管理員密碼，回傳 session token"""
    from app.core.auth import check_password, hash_password, generate_session_token

    setting = session.get(SystemSetting, "admin_password")
    stored_password = setting.value if setting else os.getenv("AEGIS_DEFAULT_PASSWORD", "aegis2026!")

    if not check_password(req.password, stored_password):
        raise HTTPException(status_code=401, detail="密碼錯誤")

    # 自動遷移：明文密碼 → scrypt 雜湊
    if not stored_password.startswith("$scrypt$"):
        hashed = hash_password(req.password)
        if setting:
            setting.value = hashed
            session.add(setting)
        else:
            session.add(SystemSetting(key="admin_password", value=hashed))
        session.commit()

    token = generate_session_token(ttl_hours=8)
    return {"success": True, "token": token, "expires_in": 28800}

@router.post("/auth/change-password")
def change_admin_password(req: AuthChangePasswordRequest, session: Session = Depends(get_session)):
    """修改管理員密碼"""
    from app.core.auth import check_password, hash_password

    setting = session.get(SystemSetting, "admin_password")
    stored_password = setting.value if setting else os.getenv("AEGIS_DEFAULT_PASSWORD", "aegis2026!")

    if not check_password(req.current_password, stored_password):
        raise HTTPException(status_code=401, detail="目前密碼錯誤")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密碼至少需要 6 個字元")

    hashed = hash_password(req.new_password)
    if setting:
        setting.value = hashed
        session.add(setting)
    else:
        session.add(SystemSetting(key="admin_password", value=hashed))
    session.commit()
    return {"success": True, "message": "密碼已更新"}

@router.get("/auth/password-status")
def get_password_status(session: Session = Depends(get_session)):
    """檢查密碼是否仍為預設值"""
    from app.core.auth import check_password

    default_password = os.getenv("AEGIS_DEFAULT_PASSWORD", "aegis2026!")
    setting = session.get(SystemSetting, "admin_password")
    stored_password = setting.value if setting else default_password

    is_default = check_password(default_password, stored_password)
    return {"is_default": is_default}

@router.post("/auth/set-initial-password")
def set_initial_password(req: AuthSetInitialPasswordRequest, session: Session = Depends(get_session)):
    """首次設定密碼（僅在密碼仍為預設值時可用）"""
    from app.core.auth import check_password, hash_password

    default_password = os.getenv("AEGIS_DEFAULT_PASSWORD", "aegis2026!")
    setting = session.get(SystemSetting, "admin_password")
    stored_password = setting.value if setting else default_password

    if not check_password(default_password, stored_password):
        raise HTTPException(status_code=403, detail="密碼已被修改，請使用一般修改密碼功能")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密碼至少需要 6 個字元")

    hashed = hash_password(req.new_password)
    if setting:
        setting.value = hashed
        session.add(setting)
    else:
        session.add(SystemSetting(key="admin_password", value=hashed))
    session.commit()
    return {"success": True, "message": "密碼已設定"}


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
    check_claude_status, update_claude_credentials,
)


class AccountCreateRequest(BaseModel):
    provider: str  # "claude" | "gemini" | "openai"
    name: str
    auth_type: str = "cli"  # "api_key" | "cli"
    api_key: Optional[str] = None  # API Key
    oauth_token: Optional[str] = None  # CLI OAuth Token


@router.get("/accounts")
def list_accounts(session: Session = Depends(get_session)):
    """列出所有帳號（含 token 過期資訊）"""
    from datetime import datetime
    accounts = session.exec(select(Account).order_by(Account.provider, Account.id)).all()
    result = []
    for a in accounts:
        data = a.model_dump()
        # 計算 CLI token 過期時間
        if a.auth_type == "cli" and a.oauth_token and a.oauth_token_set_at:
            expires_at_ts = a.oauth_token_set_at / 1000 + 365 * 24 * 3600
            expires_at = datetime.fromtimestamp(expires_at_ts)
            now = datetime.now()
            data["expires_at"] = expires_at.isoformat()
            data["expired"] = expires_at < now
            data["hours_until_expiry"] = round((expires_at - now).total_seconds() / 3600, 2)
        else:
            data["expires_at"] = None
            data["expired"] = False
            data["hours_until_expiry"] = None
        # 隱藏實際值（安全性）
        data["oauth_token"] = "***" if a.oauth_token else ""
        data["api_key"] = a.api_key[:12] + "..." if a.api_key and len(a.api_key) > 12 else ""
        data["has_oauth_token"] = bool(a.oauth_token)
        data["has_api_key"] = bool(a.api_key)
        result.append(data)
    return result


@router.post("/accounts")
def create_account(data: AccountCreateRequest, session: Session = Depends(get_session)):
    """新增帳號（支援 API Key 或 CLI Token）"""
    import time as _t

    # 驗證
    if data.auth_type == "api_key":
        if not data.api_key or not data.api_key.strip():
            raise HTTPException(status_code=400, detail="請提供 API Key")
        api_key = data.api_key.strip()
        # 格式驗證
        if data.provider == "claude" and not api_key.startswith("sk-ant-api"):
            raise HTTPException(status_code=400, detail="無效的 Claude API Key（應以 sk-ant-api 開頭）")
        if data.provider == "gemini" and not api_key.startswith("AIza"):
            raise HTTPException(status_code=400, detail="無效的 Gemini API Key（應以 AIza 開頭）")
        if data.provider == "openai" and not api_key.startswith("sk-"):
            raise HTTPException(status_code=400, detail="無效的 OpenAI API Key（應以 sk- 開頭）")

        account = Account(
            provider=data.provider,
            name=data.name,
            auth_type="api_key",
            api_key=api_key,
            subscription="api_key",
        )
    else:  # CLI
        if not data.oauth_token or not data.oauth_token.strip():
            raise HTTPException(status_code=400, detail="請提供 OAuth Token")
        token = data.oauth_token.strip()
        if data.provider == "claude" and not token.startswith("sk-ant-oat01-"):
            raise HTTPException(status_code=400, detail="無效的 Claude Token（應以 sk-ant-oat01- 開頭）")

        account = Account(
            provider=data.provider,
            name=data.name,
            auth_type="cli",
            oauth_token=token,
            oauth_token_set_at=int(_t.time() * 1000),
            subscription="cli",
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
    oauth_token: Optional[str] = None
    subscription: Optional[str] = None


@router.patch("/accounts/{account_id}")
def update_account(account_id: int, data: AccountUpdateRequest, session: Session = Depends(get_session)):
    account = session.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if data.name is not None:
        account.name = data.name
    if data.is_healthy is not None:
        account.is_healthy = data.is_healthy
    if data.oauth_token is not None:
        token = data.oauth_token.strip()
        if token:
            account.oauth_token = token
            account.oauth_token_set_at = int(_t.time() * 1000)
        else:
            account.oauth_token = ""
            account.oauth_token_set_at = 0
    if data.subscription is not None:
        account.subscription = data.subscription
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


def _generate_slug(name: str, session: Session) -> str:
    """從名稱生成唯一的 slug"""
    import re
    import unicodedata

    # 嘗試用 pypinyin 轉換中文（如果有安裝）
    try:
        from pypinyin import lazy_pinyin
        base = "-".join(lazy_pinyin(name))
    except ImportError:
        # 沒有 pypinyin，用簡單轉換
        base = name.lower()

    # 清理：只保留字母、數字、連字號
    base = re.sub(r"[^a-z0-9\-]", "-", base)
    base = re.sub(r"-+", "-", base).strip("-")

    if not base:
        base = "member"

    # 確保唯一性
    slug = base
    counter = 1
    while session.exec(select(Member).where(Member.slug == slug)).first():
        slug = f"{base}-{counter}"
        counter += 1

    return slug


@router.post("/members")
def create_member(data: MemberCreateRequest, session: Session = Depends(get_session)):
    member = Member(**data.model_dump())

    # 自動生成 slug
    if not member.slug:
        member.slug = _generate_slug(member.name, session)

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

    # 如果沒有 slug，自動生成
    if not member.slug:
        member.slug = _generate_slug(member.name, session)

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
# Member Dialogues (AVG Style)
# ==========================================
@router.get("/members/{member_id}/dialogues")
def get_member_dialogues(member_id: int, limit: int = 30, session: Session = Depends(get_session)):
    """取得成員的對話記錄（Galgame 風格）"""
    from app.models.core import MemberDialogue
    dialogues = session.exec(
        select(MemberDialogue)
        .where(MemberDialogue.member_id == member_id)
        .order_by(MemberDialogue.created_at.desc())
        .limit(limit)
    ).all()
    return [d.model_dump() for d in reversed(dialogues)]


# ==========================================
# Member Skills
# ==========================================
@router.get("/members/{member_id}/skills")
def list_member_skills(member_id: int, session: Session = Depends(get_session)):
    """列出成員的所有技能"""
    from app.core.member_profile import list_skills

    member = session.get(Member, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    if not member.slug:
        return []  # 沒有 slug 的成員沒有技能檔案

    return list_skills(member.slug)


@router.get("/members/{member_id}/skills/{skill_name}")
def get_member_skill(member_id: int, skill_name: str, session: Session = Depends(get_session)):
    """取得成員的特定技能內容"""
    from app.core.member_profile import get_skill_content

    member = session.get(Member, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    if not member.slug:
        raise HTTPException(status_code=404, detail="Member has no profile")

    content = get_skill_content(member.slug, skill_name)
    if not content:
        raise HTTPException(status_code=404, detail="Skill not found")

    return {"name": skill_name, "content": content}


class SkillUpdateRequest(BaseModel):
    content: str


@router.put("/members/{member_id}/skills/{skill_name}")
def update_member_skill(member_id: int, skill_name: str, data: SkillUpdateRequest, session: Session = Depends(get_session)):
    """更新成員的技能內容"""
    from app.core.member_profile import get_skills_dir
    import re

    member = session.get(Member, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    if not member.slug:
        # 自動生成 slug
        member.slug = _generate_slug(member.name, session)
        session.add(member)
        session.commit()

    # 驗證技能名稱
    if not skill_name or ".." in skill_name or "/" in skill_name or "\\" in skill_name:
        raise HTTPException(status_code=400, detail="Invalid skill name")
    if not re.match(r"^[a-z0-9][a-z0-9\-]*$", skill_name):
        raise HTTPException(status_code=400, detail="Skill name must be lowercase letters, numbers, and hyphens")

    skills_dir = get_skills_dir(member.slug)
    skill_file = skills_dir / f"{skill_name}.md"
    skill_file.write_text(data.content, encoding="utf-8")

    return {"name": skill_name, "content": data.content}


@router.post("/members/{member_id}/skills")
def create_member_skill(member_id: int, data: dict, session: Session = Depends(get_session)):
    """建立新技能"""
    from app.core.member_profile import get_skills_dir
    import re

    member = session.get(Member, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    if not member.slug:
        member.slug = _generate_slug(member.name, session)
        session.add(member)
        session.commit()

    skill_name = data.get("name", "").strip().lower()
    content = data.get("content", "")

    # 驗證技能名稱
    if not skill_name:
        raise HTTPException(status_code=400, detail="Skill name is required")
    if not re.match(r"^[a-z0-9][a-z0-9\-]*$", skill_name):
        raise HTTPException(status_code=400, detail="Skill name must be lowercase letters, numbers, and hyphens")

    skills_dir = get_skills_dir(member.slug)
    skill_file = skills_dir / f"{skill_name}.md"

    if skill_file.exists():
        raise HTTPException(status_code=409, detail="Skill already exists")

    skill_file.write_text(content, encoding="utf-8")
    return {"name": skill_name, "content": content}


@router.delete("/members/{member_id}/skills/{skill_name}")
def delete_member_skill(member_id: int, skill_name: str, session: Session = Depends(get_session)):
    """刪除技能"""
    from app.core.member_profile import get_skills_dir

    member = session.get(Member, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    if not member.slug:
        raise HTTPException(status_code=404, detail="Member has no profile")

    # 驗證技能名稱
    if not skill_name or ".." in skill_name or "/" in skill_name or "\\" in skill_name:
        raise HTTPException(status_code=400, detail="Invalid skill name")

    skills_dir = get_skills_dir(member.slug)
    skill_file = skills_dir / f"{skill_name}.md"

    if not skill_file.exists():
        raise HTTPException(status_code=404, detail="Skill not found")

    skill_file.unlink()
    return {"deleted": skill_name}


# ==========================================
# Member MCP Config
# ==========================================
@router.get("/members/{member_id}/mcp")
def get_member_mcp(member_id: int, session: Session = Depends(get_session)):
    """讀取成員 MCP 設定"""
    member = session.get(Member, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    from app.core.member_profile import get_mcp_config
    return get_mcp_config(member.slug)


@router.put("/members/{member_id}/mcp")
def update_member_mcp(member_id: int, data: dict, session: Session = Depends(get_session)):
    """更新成員 MCP 設定"""
    member = session.get(Member, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    if not isinstance(data, dict) or "mcpServers" not in data:
        raise HTTPException(status_code=400, detail="Must contain 'mcpServers' key")

    from app.core.member_profile import save_mcp_config
    save_mcp_config(member.slug, data)
    return data


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
# Claude Auth (Claude 認證)
# ==========================================
@router.get("/claude/status")
def get_claude_status():
    """檢查 Claude CLI 狀態和 token 過期時間"""
    from app.core.account_manager import check_claude_status
    return check_claude_status()


class ClaudeCredentialsRequest(BaseModel):
    credentials: str


@router.post("/claude/credentials")
def update_claude_creds(data: ClaudeCredentialsRequest):
    """更新 Claude credentials"""
    from app.core.account_manager import update_claude_credentials
    update_claude_credentials(data.credentials)
    return {"ok": True, "message": "Credentials 已更新！"}


class ClaudeTokenRequest(BaseModel):
    token: str


@router.post("/claude/token")
def save_claude_token(data: ClaudeTokenRequest):
    """
    儲存 Claude OAuth Token（長期 token，1 年有效）
    用戶在本地執行 `claude setup-token` 取得 token 後貼上
    """
    import time
    token = data.token.strip()
    if not token.startswith("sk-ant-oat01-"):
        raise HTTPException(status_code=400, detail="無效的 Token 格式。Token 應以 sk-ant-oat01- 開頭。")

    # 儲存到 .env 檔案
    env_file = Path(__file__).parent.parent.parent / ".env"
    env_content = ""
    if env_file.exists():
        env_content = env_file.read_text()

    # 記錄設定時間（Unix 時間戳，毫秒）
    token_set_at = int(time.time() * 1000)

    # 更新或新增 CLAUDE_CODE_OAUTH_TOKEN 和 CLAUDE_CODE_OAUTH_TOKEN_SET_AT
    lines = env_content.strip().split("\n") if env_content.strip() else []
    new_lines = [line for line in lines if not line.startswith("CLAUDE_CODE_OAUTH_TOKEN")]
    new_lines.append(f"CLAUDE_CODE_OAUTH_TOKEN={token}")
    new_lines.append(f"CLAUDE_CODE_OAUTH_TOKEN_SET_AT={token_set_at}")
    env_file.write_text("\n".join(new_lines) + "\n")

    # 同時設定到環境變數（讓當前進程立即生效）
    os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = token
    os.environ["CLAUDE_CODE_OAUTH_TOKEN_SET_AT"] = str(token_set_at)

    return {"ok": True, "message": "Token 已儲存！請重啟 Worker 服務使其生效。"}


@router.post("/claude/auth/init")
def init_claude_auth():
    """啟動 Claude 引導式登入，回傳授權 URL"""
    from app.core.account_manager import start_claude_auth
    try:
        session_id, auth_url = start_claude_auth()
        return {
            "session_id": session_id,
            "auth_url": auth_url,
            "instructions": [
                "1. 點擊上方連結在瀏覽器開啟",
                "2. 使用 Claude 帳號登入並授權",
                "3. 複製頁面顯示的授權碼",
                "4. 將授權碼貼到下方完成登入",
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ClaudeAuthCompleteRequest(BaseModel):
    session_id: str
    auth_code: str


@router.post("/claude/auth/complete")
def complete_claude_auth_api(data: ClaudeAuthCompleteRequest):
    """完成 Claude 引導式登入"""
    from app.core.account_manager import complete_claude_auth
    try:
        success = complete_claude_auth(data.session_id, data.auth_code)
        if not success:
            raise HTTPException(status_code=400, detail="登入失敗")
        return {"ok": True, "message": "登入成功！長期 token 已設定。"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class ClaudeAuthCancelRequest(BaseModel):
    session_id: str


@router.post("/claude/auth/cancel")
def cancel_claude_auth_api(data: ClaudeAuthCancelRequest):
    """取消 Claude 引導式登入"""
    from app.core.account_manager import cancel_claude_auth
    cancel_claude_auth(data.session_id)
    return {"ok": True}


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
# Claude Auth Status (Claude 認證狀態)
# ==========================================
@router.get("/claude/status")
def get_claude_status():
    """檢查 Claude CLI 狀態和 token 過期時間"""
    return check_claude_status()


class ClaudeCredentialsRequest(BaseModel):
    credentials: str  # JSON string


@router.post("/claude/credentials")
def update_claude_credentials_api(data: ClaudeCredentialsRequest):
    """更新 Claude credentials 檔案（從其他機器同步）"""
    try:
        update_claude_credentials(data.credentials)
        return {"ok": True, "message": "Credentials 已更新"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


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


# ==========================================
# Invitations API
# ==========================================

class InvitationCreate(BaseModel):
    """建立邀請碼"""
    code: Optional[str] = None           # 自訂代碼，不填則自動生成
    target_level: int = 1                # 驗證後的權限等級 (1-3)
    target_member_id: Optional[int] = None
    allowed_projects: Optional[List[int]] = None  # 可存取的專案 ID 列表
    user_display_name: str = ""          # 預設顯示名稱
    user_description: str = ""           # 預設身份描述
    default_can_view: bool = True
    default_can_create_card: bool = False
    default_can_run_task: bool = False
    default_can_access_sensitive: bool = False
    max_uses: int = 1
    expires_days: Optional[int] = None   # 幾天後過期，None 表示永不過期
    note: str = ""


class InvitationUpdate(BaseModel):
    """更新邀請碼"""
    user_display_name: Optional[str] = None
    user_description: Optional[str] = None
    default_can_view: Optional[bool] = None
    default_can_create_card: Optional[bool] = None
    default_can_run_task: Optional[bool] = None
    default_can_access_sensitive: Optional[bool] = None
    max_uses: Optional[int] = None
    expires_days: Optional[int] = None
    note: Optional[str] = None


class InvitationResponse(BaseModel):
    """邀請碼回應"""
    id: int
    code: str
    target_level: int
    target_member_id: Optional[int]
    allowed_projects: Optional[List[int]]
    user_display_name: str
    user_description: str
    default_can_view: bool
    default_can_create_card: bool
    default_can_run_task: bool
    default_can_access_sensitive: bool
    max_uses: int
    used_count: int
    expires_at: Optional[datetime]
    created_at: datetime
    note: str
    # 狀態
    status: str  # active, expired, depleted


def _invitation_status(inv: InviteCode) -> str:
    """計算邀請碼狀態"""
    if inv.expires_at:
        # 處理 naive datetime（無時區）與 aware datetime 比較
        now = datetime.now(timezone.utc)
        exp = inv.expires_at if inv.expires_at.tzinfo else inv.expires_at.replace(tzinfo=timezone.utc)
        if now > exp:
            return "expired"
    if inv.used_count >= inv.max_uses:
        return "depleted"
    return "active"


def _invitation_to_response(inv: InviteCode) -> dict:
    """轉換為回應格式"""
    allowed = None
    if inv.allowed_projects:
        try:
            allowed = json_module.loads(inv.allowed_projects)
        except:
            allowed = None
    return {
        "id": inv.id,
        "code": inv.code,
        "target_level": inv.target_level,
        "target_member_id": inv.target_member_id,
        "allowed_projects": allowed,
        "user_display_name": inv.user_display_name,
        "user_description": inv.user_description,
        "default_can_view": inv.default_can_view,
        "default_can_create_card": inv.default_can_create_card,
        "default_can_run_task": inv.default_can_run_task,
        "default_can_access_sensitive": inv.default_can_access_sensitive,
        "max_uses": inv.max_uses,
        "used_count": inv.used_count,
        "expires_at": inv.expires_at,
        "created_at": inv.created_at,
        "note": inv.note,
        "status": _invitation_status(inv),
    }


@router.get("/invitations")
def list_invitations(session: Session = Depends(get_session)):
    """列出所有邀請碼"""
    invitations = session.exec(
        select(InviteCode).order_by(InviteCode.created_at.desc())
    ).all()
    return [_invitation_to_response(inv) for inv in invitations]


@router.post("/invitations")
def create_invitation(data: InvitationCreate, session: Session = Depends(get_session)):
    """建立邀請碼"""
    from datetime import timedelta
    import secrets

    # 自動生成或使用自訂代碼
    code = data.code or secrets.token_urlsafe(6).upper()[:8]

    # 檢查代碼是否已存在
    existing = session.exec(select(InviteCode).where(InviteCode.code == code)).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"邀請碼 {code} 已存在")

    # 計算過期時間
    expires_at = None
    if data.expires_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=data.expires_days)

    # allowed_projects 轉 JSON
    allowed_json = None
    if data.allowed_projects:
        allowed_json = json_module.dumps(data.allowed_projects)

    invitation = InviteCode(
        code=code,
        target_level=data.target_level,
        target_member_id=data.target_member_id,
        allowed_projects=allowed_json,
        user_display_name=data.user_display_name,
        user_description=data.user_description,
        default_can_view=data.default_can_view,
        default_can_create_card=data.default_can_create_card,
        default_can_run_task=data.default_can_run_task,
        default_can_access_sensitive=data.default_can_access_sensitive,
        max_uses=data.max_uses,
        expires_at=expires_at,
        note=data.note,
    )
    session.add(invitation)
    session.commit()
    session.refresh(invitation)
    return _invitation_to_response(invitation)


@router.get("/invitations/{invitation_id}")
def get_invitation(invitation_id: int, session: Session = Depends(get_session)):
    """取得單一邀請碼"""
    invitation = session.get(InviteCode, invitation_id)
    if not invitation:
        raise HTTPException(status_code=404, detail="邀請碼不存在")
    return _invitation_to_response(invitation)


@router.patch("/invitations/{invitation_id}")
def update_invitation(invitation_id: int, data: InvitationUpdate, session: Session = Depends(get_session)):
    """更新邀請碼"""
    from datetime import timedelta

    invitation = session.get(InviteCode, invitation_id)
    if not invitation:
        raise HTTPException(status_code=404, detail="邀請碼不存在")

    if data.user_display_name is not None:
        invitation.user_display_name = data.user_display_name
    if data.user_description is not None:
        invitation.user_description = data.user_description
    if data.default_can_view is not None:
        invitation.default_can_view = data.default_can_view
    if data.default_can_create_card is not None:
        invitation.default_can_create_card = data.default_can_create_card
    if data.default_can_run_task is not None:
        invitation.default_can_run_task = data.default_can_run_task
    if data.default_can_access_sensitive is not None:
        invitation.default_can_access_sensitive = data.default_can_access_sensitive
    if data.max_uses is not None:
        invitation.max_uses = data.max_uses
    if data.expires_days is not None:
        invitation.expires_at = datetime.now(timezone.utc) + timedelta(days=data.expires_days)
    if data.note is not None:
        invitation.note = data.note

    session.commit()
    session.refresh(invitation)
    return _invitation_to_response(invitation)


@router.delete("/invitations/{invitation_id}")
def delete_invitation(invitation_id: int, session: Session = Depends(get_session)):
    """刪除邀請碼"""
    invitation = session.get(InviteCode, invitation_id)
    if not invitation:
        raise HTTPException(status_code=404, detail="邀請碼不存在")
    session.delete(invitation)
    session.commit()
    return {"ok": True}


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


# ==========================================
# System Update API
# ==========================================
from app.core import updater


class UpdateSettingsPayload(BaseModel):
    auto_update_enabled: Optional[bool] = None
    auto_update_time: Optional[str] = None
    update_keep_versions: Optional[int] = None
    update_channel: Optional[str] = None  # "development" | "stable"


class ApplyUpdatePayload(BaseModel):
    version: Optional[str] = None
    wait_timeout: int = 300


class RollbackPayload(BaseModel):
    version: Optional[str] = None


@router.get("/update/status")
async def get_update_status(session: Session = Depends(get_session)):
    """取得更新狀態"""
    state = updater.get_update_state()

    # 讀取更新設定
    auto_enabled = session.get(SystemSetting, "auto_update_enabled")
    auto_time = session.get(SystemSetting, "auto_update_time")
    keep_versions = session.get(SystemSetting, "update_keep_versions")
    channel = session.get(SystemSetting, "update_channel")

    return {
        "current_version": state.current_version,
        "latest_version": state.latest_version,
        "has_update": state.has_update,
        "is_updating": state.is_updating,
        "update_stage": state.stage,
        "progress": state.progress,
        "message": state.message,
        "error": state.error,
        "available_versions": state.available_versions,
        "is_deployed": updater.is_deployed_environment(),
        "auto_update_enabled": auto_enabled.value == "true" if auto_enabled else False,
        "auto_update_time": auto_time.value if auto_time else "03:00",
        "update_keep_versions": int(keep_versions.value) if keep_versions else 3,
        "update_channel": channel.value if channel else "development",
    }


class CheckUpdatePayload(BaseModel):
    channel: Optional[str] = None  # 若未指定則從 DB 讀取


@router.post("/update/check")
async def check_for_updates(payload: CheckUpdatePayload = None, session: Session = Depends(get_session)):
    """檢查是否有新版本（獨立查詢，不污染全域 _state）"""
    if payload and payload.channel:
        channel = payload.channel
    else:
        channel_setting = session.get(SystemSetting, "update_channel")
        channel = channel_setting.value if channel_setting else "development"

    # 獨立查詢 GitHub，避免並行 check 互相覆蓋全域 _state
    try:
        import httpx

        current = updater.get_current_version()

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.github.com/repos/cwen0708/aegis/tags",
                headers={"Accept": "application/vnd.github.v3+json"},
                timeout=30.0
            )
            if resp.status_code != 200:
                raise Exception(f"GitHub API {resp.status_code}")
            tags = resp.json()

        if channel == "stable":
            tag_pattern = re.compile(r"^v\d+\.\d+\.\d+-stable$")
            channel_name = "穩定版"
        else:
            tag_pattern = re.compile(r"^v\d+\.\d+\.\d+(-dev\.\d+)?$")
            channel_name = "開發版"

        filtered = [t["name"] for t in tags if tag_pattern.match(t["name"])]

        if not filtered:
            return {
                "current_version": current, "latest_version": current,
                "has_update": False, "available_versions": [],
                "message": f"已是最新{channel_name}", "error": "", "channel": channel,
            }

        filtered.sort(key=updater.parse_version, reverse=True)
        latest = filtered[0].lstrip("v").replace("-stable", "")
        has_update = updater.is_newer_version(latest, current)

        return {
            "current_version": current,
            "latest_version": latest,
            "has_update": has_update,
            "available_versions": filtered[:10],
            "message": f"發現新{channel_name} {latest}" if has_update else f"已是最新{channel_name}",
            "error": "",
            "channel": channel,
        }
    except Exception as e:
        return {
            "current_version": updater.get_current_version(),
            "latest_version": "", "has_update": False,
            "available_versions": [], "message": "", "error": str(e),
            "channel": channel,
        }


@router.get("/update/versions")
async def list_versions():
    """列出所有版本 tag（含 commit 訊息和時間），最近 15 筆"""
    import httpx
    repo = "cwen0708/aegis"
    current = updater.get_current_version()
    tag_pattern = re.compile(r"^v\d+\.\d+\.\d+(-dev\.\d+|-stable)?$")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.github.com/repos/{repo}/tags?per_page=50",
                headers={"Accept": "application/vnd.github.v3+json"},
                timeout=30.0,
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail=f"GitHub API {resp.status_code}")
            tags = resp.json()

        # 過濾合法 tag
        filtered = [t for t in tags if tag_pattern.match(t["name"])]
        # 排序（用 updater.parse_version）
        filtered.sort(key=lambda t: updater.parse_version(t["name"]), reverse=True)
        filtered = filtered[:15]

        # 批次查 commit 訊息和時間
        results = []
        async with httpx.AsyncClient() as client:
            for t in filtered:
                sha = t["commit"]["sha"]
                try:
                    cr = await client.get(
                        f"https://api.github.com/repos/{repo}/commits/{sha}",
                        headers={"Accept": "application/vnd.github.v3+json"},
                        timeout=15.0,
                    )
                    if cr.status_code == 200:
                        cd = cr.json()
                        msg = cd["commit"]["message"].split("\n")[0]  # 首行
                        date = cd["commit"]["committer"]["date"]  # ISO 8601
                    else:
                        msg = ""
                        date = ""
                except Exception:
                    msg = ""
                    date = ""

                tag_name = t["name"]
                channel = "stable" if tag_name.endswith("-stable") else "dev"
                ver_clean = tag_name.lstrip("v").replace("-stable", "")
                results.append({
                    "tag": tag_name,
                    "channel": channel,
                    "message": msg,
                    "date": date,
                    "is_current": ver_clean == current,
                })
        return results
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/update/download")
async def download_update(version: Optional[str] = None):
    """下載指定版本"""
    if not updater.is_deployed_environment():
        raise HTTPException(status_code=400, detail="本地開發環境不支援熱更新")

    state = updater.get_update_state()
    target_version = version or state.latest_version

    if not target_version:
        raise HTTPException(status_code=400, detail="未指定版本且無可用更新")

    success = await updater.download_version(target_version)
    return {
        "ok": success,
        "version": target_version,
        "message": state.message,
        "error": state.error,
    }


@router.post("/update/build")
async def build_update(version: str):
    """建構指定版本"""
    if not updater.is_deployed_environment():
        raise HTTPException(status_code=400, detail="本地開發環境不支援熱更新")

    success = await updater.build_version(version)
    state = updater.get_update_state()
    return {
        "ok": success,
        "version": version,
        "message": state.message,
        "error": state.error,
    }


@router.post("/update/apply")
async def apply_update(payload: ApplyUpdatePayload, session: Session = Depends(get_session)):
    """套用更新（背景執行，立即回應）"""
    import asyncio

    if not updater.is_deployed_environment():
        raise HTTPException(status_code=400, detail="本地開發環境不支援熱更新")

    # 檢查是否已在更新中
    state = updater.get_update_state()
    if state.is_updating:
        return {
            "ok": False,
            "version": state.current_version,
            "message": "已有更新正在進行中",
            "error": "",
        }

    # 背景執行完整更新流程，API 立即回應
    asyncio.create_task(updater.full_update(
        version=payload.version,
        wait_timeout=payload.wait_timeout
    ))

    return {
        "ok": True,
        "version": payload.version or "latest",
        "message": "更新已觸發，請透過 /update/status 查詢進度",
        "error": "",
    }


@router.post("/update/rollback")
async def rollback_update(payload: RollbackPayload):
    """回滾到指定版本"""
    if not updater.is_deployed_environment():
        raise HTTPException(status_code=400, detail="本地開發環境不支援回滾")

    success = await updater.rollback(payload.version)
    state = updater.get_update_state()
    return {
        "ok": success,
        "version": state.current_version,
        "message": state.message,
        "error": state.error,
    }


@router.put("/update/settings")
async def update_settings(payload: UpdateSettingsPayload, session: Session = Depends(get_session)):
    """更新自動更新設定（同時同步 CronJob）"""
    if payload.auto_update_enabled is not None:
        setting = session.get(SystemSetting, "auto_update_enabled")
        if setting:
            setting.value = "true" if payload.auto_update_enabled else "false"
        else:
            setting = SystemSetting(key="auto_update_enabled", value="true" if payload.auto_update_enabled else "false")
        session.add(setting)

    if payload.auto_update_time is not None:
        setting = session.get(SystemSetting, "auto_update_time")
        if setting:
            setting.value = payload.auto_update_time
        else:
            setting = SystemSetting(key="auto_update_time", value=payload.auto_update_time)
        session.add(setting)

    if payload.update_keep_versions is not None:
        setting = session.get(SystemSetting, "update_keep_versions")
        if setting:
            setting.value = str(payload.update_keep_versions)
        else:
            setting = SystemSetting(key="update_keep_versions", value=str(payload.update_keep_versions))
        session.add(setting)

    if payload.update_channel is not None:
        # 驗證頻道值
        if payload.update_channel not in ("development", "stable"):
            raise HTTPException(status_code=400, detail="無效的更新頻道")
        setting = session.get(SystemSetting, "update_channel")
        if setting:
            setting.value = payload.update_channel
        else:
            setting = SystemSetting(key="update_channel", value=payload.update_channel)
        session.add(setting)

    # 同步更新 CronJob
    aegis_project = session.exec(
        select(Project).where(Project.is_system == True)
    ).first()

    if aegis_project:
        update_job = session.exec(
            select(CronJob).where(
                CronJob.project_id == aegis_project.id,
                CronJob.name == "系統更新檢查"
            )
        ).first()

        if update_job:
            if payload.auto_update_enabled is not None:
                update_job.is_enabled = payload.auto_update_enabled

            if payload.auto_update_time is not None:
                hour, minute = map(int, payload.auto_update_time.split(":"))
                update_job.cron_expression = f"{minute} {hour} * * *"
                # 重新計算下次執行時間（用系統時區）
                from app.core.cron_poller import _calculate_next_time, _get_system_timezone
                tz_name = _get_system_timezone(session)
                next_time = _calculate_next_time(update_job.cron_expression, tz_name)
                if next_time:
                    update_job.next_scheduled_at = next_time

            session.add(update_job)

    session.commit()
    return {"ok": True}


@router.get("/update/versions")
async def list_versions():
    """列出可用版本"""
    if not updater.is_deployed_environment():
        return {"versions": [], "current": updater.get_current_version()}

    paths = updater.get_deployment_paths()
    releases_dir = paths["releases"]

    versions = []
    if releases_dir and releases_dir.exists():
        versions = sorted(
            [d.name for d in releases_dir.iterdir() if d.is_dir()],
            key=updater.parse_version,
            reverse=True
        )

    return {
        "versions": versions,
        "current": updater.get_current_version(),
    }


# ==========================================================
# Email API
# ==========================================================

@router.get("/emails/")
async def list_emails(
    session: Session = Depends(get_session),
    is_processed: Optional[bool] = None,
    category: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """列出 Email 紀錄"""
    q = select(EmailMessage).order_by(EmailMessage.created_at.desc())
    if is_processed is not None:
        q = q.where(EmailMessage.is_processed == is_processed)
    if category:
        q = q.where(EmailMessage.category == category)
    q = q.offset(offset).limit(limit)
    return session.exec(q).all()


@router.get("/emails/{email_id}")
async def get_email(email_id: int, session: Session = Depends(get_session)):
    """取得單封 Email 詳情"""
    em = session.get(EmailMessage, email_id)
    if not em:
        raise HTTPException(404, "Email not found")
    return em


class EmailClassifyPayload(BaseModel):
    """AI 分類結果（供 CronJob AI 回寫）"""
    category: str = ""       # actionable / informational / spam / newsletter
    urgency: str = ""        # high / medium / low
    summary: str = ""
    suggested_action: str = ""
    project_id: Optional[int] = None


@router.patch("/emails/{email_id}/classify")
async def classify_email(
    email_id: int,
    payload: EmailClassifyPayload,
    session: Session = Depends(get_session),
):
    """更新 Email 的 AI 分類結果（供排程 AI 呼叫）"""
    em = session.get(EmailMessage, email_id)
    if not em:
        raise HTTPException(404, "Email not found")

    if payload.category:
        em.category = payload.category
    if payload.urgency:
        em.urgency = payload.urgency
    if payload.summary:
        em.summary = payload.summary
    if payload.suggested_action:
        em.suggested_action = payload.suggested_action
    if payload.project_id is not None:
        em.project_id = payload.project_id
    em.is_processed = True

    session.add(em)
    session.commit()
    session.refresh(em)
    return em


@router.post("/emails/classify-batch")
async def classify_emails_batch(
    items: list[dict],
    session: Session = Depends(get_session),
):
    """批次更新 Email 分類結果（一次處理多封）

    Body: [{"id": 1, "category": "actionable", "urgency": "high", "summary": "..."}, ...]
    """
    updated = []
    for item in items:
        email_id = item.get("id")
        if not email_id:
            continue
        em = session.get(EmailMessage, email_id)
        if not em:
            continue
        for field in ("category", "urgency", "summary", "suggested_action", "project_id"):
            if field in item and item[field]:
                setattr(em, field, item[field])
        em.is_processed = True
        session.add(em)
        updated.append(email_id)

    session.commit()
    return {"updated": updated, "count": len(updated)}
