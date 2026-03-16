"""
命令解析器 — 將訊息文字解析為結構化命令
"""
import re
from dataclasses import dataclass
from typing import Optional
from enum import Enum


class CommandType(str, Enum):
    """命令類型"""
    # 卡片操作
    CARD_CREATE = "card.create"
    CARD_LIST = "card.list"
    CARD_VIEW = "card.view"

    # 任務操作
    TASK_RUN = "task.run"
    TASK_STOP = "task.stop"
    TASK_STATUS = "task.status"

    # 綁定操作
    BIND = "bind"
    UNBIND = "unbind"
    BIND_LIST = "bind.list"

    # P2: 用戶驗證
    VERIFY = "verify"
    INVITE = "invite"

    # P2: 用戶管理
    ME = "me"
    USER_LIST = "user.list"
    USER_INFO = "user.info"
    USER_GRANT = "user.grant"
    USER_BAN = "user.ban"
    USER_ASSIGN = "user.assign"

    # P2: 角色切換
    SWITCH = "switch"

    # 個人資料
    PROFILE = "profile"

    # 系統操作
    STATUS = "status"
    HELP = "help"


@dataclass
class ParsedCommand:
    """解析後的命令"""
    cmd_type: CommandType
    args: list[str]
    raw: str


# 命令模式定義
# (正則表達式, 命令類型)
COMMAND_PATTERNS: list[tuple[str, CommandType]] = [
    # 卡片命令
    (r"^/card\s+create\s+(.+)$", CommandType.CARD_CREATE),
    (r"^/card\s+list$", CommandType.CARD_LIST),
    (r"^/cards?$", CommandType.CARD_LIST),  # /card 或 /cards
    (r"^/card\s+(\d+)$", CommandType.CARD_VIEW),

    # 任務命令
    (r"^/task\s+run\s+(\d+)$", CommandType.TASK_RUN),
    (r"^/run\s+(\d+)$", CommandType.TASK_RUN),  # 簡寫
    (r"^/task\s+stop\s+(\d+)$", CommandType.TASK_STOP),
    (r"^/stop\s+(\d+)$", CommandType.TASK_STOP),  # 簡寫
    (r"^/task\s+status\s+(\d+)$", CommandType.TASK_STATUS),
    (r"^/task\s+(\d+)$", CommandType.TASK_STATUS),  # /task 123

    # 綁定命令
    (r"^/bind$", CommandType.BIND),
    (r"^/bind\s+(\w+)\s+(\d+)$", CommandType.BIND),  # /bind project 123
    (r"^/unbind$", CommandType.UNBIND),
    (r"^/unbind\s+(\d+)$", CommandType.UNBIND),      # /unbind <binding_id>
    (r"^/bindings?$", CommandType.BIND_LIST),

    # P2: 用戶驗證
    (r"^/verify\s+(\S+)$", CommandType.VERIFY),      # /verify ABC123
    (r"^/invite$", CommandType.INVITE),              # /invite (產生預設邀請碼)
    (r"^/invite\s+(.+)$", CommandType.INVITE),       # /invite 1 王小華 "描述" 1,2

    # P2: 用戶管理
    (r"^/me$", CommandType.ME),
    (r"^/user\s+list$", CommandType.USER_LIST),
    (r"^/users?$", CommandType.USER_LIST),           # /user 或 /users
    (r"^/user\s+info\s+(\d+)$", CommandType.USER_INFO),
    (r"^/user\s+(\d+)$", CommandType.USER_INFO),     # /user 123
    (r"^/user\s+grant\s+(\d+)\s+(\d+)$", CommandType.USER_GRANT),  # /user grant 1 2
    (r"^/grant\s+(\d+)\s+(\d+)$", CommandType.USER_GRANT),         # /grant 1 2
    (r"^/user\s+ban\s+(\d+)$", CommandType.USER_BAN),
    (r"^/ban\s+(\d+)$", CommandType.USER_BAN),       # /ban 123
    (r"^/user\s+assign\s+(\d+)\s+(\d+)$", CommandType.USER_ASSIGN),  # /user assign 1 2
    (r"^/assign\s+(\d+)\s+(\d+)$", CommandType.USER_ASSIGN),         # /assign 1 2

    # P2: 角色切換
    (r"^/switch\s+(\d+)$", CommandType.SWITCH),      # /switch 2 (member_id)
    (r"^/switch\s+(.+)$", CommandType.SWITCH),       # /switch 小美 (member name)

    # 個人資料
    (r"^/profile$", CommandType.PROFILE),                          # /profile (查看)
    (r"^/profile\s+set\s+(\S+)\s+(.+)$", CommandType.PROFILE),   # /profile set ad_user john
    (r"^/profile\s+del\s+(\S+)$", CommandType.PROFILE),           # /profile del ad_user
    (r"^/profile\s+clear$", CommandType.PROFILE),                  # /profile clear

    # 系統命令
    (r"^/status$", CommandType.STATUS),
    (r"^/(help|start)$", CommandType.HELP),
]


def parse_command(text: str) -> Optional[ParsedCommand]:
    """
    解析命令文字

    Args:
        text: 訊息文字

    Returns:
        解析後的命令，或 None（非命令訊息）

    Examples:
        >>> parse_command("/card create 新功能")
        ParsedCommand(cmd_type=CommandType.CARD_CREATE, args=["新功能"], raw="/card create 新功能")

        >>> parse_command("/status")
        ParsedCommand(cmd_type=CommandType.STATUS, args=[], raw="/status")

        >>> parse_command("hello")
        None
    """
    text = text.strip()

    # 非命令訊息
    if not text.startswith("/"):
        return None

    # 嘗試匹配所有模式
    for pattern, cmd_type in COMMAND_PATTERNS:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            return ParsedCommand(
                cmd_type=cmd_type,
                args=list(match.groups()),
                raw=text,
            )

    return None


def get_help_text(level: int = 0) -> str:
    """
    取得說明文字（根據權限等級）

    Args:
        level: 用戶權限等級 (0-3)
    """
    lines = ["*Aegis Bot 命令*", ""]

    # L0: 所有人可用
    lines.append("🔑 *驗證*")
    lines.append("/verify <邀請碼> — 驗證身份")
    lines.append("")

    if level >= 1:
        lines.append("👤 *個人*")
        lines.append("/me — 查看我的資訊")
        lines.append("/profile — 查看/設定額外資料")
        lines.append("/profile set <key> <value> — 設定欄位")
        lines.append("/profile del <key> — 刪除欄位")
        lines.append("")

        lines.append("📋 *卡片*")
        lines.append("/card list — 列出最近卡片")
        lines.append("/card <ID> — 查看卡片詳情")
        lines.append("")

        lines.append("🔗 *綁定*")
        lines.append("/bind — 綁定此頻道接收通知")
        lines.append("/unbind — 解除此頻道綁定")
        lines.append("/bindings — 查看綁定列表")
        lines.append("")

    if level >= 2:
        lines.append("⚡ *任務*")
        lines.append("/run <ID> — 執行卡片任務")
        lines.append("/stop <ID> — 中止任務")
        lines.append("/card create <標題> — 建立新卡片")
        lines.append("/switch <角色> — 切換 AI 角色")
        lines.append("")

    if level >= 3:
        lines.append("👑 *管理員*")
        lines.append("/invite [等級] [備註] — 產生邀請碼")
        lines.append("/users — 列出所有用戶")
        lines.append("/user <ID> — 查看用戶詳情")
        lines.append("/grant <用戶ID> <等級> — 設定權限")
        lines.append("/ban <用戶ID> — 停用用戶")
        lines.append("/assign <用戶ID> <角色ID> — 指派角色")
        lines.append("")

    lines.append("🔧 *系統*")
    lines.append("/status — 系統狀態")
    lines.append("/help — 顯示此說明")

    return "\n".join(lines)
