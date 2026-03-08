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


def get_help_text() -> str:
    """取得說明文字"""
    return """*Aegis Bot 命令*

📋 *卡片*
/card create <標題> — 建立新卡片
/card list — 列出最近卡片
/card <ID> — 查看卡片詳情

⚡ *任務*
/run <ID> — 執行卡片任務
/stop <ID> — 中止任務
/task <ID> — 查看任務狀態

🔗 *綁定*
/bind — 綁定此頻道接收通知
/bind project <ID> — 綁定特定專案
/unbind — 解除此頻道綁定
/bindings — 查看綁定列表

🔧 *系統*
/status — 系統狀態
/help — 顯示此說明"""
