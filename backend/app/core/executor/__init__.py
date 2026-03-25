"""
Executor — 統一 Worker/Runner 的共用邏輯模組

消除兩條 AI 執行路徑的重複程式碼：
- providers.py: PROVIDERS 設定 + build_command()
- auth.py: inject_auth_env() + get_mcp_config_path()
- context.py: MemberContext dataclass + resolve 函式
- config_md.py: build_config_md() + PROVIDER_CONFIG（多 provider 設定檔模板）
- emitter.py: StreamEmitter 三層架構（StreamEvent + StreamTarget）
- heartbeat.py: heartbeat_monitor context manager
"""

from app.core.executor.providers import PROVIDERS, build_command  # noqa: F401
from app.core.executor.auth import inject_auth_env, get_mcp_config_path  # noqa: F401
from app.core.executor.context import (  # noqa: F401
    MemberContext, AccountInfo,
    resolve_member_for_task, resolve_member_for_chat,
)
from app.core.executor.config_md import (  # noqa: F401
    build_config_md, build_claude_md,  # build_claude_md = 向後相容別名
    PROVIDER_CONFIG, get_config_filename, get_dot_dir,
)
from app.core.executor.emitter import (  # noqa: F401
    StreamEmitter, StreamEvent, StreamTarget,
    WebSocketTarget, PlatformTarget, OneStackTarget, NullTarget,
    parse_stream_event,
)
from app.core.executor.heartbeat import heartbeat_monitor  # noqa: F401

__all__ = [
    # providers
    "PROVIDERS",
    "build_command",
    # auth
    "inject_auth_env",
    "get_mcp_config_path",
    # context
    "MemberContext",
    "AccountInfo",
    "resolve_member_for_task",
    "resolve_member_for_chat",
    # config_md
    "build_config_md",
    "build_claude_md",  # 向後相容
    "PROVIDER_CONFIG",
    "get_config_filename",
    "get_dot_dir",
    # emitter
    "StreamEmitter",
    "StreamEvent",
    "StreamTarget",
    "WebSocketTarget",
    "PlatformTarget",
    "OneStackTarget",
    "NullTarget",
    "parse_stream_event",
    # heartbeat
    "heartbeat_monitor",
]
