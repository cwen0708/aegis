"""
共用依賴：helpers、visibility filter、常用查詢函式。
從 routes.py 提取，供各模組 import。
"""
import asyncio
from fastapi import HTTPException, Request
from sqlmodel import Session, select
from app.models.core import (
    Project, StageList, Member, MemberAccount, Account,
    Domain, PersonProject, BotUser,
)


# ==========================================
# Per-card lock manager (for async endpoints)
# ==========================================
_card_locks: dict[int, asyncio.Lock] = {}


def get_card_lock(card_id: int) -> asyncio.Lock:
    return _card_locks.setdefault(card_id, asyncio.Lock())


def get_visibility_filter(request: Request, session: Session):
    """根據登入狀態回傳 (visible_project_ids, visible_room_ids)。
    回傳 (None, None) 表示不過濾（admin / localhost）。

    可見性規則：
    - admin token / localhost / ?all=true → 不過濾
    - user token → PersonProject 中 can_view=True 的專案
    - 未登入 → Project.allow_anonymous=True 的專案
    """
    from app.core.auth import verify_session_token, decode_session_token

    # ?all=true + 有效 admin token → 不過濾（settings 頁面用）
    if request.query_params.get("all") == "true":
        auth_header = request.headers.get("authorization", "")
        token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""
        if token and verify_session_token(token):
            return None, None

    # localhost → 不過濾（worker / 內部呼叫）
    # 注意：nginx proxy 時 client.host 是 127.0.0.1，需看 X-Real-IP
    real_ip = request.headers.get("x-real-ip", "")
    client_host = real_ip or (request.client.host if request.client else "")
    if client_host in ("127.0.0.1", "::1", "localhost") and not real_ip:
        return None, None

    # 解析 token
    auth_header = request.headers.get("authorization", "")
    token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""

    if token:
        payload = decode_session_token(token)
        if payload:
            # admin token → 不過濾
            if payload.get("type") == "admin":
                return None, None

            # user token → 查 PersonProject
            if payload.get("type") == "user" and payload.get("uid"):
                user = session.get(BotUser, payload["uid"])
                if user and user.person_id:
                    projects = session.exec(
                        select(PersonProject.project_id)
                        .where(PersonProject.person_id == user.person_id, PersonProject.can_view == True)
                    ).all()
                    project_ids = set(projects) if projects else set()
                    # 從專案的 room_id 推導可見空間
                    if project_ids:
                        rooms = session.exec(
                            select(Project.room_id).where(
                                Project.id.in_(project_ids),
                                Project.room_id != None
                            )
                        ).all()
                        room_ids = {r for r in rooms if r}
                    else:
                        room_ids = set()
                    return project_ids or None, room_ids or None

    # 未登入 → 只看 allow_anonymous
    anon_projects = session.exec(
        select(Project.id).where(Project.allow_anonymous == True, Project.is_active == True)
    ).all()
    anon_rooms_raw = session.exec(
        select(Project.room_id).where(
            Project.allow_anonymous == True, Project.is_active == True, Project.room_id != None
        )
    ).all()
    # 也加上 Room.allow_anonymous=True 的空間
    from app.models.core import Room
    anon_rooms_direct = session.exec(
        select(Room.id).where(Room.allow_anonymous == True, Room.is_active == True)
    ).all()

    project_ids = set(anon_projects)
    room_ids = {r for r in anon_rooms_raw if r} | set(anon_rooms_direct)

    return project_ids or set(), room_ids or set()


# 保留舊函式名作為相容（逐步移除）
def get_domain_filter(request: Request, session: Session):
    """[deprecated] 改用 get_visibility_filter"""
    project_ids, room_ids = get_visibility_filter(request, session)
    # 舊介面回傳 (project_ids, member_ids)，新介面不再回傳 member_ids
    return project_ids, None


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
