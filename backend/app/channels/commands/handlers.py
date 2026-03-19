"""
命令處理器 — 執行業務邏輯並產生回應
"""
from typing import Optional
from sqlmodel import Session, select
from .parser import ParsedCommand, CommandType, get_help_text
from ..types import InboundMessage
from ..bot_user import (
    get_or_create_bot_user, check_permission, verify_invite_code,
    create_invite_code, get_user_info, list_users, set_user_level,
    ban_user, assign_member, switch_member, get_available_members,
    get_user_extra, merge_user_extra, delete_user_extra_keys, set_user_extra,
    # P2: 專案權限檢查
    get_user_projects, can_user_view_project, can_user_create_card, can_user_run_task,
)
from app.database import engine
from app.models.core import Card, StageList, Project, ChannelBinding, BotUser, Member
import logging

logger = logging.getLogger(__name__)


async def handle_command(cmd: ParsedCommand, msg: InboundMessage, bot_user: Optional[BotUser] = None) -> Optional[str]:
    """
    處理命令並返回回應文字

    Args:
        cmd: 解析後的命令
        msg: 原始訊息（用於取得用戶資訊）
        bot_user: BotUser 實例（由 Router 傳入）

    Returns:
        回應文字，或 None（不需要回應）
    """
    # 取得或建立 BotUser
    if not bot_user:
        bot_user = get_or_create_bot_user(msg.platform, msg.user_id, msg.user_name)

    # 檢查用戶是否被停用
    if not bot_user.is_active:
        return "⛔ 您的帳號已被停用"

    # 命令到處理器的對應
    handler_map = {
        # 卡片操作
        CommandType.CARD_CREATE: _handle_card_create,
        CommandType.CARD_LIST: _handle_card_list,
        CommandType.CARD_VIEW: _handle_card_view,
        # 任務操作
        CommandType.TASK_RUN: _handle_task_run,
        CommandType.TASK_STOP: _handle_task_stop,
        CommandType.TASK_STATUS: _handle_task_status,
        # 綁定操作
        CommandType.BIND: _handle_bind,
        CommandType.UNBIND: _handle_unbind,
        CommandType.BIND_LIST: _handle_bind_list,
        # P2: 驗證
        CommandType.VERIFY: _handle_verify,
        CommandType.INVITE: _handle_invite,
        # P2: 用戶管理
        CommandType.ME: _handle_me,
        CommandType.USER_LIST: _handle_user_list,
        CommandType.USER_INFO: _handle_user_info,
        CommandType.USER_GRANT: _handle_user_grant,
        CommandType.USER_BAN: _handle_user_ban,
        CommandType.USER_ASSIGN: _handle_user_assign,
        # P2: 角色切換
        CommandType.SWITCH: _handle_switch,
        # 個人資料
        CommandType.PROFILE: _handle_profile,
        # 系統操作
        CommandType.STATUS: _handle_status,
        CommandType.HELP: _handle_help,
    }

    handler = handler_map.get(cmd.cmd_type)
    if not handler:
        return "❓ 未知命令，輸入 /help 查看說明"

    # 從命令類型取得命令名稱（用於權限檢查）
    cmd_name = cmd.cmd_type.value.split(".")[0]  # card.create -> card

    # 權限檢查
    if not check_permission(bot_user, cmd_name):
        level_names = {0: "未驗證", 1: "訪客", 2: "成員", 3: "管理員"}
        return (
            f"🔒 權限不足\n"
            f"您的身份：{level_names.get(bot_user.level, '未知')}\n"
            f"請使用 /verify <邀請碼> 驗證身份"
        )

    try:
        return await handler(cmd, msg, bot_user)
    except Exception as e:
        logger.error(f"Command handler error: {e}", exc_info=True)
        return f"❌ 執行失敗: {str(e)[:100]}"


# ===== 卡片命令 =====

async def _handle_card_create(cmd: ParsedCommand, msg: InboundMessage, bot_user: BotUser) -> str:
    """建立新卡片"""
    title = cmd.args[0] if cmd.args else "新卡片"

    # 清理輸入
    title = title.strip()[:200]
    if not title:
        return "❌ 標題不可為空"

    with Session(engine) as session:
        # 找用戶可建卡的專案（優先用預設專案）
        user_projects = get_user_projects(bot_user.id)
        project = None

        # 管理員可以建任何專案
        if bot_user.level >= 3:
            project = session.exec(
                select(Project).where(Project.is_system == False)
            ).first()
        else:
            # 找用戶可建卡的專案
            for p in user_projects:
                if can_user_create_card(bot_user.id, p.id):
                    project = p
                    break

            if not project:
                return "🔒 您沒有權限在任何專案建立卡片"

        backlog = session.exec(
            select(StageList).where(
                StageList.project_id == project.id,
                StageList.name == "Backlog"
            )
        ).first()

        if not backlog:
            return "❌ 找不到 Backlog 列表"

        card = Card(
            list_id=backlog.id,
            title=title,
            description=f"由 {msg.platform} 用戶 {msg.user_name or msg.user_id} 建立",
            status="idle",
        )
        session.add(card)
        session.commit()
        session.refresh(card)

        return (
            f"✅ 卡片 #{card.id} 已建立\n"
            f"📋 {title}\n"
            f"📁 {project.name} / Backlog"
        )


async def _handle_card_list(cmd: ParsedCommand, msg: InboundMessage, bot_user: BotUser) -> str:
    """列出最近卡片（只顯示用戶有權限的專案）"""
    with Session(engine) as session:
        # 管理員看所有卡片
        if bot_user.level >= 3:
            cards = session.exec(
                select(Card).order_by(Card.updated_at.desc()).limit(10)
            ).all()
        else:
            # 只顯示用戶可存取的專案的卡片
            user_projects = get_user_projects(bot_user.id)
            if not user_projects:
                return "📭 您沒有可存取的專案"

            project_ids = [p.id for p in user_projects]

            # 找出這些專案的所有 StageList
            stage_lists = session.exec(
                select(StageList).where(StageList.project_id.in_(project_ids))
            ).all()
            list_ids = [s.id for s in stage_lists]

            if not list_ids:
                return "📭 目前沒有卡片"

            cards = session.exec(
                select(Card)
                .where(Card.list_id.in_(list_ids))
                .order_by(Card.updated_at.desc())
                .limit(10)
            ).all()

        if not cards:
            return "📭 目前沒有卡片"

        lines = ["📋 *最近卡片*\n"]
        status_icons = {
            "idle": "⚪",
            "pending": "🟡",
            "running": "🔵",
            "done": "✅",
            "failed": "❌",
        }

        for c in cards:
            icon = status_icons.get(c.status, "⚪")
            lines.append(f"{icon} #{c.id} {c.title[:30]}")

        return "\n".join(lines)


async def _handle_card_view(cmd: ParsedCommand, msg: InboundMessage, bot_user: BotUser) -> str:
    """查看卡片詳情"""
    card_id = int(cmd.args[0])

    with Session(engine) as session:
        card = session.get(Card, card_id)
        if not card:
            return f"❌ 找不到卡片 #{card_id}"

        # 取得卡片所屬專案
        stage_list = session.get(StageList, card.list_id)
        if stage_list:
            # 專案權限檢查（管理員跳過）
            if bot_user.level < 3 and not can_user_view_project(bot_user.id, stage_list.project_id):
                return f"🔒 您沒有權限查看此專案的卡片"

        status_text = {
            "idle": "閒置",
            "pending": "等待中",
            "running": "執行中",
            "done": "完成",
            "failed": "失敗",
        }.get(card.status, card.status)

        return (
            f"📋 *卡片 #{card.id}*\n\n"
            f"*標題*: {card.title}\n"
            f"*狀態*: {status_text}\n"
            f"*描述*: {card.description or '(無)'}\n\n"
            f"執行: /run {card.id}"
        )


# ===== 任務命令 =====

async def _handle_task_run(cmd: ParsedCommand, msg: InboundMessage, bot_user: BotUser) -> str:
    """執行任務"""
    card_id = int(cmd.args[0])

    with Session(engine) as session:
        card = session.get(Card, card_id)
        if not card:
            return f"❌ 找不到卡片 #{card_id}"

        # 取得卡片所屬專案並檢查權限
        stage_list = session.get(StageList, card.list_id)
        if stage_list and bot_user.level < 3:
            if not can_user_run_task(bot_user.id, stage_list.project_id):
                return f"🔒 您沒有權限執行此專案的任務"

        if card.status == "running":
            return f"⚠️ 卡片 #{card_id} 已在執行中"

        # 更新狀態為 pending
        card.status = "pending"
        session.add(card)
        session.commit()

    # TODO: 觸發實際任務執行（透過現有 runner 機制）
    return f"🚀 卡片 #{card_id} 已加入執行佇列"


async def _handle_task_stop(cmd: ParsedCommand, msg: InboundMessage, bot_user: BotUser) -> str:
    """中止任務"""
    card_id = int(cmd.args[0])

    with Session(engine) as session:
        card = session.get(Card, card_id)
        if not card:
            return f"❌ 找不到卡片 #{card_id}"

        if card.status != "running":
            return f"⚠️ 卡片 #{card_id} 未在執行中"

    # TODO: 觸發實際任務中止
    return f"🛑 已請求中止卡片 #{card_id}"


async def _handle_task_status(cmd: ParsedCommand, msg: InboundMessage, bot_user: BotUser) -> str:
    """查看任務狀態"""
    card_id = int(cmd.args[0])

    with Session(engine) as session:
        card = session.get(Card, card_id)
        if not card:
            return f"❌ 找不到卡片 #{card_id}"

        status_emoji = {
            "idle": "⚪",
            "pending": "🟡",
            "running": "🔵",
            "done": "✅",
            "failed": "❌",
        }

        return (
            f"{status_emoji.get(card.status, '❓')} 卡片 #{card.id}\n"
            f"*{card.title}*\n"
            f"狀態: {card.status}"
        )


# ===== 系統命令 =====

async def _handle_status(cmd: ParsedCommand, msg: InboundMessage, bot_user: BotUser) -> str:
    """系統狀態"""
    import psutil

    cpu = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()

    with Session(engine) as session:
        running_count = session.exec(
            select(Card).where(Card.status == "running")
        ).all()
        pending_count = session.exec(
            select(Card).where(Card.status == "pending")
        ).all()

    return (
        f"📊 *Aegis 系統狀態*\n\n"
        f"🖥️ CPU: {cpu}%\n"
        f"💾 RAM: {mem.percent}%\n"
        f"🔵 執行中: {len(running_count)}\n"
        f"🟡 等待中: {len(pending_count)}"
    )


async def _handle_help(cmd: ParsedCommand, msg: InboundMessage, bot_user: BotUser) -> str:
    """顯示說明"""
    return get_help_text(bot_user.level)


# ===== 綁定命令 =====

async def _handle_bind(cmd: ParsedCommand, msg: InboundMessage, bot_user: BotUser) -> str:
    """綁定頻道接收通知"""
    with Session(engine) as session:
        # 檢查是否已綁定
        existing = session.exec(
            select(ChannelBinding).where(
                ChannelBinding.platform == msg.platform,
                ChannelBinding.chat_id == msg.chat_id,
            )
        ).first()

        if existing:
            return (
                f"⚠️ 此頻道已綁定\n"
                f"類型: {existing.entity_type}\n"
                f"使用 /unbind 可解除綁定"
            )

        # 解析參數
        entity_type = "global"
        entity_id = None

        if len(cmd.args) >= 2:
            entity_type = cmd.args[0]  # project, member
            entity_id = int(cmd.args[1])

            # 驗證實體存在
            if entity_type == "project":
                project = session.get(Project, entity_id)
                if not project:
                    return f"❌ 找不到專案 #{entity_id}"

        # 建立綁定
        binding = ChannelBinding(
            platform=msg.platform,
            user_id=msg.user_id,
            chat_id=msg.chat_id,
            user_name=msg.user_name,
            entity_type=entity_type,
            entity_id=entity_id,
            bot_user_id=bot_user.id,  # P2: 關聯 BotUser
        )
        session.add(binding)
        session.commit()
        session.refresh(binding)

        scope = f"專案 #{entity_id}" if entity_type == "project" else "全域"
        return (
            f"✅ 綁定成功！\n"
            f"🔗 ID: {binding.id}\n"
            f"📍 範圍: {scope}\n"
            f"📢 將接收任務完成通知"
        )


async def _handle_unbind(cmd: ParsedCommand, msg: InboundMessage, bot_user: BotUser) -> str:
    """解除綁定"""
    with Session(engine) as session:
        if cmd.args:
            # 指定 binding ID
            binding_id = int(cmd.args[0])
            binding = session.get(ChannelBinding, binding_id)
            if not binding:
                return f"❌ 找不到綁定 #{binding_id}"
            if binding.chat_id != msg.chat_id:
                return "❌ 無權解除此綁定"
        else:
            # 解除此頻道的綁定
            binding = session.exec(
                select(ChannelBinding).where(
                    ChannelBinding.platform == msg.platform,
                    ChannelBinding.chat_id == msg.chat_id,
                )
            ).first()

            if not binding:
                return "⚠️ 此頻道尚未綁定"

        session.delete(binding)
        session.commit()

        return f"✅ 已解除綁定 #{binding.id}"


async def _handle_bind_list(cmd: ParsedCommand, msg: InboundMessage, bot_user: BotUser) -> str:
    """列出綁定"""
    with Session(engine) as session:
        bindings = session.exec(
            select(ChannelBinding).where(
                ChannelBinding.platform == msg.platform,
                ChannelBinding.user_id == msg.user_id,
            )
        ).all()

        if not bindings:
            return "📭 尚無綁定\n使用 /bind 開始接收通知"

        lines = ["🔗 *您的綁定*\n"]
        for b in bindings:
            scope = f"專案#{b.entity_id}" if b.entity_type == "project" else "全域"
            notify = []
            if b.notify_on_complete:
                notify.append("完成")
            if b.notify_on_fail:
                notify.append("失敗")
            lines.append(f"#{b.id} [{scope}] → {', '.join(notify)}")

        return "\n".join(lines)


# ===== P2: 用戶驗證命令 =====

async def _handle_verify(cmd: ParsedCommand, msg: InboundMessage, bot_user: BotUser) -> str:
    """驗證邀請碼"""
    if not cmd.args:
        return "用法: /verify <邀請碼>"

    code = cmd.args[0]
    success, message = verify_invite_code(bot_user, code)

    if success:
        return f"✅ {message}"
    else:
        return f"❌ {message}"


async def _handle_invite(cmd: ParsedCommand, msg: InboundMessage, bot_user: BotUser) -> str:
    """
    產生邀請碼

    語法：
        /invite                              → 訪客，無專案
        /invite 2                            → 成員，無專案
        /invite 1 王小華                     → 訪客，有名稱
        /invite 1 王小華 "案場業主" 1,2      → 完整設定
        /invite 1 王小華 "案場業主" 1,2 成員  → 使用模板
    """
    import shlex

    # 預設值
    target_level = 1
    user_display_name = ""
    user_description = ""
    allowed_projects = None
    # 預設權限（訪客模板）
    can_view = True
    can_create = False
    can_run = False
    can_sensitive = False

    # 權限模板
    templates = {
        "訪客": (True, False, False, False, "外部人員，僅可查看專案進度"),
        "成員": (True, True, True, False, "內部成員，可查看、建立卡片和執行任務"),
        "管理員": (True, True, True, True, "專案管理員，擁有完整權限"),
    }

    # 用 shlex 解析參數（正確處理引號）
    args = []
    if cmd.args and cmd.args[0]:
        try:
            args = shlex.split(cmd.args[0])
        except ValueError as e:
            return f"❌ 參數格式錯誤: {e}\n用法: /invite [等級] [名稱] [\"描述\"] [專案IDs] [模板]"

    # arg[0]: 等級
    if len(args) >= 1:
        try:
            target_level = int(args[0])
            if target_level < 1 or target_level > 3:
                return "❌ 等級必須是 1-3"
        except ValueError:
            return "❌ 等級必須是數字\n用法: /invite [等級] [名稱] [\"描述\"] [專案IDs] [模板]"

    # arg[1]: 名稱
    if len(args) >= 2:
        user_display_name = args[1]

    # arg[2]: 描述
    if len(args) >= 3:
        user_description = args[2]

    # arg[3]: 專案 IDs（逗號分隔）
    if len(args) >= 4:
        try:
            allowed_projects = [int(x.strip()) for x in args[3].split(",")]
        except ValueError:
            return "❌ 專案 ID 格式錯誤（用逗號分隔數字，如: 1,2,3）"

    # arg[4]: 模板（覆蓋權限和描述）
    if len(args) >= 5:
        template_name = args[4]
        if template_name in templates:
            can_view, can_create, can_run, can_sensitive, default_desc = templates[template_name]
            if not user_description:
                user_description = default_desc
        else:
            return f"❌ 未知模板: {template_name}\n可用: 訪客, 成員, 管理員"

    # 根據等級自動套用模板（如果沒指定）
    if len(args) < 5:
        if target_level == 2:
            can_view, can_create, can_run, can_sensitive, _ = templates["成員"]
        elif target_level == 3:
            can_view, can_create, can_run, can_sensitive, _ = templates["管理員"]

    code = create_invite_code(
        created_by=bot_user.id,
        target_level=target_level,
        allowed_projects=allowed_projects,
        user_display_name=user_display_name,
        user_description=user_description,
        default_can_view=can_view,
        default_can_create_card=can_create,
        default_can_run_task=can_run,
        default_can_access_sensitive=can_sensitive,
    )

    level_names = {1: "訪客", 2: "成員", 3: "管理員"}

    lines = [
        f"🎟️ 邀請碼已產生\n",
        f"*{code}*\n",
        f"權限等級: {level_names.get(target_level, '未知')}",
    ]

    if user_display_name:
        lines.append(f"用戶名稱: {user_display_name}")
    if user_description:
        lines.append(f"身份描述: {user_description[:50]}{'...' if len(user_description) > 50 else ''}")
    if allowed_projects:
        lines.append(f"可存取專案: {', '.join(map(str, allowed_projects))}")

    lines.append(f"\n有效期: 7 天 | 使用次數: 1 次")

    return "\n".join(lines)


# ===== P2: 用戶管理命令 =====

async def _handle_me(cmd: ParsedCommand, msg: InboundMessage, bot_user: BotUser) -> str:
    """查看自己的資訊"""
    info = get_user_info(bot_user)

    lines = [
        f"👤 *{info['username']}*",
        f"",
        f"🔑 身份: {info['level_name']}",
        f"📅 加入: {info['created_at'][:10] if info['created_at'] else '未知'}",
    ]

    if info['default_member']:
        lines.append(f"🤖 AI 角色: {info['default_member']['name']}")

    if info['members']:
        lines.append(f"")
        lines.append(f"可切換角色:")
        for m in info['members']:
            marker = "✓" if m['is_default'] else " "
            lines.append(f"  {marker} {m['name']} (ID: {m['id']})")

    return "\n".join(lines)


async def _handle_user_list(cmd: ParsedCommand, msg: InboundMessage, bot_user: BotUser) -> str:
    """列出所有用戶"""
    users = list_users(limit=20)

    if not users:
        return "📭 目前沒有用戶"

    lines = ["👥 *用戶列表*\n"]
    for u in users:
        status = "🟢" if u['is_active'] else "🔴"
        lines.append(f"{status} #{u['id']} {u['username']} [{u['level_name']}]")

    return "\n".join(lines)


async def _handle_user_info(cmd: ParsedCommand, msg: InboundMessage, bot_user: BotUser) -> str:
    """查看用戶詳情"""
    if not cmd.args:
        return "用法: /user <ID>"

    try:
        user_id = int(cmd.args[0])
    except ValueError:
        return "❌ ID 必須是數字"

    with Session(engine) as session:
        target = session.get(BotUser, user_id)
        if not target:
            return f"❌ 找不到用戶 #{user_id}"

        info = get_user_info(target)

    lines = [
        f"👤 *用戶 #{info['id']}*",
        f"",
        f"名稱: {info['username']}",
        f"平台: {info['platform']}",
        f"身份: {info['level_name']}",
        f"狀態: {'啟用' if info['is_active'] else '停用'}",
        f"加入: {info['created_at'][:10] if info['created_at'] else '未知'}",
        f"最後活躍: {info['last_active_at'][:10] if info['last_active_at'] else '未知'}",
    ]

    if info['default_member']:
        lines.append(f"AI 角色: {info['default_member']['name']}")

    return "\n".join(lines)


async def _handle_user_grant(cmd: ParsedCommand, msg: InboundMessage, bot_user: BotUser) -> str:
    """設定用戶權限"""
    if len(cmd.args) < 2:
        return "用法: /grant <用戶ID> <等級(0-3)>"

    try:
        user_id = int(cmd.args[0])
        level = int(cmd.args[1])
    except ValueError:
        return "❌ ID 和等級必須是數字"

    if level < 0 or level > 3:
        return "❌ 等級必須是 0-3"

    if set_user_level(user_id, level):
        level_names = {0: "未驗證", 1: "訪客", 2: "成員", 3: "管理員"}
        return f"✅ 已將用戶 #{user_id} 設為 {level_names.get(level, '未知')}"
    else:
        return f"❌ 找不到用戶 #{user_id}"


async def _handle_user_ban(cmd: ParsedCommand, msg: InboundMessage, bot_user: BotUser) -> str:
    """停用用戶"""
    if not cmd.args:
        return "用法: /ban <用戶ID>"

    try:
        user_id = int(cmd.args[0])
    except ValueError:
        return "❌ ID 必須是數字"

    if user_id == bot_user.id:
        return "❌ 不能停用自己"

    if ban_user(user_id):
        return f"⛔ 已停用用戶 #{user_id}"
    else:
        return f"❌ 找不到用戶 #{user_id}"


async def _handle_user_assign(cmd: ParsedCommand, msg: InboundMessage, bot_user: BotUser) -> str:
    """指派 Member 給用戶"""
    if len(cmd.args) < 2:
        return "用法: /assign <用戶ID> <角色ID>"

    try:
        user_id = int(cmd.args[0])
        member_id = int(cmd.args[1])
    except ValueError:
        return "❌ ID 必須是數字"

    with Session(engine) as session:
        member = session.get(Member, member_id)
        if not member:
            return f"❌ 找不到角色 #{member_id}"

    if assign_member(user_id, member_id):
        return f"✅ 已將角色 {member.name} 指派給用戶 #{user_id}"
    else:
        return f"❌ 找不到用戶 #{user_id}"


# ===== P2: 角色切換命令 =====

async def _handle_switch(cmd: ParsedCommand, msg: InboundMessage, bot_user: BotUser) -> str:
    """切換 AI 角色"""
    if not cmd.args:
        # 列出可用角色
        members = get_available_members(bot_user)
        if not members:
            return "📭 您沒有可用的 AI 角色"

        lines = ["🤖 *可切換角色*\n"]
        for m in members:
            marker = "✓" if m['is_default'] else " "
            lines.append(f"{marker} {m['avatar']} {m['name']} → /switch {m['id']}")

        return "\n".join(lines)

    # 嘗試切換
    arg = cmd.args[0]

    # 先嘗試當作 ID
    try:
        member_id = int(arg)
    except ValueError:
        # 當作名稱搜尋
        with Session(engine) as session:
            member = session.exec(
                select(Member).where(Member.name.contains(arg))
            ).first()
            if not member:
                return f"❌ 找不到角色: {arg}"
            member_id = member.id

    success, message = switch_member(bot_user, member_id)
    if success:
        return f"✅ {message}"
    else:
        return f"❌ {message}"


# ===== 個人資料命令 =====

async def _handle_profile(cmd: ParsedCommand, msg: InboundMessage, bot_user: BotUser) -> str:
    """回覆個人資料設定頁面連結"""
    from app.api.profile_page import resolve_domain_for_user, get_profile_url

    domain = resolve_domain_for_user(bot_user.id)
    url = get_profile_url(bot_user.id, domain)

    return (
        "📋 *個人資料設定*\n\n"
        f"👉 [點此開啟設定頁面]({url})\n\n"
        "可設定：\n"
        "• NAS / AD 帳號密碼\n"
        "• 網頁登入帳號密碼\n"
        "• 暱稱及其他資料\n\n"
        "連結 30 分鐘內有效。"
    )
