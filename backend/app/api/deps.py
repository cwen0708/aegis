"""
共用依賴：helpers、domain filter、常用查詢函式。
從 routes.py 提取，供各模組 import。
"""
import asyncio
import json as json_module
from fastapi import HTTPException, Request
from sqlmodel import Session, select
from app.models.core import (
    Project, StageList, Member, MemberAccount, Account,
    Domain, RoomProject, RoomMember,
)


# ==========================================
# Per-card lock manager (for async endpoints)
# ==========================================
_card_locks: dict[int, asyncio.Lock] = {}


def get_card_lock(card_id: int) -> asyncio.Lock:
    return _card_locks.setdefault(card_id, asyncio.Lock())


def get_domain_filter(request: Request, session: Session):
    """根據 Host header 回傳 (visible_project_ids, visible_member_ids)。
    回傳 (None, None) 表示不過濾（admin / localhost / 無網域設定）。"""
    # ?all=true → 不過濾（需登入，settings 頁面用）
    if request.query_params.get("all") == "true":
        from app.core.auth import verify_session_token
        auth_header = request.headers.get("authorization", "")
        token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""
        if token and verify_session_token(token):
            return None, None

    # localhost → 不過濾（worker / 內部呼叫）
    client_host = request.client.host if request.client else ""
    if client_host in ("127.0.0.1", "::1", "localhost"):
        return None, None

    # Host header → Domain → Rooms
    host = (request.headers.get("host") or "").split(":")[0]
    if not host:
        return None, None

    domain = session.exec(
        select(Domain).where(Domain.hostname == host, Domain.is_active == True)
    ).first()
    if not domain:
        domain = session.exec(
            select(Domain).where(Domain.is_default == True, Domain.is_active == True)
        ).first()
    if not domain:
        return None, None

    room_ids = json_module.loads(domain.room_ids_json or "[]")
    if not room_ids:
        return None, None

    project_ids = {rp.project_id for rp in session.exec(
        select(RoomProject).where(RoomProject.room_id.in_(room_ids))
    ).all()}
    member_ids = {rm.member_id for rm in session.exec(
        select(RoomMember).where(RoomMember.room_id.in_(room_ids))
    ).all()}

    return project_ids or None, member_ids or None


def get_project_for_list(session: Session, list_id: int):
    """Get Project from a list_id. Returns (project, stage_list) or raises 404."""
    sl = session.get(StageList, list_id)
    if not sl:
        raise HTTPException(status_code=404, detail="List not found")
    project = session.get(Project, sl.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project, sl


def get_member_primary_provider(member_id: int, session: Session) -> str:
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


def generate_slug(name: str, session: Session) -> str:
    """從成員名稱生成唯一 slug"""
    from pypinyin import lazy_pinyin
    import re

    raw = "-".join(lazy_pinyin(name))
    base = re.sub(r"[^a-z0-9-]", "", raw.lower()).strip("-")
    if not base:
        base = "member"

    slug = base
    counter = 1
    while session.exec(select(Member).where(Member.slug == slug)).first():
        slug = f"{base}-{counter}"
        counter += 1

    return slug
