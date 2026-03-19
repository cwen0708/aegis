"""邀請碼 + Bot User + Person 管理 API"""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from datetime import datetime, timezone
from app.database import get_session
from app.models.core import InviteCode, BotUser, Person, PersonProject, PersonMember, Member
from app.api.schemas import (
    InvitationCreate, InvitationUpdate, BotUserUpdate, TTSRequest,
    PersonCreate, PersonUpdate, PersonProjectCreate, PersonProjectUpdate,
    PersonMemberCreate, PersonMemberUpdate,
)
import json as json_module

router = APIRouter(tags=["invitations"])


# ==========================================
# Invitation helpers
# ==========================================

def _invitation_status(inv: InviteCode) -> str:
    """計算邀請碼狀態"""
    if inv.expires_at:
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


# ==========================================
# Invitation CRUD
# ==========================================

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

    code = data.code or secrets.token_urlsafe(6).upper()[:8]

    existing = session.exec(select(InviteCode).where(InviteCode.code == code)).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"邀請碼 {code} 已存在")

    expires_at = None
    if data.expires_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=data.expires_days)

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
        access_valid_days=data.access_valid_days,
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
    if data.access_valid_days is not None:
        invitation.access_valid_days = data.access_valid_days
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
# Bot User CRUD
# ==========================================

@router.get("/bot-users")
def list_bot_users(session: Session = Depends(get_session)):
    """列出所有 Bot User"""
    users = session.exec(select(BotUser).order_by(BotUser.created_at.desc())).all()
    result = []
    for u in users:
        projects = session.exec(
            select(PersonProject).where(PersonProject.person_id == u.person_id)
        ).all() if u.person_id else []
        member = session.get(Member, u.default_member_id) if u.default_member_id else None
        result.append({
            "id": u.id,
            "platform": u.platform,
            "platform_user_id": u.platform_user_id,
            "username": u.username,
            "level": u.level,
            "is_active": u.is_active,
            "default_member_id": u.default_member_id,
            "default_member_name": member.name if member else None,
            "access_expires_at": u.access_expires_at.isoformat() if u.access_expires_at else None,
            "created_at": u.created_at.isoformat(),
            "last_active_at": u.last_active_at.isoformat() if u.last_active_at else None,
            "projects": [{"id": p.id, "project_id": p.project_id, "display_name": p.display_name, "can_view": p.can_view, "can_create_card": p.can_create_card, "can_run_task": p.can_run_task} for p in projects],
        })
    return result


@router.patch("/bot-users/{user_id}")
def update_bot_user(user_id: int, data: BotUserUpdate, session: Session = Depends(get_session)):
    """更新 Bot User"""
    user = session.get(BotUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if data.level is not None:
        user.level = data.level
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.default_member_id is not None:
        user.default_member_id = data.default_member_id
    if data.access_expires_at is not None:
        if data.access_expires_at == "" or data.access_expires_at == "null":
            user.access_expires_at = None
        else:
            user.access_expires_at = datetime.fromisoformat(data.access_expires_at.replace("Z", "+00:00"))
    session.add(user)
    session.commit()
    return {"ok": True}


@router.delete("/bot-users/{user_id}")
def delete_bot_user(user_id: int, session: Session = Depends(get_session)):
    """刪除 Bot User 及其關聯資料"""
    user = session.get(BotUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    from app.models.core import ChatSession as CS, ChatMessage as CM
    # 清理 Person 相關資料
    if user.person_id:
        for pp in session.exec(select(PersonProject).where(PersonProject.person_id == user.person_id)).all():
            session.delete(pp)
        for pm in session.exec(select(PersonMember).where(PersonMember.person_id == user.person_id)).all():
            session.delete(pm)
    for cs in session.exec(select(CS).where(CS.bot_user_id == user_id)).all():
        for cm in session.exec(select(CM).where(CM.session_id == cs.id)).all():
            session.delete(cm)
        session.delete(cs)
    session.delete(user)
    session.commit()
    return {"ok": True}


# ==========================================
# Person CRUD
# ==========================================

def _person_to_response(person: Person, session: Session) -> dict:
    """轉換 Person 為完整回應格式"""
    # 關聯的 BotUser
    bot_users = session.exec(
        select(BotUser).where(BotUser.person_id == person.id)
    ).all()
    bot_users_data = [
        {
            "id": bu.id,
            "platform": bu.platform,
            "username": bu.username,
            "platform_user_id": bu.platform_user_id,
            "last_active_at": bu.last_active_at.isoformat() if bu.last_active_at else None,
            "level": bu.level,
            "is_active": bu.is_active,
        }
        for bu in bot_users
    ]

    # 關聯的 InviteCode
    invite_codes = session.exec(
        select(InviteCode).where(InviteCode.owner_person_id == person.id)
    ).all()
    invite_codes_data = [
        {
            "id": ic.id,
            "code": ic.code,
            "status": _invitation_status(ic),
            "used_count": ic.used_count,
            "max_uses": ic.max_uses,
        }
        for ic in invite_codes
    ]

    # 關聯的 PersonProject
    person_projects = session.exec(
        select(PersonProject).where(PersonProject.person_id == person.id)
    ).all()
    projects_data = [
        {
            "id": pp.id,
            "project_id": pp.project_id,
            "display_name": pp.display_name,
            "description": pp.description,
            "can_view": pp.can_view,
            "can_create_card": pp.can_create_card,
            "can_run_task": pp.can_run_task,
            "can_access_sensitive": pp.can_access_sensitive,
            "is_default": pp.is_default,
        }
        for pp in person_projects
    ]

    # 關聯的 PersonMember
    person_members = session.exec(
        select(PersonMember).where(PersonMember.person_id == person.id)
    ).all()
    members_data = []
    for pm in person_members:
        member = session.get(Member, pm.member_id)
        members_data.append({
            "id": pm.id,
            "member_id": pm.member_id,
            "member_name": member.name if member else f"#{pm.member_id}",
            "member_avatar": member.avatar if member else "",
            "is_default": pm.is_default,
            "can_switch": pm.can_switch,
        })

    # status
    status = "active" if len(bot_users) > 0 else "pending"

    return {
        "id": person.id,
        "display_name": person.display_name,
        "description": person.description,
        "level": person.level,
        "extra_json": person.extra_json,
        "access_expires_at": person.access_expires_at.isoformat() if person.access_expires_at else None,
        "default_member_id": person.default_member_id,
        "created_at": person.created_at.isoformat(),
        "status": status,
        "bot_users": bot_users_data,
        "invite_codes": invite_codes_data,
        "projects": projects_data,
        "members": members_data,
    }


@router.get("/persons")
def list_persons(session: Session = Depends(get_session)):
    """列出所有 Person"""
    persons = session.exec(
        select(Person).order_by(Person.created_at.desc())
    ).all()
    return [_person_to_response(p, session) for p in persons]


@router.get("/persons/{person_id}")
def get_person(person_id: int, session: Session = Depends(get_session)):
    """取得 Person 詳情"""
    person = session.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person 不存在")
    return _person_to_response(person, session)


@router.post("/persons")
def create_person(data: PersonCreate, session: Session = Depends(get_session)):
    """建立 Person + 自動生成邀請碼 + 建 PersonProject"""
    from datetime import timedelta
    import secrets

    # 1. 建立 Person
    person = Person(
        display_name=data.display_name,
        description=data.description,
        level=data.target_level,
        default_member_id=data.target_member_id,
    )
    session.add(person)
    session.flush()  # 取得 person.id

    # 2. 建立 InviteCode
    code = secrets.token_urlsafe(6).upper()[:8]
    # 確保不重複
    while session.exec(select(InviteCode).where(InviteCode.code == code)).first():
        code = secrets.token_urlsafe(6).upper()[:8]

    expires_at = None
    if data.expires_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=data.expires_days)

    allowed_json = None
    if data.allowed_projects:
        allowed_json = json_module.dumps(data.allowed_projects)

    invite = InviteCode(
        code=code,
        target_level=data.target_level,
        target_member_id=data.target_member_id,
        allowed_projects=allowed_json,
        user_display_name=data.display_name,
        user_description=data.description,
        default_can_view=data.default_can_view,
        default_can_create_card=data.default_can_create_card,
        default_can_run_task=data.default_can_run_task,
        default_can_access_sensitive=data.default_can_access_sensitive,
        max_uses=1,
        expires_at=expires_at,
        owner_person_id=person.id,
        note=data.note,
    )
    session.add(invite)

    # 3. 建立 PersonProject
    project_ids = data.allowed_projects or []
    if project_ids:
        for pid in project_ids:
            pp = PersonProject(
                person_id=person.id,
                project_id=pid,
                display_name=data.display_name,
                description=data.description,
                can_view=data.default_can_view,
                can_create_card=data.default_can_create_card,
                can_run_task=data.default_can_run_task,
                can_access_sensitive=data.default_can_access_sensitive,
            )
            session.add(pp)

    session.commit()
    session.refresh(person)
    return _person_to_response(person, session)


@router.patch("/persons/{person_id}")
def update_person(person_id: int, data: PersonUpdate, session: Session = Depends(get_session)):
    """更新 Person"""
    person = session.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person 不存在")

    if data.display_name is not None:
        person.display_name = data.display_name
    if data.description is not None:
        person.description = data.description
    if data.level is not None:
        person.level = data.level
    if data.access_expires_at is not None:
        if data.access_expires_at == "" or data.access_expires_at == "null":
            person.access_expires_at = None
        else:
            person.access_expires_at = datetime.fromisoformat(
                data.access_expires_at.replace("Z", "+00:00")
            )

    session.commit()
    session.refresh(person)
    return _person_to_response(person, session)


@router.delete("/persons/{person_id}")
def delete_person(person_id: int, session: Session = Depends(get_session)):
    """刪除 Person + 關聯資料（PersonProject, PersonMember, InviteCode, BotUser）"""
    person = session.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person 不存在")

    # 清理 PersonProject
    for pp in session.exec(select(PersonProject).where(PersonProject.person_id == person_id)).all():
        session.delete(pp)

    # 清理 PersonMember
    for pm in session.exec(select(PersonMember).where(PersonMember.person_id == person_id)).all():
        session.delete(pm)

    # 清理 InviteCode
    for ic in session.exec(select(InviteCode).where(InviteCode.owner_person_id == person_id)).all():
        session.delete(ic)

    # 解綁 BotUser（不刪除 BotUser，只清 person_id）
    for bu in session.exec(select(BotUser).where(BotUser.person_id == person_id)).all():
        bu.person_id = 0
        session.add(bu)

    session.delete(person)
    session.commit()
    return {"ok": True}


# ==========================================
# PersonProject CRUD
# ==========================================

@router.post("/persons/{person_id}/projects")
def add_person_project(person_id: int, data: PersonProjectCreate, session: Session = Depends(get_session)):
    """新增 Person 專案權限"""
    from app.models.core import Project
    person = session.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person 不存在")
    project = session.get(Project, data.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="專案不存在")
    existing = session.exec(
        select(PersonProject).where(
            PersonProject.person_id == person_id,
            PersonProject.project_id == data.project_id,
        )
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="此專案權限已存在")
    pp = PersonProject(
        person_id=person_id,
        project_id=data.project_id,
        display_name=person.display_name or "",
        description=person.description or "",
        can_view=data.can_view,
        can_create_card=data.can_create_card,
        can_run_task=data.can_run_task,
        can_access_sensitive=data.can_access_sensitive,
        is_default=data.is_default,
    )
    session.add(pp)
    session.commit()
    session.refresh(pp)
    return {
        "id": pp.id,
        "project_id": pp.project_id,
        "display_name": pp.display_name,
        "description": pp.description,
        "can_view": pp.can_view,
        "can_create_card": pp.can_create_card,
        "can_run_task": pp.can_run_task,
        "can_access_sensitive": pp.can_access_sensitive,
        "is_default": pp.is_default,
    }


@router.patch("/persons/{person_id}/projects/{project_id}")
def update_person_project(person_id: int, project_id: int, data: PersonProjectUpdate, session: Session = Depends(get_session)):
    """更新 Person 專案權限"""
    pp = session.exec(
        select(PersonProject).where(
            PersonProject.person_id == person_id,
            PersonProject.project_id == project_id,
        )
    ).first()
    if not pp:
        raise HTTPException(status_code=404, detail="PersonProject 不存在")
    if data.can_view is not None:
        pp.can_view = data.can_view
    if data.can_create_card is not None:
        pp.can_create_card = data.can_create_card
    if data.can_run_task is not None:
        pp.can_run_task = data.can_run_task
    if data.can_access_sensitive is not None:
        pp.can_access_sensitive = data.can_access_sensitive
    if data.is_default is not None:
        pp.is_default = data.is_default
    session.commit()
    session.refresh(pp)
    return {
        "id": pp.id,
        "project_id": pp.project_id,
        "display_name": pp.display_name,
        "description": pp.description,
        "can_view": pp.can_view,
        "can_create_card": pp.can_create_card,
        "can_run_task": pp.can_run_task,
        "can_access_sensitive": pp.can_access_sensitive,
        "is_default": pp.is_default,
    }


@router.delete("/persons/{person_id}/projects/{project_id}")
def remove_person_project(person_id: int, project_id: int, session: Session = Depends(get_session)):
    """移除 Person 專案權限"""
    pp = session.exec(
        select(PersonProject).where(
            PersonProject.person_id == person_id,
            PersonProject.project_id == project_id,
        )
    ).first()
    if not pp:
        raise HTTPException(status_code=404, detail="PersonProject 不存在")
    session.delete(pp)
    session.commit()
    return {"ok": True}


# ==========================================
# PersonMember CRUD
# ==========================================

@router.post("/persons/{person_id}/members")
def add_person_member(person_id: int, data: PersonMemberCreate, session: Session = Depends(get_session)):
    """新增 Person 成員綁定"""
    person = session.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person 不存在")
    member = session.get(Member, data.member_id)
    if not member:
        raise HTTPException(status_code=404, detail="成員不存在")
    existing = session.exec(
        select(PersonMember).where(
            PersonMember.person_id == person_id,
            PersonMember.member_id == data.member_id,
        )
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="此成員已綁定")
    pm = PersonMember(
        person_id=person_id,
        member_id=data.member_id,
        is_default=data.is_default,
        can_switch=data.can_switch,
    )
    session.add(pm)
    session.commit()
    session.refresh(pm)
    return {
        "id": pm.id,
        "member_id": pm.member_id,
        "member_name": member.name,
        "member_avatar": member.avatar,
        "is_default": pm.is_default,
        "can_switch": pm.can_switch,
    }


@router.patch("/persons/{person_id}/members/{member_id}")
def update_person_member(person_id: int, member_id: int, data: PersonMemberUpdate, session: Session = Depends(get_session)):
    """更新 Person 成員綁定"""
    pm = session.exec(
        select(PersonMember).where(
            PersonMember.person_id == person_id,
            PersonMember.member_id == member_id,
        )
    ).first()
    if not pm:
        raise HTTPException(status_code=404, detail="PersonMember 不存在")
    if data.is_default is not None:
        pm.is_default = data.is_default
    if data.can_switch is not None:
        pm.can_switch = data.can_switch
    session.commit()
    session.refresh(pm)
    member = session.get(Member, pm.member_id)
    return {
        "id": pm.id,
        "member_id": pm.member_id,
        "member_name": member.name if member else f"#{pm.member_id}",
        "member_avatar": member.avatar if member else "",
        "is_default": pm.is_default,
        "can_switch": pm.can_switch,
    }


@router.delete("/persons/{person_id}/members/{member_id}")
def remove_person_member(person_id: int, member_id: int, session: Session = Depends(get_session)):
    """移除 Person 成員綁定"""
    pm = session.exec(
        select(PersonMember).where(
            PersonMember.person_id == person_id,
            PersonMember.member_id == member_id,
        )
    ).first()
    if not pm:
        raise HTTPException(status_code=404, detail="PersonMember 不存在")
    session.delete(pm)
    session.commit()
    return {"ok": True}


# ==========================================
# TTS 語音合成
# ==========================================

@router.post("/tts")
async def text_to_speech(data: TTSRequest):
    """Gemini TTS 語音合成，回傳 WAV 音檔。無 Gemini 時回 204（前端降級 Web Speech）"""
    from app.core.tts import synthesize
    from fastapi.responses import Response

    audio = await synthesize(data.text, voice=data.voice or "Kore")
    if audio is None:
        return Response(status_code=204)

    media_type = "audio/wav" if audio[:4] == b"RIFF" else "audio/mpeg"
    return Response(content=audio, media_type=media_type)
