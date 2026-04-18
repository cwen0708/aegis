"""Directive Protocol — AI → 前端指令類型系統

集中定義 directive type enum 與已知 type 的 payload schema，
提供純函式 validate_directive() 給 /internal/directive 端點驗證。

設計原則：
- 不變性：validate_directive 為純函式，無副作用
- 向後相容：未知 type 一律視為合法（讓既有非結構化 directive 仍可廣播）
- 漸進擴充：新增 type 不會破壞既有呼叫；新增 schema 只需在 _PAYLOAD_SCHEMAS 註冊
"""
from __future__ import annotations

from enum import StrEnum
from typing import Literal, Optional

from pydantic import BaseModel, ValidationError


class DirectiveType(StrEnum):
    """已知的 directive 類型（值即字串，便於 JSON 序列化）"""

    # 程式碼類
    UPDATE_CODE = "update_code"
    RUN_TASK = "run_task"
    OPEN_FILE = "open_file"
    SHOW_DIFF = "show_diff"

    # 互動類
    ASK_USER = "ask_user"
    NOTIFY = "notify"
    PROMPT = "prompt"
    CONFIRM = "confirm"

    # 任務類
    CARD_UPDATE = "card_update"
    CARD_COMMENT = "card_comment"
    CARD_MOVE = "card_move"

    # 檔案類
    UPLOAD_FILE = "upload_file"
    DOWNLOAD_FILE = "download_file"

    # UI 類
    NAVIGATE = "navigate"
    HIGHLIGHT = "highlight"


class UpdateCodePayload(BaseModel):
    """UPDATE_CODE：對指定檔案進行替換 / 追加 / patch"""

    file_path: str
    content: str
    mode: Literal["replace", "append", "patch"]


class RunTaskPayload(BaseModel):
    """RUN_TASK：在指定工作目錄執行命令；task_id 可選"""

    task_id: Optional[int] = None
    command: str
    working_dir: Optional[str] = None


class AskUserPayload(BaseModel):
    """ASK_USER：向使用者提問；choices/timeout 可選"""

    question: str
    choices: Optional[list[str]] = None
    timeout_sec: Optional[int] = None


_PAYLOAD_SCHEMAS: dict[str, type[BaseModel]] = {
    DirectiveType.UPDATE_CODE.value: UpdateCodePayload,
    DirectiveType.RUN_TASK.value: RunTaskPayload,
    DirectiveType.ASK_USER.value: AskUserPayload,
}


def validate_directive(action: str, params: dict) -> tuple[bool, Optional[str]]:
    """驗證 directive action + params 是否合法。

    回傳：
        (True, None)  — 已知 type 且 payload 合法，或未知 type（向後相容）
        (False, msg) — 已知 type 但 payload 驗證失敗，msg 為人類可讀錯誤訊息
    """
    schema = _PAYLOAD_SCHEMAS.get(action)
    if schema is None:
        # 未知 type：向後相容，允許廣播
        return True, None

    try:
        schema.model_validate(params)
    except ValidationError as e:
        return False, f"Invalid payload for directive '{action}': {e.errors()}"
    return True, None
