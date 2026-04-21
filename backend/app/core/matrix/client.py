"""Matrix client 介面與 NoOp 實作（matrix.org 協議）。

⚠️ 此 `Matrix` 指 matrix.org 協議，非 `app/core/sync_matrix.py` 的欄位同步規則。

Phase 1 的 Shadow Mode 預設注入 `NoopMatrixClient`，完全不做 I/O，
讓 `ConversationRoom` 的雙寫路徑可先接線而不影響現有流程。真實實作
（matrix-nio）留在後續步驟引入。

介面設計原則：
- 純不變性：client 方法**不 mutate 輸入**的 `MatrixRoom` / `MatrixMessage`。
- 純回傳字串：成功回傳 event_id / room_id，shadow 模式回空字串表示未實際送出。
- 不拋例外：NoOp 實作保證「即使下游尚未接線也不會打斷 caller」。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.matrix.models import MatrixMessage, MatrixRoom


@runtime_checkable
class MatrixClient(Protocol):
    """Matrix client 最小介面（Phase 1 只需 create_room / send_message）。"""

    def create_room(self, room: MatrixRoom) -> str:
        """建立房間，回傳 room_id；不 mutate `room`。

        Shadow / NoOp 實作回空字串表示「未實際建立」。
        """
        ...

    def send_message(self, message: MatrixMessage) -> str:
        """送訊息，回傳 event_id；不 mutate `message`。

        Shadow / NoOp 實作回空字串表示「未實際送出」。
        """
        ...


class NoopMatrixClient:
    """Shadow mode 預設實作：所有方法回空字串、不做 I/O、不拋例外。

    用來讓 Phase 1 的雙寫路徑先接線，等 matrix-nio 客戶端準備好後再替換。
    """

    def create_room(self, room: MatrixRoom) -> str:
        # 僅讀取 room（純函式），回傳空 event_id
        _ = room.room_id
        return ""

    def send_message(self, message: MatrixMessage) -> str:
        _ = message.room_id
        return ""
