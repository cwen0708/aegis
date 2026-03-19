"""
Bot 用戶服務 — 用戶管理、權限檢查、驗證
"""
import secrets
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from sqlmodel import Session, select

from app.database import engine
from app.models.core import (
    BotUser, BotUserPermission, InviteCode,
    ChatSession, ChatMessage, Member, Project, SystemSetting,
    PersonProject, PersonMember,
)

logger = logging.getLogger(__name__)

# 命令權限等級對應
COMMAND_PERMISSIONS = {
    # L0: 任何人
    "help": 0, "start": 0, "verify": 0,
    # L1: 訪客
    "me": 1, "status": 1, "card_list": 1, "card": 1, "bind": 1, "unbind": 1, "bindings": 1, "profile": 1,
    # L2: 成員
    "run": 2, "stop": 2, "card_create": 2, "switch": 2,
    # L3: 管理員
    "user": 3, "invite": 3, "grant": 3, "assign": 3, "ban": 3,
}


def get_or_create_bot_user(platform: str, platform_user_id: str, username: Optional[str] = None) -> BotUser:
    """
    查詢或建立 BotUser

    Args:
        platform: 平台名稱 (telegram, line, ...)
        platform_user_id: 平台用戶 ID
        username: 顯示名稱（可選）

    Returns:
        BotUser 實例
    """
    with Session(engine) as session:
        stmt = select(BotUser).where(
            BotUser.platform == platform,
            BotUser.platform_user_id == platform_user_id
        )
        bot_user = session.exec(stmt).first()

        if bot_user:
            # 更新最後活躍時間
            bot_user.last_active_at = datetime.now(timezone.utc)
            if username and not bot_user.username:
                bot_user.username = username
            session.add(bot_user)
            session.commit()
            session.refresh(bot_user)
            return bot_user

        # 建立新用戶
        # 檢查是否為管理員（第一個用戶或設定中指定的管理員）
        admin_user_ids = _get_admin_user_ids()
        is_admin = f"{platform}:{platform_user_id}" in admin_user_ids

        bot_user = BotUser(
            platform=platform,
            platform_user_id=platform_user_id,
            username=username,
            level=3 if is_admin else 0,  # 管理員 level=3，否則 level=0
        )
        session.add(bot_user)
        session.commit()
        session.refresh(bot_user)

        # 管理員自動綁定所有 Members
        if is_admin:
            _setup_admin_members(session, bot_user)

        logger.info(f"[BotUser] Created new user: {platform}:{platform_user_id} (level={bot_user.level})")
        return bot_user


def _setup_admin_members(session: Session, bot_user: BotUser):
    """為管理員設定所有 Member 權限"""
    members = session.exec(select(Member).order_by(Member.id)).all()
    if not members:
        return

    # 設定第一個 Member 為預設
    bot_user.default_member_id = members[0].id

    # 確保 Person 存在
    if not bot_user.person_id:
        from app.models.core import Person
        person = Person(
            display_name=bot_user.username or "",
            level=bot_user.level,
            default_member_id=members[0].id,
        )
        session.add(person)
        session.flush()
        bot_user.person_id = person.id

    # 建立所有 PersonMember 關聯
    for idx, member in enumerate(members):
        existing = session.exec(
            select(PersonMember).where(
                PersonMember.person_id == bot_user.person_id,
                PersonMember.member_id == member.id,
            )
        ).first()
        if not existing:
            session.add(PersonMember(
                person_id=bot_user.person_id,
                member_id=member.id,
                is_default=(idx == 0),
                can_switch=True,
            ))

    session.commit()
    logger.info(f"[BotUser] Admin {bot_user.id} linked to {len(members)} members")


def _get_admin_user_ids() -> set:
    """從 SystemSetting 取得管理員用戶 ID 列表"""
    with Session(engine) as session:
        setting = session.get(SystemSetting, "admin_user_ids")
        if setting and setting.value:
            # 格式: "telegram:123456,line:abcdef"
            return set(setting.value.split(","))
    return set()


def check_permission(bot_user: BotUser, command: str) -> bool:
    """
    檢查用戶是否有權限執行命令

    Args:
        bot_user: BotUser 實例
        command: 命令名稱（不含 /）

    Returns:
        True 如果有權限
    """
    if not bot_user.is_active:
        return False

    required_level = COMMAND_PERMISSIONS.get(command, 3)  # 預設需要管理員
    return bot_user.level >= required_level


def check_verify_lockout(bot_user: BotUser) -> bool:
    """
    檢查用戶是否被鎖定（驗證失敗過多）

    Returns:
        True 如果被鎖定
    """
    now = datetime.now(timezone.utc)

    # 已設定鎖定時間
    if bot_user.locked_until and bot_user.locked_until > now:
        return True

    # 檢查失敗次數
    if bot_user.failed_verify_count >= 5:
        if bot_user.last_failed_at:
            lockout_until = bot_user.last_failed_at + timedelta(minutes=30)
            if now < lockout_until:
                # 設定鎖定時間
                with Session(engine) as session:
                    db_user = session.get(BotUser, bot_user.id)
                    if db_user:
                        db_user.locked_until = lockout_until
                        session.commit()
                return True

        # 超過鎖定時間，重置計數
        with Session(engine) as session:
            db_user = session.get(BotUser, bot_user.id)
            if db_user:
                db_user.failed_verify_count = 0
                db_user.locked_until = None
                session.commit()

    return False


def record_verify_failure(bot_user: BotUser):
    """記錄驗證失敗"""
    with Session(engine) as session:
        db_user = session.get(BotUser, bot_user.id)
        if db_user:
            db_user.failed_verify_count += 1
            db_user.last_failed_at = datetime.now(timezone.utc)
            session.commit()


def verify_invite_code(bot_user: BotUser, code: str) -> tuple[bool, str]:
    """
    驗證邀請碼

    Returns:
        (success, message)
    """
    # 檢查鎖定
    if check_verify_lockout(bot_user):
        remaining = bot_user.locked_until - datetime.now(timezone.utc)
        minutes = int(remaining.total_seconds() / 60) + 1
        return False, f"驗證失敗次數過多，請 {minutes} 分鐘後再試"

    with Session(engine) as session:
        stmt = select(InviteCode).where(InviteCode.code == code)
        invite = session.exec(stmt).first()

        if not invite:
            record_verify_failure(bot_user)
            return False, "無效的邀請碼"

        # 檢查過期（處理 naive datetime）
        if invite.expires_at:
            exp = invite.expires_at if invite.expires_at.tzinfo else invite.expires_at.replace(tzinfo=timezone.utc)
            if exp < datetime.now(timezone.utc):
                record_verify_failure(bot_user)
                return False, "邀請碼已過期"

        # 檢查使用次數
        if invite.used_count >= invite.max_uses:
            record_verify_failure(bot_user)
            return False, "邀請碼已達使用上限"

        # 驗證成功，更新用戶
        db_user = session.get(BotUser, bot_user.id)
        if db_user:
            db_user.level = invite.target_level
            db_user.failed_verify_count = 0
            db_user.locked_until = None

            # 綁定到 Person（邀請碼建立時已建好 Person）
            if invite.owner_person_id:
                db_user.person_id = invite.owner_person_id
            else:
                # fallback：舊邀請碼沒有 Person，建一個
                from app.models.core import Person
                person = Person(
                    display_name=invite.user_display_name or db_user.username or "",
                    description=invite.user_description,
                    level=invite.target_level,
                    default_member_id=invite.target_member_id,
                )
                session.add(person)
                session.flush()
                db_user.person_id = person.id
                invite.owner_person_id = person.id

            # 設定存取期限
            if invite.access_valid_days:
                from datetime import timedelta
                db_user.access_expires_at = datetime.now(timezone.utc) + timedelta(days=invite.access_valid_days)

            # 設定預設 Member
            if invite.target_member_id:
                db_user.default_member_id = invite.target_member_id

                # 建立 PersonMember 關聯
                existing_pm = session.exec(
                    select(PersonMember).where(
                        PersonMember.person_id == db_user.person_id,
                        PersonMember.member_id == invite.target_member_id,
                    )
                ).first()
                if not existing_pm:
                    session.add(PersonMember(
                        person_id=db_user.person_id,
                        member_id=invite.target_member_id,
                        is_default=True,
                    ))

            # 建立專案權限（PersonProject）
            if invite.allowed_projects:
                try:
                    project_ids = json.loads(invite.allowed_projects)
                    for idx, pid in enumerate(project_ids):
                        existing_pp = session.exec(
                            select(PersonProject).where(
                                PersonProject.person_id == db_user.person_id,
                                PersonProject.project_id == pid,
                            )
                        ).first()
                        if not existing_pp:
                            session.add(PersonProject(
                                person_id=db_user.person_id,
                                project_id=pid,
                                display_name=invite.user_display_name,
                                description=invite.user_description,
                                can_view=invite.default_can_view,
                                can_create_card=invite.default_can_create_card,
                                can_run_task=invite.default_can_run_task,
                                can_access_sensitive=invite.default_can_access_sensitive,
                                is_default=(idx == 0),
                            ))
                except json.JSONDecodeError:
                    pass

            # 更新邀請碼使用次數
            invite.used_count += 1

            session.commit()

        # 取得 Member 名稱
        member_name = ""
        if invite.target_member_id:
            member = session.get(Member, invite.target_member_id)
            if member:
                member_name = member.name

        level_names = {1: "訪客", 2: "成員", 3: "管理員"}
        level_name = level_names.get(invite.target_level, "用戶")

        msg = f"驗證成功！您的身份：{level_name}"
        if member_name:
            msg += f"\n您的 AI 助理：{member_name}"

        return True, msg


def create_invite_code(
    created_by: int,
    target_level: int = 1,
    target_member_id: Optional[int] = None,
    allowed_projects: Optional[List[int]] = None,
    max_uses: int = 1,
    expires_days: int = 7,
    note: str = "",
    # P2: 用戶身份描述
    user_display_name: str = "",
    user_description: str = "",
    # P2: 預設權限
    default_can_view: bool = True,
    default_can_create_card: bool = False,
    default_can_run_task: bool = False,
    default_can_access_sensitive: bool = False,
) -> str:
    """
    產生邀請碼

    Args:
        created_by: 建立者 BotUser ID
        target_level: 驗證後的權限等級 (1=訪客, 2=成員, 3=管理員)
        target_member_id: 預設綁定的 Member ID
        allowed_projects: 可存取的專案 ID 列表
        user_display_name: 用戶顯示名稱 (AI 稱呼用)
        user_description: 身份描述 (AI 理解用)
        default_can_*: 預設權限

    Returns:
        邀請碼字串
    """
    code = secrets.token_urlsafe(8).upper()[:12]  # 12 字元

    with Session(engine) as session:
        # 建立 Person（邀請碼 = 一個人的身份）
        from app.models.core import Person
        person = Person(
            display_name=user_display_name,
            description=user_description,
            level=target_level,
            default_member_id=target_member_id,
        )
        session.add(person)
        session.flush()  # 取得 person.id

        invite = InviteCode(
            code=code,
            target_level=target_level,
            target_member_id=target_member_id,
            allowed_projects=json.dumps(allowed_projects) if allowed_projects else None,
            max_uses=max_uses,
            expires_at=datetime.now(timezone.utc) + timedelta(days=expires_days),
            created_by=created_by,
            note=note,
            owner_person_id=person.id,
            # P2: 用戶身份描述
            user_display_name=user_display_name,
            user_description=user_description,
            # P2: 預設權限
            default_can_view=default_can_view,
            default_can_create_card=default_can_create_card,
            default_can_run_task=default_can_run_task,
            default_can_access_sensitive=default_can_access_sensitive,
        )
        session.add(invite)
        session.commit()

    logger.info(f"[InviteCode] Created: {code} (level={target_level}, projects={allowed_projects}, person={person.id})")
    return code


def get_user_info(bot_user: BotUser) -> dict:
    """取得用戶資訊"""
    level_names = {0: "未驗證", 1: "訪客", 2: "成員", 3: "管理員"}

    with Session(engine) as session:
        # 取得關聯的 Members（透過 Person）
        person_id = _resolve_person_id(bot_user.id) if not bot_user.person_id else bot_user.person_id
        stmt = select(PersonMember).where(PersonMember.person_id == person_id) if person_id else None
        user_members = session.exec(stmt).all() if stmt is not None else []

        members = []
        for um in user_members:
            member = session.get(Member, um.member_id)
            if member:
                members.append({
                    "id": member.id,
                    "name": member.name,
                    "is_default": um.is_default
                })

        # 取得預設 Member
        default_member = None
        if bot_user.default_member_id:
            m = session.get(Member, bot_user.default_member_id)
            if m:
                default_member = {"id": m.id, "name": m.name}

    return {
        "id": bot_user.id,
        "platform": bot_user.platform,
        "username": bot_user.username or bot_user.platform_user_id,
        "level": bot_user.level,
        "level_name": level_names.get(bot_user.level, "未知"),
        "is_active": bot_user.is_active,
        "default_member": default_member,
        "members": members,
        "created_at": bot_user.created_at.isoformat() if bot_user.created_at else None,
        "last_active_at": bot_user.last_active_at.isoformat() if bot_user.last_active_at else None,
    }


def list_users(limit: int = 50) -> List[dict]:
    """列出所有用戶"""
    with Session(engine) as session:
        stmt = select(BotUser).order_by(BotUser.last_active_at.desc()).limit(limit)
        users = session.exec(stmt).all()
        return [get_user_info(u) for u in users]


def set_user_level(user_id: int, level: int) -> bool:
    """設定用戶權限等級"""
    with Session(engine) as session:
        user = session.get(BotUser, user_id)
        if user:
            user.level = level
            session.commit()
            logger.info(f"[BotUser] Set level: user={user_id}, level={level}")
            return True
    return False


def ban_user(user_id: int) -> bool:
    """停用用戶"""
    with Session(engine) as session:
        user = session.get(BotUser, user_id)
        if user:
            user.is_active = False
            session.commit()
            logger.info(f"[BotUser] Banned: user={user_id}")
            return True
    return False


def assign_member(user_id: int, member_id: int, is_default: bool = True) -> bool:
    """指派 Member 給用戶"""
    with Session(engine) as session:
        user = session.get(BotUser, user_id)
        member = session.get(Member, member_id)

        if not user or not member:
            return False

        person_id = user.person_id
        if not person_id:
            return False

        # 檢查是否已存在
        existing = session.exec(
            select(PersonMember).where(
                PersonMember.person_id == person_id,
                PersonMember.member_id == member_id
            )
        ).first()

        if existing:
            existing.is_default = is_default
        else:
            pm = PersonMember(
                person_id=person_id,
                member_id=member_id,
                is_default=is_default
            )
            session.add(pm)

        # 如果設為預設，更新 BotUser.default_member_id
        if is_default:
            user.default_member_id = member_id
            # 清除其他 Member 的 is_default
            stmt = select(PersonMember).where(
                PersonMember.person_id == person_id,
                PersonMember.member_id != member_id
            )
            for pm in session.exec(stmt).all():
                pm.is_default = False

        session.commit()
        logger.info(f"[BotUser] Assigned member: user={user_id}, member={member_id}")
        return True


def switch_member(bot_user: BotUser, member_id: int) -> tuple[bool, str]:
    """切換用戶的當前 Member"""
    with Session(engine) as session:
        person_id = _resolve_person_id(bot_user.id)
        if not person_id:
            return False, "用戶尚未綁定身份"

        # 檢查用戶是否有此 Member 的權限
        stmt = select(PersonMember).where(
            PersonMember.person_id == person_id,
            PersonMember.member_id == member_id,
            PersonMember.can_switch == True
        )
        pm = session.exec(stmt).first()

        if not pm:
            return False, "您沒有切換到此角色的權限"

        member = session.get(Member, member_id)
        if not member:
            return False, "找不到此角色"

        member_name = member.name  # commit 前先取，避免 expire 後讀到錯誤值

        # 更新預設 Member
        db_user = session.get(BotUser, bot_user.id)
        if db_user:
            db_user.default_member_id = member_id
            session.commit()

        return True, f"已切換到 {member_name}"


def get_available_members(bot_user: BotUser) -> List[dict]:
    """取得用戶可用的 Members"""
    with Session(engine) as session:
        person_id = _resolve_person_id(bot_user.id)
        if not person_id:
            return []
        stmt = select(PersonMember).where(
            PersonMember.person_id == person_id,
            PersonMember.can_switch == True
        )
        user_members = session.exec(stmt).all()

        result = []
        for um in user_members:
            member = session.get(Member, um.member_id)
            if member:
                result.append({
                    "id": member.id,
                    "name": member.name,
                    "avatar": member.avatar,
                    "is_default": um.is_default
                })

        return result


# ==========================================
# 專案存取查詢（Person 表直達查詢）
# ==========================================

def _resolve_person_id(bot_user_id: int) -> int:
    """從 BotUser ID 取得 person_id"""
    with Session(engine) as session:
        user = session.get(BotUser, bot_user_id)
        return user.person_id if user and user.person_id else 0


def get_user_projects(bot_user_id: int, can_view_only: bool = True) -> List[Project]:
    """取得用戶可存取的專案（透過 Person → PersonProject）"""
    from app.models.core import PersonProject
    person_id = _resolve_person_id(bot_user_id)
    if not person_id:
        return []
    with Session(engine) as session:
        stmt = (
            select(Project)
            .join(PersonProject, PersonProject.project_id == Project.id)
            .where(PersonProject.person_id == person_id)
        )
        if can_view_only:
            stmt = stmt.where(PersonProject.can_view == True)
        return list(session.exec(stmt).all())


def get_default_project(bot_user_id: int) -> Optional[Project]:
    """取得用戶的預設專案"""
    from app.models.core import PersonProject
    person_id = _resolve_person_id(bot_user_id)
    if not person_id:
        return None
    with Session(engine) as session:
        stmt = (
            select(Project)
            .join(PersonProject, PersonProject.project_id == Project.id)
            .where(PersonProject.person_id == person_id, PersonProject.is_default == True)
        )
        return session.exec(stmt).first()


def get_user_context(bot_user_id: int, project_id: int) -> Optional["PersonProject"]:
    """取得用戶在指定專案的身份上下文（回傳 PersonProject）"""
    from app.models.core import PersonProject
    person_id = _resolve_person_id(bot_user_id)
    if not person_id:
        return None
    with Session(engine) as session:
        return session.exec(
            select(PersonProject).where(PersonProject.person_id == person_id, PersonProject.project_id == project_id)
        ).first()


def can_user_view_project(bot_user_id: int, project_id: int) -> bool:
    """檢查用戶能否查看指定專案"""
    from app.models.core import PersonProject
    person_id = _resolve_person_id(bot_user_id)
    if not person_id:
        return False
    with Session(engine) as session:
        return session.exec(
            select(PersonProject).where(PersonProject.person_id == person_id, PersonProject.project_id == project_id, PersonProject.can_view == True)
        ).first() is not None


def can_user_create_card(bot_user_id: int, project_id: int) -> bool:
    """檢查用戶能否在指定專案建卡"""
    from app.models.core import PersonProject
    person_id = _resolve_person_id(bot_user_id)
    if not person_id:
        return False
    with Session(engine) as session:
        return session.exec(
            select(PersonProject).where(PersonProject.person_id == person_id, PersonProject.project_id == project_id, PersonProject.can_create_card == True)
        ).first() is not None


def can_user_run_task(bot_user_id: int, project_id: int) -> bool:
    """檢查用戶能否在指定專案執行任務"""
    from app.models.core import PersonProject
    person_id = _resolve_person_id(bot_user_id)
    if not person_id:
        return False
    with Session(engine) as session:
        return session.exec(
            select(PersonProject).where(PersonProject.person_id == person_id, PersonProject.project_id == project_id, PersonProject.can_run_task == True)
        ).first() is not None


def grant_project_access(
    bot_user_id: int,
    project_id: int,
    display_name: str = "",
    description: str = "",
    can_view: bool = True,
    can_create_card: bool = False,
    can_run_task: bool = False,
    can_access_sensitive: bool = False,
    is_default: bool = False,
    created_by: Optional[int] = None,
) -> Optional[PersonProject]:
    """
    授予用戶專案存取權限（透過 Person → PersonProject）

    Args:
        bot_user_id: BotUser ID
        project_id: Project ID
        display_name: 用戶顯示名稱（AI 稱呼用）
        description: 身份描述（AI 理解用）
        can_*: 硬性權限
        is_default: 是否設為預設專案
        created_by: 授權者 BotUser ID

    Returns:
        PersonProject 實例
    """
    with Session(engine) as session:
        person_id = _resolve_person_id(bot_user_id)
        if not person_id:
            logger.warning(f"[PersonProject] Cannot grant: user={bot_user_id} has no person_id")
            return None

        # 檢查是否已存在
        pp = session.exec(
            select(PersonProject).where(
                PersonProject.person_id == person_id,
                PersonProject.project_id == project_id,
            )
        ).first()

        if pp:
            # 更新現有記錄
            pp.display_name = display_name
            pp.description = description
            pp.can_view = can_view
            pp.can_create_card = can_create_card
            pp.can_run_task = can_run_task
            pp.can_access_sensitive = can_access_sensitive
            pp.is_default = is_default
        else:
            # 建立新記錄
            pp = PersonProject(
                person_id=person_id,
                project_id=project_id,
                display_name=display_name,
                description=description,
                can_view=can_view,
                can_create_card=can_create_card,
                can_run_task=can_run_task,
                can_access_sensitive=can_access_sensitive,
                is_default=is_default,
                created_by=created_by,
            )
            session.add(pp)

        # 如果設為預設，清除其他專案的 is_default
        if is_default:
            stmt = select(PersonProject).where(
                PersonProject.person_id == person_id,
                PersonProject.project_id != project_id,
            )
            for other in session.exec(stmt).all():
                other.is_default = False

        session.commit()
        session.refresh(pp)

        logger.info(f"[PersonProject] Granted: user={bot_user_id}, person={person_id}, project={project_id}")
        return pp


# ==========================================
# 額外資料 (extra_json) CRUD
# ==========================================

def get_user_extra(bot_user_id: int) -> dict:
    """取得用戶的 extra_json（從 Person 表讀取，跨平台共用）"""
    from app.models.core import Person
    with Session(engine) as session:
        user = session.get(BotUser, bot_user_id)
        if not user:
            return {}
        # 優先從 Person 讀取
        if user.person_id:
            person = session.get(Person, user.person_id)
            if person:
                try:
                    return json.loads(person.extra_json or "{}")
                except (json.JSONDecodeError, TypeError):
                    pass
        # fallback: 從 BotUser 自己讀（舊資料）
        try:
            return json.loads(user.extra_json or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}


def set_user_extra(bot_user_id: int, data: dict) -> bool:
    """整筆覆寫 extra_json（寫入 Person 表）"""
    from app.models.core import Person
    with Session(engine) as session:
        user = session.get(BotUser, bot_user_id)
        if not user:
            return False
        data_str = json.dumps(data, ensure_ascii=False)
        # 寫入 Person
        if user.person_id:
            person = session.get(Person, user.person_id)
            if person:
                person.extra_json = data_str
        # 同時寫 BotUser（過渡期相容）
        user.extra_json = data_str
        session.commit()
        return True


def merge_user_extra(bot_user_id: int, updates: dict, mode: str = "union") -> dict:
    """
    合併更新 extra_json

    mode:
      - "union": 聯集 — 新 key 加入，已有 key 覆蓋值（預設）
      - "intersect": 交集 — 只更新已存在的 key
      - "deep": 深度合併 — 遇到 dict 值遞迴合併

    Returns: 合併後的完整 dict
    """
    current = get_user_extra(bot_user_id)

    if mode == "intersect":
        # 只更新已存在的 key
        merged = {**current}
        for k, v in updates.items():
            if k in current:
                merged[k] = v
    elif mode == "deep":
        # 深度合併
        merged = _deep_merge(current, updates)
    else:
        # union: 直接覆蓋
        merged = {**current, **updates}

    set_user_extra(bot_user_id, merged)
    return merged


def delete_user_extra_keys(bot_user_id: int, keys: list[str]) -> dict:
    """刪除 extra_json 中的指定 key"""
    current = get_user_extra(bot_user_id)
    for k in keys:
        current.pop(k, None)
    set_user_extra(bot_user_id, current)
    return current


def _deep_merge(base: dict, override: dict) -> dict:
    """遞迴合併兩個 dict"""
    result = {**base}
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result
