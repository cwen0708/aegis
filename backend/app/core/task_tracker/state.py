"""Task Tracker Event Buffer — 純資料結構與純函式（P2-MA-14 step 1）。

參考 CoPaw `app/runner/task_tracker.py` 的 `_RunState`（task / queues / buffer
三件組），但機制抽出來後以 Aegis 風格重寫：

- 全部 immutable（``dataclass(frozen=True)`` + ``tuple`` 容器）
- 所有操作回傳新 ``RunState``，不 mutate 入參
- 與傳輸協定解耦：本檔不引入 asyncio / WebSocket / SSE
- 本 step 僅資料結構；訂閱者佇列、reconnect-replay、與 ws_manager 的整合
  留到 step 2/3。

對應卡片 #13111。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Mapping


@dataclass(frozen=True)
class EventRecord:
    """單一廣播事件（immutable）。

    ``payload`` 雖為 ``dict``，但呼叫端不應在建立後修改；後續 step 2/3
    會在進入 buffer 前統一轉為 JSON-safe 淺拷貝。
    """
    event_type: str
    payload: Mapping[str, object]
    ts: float


@dataclass(frozen=True)
class RunState:
    """某個 run_key 的完整狀態快照（immutable）。

    - ``buffer`` 保留事件插入順序，供 client 重連時 replay
    - ``subscriber_ids`` 用於 step 2 與 asyncio.Queue 對應；本 step
      只維護 id 集合本身
    """
    run_key: str
    buffer: tuple[EventRecord, ...] = field(default_factory=tuple)
    subscriber_ids: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# 純函式（全部 return 新 RunState，不 mutate）
# ---------------------------------------------------------------------------


def create_run(run_key: str) -> RunState:
    """建立新的 RunState，buffer / subscriber 皆為空。"""
    return RunState(run_key=run_key)


def append_event(state: RunState, event: EventRecord) -> RunState:
    """把事件追加到 buffer 尾端，回傳新 state。"""
    return replace(state, buffer=state.buffer + (event,))


def add_subscriber(state: RunState, sid: str) -> RunState:
    """加入訂閱者；若 sid 已存在則回傳原 state（idempotent）。"""
    if sid in state.subscriber_ids:
        return state
    return replace(state, subscriber_ids=state.subscriber_ids + (sid,))


def remove_subscriber(state: RunState, sid: str) -> RunState:
    """移除訂閱者；若 sid 不存在則回傳原 state（idempotent）。"""
    if sid not in state.subscriber_ids:
        return state
    remaining = tuple(s for s in state.subscriber_ids if s != sid)
    return replace(state, subscriber_ids=remaining)
