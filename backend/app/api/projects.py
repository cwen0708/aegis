from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlmodel import Session, select, func
from typing import Dict, List, Optional, Any
from pydantic import BaseModel
from datetime import datetime, timezone
from app.database import get_session
from app.models.core import Project, Card, StageList, SystemSetting, Account, Member, MemberAccount, CardIndex, Person, PersonProject
from app.core.card_index import sync_card_to_index, remove_card_from_index, query_board, rebuild_index
from app.core.sync_matrix import SyncEnforcer, load_registry_from_db, validate_actor
from app.api.deps import get_domain_filter, get_visibility_filter, get_card_lock, get_member_primary_provider, get_project_for_list
from pathlib import Path
import json
import logging
import subprocess
import time as time_module
import threading
import re as _re

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Projects"])


def _safe_parse_tags(tags_json: str) -> list:
    """安全解析 tags_json，非陣列時自動包裝"""
    if not tags_json:
        return []
    try:
        parsed = json.loads(tags_json)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, str):
            return [parsed] if parsed else []
        return []
    except (json.JSONDecodeError, TypeError):
        return []


# ==========================================
# Response Models
# ==========================================
class CardResponse(BaseModel):
    id: int
    list_id: int
    title: str
    description: Optional[str]
    status: str
    tags: List[str] = []
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
    auto_commit: bool = False

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
    room_id: Optional[int] = None            # 所屬空間
    allow_anonymous: Optional[bool] = None   # 允許未登入瀏覽


# ==========================================
# StageList Schemas
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
    auto_commit: Optional[bool] = None  # 成功自動 git commit


class MemberListCreateRequest(BaseModel):
    member_id: int
    name: Optional[str] = None  # 預設："{member.name} 收件匣"


class StageListReorderRequest(BaseModel):
    order: list[int]  # list of stage_list IDs in desired order


# ==========================================
# Environment Variable Schemas
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


# ==========================================
# Internal Helpers
# ==========================================
# 追蹤運行中的 remote control sessions
# key: project_id, value: { process, bridge_url, name, started_at, pid }
_rc_sessions: Dict[int, Dict[str, Any]] = {}


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


# ==========================================
# Project Routes
# ==========================================
@router.get("/projects/", response_model=List[Project])
def read_projects(request: Request, session: Session = Depends(get_session)):
    projects = session.exec(select(Project)).all()

    # 統一過濾：admin/localhost 不過濾，user token 查 PersonProject，未登入查 allow_anonymous
    from app.api.deps import get_visibility_filter
    visible_project_ids, _ = get_visibility_filter(request, session)
    if visible_project_ids is not None:
        projects = [p for p in projects if p.id in visible_project_ids]

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
def update_project(
    project_id: int,
    update_data: ProjectUpdate,
    actor: str = Query("human"),
    session: Session = Depends(get_session),
):
    validate_actor(actor)

    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    # 系統專案禁止改名（名稱未變更時放行）
    if project.is_system and update_data.name is not None and update_data.name != project.name:
        raise HTTPException(status_code=403, detail="無法修改系統專案名稱")

    # --- SyncEnforcer：欄位級寫入權限控制 ---
    registry = load_registry_from_db(session)
    enforcer = SyncEnforcer(registry)

    _METADATA_FIELDS = {"default_member_id", "room_id", "allow_anonymous"}

    all_changes = {
        k: v for k, v in update_data.model_dump().items()
        if v is not None
    }
    sync_changes = {k: v for k, v in all_changes.items() if k not in _METADATA_FIELDS}
    metadata_changes = {k: v for k, v in all_changes.items() if k in _METADATA_FIELDS}

    result = enforcer.validate("project", sync_changes, actor)
    if result.rejected:
        rejected_names = [r.field_name for r in result.rejected]
        logger.info("SyncEnforcer rejected fields for project %d (actor=%s): %s", project_id, actor, rejected_names)

    approved = {**result.approved, **metadata_changes}

    # --- 套用已核准的欄位 ---
    if "name" in approved:
        project.name = approved["name"]
    if "path" in approved:
        new_path = Path(approved["path"])
        if not new_path.exists():
            raise HTTPException(status_code=400, detail="路徑不存在")
        project.path = str(new_path)
    if "is_active" in approved:
        project.is_active = approved["is_active"]
    if "deploy_type" in approved:
        project.deploy_type = approved["deploy_type"]
    if "default_member_id" in approved:
        project.default_member_id = approved["default_member_id"] if approved["default_member_id"] != 0 else None
    if "room_id" in approved:
        project.room_id = approved["room_id"] if approved["room_id"] != 0 else None
    if "allow_anonymous" in approved:
        project.allow_anonymous = approved["allow_anonymous"]
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@router.get("/projects/{project_id}/board", response_model=List[StageListResponse])
def read_project_board(project_id: int, request: Request, session: Session = Depends(get_session)):
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

    # 未登入時根據 Room 成員過濾收件匣
    # 如果專案有 room_id，用 RoomMember 過濾可見成員
    from app.api.deps import get_visibility_filter
    visible_project_ids, _ = get_visibility_filter(request, session)
    if visible_project_ids is not None and project.room_id:
        from app.models.core import RoomMember
        room_members = session.exec(
            select(RoomMember.member_id).where(RoomMember.room_id == project.room_id)
        ).all()
        visible_member_ids = set(room_members)
        if visible_member_ids:
            lists = [l for l in lists if not l.is_member_bound or l.member_id in visible_member_ids]

    # Query all cards for this project from the index
    card_indices = query_board(session, project_id)
    # Group by list_id
    cards_by_list: dict[int, list[CardIndex]] = {}
    for ci in card_indices:
        cards_by_list.setdefault(ci.list_id, []).append(ci)
    # Sort each group by created_at desc (strip tzinfo to avoid naive vs aware comparison)
    for lst in cards_by_list.values():
        lst.sort(key=lambda c: c.created_at.replace(tzinfo=None) if c.created_at else datetime.min, reverse=True)

    # 批量預載所有相關 Member，避免 N+1 查詢
    member_ids = [l.member_id for l in lists if l.member_id]
    if member_ids:
        members_list = session.exec(select(Member).where(Member.id.in_(member_ids))).all()
        members_map = {m.id: m for m in members_list}
        # 批量預載 MemberAccount（取 priority 最低的）
        bindings = session.exec(
            select(MemberAccount)
            .where(MemberAccount.member_id.in_(member_ids))
            .order_by(MemberAccount.member_id, MemberAccount.priority)
        ).all()
        # 每個 member 只取第一筆 binding
        first_binding: dict[int, MemberAccount] = {}
        for b in bindings:
            if b.member_id not in first_binding:
                first_binding[b.member_id] = b
        # 批量預載 Account
        account_ids = [b.account_id for b in first_binding.values()]
        if account_ids:
            accounts_list = session.exec(select(Account).where(Account.id.in_(account_ids))).all()
            accounts_map = {a.id: a for a in accounts_list}
        else:
            accounts_map = {}
        # 建立 member_id -> provider 對照
        provider_map: dict[int, str] = {}
        for mid, b in first_binding.items():
            acc = accounts_map.get(b.account_id)
            provider_map[mid] = acc.provider if acc else ""
    else:
        members_map = {}
        provider_map = {}

    result = []
    for l in lists:
        member_brief = None
        if l.member_id:
            m = members_map.get(l.member_id)
            if m:
                member_brief = MemberBrief(id=m.id, name=m.name, avatar=m.avatar, provider=provider_map.get(m.id, ""))
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
                description=ci.description, status=ci.status,
                tags=_safe_parse_tags(ci.tags_json),
                created_at=ci.created_at,
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
# Project Persons (reverse lookup)
# ==========================================
@router.get("/projects/{project_id}/persons")
def list_project_persons(project_id: int, session: Session = Depends(get_session)):
    """回傳可存取此專案的 Person 列表"""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    pps = session.exec(
        select(PersonProject).where(PersonProject.project_id == project_id)
    ).all()

    person_ids = [pp.person_id for pp in pps]
    if not person_ids:
        return []

    persons = session.exec(select(Person).where(Person.id.in_(person_ids))).all()
    persons_map = {p.id: p for p in persons}

    result = []
    for pp in pps:
        p = persons_map.get(pp.person_id)
        if not p:
            continue
        result.append({
            "person_id": p.id,
            "display_name": pp.display_name or p.display_name,
            "level": p.level,
            "can_view": pp.can_view,
            "can_create_card": pp.can_create_card,
            "can_run_task": pp.can_run_task,
            "can_comment": pp.can_comment,
            "can_access_sensitive": pp.can_access_sensitive,
        })
    return result


# ==========================================
# StageList Routes
# ==========================================
@router.patch("/lists/{list_id}")
def update_stage_list(
    list_id: int,
    data: StageListUpdateRequest,
    actor: str = Query("human"),
    session: Session = Depends(get_session),
):
    validate_actor(actor)

    stage_list = session.get(StageList, list_id)
    if not stage_list:
        raise HTTPException(status_code=404, detail="StageList not found")

    # 成員綁定列表：禁止變更 member_id
    if stage_list.is_member_bound and data.member_id is not None and data.member_id != stage_list.member_id:
        raise HTTPException(status_code=403, detail="成員綁定列表無法變更成員指派")

    # --- SyncEnforcer：欄位級寫入權限控制 ---
    registry = load_registry_from_db(session)
    enforcer = SyncEnforcer(registry)

    # metadata 欄位不受 SyncRule 控制，直接通過
    _METADATA_FIELDS = {
        "description", "member_id", "system_instruction",
        "prompt_template", "is_ai_stage", "on_success_action",
        "on_fail_action", "auto_commit",
    }

    all_changes = {
        k: v for k, v in data.model_dump().items()
        if v is not None
    }
    sync_changes = {k: v for k, v in all_changes.items() if k not in _METADATA_FIELDS}
    metadata_changes = {k: v for k, v in all_changes.items() if k in _METADATA_FIELDS}

    result = enforcer.validate("stagelist", sync_changes, actor)
    if result.rejected:
        rejected_names = [r.field_name for r in result.rejected]
        logger.info("SyncEnforcer rejected fields for stagelist %d (actor=%s): %s", list_id, actor, rejected_names)

    approved = {**result.approved, **metadata_changes}

    # --- 套用已核准的欄位 ---
    if "name" in approved and approved["name"] and str(approved["name"]).strip():
        stage_list.name = str(approved["name"]).strip()

    if "description" in approved:
        stage_list.description = approved["description"] if approved["description"] and str(approved["description"]).strip() else None

    if "position" in approved:
        stage_list.position = approved["position"]

    if "member_id" in approved:
        stage_list.member_id = approved["member_id"] if approved["member_id"] != 0 else None

    if "system_instruction" in approved:
        stage_list.system_instruction = approved["system_instruction"] if approved["system_instruction"] else None
    if "prompt_template" in approved:
        stage_list.prompt_template = approved["prompt_template"] if approved["prompt_template"] else None
    if "is_ai_stage" in approved:
        stage_list.is_ai_stage = approved["is_ai_stage"]

    if "on_success_action" in approved:
        stage_list.on_success_action = approved["on_success_action"]
    if "on_fail_action" in approved:
        stage_list.on_fail_action = approved["on_fail_action"]

    session.add(stage_list)
    session.commit()
    session.refresh(stage_list)

    # 回傳完整資訊
    member_brief = None
    if stage_list.member_id:
        m = session.get(Member, stage_list.member_id)
        if m:
            member_brief = {"id": m.id, "name": m.name, "avatar": m.avatar, "provider": get_member_primary_provider(m.id, session)}

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
        provider=get_member_primary_provider(member.id, session),
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
# Archived Cards
# ==========================================
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


@router.delete("/projects/{project_id}/cards/archived")
def delete_all_archived_cards(project_id: int, session: Session = Depends(get_session)):
    """永久刪除專案中所有封存卡片"""
    from app.core.card_index import query_archived
    from app.api.deps import _card_locks

    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    archived = query_archived(session, project_id)
    count = 0
    for idx in archived:
        # 跳過運行中的卡片
        if idx.status in ("running", "pending"):
            continue
        # 刪除 MD 檔案
        if idx.file_path:
            md_path = Path(idx.file_path)
            if md_path.exists():
                md_path.unlink()
        # 移除索引
        remove_card_from_index(session, idx.card_id)
        # 刪除 ORM Card 記錄
        orm_card = session.get(Card, idx.card_id)
        if orm_card:
            session.delete(orm_card)
        # 清除鎖
        _card_locks.pop(idx.card_id, None)
        count += 1

    session.commit()
    return {"deleted": count}


# ==========================================
# Project Environment Variables
# ==========================================
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
# Project Cost
# ==========================================
@router.get("/projects/{project_id}/cost")
def get_project_cost(project_id: int, session: Session = Depends(get_session)):
    """取得專案下所有卡片的累計費用統計（排除已封存）"""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    row = session.exec(
        select(
            func.coalesce(func.sum(CardIndex.total_input_tokens), 0),
            func.coalesce(func.sum(CardIndex.total_output_tokens), 0),
            func.coalesce(func.sum(CardIndex.estimated_cost_usd), 0.0),
            func.count(CardIndex.card_id),
        ).where(
            CardIndex.project_id == project_id,
            CardIndex.is_archived == False,
        )
    ).one()

    return {
        "project_id": project_id,
        "total_input_tokens": int(row[0]),
        "total_output_tokens": int(row[1]),
        "estimated_cost_usd": float(row[2]),
        "card_count": int(row[3]),
    }
