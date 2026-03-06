from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlmodel import Session, select
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
from app.database import get_session
from app.models.core import Project, Card, StageList, CronJob, SystemSetting, Account, Member, MemberAccount, TaskLog
from typing import Any
from app.core.runner import running_tasks, abort_task
import app.core.runner as runner_module
from app.core.usage_poller import get_cached_claude_usage, get_cached_gemini_usage, get_last_updated
import app.core.poller as poller_module
import app.core.cron_poller as cron_module
from app.core.ws_manager import websocket_clients
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

# ==========================================
# Project Routes
# ==========================================
@router.get("/projects/", response_model=List[Project])
def read_projects(session: Session = Depends(get_session)):
    # 回傳所有專案，讓前端可以顯示停用狀態
    projects = session.exec(select(Project)).all()
    return projects

@router.post("/projects/", response_model=Project)
def create_project(project: Project, session: Session = Depends(get_session)):
    session.add(project)
    session.commit()
    session.refresh(project)
    return project

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    path: Optional[str] = None
    is_active: Optional[bool] = None

@router.patch("/projects/{project_id}", response_model=Project)
def update_project(project_id: int, update_data: ProjectUpdate, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if update_data.name is not None:
        project.name = update_data.name
    if update_data.path is not None:
        project.path = update_data.path
    if update_data.is_active is not None:
        project.is_active = update_data.is_active
    session.add(project)
    session.commit()
    session.refresh(project)
    return project

@router.get("/projects/{project_id}/board", response_model=List[StageListResponse])
def read_project_board(project_id: int, session: Session = Depends(get_session)):
    """一次抓取整個看板所需的資料：列表與其中的卡片"""
    # 就算專案停用，看板資料還是可以抓，前端再決定怎麼顯示
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    lists = session.exec(
        select(StageList).where(StageList.project_id == project_id).order_by(StageList.position)
    ).all()
    
    result = []
    for l in lists:
        cards = session.exec(
            select(Card).where(Card.list_id == l.id).order_by(Card.created_at.desc())
        ).all()
        member_brief = None
        if l.member_id:
            m = session.get(Member, l.member_id)
            if m:
                member_brief = MemberBrief(id=m.id, name=m.name, avatar=m.avatar, provider=_get_member_primary_provider(m.id, session))
        result.append(StageListResponse(
            id=l.id,
            project_id=l.project_id,
            name=l.name,
            position=l.position,
            member_id=l.member_id,
            member=member_brief,
            cards=[CardResponse(
                id=c.id, list_id=c.list_id, title=c.title,
                description=c.description, status=c.status, created_at=c.created_at
            ) for c in cards]
        ))
    return result

# ==========================================
# StageList Routes
# ==========================================
class StageListUpdateRequest(BaseModel):
    member_id: Optional[int] = None  # null = 使用預設路由


@router.patch("/lists/{list_id}")
def update_stage_list(list_id: int, data: StageListUpdateRequest, session: Session = Depends(get_session)):
    stage_list = session.get(StageList, list_id)
    if not stage_list:
        raise HTTPException(status_code=404, detail="StageList not found")
    stage_list.member_id = data.member_id
    session.add(stage_list)
    session.commit()
    session.refresh(stage_list)
    # 回傳 member brief
    member_brief = None
    if stage_list.member_id:
        m = session.get(Member, stage_list.member_id)
        if m:
            member_brief = {"id": m.id, "name": m.name, "avatar": m.avatar, "provider": _get_member_primary_provider(m.id, session)}
    return {"ok": True, "member_id": stage_list.member_id, "member": member_brief}


# ==========================================
# Card Routes
# ==========================================
@router.get("/cards/", response_model=List[Card])
def read_cards(session: Session = Depends(get_session)):
    cards = session.exec(select(Card)).all()
    return cards

@router.get("/cards/{card_id}", response_model=Card)
def read_card(card_id: int, session: Session = Depends(get_session)):
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
    card = Card(list_id=card_in.list_id, title=card_in.title, description=card_in.description)
    session.add(card)
    session.commit()
    session.refresh(card)
    return card

class CardUpdateRequest(BaseModel):
    list_id: Optional[int] = None
    status: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None

@router.patch("/cards/{card_id}", response_model=Card)
def update_card(card_id: int, update_data: CardUpdateRequest, session: Session = Depends(get_session)):
    card = session.get(Card, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    
    if update_data.list_id is not None:
        card.list_id = update_data.list_id
        card.status = "pending"
    
    if update_data.status is not None:
        card.status = update_data.status
    if update_data.title is not None:
        card.title = update_data.title
    if update_data.description is not None:
        card.description = update_data.description
    if update_data.content is not None:
        card.content = update_data.content
        
    card.updated_at = datetime.utcnow()
    session.add(card)
    session.commit()
    session.refresh(card)
    return card

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
    card = session.get(Card, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    if card.status == "running":
        raise HTTPException(status_code=409, detail="Cannot delete a running card")
    session.delete(card)
    session.commit()
    return {"ok": True}


@router.delete("/cron-jobs/{job_id}")
def delete_cron_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(CronJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="CronJob not found")
    session.delete(job)
    session.commit()
    return {"ok": True}


# ==========================================
# Card Trigger / Abort
# ==========================================
@router.post("/cards/{card_id}/trigger")
def trigger_card(card_id: int, session: Session = Depends(get_session)):
    """手動觸發卡片執行（將 status 設為 pending）"""
    card = session.get(Card, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    if card.status == "running":
        raise HTTPException(status_code=409, detail="Card is already running")
    card.status = "pending"
    card.updated_at = datetime.utcnow()
    session.add(card)
    session.commit()
    return {"ok": True, "status": "pending"}


@router.post("/cards/{card_id}/abort")
def abort_card(card_id: int, session: Session = Depends(get_session)):
    """中止執行中的任務"""
    card = session.get(Card, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    killed = abort_task(card_id)
    if killed:
        card.status = "failed"
        card.content = (card.content or "") + "\n\n### Aborted\n任務已被手動中止。"
        card.updated_at = datetime.utcnow()
        session.add(card)
        session.commit()
        return {"ok": True, "status": "aborted"}
    # 即使 process 不在 running_tasks，也重設狀態
    if card.status == "running":
        card.status = "failed"
        card.updated_at = datetime.utcnow()
        session.add(card)
        session.commit()
    return {"ok": True, "status": "reset"}


# ==========================================
# Runner Control
# ==========================================
@router.post("/runner/pause")
def pause_runner():
    poller_module.is_paused = True
    return {"ok": True, "is_paused": True}


@router.post("/runner/resume")
def resume_runner():
    poller_module.is_paused = False
    return {"ok": True, "is_paused": False}


@router.get("/runner/status")
def runner_status():
    tasks_data = []
    for tid, info in list(running_tasks.items()):
        tasks_data.append({
            "task_id": info["task_id"],
            "project": info.get("project", ""),
            "card_title": info.get("card_title", ""),
            "started_at": info.get("started_at", 0),
            "pid": info.get("pid"),
            "provider": info.get("provider", ""),
            "member_id": info.get("member_id"),
        })
    return {
        "is_paused": poller_module.is_paused,
        "running_tasks": tasks_data,
        "workstations_used": len(running_tasks),
        "workstations_total": runner_module.MAX_WORKSTATIONS,
    }


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
def get_services():
    """查詢所有服務健康狀態（引擎 + CLI 工具，10 秒快取）"""
    now = time_module.time()
    if _services_cache["data"] and (now - _services_cache["ts"]) < _CACHE_TTL:
        return _services_cache["data"]

    result = {
        "pid": os.getpid(),
        "engines": {
            "task_poller": {
                "status": "paused" if poller_module.is_paused else "running",
                "interval_sec": 3,
                "is_paused": poller_module.is_paused,
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
SETTING_DEFAULTS = {
    "timezone": "Asia/Taipei",
    "max_workstations": "3",
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
    # 即時更新工作台數量
    if "max_workstations" in data:
        from app.core.runner import update_max_workstations
        update_max_workstations(int(data["max_workstations"]))
    return get_settings(session=session)


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
    """任務統計：token 用量、任務數、費用"""
    from sqlalchemy import func

    logs = session.exec(select(TaskLog)).all()

    total_tasks = len(logs)
    success_tasks = sum(1 for l in logs if l.status == "success")
    failed_tasks = sum(1 for l in logs if l.status in ("error", "timeout"))

    total_input = sum(l.input_tokens for l in logs)
    total_output = sum(l.output_tokens for l in logs)
    total_cache_read = sum(l.cache_read_tokens for l in logs)
    total_cache_create = sum(l.cache_creation_tokens for l in logs)
    total_cost = sum(l.cost_usd for l in logs)
    total_duration = sum(l.duration_ms for l in logs)

    # 按 provider 分組
    by_provider: dict = {}
    for l in logs:
        p = l.provider or "unknown"
        if p not in by_provider:
            by_provider[p] = {"tasks": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0}
        by_provider[p]["tasks"] += 1
        by_provider[p]["input_tokens"] += l.input_tokens
        by_provider[p]["output_tokens"] += l.output_tokens
        by_provider[p]["cost_usd"] += l.cost_usd

    # 最近 10 筆
    recent = session.exec(select(TaskLog).order_by(TaskLog.id.desc()).limit(10)).all()

    return {
        "total_tasks": total_tasks,
        "success_tasks": success_tasks,
        "failed_tasks": failed_tasks,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cache_read_tokens": total_cache_read,
        "total_cache_creation_tokens": total_cache_create,
        "total_cost_usd": total_cost,
        "total_duration_ms": total_duration,
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

    # 儲存新檔案
    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    # 更新資料庫
    member.portrait = f"/api/v1/portraits/{filename}"
    session.add(member)
    session.commit()

    return {"portrait": member.portrait}


@router.get("/portraits/{filename}")
async def get_portrait(filename: str):
    """取得立繪圖片"""
    filepath = UPLOAD_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Portrait not found")
    return FileResponse(filepath)


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
    """檢查 Claude CLI 和 Gemini CLI 安裝狀態"""
    result = {
        "claude": {"installed": False, "version": None, "path": None},
        "gemini": {"installed": False, "version": None, "path": None},
    }

    # 檢查 Claude CLI
    try:
        which_result = subprocess.run(
            "which claude", shell=True, capture_output=True, text=True, timeout=5
        )
        if which_result.returncode == 0:
            result["claude"]["installed"] = True
            result["claude"]["path"] = which_result.stdout.strip()
            # 取得版本
            ver_result = subprocess.run(
                "claude --version", shell=True, capture_output=True, text=True, timeout=10
            )
            if ver_result.returncode == 0:
                result["claude"]["version"] = ver_result.stdout.strip().split("\n")[0]
    except Exception:
        pass

    # 檢查 Gemini CLI
    try:
        which_result = subprocess.run(
            "which gemini", shell=True, capture_output=True, text=True, timeout=5
        )
        if which_result.returncode == 0:
            result["gemini"]["installed"] = True
            result["gemini"]["path"] = which_result.stdout.strip()
            # 取得版本
            ver_result = subprocess.run(
                "gemini --version", shell=True, capture_output=True, text=True, timeout=10
            )
            if ver_result.returncode == 0:
                result["gemini"]["version"] = ver_result.stdout.strip().split("\n")[0]
    except Exception:
        pass

    return result


def _npm_install_global(package: str) -> subprocess.CompletedProcess:
    """Cross-platform npm global install (no sudo on Windows)."""
    if os.name == "nt":
        cmd = f"npm install -g {package}"
    else:
        cmd = f"sudo -n npm install -g {package}"
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)


@router.post("/cli/claude/install")
def install_claude_cli():
    """安裝 Claude CLI"""
    try:
        result = _npm_install_global("@anthropic-ai/claude-code")
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
    try:
        result = _npm_install_global("@google/gemini-cli")
        if result.returncode == 0:
            return {"ok": True, "message": "Gemini CLI 安裝成功", "output": result.stdout}
        else:
            raise HTTPException(status_code=500, detail=f"安裝失敗: {result.stderr}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="安裝超時")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
