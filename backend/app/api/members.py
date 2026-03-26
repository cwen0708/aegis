from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from fastapi.responses import FileResponse
from sqlmodel import Session, select
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, timezone
from app.database import get_session
from app.models.core import Project, Card, StageList, SystemSetting, Account, Member, MemberAccount, TaskLog
from app.api.deps import get_domain_filter, generate_slug
from pathlib import Path
import uuid
import re
import time as _t

router = APIRouter(tags=["Members"])

# 確保上傳目錄存在
UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads" / "portraits"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ==========================================
# Account Schemas
# ==========================================
class AccountCreateRequest(BaseModel):
    provider: str  # "claude" | "gemini" | "openai"
    name: str
    auth_type: str = "cli"  # "api_key" | "cli"
    api_key: Optional[str] = None  # API Key
    oauth_token: Optional[str] = None  # CLI OAuth Token


class AccountUpdateRequest(BaseModel):
    name: Optional[str] = None
    is_healthy: Optional[bool] = None
    oauth_token: Optional[str] = None
    subscription: Optional[str] = None


# ==========================================
# Member Schemas
# ==========================================
class MemberCreateRequest(BaseModel):
    name: str
    avatar: str = ""
    role: str = ""
    description: str = ""


class MemberUpdateRequest(BaseModel):
    name: Optional[str] = None
    avatar: Optional[str] = None
    role: Optional[str] = None
    description: Optional[str] = None
    sprite_index: Optional[int] = None
    portrait: Optional[str] = None


class BindAccountRequest(BaseModel):
    account_id: int
    priority: int = 0
    model: str = ""


class SkillUpdateRequest(BaseModel):
    content: str


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
@router.get("/members")
def list_members(request: Request, session: Session = Depends(get_session)):
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
    # 成員可見性改由前端根據 Room 的 RoomMember 過濾（Office.vue）
    return result


@router.post("/members")
def create_member(data: MemberCreateRequest, session: Session = Depends(get_session)):
    member = Member(**data.model_dump())

    # 自動生成 slug
    if not member.slug:
        member.slug = generate_slug(member.name, session)

    session.add(member)
    session.commit()
    session.refresh(member)
    return member.model_dump()


@router.put("/members/{member_id}")
def update_member(member_id: int, data: MemberUpdateRequest, session: Session = Depends(get_session)):
    member = session.get(Member, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    for field, val in data.model_dump(exclude_unset=True).items():
        setattr(member, field, val)

    # 如果沒有 slug，自動生成
    if not member.slug:
        member.slug = generate_slug(member.name, session)

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
# Usage Dashboard（Token 用量時間序列）
# ==========================================
@router.get("/usage-dashboard")
def usage_dashboard(
    days: int = 30,
    group_by: str = "date",
    session: Session = Depends(get_session),
):
    """Token 用量儀表板：依日期 / 成員 / provider 聚合"""
    from sqlalchemy import func
    from datetime import timedelta

    if group_by not in ("date", "member", "provider"):
        raise HTTPException(status_code=400, detail="group_by 必須是 date / member / provider")

    # 日期範圍過濾
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(days, 1))

    base_aggs = [
        func.count(TaskLog.id).label("tasks"),
        func.coalesce(func.sum(TaskLog.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(TaskLog.output_tokens), 0).label("output_tokens"),
        func.coalesce(func.sum(TaskLog.cache_read_tokens), 0).label("cache_read_tokens"),
        func.coalesce(func.sum(TaskLog.cache_creation_tokens), 0).label("cache_creation_tokens"),
        func.coalesce(func.sum(TaskLog.cost_usd), 0).label("cost_usd"),
    ]

    if group_by == "date":
        date_col = func.date(TaskLog.created_at).label("date")
        rows = session.exec(
            select(date_col, *base_aggs)
            .where(TaskLog.created_at >= cutoff)
            .group_by(date_col)
            .order_by(date_col)
        ).all()
        items = [
            {
                "date": str(r[0]),
                "tasks": int(r[1]),
                "input_tokens": int(r[2]),
                "output_tokens": int(r[3]),
                "cache_read_tokens": int(r[4]),
                "cache_creation_tokens": int(r[5]),
                "cost_usd": float(r[6]),
            }
            for r in rows
        ]

    elif group_by == "member":
        rows = session.exec(
            select(TaskLog.member_id, Member.name, *base_aggs)
            .outerjoin(Member, TaskLog.member_id == Member.id)
            .where(TaskLog.created_at >= cutoff)
            .group_by(TaskLog.member_id, Member.name)
            .order_by(func.coalesce(func.sum(TaskLog.cost_usd), 0).desc())
        ).all()
        items = [
            {
                "member_id": r[0],
                "member_name": r[1] or "unknown",
                "tasks": int(r[2]),
                "input_tokens": int(r[3]),
                "output_tokens": int(r[4]),
                "cache_read_tokens": int(r[5]),
                "cache_creation_tokens": int(r[6]),
                "cost_usd": float(r[7]),
            }
            for r in rows
        ]

    else:  # provider
        provider_col = func.coalesce(TaskLog.provider, "unknown").label("provider")
        rows = session.exec(
            select(provider_col, *base_aggs)
            .where(TaskLog.created_at >= cutoff)
            .group_by(provider_col)
            .order_by(provider_col)
        ).all()
        items = [
            {
                "provider": str(r[0]),
                "tasks": int(r[1]),
                "input_tokens": int(r[2]),
                "output_tokens": int(r[3]),
                "cache_read_tokens": int(r[4]),
                "cache_creation_tokens": int(r[5]),
                "cost_usd": float(r[6]),
            }
            for r in rows
        ]

    return {"group_by": group_by, "days": days, "items": items}


# ==========================================
# Member Memory CRUD
# ==========================================
class MemoryUpdateRequest(BaseModel):
    content: str
    category: Optional[str] = None


@router.get("/members/{slug}/memories")
def list_member_memories_api(slug: str, type: str = "all"):
    """列出成員的記憶檔案"""
    from app.core.memory_manager import list_member_memories
    if type not in ("short-term", "long-term", "all"):
        raise HTTPException(status_code=400, detail="type 必須是 short-term / long-term / all")
    return list_member_memories(slug, memory_type=type)


@router.delete("/members/{slug}/memories/{filename}")
def delete_member_memory_api(slug: str, filename: str):
    """刪除指定的成員記憶檔案"""
    from app.core.memory_manager import delete_member_memory
    if not filename or ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    ok = delete_member_memory(slug, filename)
    if not ok:
        raise HTTPException(status_code=404, detail="Memory file not found")
    return {"ok": True, "deleted": filename}


@router.put("/members/{slug}/memories/{filename}")
def update_member_memory_api(slug: str, filename: str, data: MemoryUpdateRequest):
    """更新長期記憶內容"""
    from app.core.memory_manager import update_member_long_term_memory
    if not filename or ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = update_member_long_term_memory(slug, filename, data.content, data.category)
    return {"ok": True, "path": str(path)}


# ==========================================
# Member Memory Search (BM25 + Time Decay)
# ==========================================
@router.get("/members/{slug}/memory/search")
def search_member_memory(slug: str, q: str = "", top_k: int = 5):
    """搜尋成員記憶：BM25 關鍵字搜尋 + 時間衰減"""
    from app.core.memory_manager import search_member_memories
    if not q.strip():
        return []
    return search_member_memories(slug, q.strip(), top_k=min(top_k, 20))


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


@router.put("/members/{member_id}/skills/{skill_name}")
def update_member_skill(member_id: int, skill_name: str, data: SkillUpdateRequest, session: Session = Depends(get_session)):
    """更新成員的技能內容"""
    from app.core.member_profile import get_skills_dir

    member = session.get(Member, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    if not member.slug:
        # 自動生成 slug
        member.slug = generate_slug(member.name, session)
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

    member = session.get(Member, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    if not member.slug:
        member.slug = generate_slug(member.name, session)
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
