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
    """清除 ANSI escape codes 和不可列印字元。"""
    clean = _ANSI_RE.sub("", text)
    return "".join(c for c in clean if c.isprintable() or c in "\n\r\t")


# 路徑去敏（動態取得 HOME，不寫死用戶名）
import os as _os
from pathlib import Path as _Path

_HOME = _Path(_os.path.expanduser("~"))
_INSTALL_ROOT = _Path(__file__).resolve().parent.parent.parent.parent

_SENSITIVE_PATHS: list[str] = []


def _build_sensitive_paths() -> list[str]:
    """動態建構敏感路徑列表（長路徑在前，避免短路徑先匹配導致殘留）。"""
    paths = set()
    home = str(_HOME)

    # 用 / 和 \ 兩種格式（跨平台）
    for h in [home, home.replace("\\", "/")]:
        for sub in [".local/aegis/", "projects/", ""]:
            p = f"{h}/{sub}" if not h.endswith("/") else f"{h}{sub}"
            paths.add(p)

    # Aegis 安裝目錄
    install = str(_INSTALL_ROOT)
    for p in [install, install.replace("\\", "/")]:
        paths.add(p + "/" if not p.endswith("/") else p)

    # 長路徑在前
    return sorted(paths, key=len, reverse=True)


_HOME_RE = re.compile(r'/home/[^/]+/')  # 任何 Linux 用戶的 home


def sanitize_output(text: str) -> str:
    """去除敏感路徑（伺服器路徑 → 相對路徑）。用於送出給用戶的內容。"""
    global _SENSITIVE_PATHS
    if not _SENSITIVE_PATHS:
        _SENSITIVE_PATHS = _build_sensitive_paths()
    # 精確替換（已知路徑）
    for path in _SENSITIVE_PATHS:
        text = text.replace(path, "")
    # 通用替換（任何 /home/xxx/ 開頭）
    text = _HOME_RE.sub("", text)
    return text


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



# WebSocketTarget, PlatformTarget, OneStackTarget 已遷移到 app/hooks/
# 保留 NullTarget 供測試用

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


class HookEmitter(StreamEmitter):
    """Hook 驅動的 StreamEmitter — emit_raw 分發給 Hook.on_stream，取代 Target。

    用法：
        hooks = collect_hooks("worker")
        emitter = HookEmitter(hooks)
        emitter.emit_raw(json_line)      # stream-json → parse → Hook.on_stream
        emitter.emit_output("plain text") # 非 stream-json → 直接當 output 事件
    """

    def __init__(self, hooks: list = None):
        super().__init__(targets=[])
        self._hooks = hooks or []

    def emit_raw(self, raw_line: str) -> None:
        event = parse_stream_event(raw_line)
        if not event:
            return
        if event.kind == "text":
            self._text_parts.append(event.content)
        if event.kind == "result" and event.token_info:
            self._token_info = event.token_info
        from app.hooks import run_on_stream
        run_on_stream(self._hooks, event)

    def emit_output(self, text: str) -> None:
        """非 stream-json 模式：直接當 output 事件送給 Hook。"""
        from app.hooks import run_on_stream
        run_on_stream(self._hooks, StreamEvent(kind="output", content=text))

    def emit_heartbeat(self, idle_seconds: int) -> None:
        from app.hooks import run_on_stream
        run_on_stream(self._hooks, StreamEvent(
            kind="heartbeat", content=f"⏳ 處理中... ({idle_seconds}s)",
        ))
