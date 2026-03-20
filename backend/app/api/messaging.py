"""Messaging API — emails, domains, rooms, raw messages"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select
from sqlalchemy import func as sa_func
from typing import Optional
from pydantic import BaseModel
from datetime import datetime, timezone
from app.database import get_session
from app.models.core import (
    EmailMessage, Project, Room, RoomProject, RoomMember,
    Domain, RawMessage, RawMessageUser, RawMessageGroup,
)
from app.api.deps import get_domain_filter
import json as json_module

router = APIRouter(tags=["messaging"])


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


# ==========================================
# Room & Domain Schemas
# ==========================================
class RoomCreate(BaseModel):
    name: str
    description: str = ""

class RoomUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    position: Optional[int] = None
    is_active: Optional[bool] = None

class DomainCreate(BaseModel):
    hostname: str
    name: str = ""
    room_ids_json: str = "[]"
    is_default: bool = False

class DomainUpdate(BaseModel):
    hostname: Optional[str] = None
    name: Optional[str] = None
    room_ids_json: Optional[str] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    require_login: Optional[bool] = None
    show_onboarding: Optional[bool] = None

class RoomAssignment(BaseModel):
    project_ids: Optional[list[int]] = None
    member_ids: Optional[list[int]] = None


# ==========================================
# Domain Resolution (public)
# ==========================================
@router.get("/domain/current")
def resolve_domain(hostname: str = "", session: Session = Depends(get_session)):
    """根據 hostname 解析對應的 Domain 和 Rooms"""
    domain = None
    if hostname:
        domain = session.exec(
            select(Domain).where(Domain.hostname == hostname, Domain.is_active == True)
        ).first()
    if not domain:
        domain = session.exec(
            select(Domain).where(Domain.is_default == True, Domain.is_active == True)
        ).first()

    if not domain:
        return {"domain": None, "rooms": []}

    # 解析 room_ids_json
    try:
        room_ids = json_module.loads(domain.room_ids_json) if domain.room_ids_json else []
    except (json_module.JSONDecodeError, TypeError):
        room_ids = []

    rooms = []
    if room_ids:
        room_list = session.exec(
            select(Room).where(Room.id.in_(room_ids), Room.is_active == True)
        ).all()
    else:
        room_list = []

    for room in room_list:
        project_links = session.exec(
            select(RoomProject).where(RoomProject.room_id == room.id)
        ).all()
        member_links = session.exec(
            select(RoomMember).where(RoomMember.room_id == room.id)
        ).all()
        rooms.append({
            "id": room.id,
            "name": room.name,
            "description": room.description,
            "project_ids": [lnk.project_id for lnk in project_links],
            "member_ids": [lnk.member_id for lnk in member_links],
        })

    return {"domain": domain, "rooms": rooms}


# ==========================================
# Domain CRUD
# ==========================================
@router.get("/domains", response_model=list[Domain])
@router.get("/domains/", response_model=list[Domain])
def list_domains(session: Session = Depends(get_session)):
    return session.exec(select(Domain)).all()


@router.post("/domains", response_model=Domain)
def create_domain(data: DomainCreate, session: Session = Depends(get_session)):
    if data.is_default:
        # 清除其他 domain 的 is_default
        existing = session.exec(select(Domain).where(Domain.is_default == True)).all()
        for d in existing:
            d.is_default = False
            session.add(d)

    domain = Domain(
        hostname=data.hostname,
        name=data.name,
        room_ids_json=data.room_ids_json,
        is_default=data.is_default,
    )
    session.add(domain)
    session.commit()
    session.refresh(domain)
    return domain


@router.get("/domains/{domain_id}", response_model=Domain)
def get_domain(domain_id: int, session: Session = Depends(get_session)):
    domain = session.get(Domain, domain_id)
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    return domain


@router.patch("/domains/{domain_id}", response_model=Domain)
def update_domain(domain_id: int, data: DomainUpdate, session: Session = Depends(get_session)):
    domain = session.get(Domain, domain_id)
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")

    if data.is_default is True:
        # 清除其他 domain 的 is_default
        existing = session.exec(
            select(Domain).where(Domain.is_default == True, Domain.id != domain_id)
        ).all()
        for d in existing:
            d.is_default = False
            session.add(d)

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(domain, key, value)

    session.add(domain)
    session.commit()
    session.refresh(domain)
    return domain


@router.delete("/domains/{domain_id}")
def delete_domain(domain_id: int, session: Session = Depends(get_session)):
    domain = session.get(Domain, domain_id)
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    session.delete(domain)
    session.commit()
    return {"ok": True}


# ==========================================
# Room CRUD
# ==========================================
@router.get("/rooms")
@router.get("/rooms/")
def list_rooms(request: Request, session: Session = Depends(get_session)):
    from app.api.deps import get_visibility_filter
    _, visible_room_ids = get_visibility_filter(request, session)

    rooms = session.exec(select(Room).where(Room.is_active == True).order_by(Room.position)).all()

    # 過濾可見空間
    if visible_room_ids is not None:
        rooms = [r for r in rooms if r.id in visible_room_ids]

    room_ids = [r.id for r in rooms]
    projects_by_room: dict[int, list[int]] = {r.id: [] for r in rooms}
    if room_ids:
        for p in session.exec(
            select(Project).where(Project.room_id.in_(room_ids), Project.is_active == True)
        ).all():
            if p.room_id in projects_by_room:
                projects_by_room[p.room_id].append(p.id)
    members_by_room: dict[int, list[int]] = {r.id: [] for r in rooms}
    if room_ids:
        for rm in session.exec(
            select(RoomMember).where(RoomMember.room_id.in_(room_ids))
        ).all():
            if rm.room_id in members_by_room:
                members_by_room[rm.room_id].append(rm.member_id)

    result = []
    for room in rooms:
        d = room.model_dump() if hasattr(room, 'model_dump') else dict(room)
        d["project_ids"] = projects_by_room[room.id]
        d["member_ids"] = members_by_room[room.id]
        d.pop("layout_json", None)
        result.append(d)
    return result


@router.get("/rooms/{room_id}")
def get_room(room_id: int, session: Session = Depends(get_session)):
    """取得單一房間（含 layout_json）"""
    room = session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    project_ids = [rp.project_id for rp in session.exec(
        select(RoomProject).where(RoomProject.room_id == room.id)
    ).all()]
    member_ids = [rm.member_id for rm in session.exec(
        select(RoomMember).where(RoomMember.room_id == room.id)
    ).all()]
    d = room.model_dump() if hasattr(room, 'model_dump') else dict(room)
    d["project_ids"] = project_ids
    d["member_ids"] = member_ids
    return d


@router.post("/rooms", response_model=Room)
def create_room(data: RoomCreate, session: Session = Depends(get_session)):
    # 自動設 position 為最大值 + 1
    max_pos = session.exec(select(sa_func.max(Room.position))).one()
    from app.core.default_office_layout import get_default_office_layout_json
    room = Room(
        name=data.name,
        description=data.description,
        layout_json=get_default_office_layout_json(),
        position=(max_pos or 0) + 1,
    )
    session.add(room)
    session.commit()
    session.refresh(room)
    return room


@router.patch("/rooms/{room_id}", response_model=Room)
def update_room(room_id: int, data: RoomUpdate, session: Session = Depends(get_session)):
    room = session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(room, key, value)

    session.add(room)
    session.commit()
    session.refresh(room)
    return room


@router.patch("/rooms/{room_id}/layout")
def update_room_layout(room_id: int, body: dict, session: Session = Depends(get_session)):
    """獨立更新 layout_json（可能很大，不與其他欄位一起 PATCH）"""
    room = session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    if "layout_json" in body:
        room.layout_json = body["layout_json"] if isinstance(body["layout_json"], str) else json_module.dumps(body["layout_json"])
    session.add(room)
    session.commit()
    session.refresh(room)
    return {"ok": True, "id": room.id}


@router.delete("/rooms/{room_id}")
def delete_room(room_id: int, session: Session = Depends(get_session)):
    room = session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # 刪除關聯的 RoomProject 和 RoomMember
    for rp in session.exec(select(RoomProject).where(RoomProject.room_id == room_id)).all():
        session.delete(rp)
    for rm in session.exec(select(RoomMember).where(RoomMember.room_id == room_id)).all():
        session.delete(rm)

    session.delete(room)
    session.commit()
    return {"ok": True}


# ==========================================
# Room Assignments
# ==========================================
@router.put("/rooms/{room_id}/projects")
def set_room_projects(room_id: int, data: RoomAssignment, session: Session = Depends(get_session)):
    """全量替換房間的專案列表"""
    room = session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # 刪除舊的
    old = session.exec(select(RoomProject).where(RoomProject.room_id == room_id)).all()
    for rp in old:
        session.delete(rp)
    session.flush()  # 確保 DELETE 先執行，避免 UNIQUE 衝突

    # 新增
    project_ids = data.project_ids or []
    for pid in project_ids:
        session.add(RoomProject(room_id=room_id, project_id=pid))

    session.commit()
    return {"ok": True, "project_ids": project_ids}


@router.put("/rooms/{room_id}/members")
def set_room_members(room_id: int, data: RoomAssignment, session: Session = Depends(get_session)):
    """全量替換房間的成員列表"""
    room = session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # 刪除舊的
    old = session.exec(select(RoomMember).where(RoomMember.room_id == room_id)).all()
    for rm in old:
        session.delete(rm)
    session.flush()

    # 新增
    member_ids = data.member_ids or []
    for idx, mid in enumerate(member_ids):
        session.add(RoomMember(room_id=room_id, member_id=mid, desk_index=idx))

    session.commit()
    return {"ok": True, "member_ids": member_ids}


# ==========================================
# 原始訊息收集 (RawMessage)
# ==========================================

@router.get("/raw-messages/")
async def list_raw_messages(
    session: Session = Depends(get_session),
    source_id: Optional[str] = None,
    platform: Optional[str] = None,
    event_type: Optional[str] = None,
    is_processed: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
):
    """列出原始訊息（支援篩選群組/平台/事件類型）"""
    q = select(RawMessage).order_by(RawMessage.created_at.desc())
    if source_id:
        q = q.where(RawMessage.source_id == source_id)
    if platform:
        q = q.where(RawMessage.platform == platform)
    if event_type:
        q = q.where(RawMessage.event_type == event_type)
    if is_processed is not None:
        q = q.where(RawMessage.is_processed == is_processed)
    q = q.offset(offset).limit(limit)

    messages = session.exec(q).all()

    # 批次查詢 user display_name
    user_ids = list({m.user_id for m in messages if m.user_id})
    user_map = {}
    if user_ids:
        users = session.exec(
            select(RawMessageUser).where(RawMessageUser.user_id.in_(user_ids))
        ).all()
        user_map = {u.user_id: u.display_name for u in users}

    # 組合回傳
    result = []
    for m in messages:
        d = {
            "id": m.id,
            "platform": m.platform,
            "source_type": m.source_type,
            "source_id": m.source_id,
            "user_id": m.user_id,
            "user_name": user_map.get(m.user_id, ""),
            "event_type": m.event_type,
            "content_type": m.content_type,
            "content": m.content,
            "is_processed": m.is_processed,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        result.append(d)
    return result


@router.get("/raw-messages/stats")
async def raw_message_stats(
    session: Session = Depends(get_session),
):
    """統計各群組的訊息數量"""
    from sqlalchemy import func as sa_fn
    rows = session.exec(
        select(
            RawMessage.source_id,
            sa_fn.count(RawMessage.id).label("count"),
            sa_fn.max(RawMessage.created_at).label("last_at"),
        )
        .where(RawMessage.event_type == "message")
        .group_by(RawMessage.source_id)
    ).all()

    # 查群組名稱
    source_ids = [r[0] for r in rows]
    groups = session.exec(
        select(RawMessageGroup).where(RawMessageGroup.group_id.in_(source_ids))
    ).all() if source_ids else []
    group_map = {g.group_id: g for g in groups}

    result = []
    for source_id, count, last_at in rows:
        g = group_map.get(source_id)
        result.append({
            "source_id": source_id,
            "group_name": g.group_name if g else "",
            "project_id": g.project_id if g else None,
            "member_count": g.member_count if g else 0,
            "message_count": count,
            "last_message_at": last_at.isoformat() if last_at else None,
        })
    return sorted(result, key=lambda x: x["message_count"], reverse=True)


# ==========================================
# 群組管理 (RawMessageGroup)
# ==========================================

@router.get("/raw-messages/groups/")
async def list_raw_message_groups(
    session: Session = Depends(get_session),
    platform: Optional[str] = None,
):
    """列出所有收集中的群組"""
    q = select(RawMessageGroup)
    if platform:
        q = q.where(RawMessageGroup.platform == platform)
    return session.exec(q.order_by(RawMessageGroup.updated_at.desc())).all()


class GroupUpdatePayload(BaseModel):
    project_id: Optional[int] = None
    group_name: Optional[str] = None


@router.patch("/raw-messages/groups/{group_id}")
async def update_raw_message_group(
    group_id: int,
    payload: GroupUpdatePayload,
    session: Session = Depends(get_session),
):
    """更新群組設定（指派專案等）"""
    g = session.get(RawMessageGroup, group_id)
    if not g:
        raise HTTPException(404, "Group not found")
    if payload.project_id is not None:
        g.project_id = payload.project_id
    if payload.group_name is not None:
        g.group_name = payload.group_name
    g.updated_at = datetime.now(timezone.utc)
    session.add(g)
    session.commit()
    session.refresh(g)
    return g


# ==========================================
# 用戶快取 (RawMessageUser)
# ==========================================

@router.get("/raw-messages/users/")
async def list_raw_message_users(
    session: Session = Depends(get_session),
    platform: Optional[str] = None,
):
    """列出所有收集到的用戶"""
    q = select(RawMessageUser)
    if platform:
        q = q.where(RawMessageUser.platform == platform)
    return session.exec(q.order_by(RawMessageUser.updated_at.desc())).all()
