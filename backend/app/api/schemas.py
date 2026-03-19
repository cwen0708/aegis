"""
共用 Pydantic schemas。
Phase 1: channels、invitations、bot_users 需要的 schemas。
後續 Phase 會逐步從 routes.py 搬移更多 schemas 到這裡。
"""
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


# ==========================================
# Channels
# ==========================================
# channels 沒有額外的 schema（直接用 dict）


# ==========================================
# Invitations
# ==========================================
class InvitationCreate(BaseModel):
    """建立邀請碼"""
    code: Optional[str] = None
    target_level: int = 1
    target_member_id: Optional[int] = None
    allowed_projects: Optional[List[int]] = None
    user_display_name: str = ""
    user_description: str = ""
    default_can_view: bool = True
    default_can_create_card: bool = False
    default_can_run_task: bool = False
    default_can_access_sensitive: bool = False
    max_uses: int = 1
    expires_days: Optional[int] = None
    access_valid_days: Optional[int] = None
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
    access_valid_days: Optional[int] = None
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
    status: str  # active, expired, depleted


# ==========================================
# Bot Users
# ==========================================
class BotUserUpdate(BaseModel):
    level: Optional[int] = None
    is_active: Optional[bool] = None
    access_expires_at: Optional[str] = None  # ISO format or null
    default_member_id: Optional[int] = None


# ==========================================
# TTS
# ==========================================
class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = "Kore"


# ==========================================
# Persons
# ==========================================
class PersonCreate(BaseModel):
    """建立 Person + 自動生成邀請碼"""
    display_name: str = ""
    description: str = ""
    target_level: int = 1
    target_member_id: Optional[int] = None
    allowed_projects: Optional[List[int]] = None
    default_can_view: bool = True
    default_can_create_card: bool = False
    default_can_run_task: bool = False
    default_can_access_sensitive: bool = False
    expires_days: Optional[int] = None
    note: str = ""


class PersonUpdate(BaseModel):
    """更新 Person"""
    display_name: Optional[str] = None
    description: Optional[str] = None
    level: Optional[int] = None
    access_expires_at: Optional[str] = None  # ISO format or empty string to clear


# ==========================================
# PersonProject
# ==========================================
class PersonProjectCreate(BaseModel):
    """新增 Person 專案權限"""
    project_id: int
    can_view: bool = True
    can_create_card: bool = False
    can_run_task: bool = False
    can_access_sensitive: bool = False
    is_default: bool = False


class PersonProjectUpdate(BaseModel):
    """更新 Person 專案權限"""
    can_view: Optional[bool] = None
    can_create_card: Optional[bool] = None
    can_run_task: Optional[bool] = None
    can_access_sensitive: Optional[bool] = None
    is_default: Optional[bool] = None


# ==========================================
# PersonMember
# ==========================================
class PersonMemberCreate(BaseModel):
    """新增 Person 成員綁定"""
    member_id: int
    is_default: bool = False
    can_switch: bool = True


class PersonMemberUpdate(BaseModel):
    """更新 Person 成員綁定"""
    is_default: Optional[bool] = None
    can_switch: Optional[bool] = None
