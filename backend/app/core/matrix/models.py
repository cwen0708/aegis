"""Matrix 房間/訊息資料模型（matrix.org 協議）。

⚠️ 命名澄清：此處 `Matrix` 指 matrix.org 即時通訊協議，
並非 `app/core/sync_matrix.py`（後者為欄位級同步規則引擎，與本模組無關）。

本檔只提供不可變的 Pydantic 資料模型，供 client 介面與 NoOp 實作使用。
不引入 matrix-nio 或其他第三方套件。
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RoomKind(str, Enum):
    """房間類型（對應 Aegis 協作情境）。"""

    WORKER = "worker"
    """3-party 房：leader + admin + 單一 worker。"""

    TEAM_WORKER = "team_worker"
    """團隊房（含管理）：leader + admin + 多位 worker。"""

    TEAM = "team"
    """純團隊房：僅多位 worker，無 admin 監管。"""


class MatrixRoom(BaseModel):
    """一個 Matrix 房間的資料快照。

    - `meeting_ref` 對應現有 `ConversationRoom.meeting_id`，用來把 Matrix 房
      和 Aegis 會議 room 綁在一起（shadow mode 雙寫時需要）。
    - `members` 為成員 slug 列表；允許空 list，代表剛建立尚未 invite。
    - 本模型不可變：透過 `model_config` 凍結欄位，任何「修改」都要回傳新物件。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    room_id: str = Field(..., min_length=1, description="Matrix 房間 ID（!xxx:server 格式）")
    kind: RoomKind
    meeting_ref: str = Field(..., min_length=1, description="對應 ConversationRoom.meeting_id")
    members: list[str] = Field(default_factory=list, description="成員 slug 列表")
    topic: str = ""


class MatrixMessage(BaseModel):
    """單則 Matrix 訊息快照（不可變）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    room_id: str = Field(..., min_length=1)
    sender: str = Field(..., min_length=1, description="發送者 slug 或 Matrix user_id")
    body: str = ""
    msgtype: Literal["m.text", "m.notice"] = "m.text"
