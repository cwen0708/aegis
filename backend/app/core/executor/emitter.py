"""
StreamEmitter — 三層串流輸出架構

Layer 1: StreamEmitter（入口）— 接收原始 stream-json 行，分發給所有 target
Layer 2: parse_stream_event()（共用解析）— 整合 stream_parsers.py
Layer 3: StreamTarget（輸出目標，可組合）
    ├── WebSocketTarget     → ws_manager + BroadcastLog
    ├── PlatformTarget      → Telegram/LINE placeholder edit
    ├── OneStackTarget      → aegis_stream Supabase
    └── NullTarget          → 靜默

使用範例（Worker）：
    emitter = StreamEmitter(targets=[
        WebSocketTarget(card_id),
        OneStackTarget(card_id, member_slug),
    ])
    emitter.emit_raw(json_line)

使用範例（Chat）：
    emitter = StreamEmitter(targets=[
        PlatformTarget(platform, chat_id, placeholder_id, loop),
    ])
    # 傳給 run_ai_task 的 on_stream=emitter.emit_raw
"""
import json
import re
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# ANSI escape code 清理
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07?')
_DIRECTIVE_RE = re.compile(r'<!-- directive:(.*?) -->')


def clean_ansi(text: str) -> str:
    """清除 ANSI escape codes 和不可列印字元。公開供 worker PTY loop 使用。"""
    clean = _ANSI_RE.sub("", text)
    return "".join(c for c in clean if c.isprintable() or c in "\n\r\t")


# ════════════════════════════════════════
# Layer 2: StreamEvent + parse_stream_event
# ════════════════════════════════════════

@dataclass
class StreamEvent:
    """統一串流事件"""
    kind: str           # "tool_call" | "output" | "thinking" | "text" | "heartbeat" | "result" | "directive"
    content: str        # 人話摘要（emoji + 說明）或原始文字
    raw_line: str = ""  # 原始 JSON 行（某些 target 需要）
    event_type: str = ""  # OneStack event_type（tool_call / output）
    token_info: dict = field(default_factory=dict)  # result 行的 token 資訊


def parse_stream_event(raw_line: str) -> Optional[StreamEvent]:
    """解析 stream-json 行為統一事件（整合現有 stream_parsers.py）。

    Returns None 表示此行不值得處理（system / rate_limit / user 等）。
    """
    from app.core.stream_parsers import (
        parse_tool_call,
        parse_stream_json_text,
        parse_stream_json_tokens,
    )

    try:
        data = json.loads(raw_line.strip())
    except (json.JSONDecodeError, ValueError):
        return None

    msg_type = data.get("type", "")

    # system / rate_limit → 忽略
    if msg_type in ("system", "rate_limit_event", "user"):
        return None

    # result → token info
    if msg_type == "result":
        token_info = parse_stream_json_tokens(raw_line) or {}
        return StreamEvent(
            kind="result", content="", raw_line=raw_line, token_info=token_info,
        )

    # assistant → 嘗試解析 tool_call / text / thinking
    if msg_type == "assistant":
        tool = parse_tool_call(raw_line)
        if tool:
            event_type, summary = tool
            return StreamEvent(
                kind=event_type, content=summary, raw_line=raw_line, event_type=event_type,
            )

        text = parse_stream_json_text(raw_line)
        if text:
            # 偵測 directive 標記
            m = _DIRECTIVE_RE.search(text)
            if m:
                try:
                    directive_data = json.loads(m.group(1))
                    return StreamEvent(
                        kind="directive",
                        content=text,
                        raw_line=raw_line,
                        token_info=directive_data,  # 借用 token_info 存放 directive payload
                    )
                except (json.JSONDecodeError, ValueError):
                    pass
            return StreamEvent(
                kind="text", content=text, raw_line=raw_line,
            )

    return None


# ════════════════════════════════════════
# Layer 3: StreamTarget 介面 + 實作
# ════════════════════════════════════════

@runtime_checkable
class StreamTarget(Protocol):
    """輸出目標介面"""
    def handle(self, event: StreamEvent) -> None: ...


class WebSocketTarget:
    """Worker 前端 Kanban — broadcast_log → WS + BroadcastLog DB。"""

    def __init__(self, card_id: int):
        self.card_id = card_id

    def handle(self, event: StreamEvent) -> None:
        if event.kind == "result":
            return  # result 不廣播

        # directive → 走 broadcast_directive 路徑
        if event.kind == "directive":
            try:
                from app.core.http_client import InternalAPI
                directive_data = event.token_info  # {action, params, ...}
                InternalAPI.post("/internal/directive", {
                    "card_id": self.card_id,
                    "action": directive_data.get("action", "notify"),
                    "params": directive_data.get("params", {}),
                })
            except Exception as e:
                logger.warning(f"[WebSocketTarget] directive card={self.card_id}: {e}")
            return

        clean = clean_ansi(event.content)
        if not clean.strip():
            return

        # 寫入 BroadcastLog 暫存表
        try:
            from sqlmodel import Session
            from app.database import engine
            from app.models.core import BroadcastLog
            with Session(engine) as session:
                session.add(BroadcastLog(card_id=self.card_id, line=clean))
                session.commit()
        except Exception:
            pass

        # HTTP POST → FastAPI → WebSocket 廣播
        try:
            from app.core.http_client import InternalAPI
            InternalAPI.broadcast_log(self.card_id, clean)
        except Exception as e:
            logger.warning(f"[WebSocketTarget] card={self.card_id}: {e}")


class PlatformTarget:
    """Chat placeholder 編輯（Telegram/LINE）— 節流 3 秒。"""

    def __init__(self, platform: str, chat_id: str, placeholder_id: str, loop=None):
        self.platform = platform
        self.chat_id = chat_id
        self.placeholder_id = placeholder_id
        self.loop = loop
        self._last_edit_time = 0.0
        self._last_edit_text = ""
        self._throttle = 3.0

    def handle(self, event: StreamEvent) -> None:
        if event.kind not in ("tool_call", "output", "thinking", "heartbeat"):
            return  # text / result 不編輯 placeholder

        summary = f"🤔 {event.content}" if event.kind != "heartbeat" else event.content

        now = time.time()
        if now - self._last_edit_time < self._throttle or summary == self._last_edit_text:
            return

        self._last_edit_time = now
        self._last_edit_text = summary

        if self.loop:
            import asyncio
            asyncio.run_coroutine_threadsafe(self._edit(summary), self.loop)
        else:
            try:
                from app.core.http_client import InternalAPI
                InternalAPI.channel_send(self.platform, self.chat_id, summary, self.placeholder_id)
            except Exception:
                pass

    async def _edit(self, text: str) -> None:
        try:
            from app.core.http_client import InternalAPIAsync
            await InternalAPIAsync.channel_send(
                self.platform, self.chat_id, text, self.placeholder_id,
            )
        except Exception:
            pass


class OneStackTarget:
    """OneStack aegis_stream — Supabase Realtime，節流 2 秒。"""

    def __init__(self, card_id: int, member_slug: str = "", chat_id: str = ""):
        self.card_id = card_id
        self.member_slug = member_slug
        self.chat_id = chat_id
        self._last_time = 0.0
        self._throttle = 2.0

    def handle(self, event: StreamEvent) -> None:
        if event.kind not in ("tool_call", "output"):
            return

        now = time.time()
        if now - self._last_time < self._throttle:
            return
        self._last_time = now

        try:
            import asyncio
            from app.core.onestack_connector import connector
            if not connector.enabled:
                return
            loop = asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(
                connector.stream_event(
                    self.card_id,
                    event.event_type or event.kind,
                    event.content,
                    self.member_slug,
                    chat_id=self.chat_id,
                ),
                loop,
            )
        except Exception:
            pass


class NullTarget:
    """靜默 — 不輸出（email 或測試用）。"""
    def handle(self, event: StreamEvent) -> None:
        pass


# ════════════════════════════════════════
# Layer 1: StreamEmitter（入口）
# ════════════════════════════════════════

class StreamEmitter:
    """統一串流入口 — 接收原始 stream-json 行，解析後分發給所有 target。

    也累積 assistant 文字和 token info 供呼叫端取用。
    """

    def __init__(self, targets: list[StreamTarget] | None = None):
        self.targets: list[StreamTarget] = targets or []
        self._text_parts: list[str] = []
        self._token_info: dict = {}

    def emit_raw(self, raw_line: str) -> None:
        """接收原始 stream-json JSON 行（Layer 2 → Layer 3）。

        簽名相容 Callable[[str], None]，可直接作為 on_stream callback。
        """
        event = parse_stream_event(raw_line)
        if not event:
            return

        # 累積文字
        if event.kind == "text":
            self._text_parts.append(event.content)

        # 累積 token info
        if event.kind == "result" and event.token_info:
            self._token_info = event.token_info

        # 分發給所有 target
        for target in self.targets:
            try:
                target.handle(event)
            except Exception as e:
                logger.warning(f"[StreamEmitter] Target {type(target).__name__} error: {e}")

    def emit_heartbeat(self, idle_seconds: int) -> None:
        """心跳（處理中提示）"""
        event = StreamEvent(
            kind="heartbeat", content=f"⏳ 處理中... ({idle_seconds}s)",
        )
        for target in self.targets:
            try:
                target.handle(event)
            except Exception:
                pass

    @property
    def collected_text(self) -> str:
        """累積的 assistant 文字輸出"""
        return "".join(self._text_parts)

    @property
    def token_info(self) -> dict:
        """最後一個 result 行的 token 資訊"""
        return self._token_info
