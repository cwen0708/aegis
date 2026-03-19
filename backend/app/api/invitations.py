"""邀請碼 + Bot User 管理 API — 8 endpoints"""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from datetime import datetime, timezone
from app.database import get_session
from app.models.core import InviteCode, BotUser, PersonProject, PersonMember, Member
from app.api.schemas import InvitationCreate, InvitationUpdate, BotUserUpdate, TTSRequest
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
