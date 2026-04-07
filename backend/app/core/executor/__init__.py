"""
Executor — 統一 Worker/Runner 的共用邏輯模組

- providers.py: PROVIDERS 設定 + build_command()
- auth.py: inject_auth_env() + get_mcp_config_path()
- context.py: MemberContext dataclass + resolve 函式
- config_md.py: build_config_md() + PROVIDER_CONFIG
- emitter.py: StreamEmitter + HookEmitter + StreamEvent + parse_stream_event
- heartbeat.py: heartbeat_monitor context manager

串流輸出和任務後處理由 app/hooks/ 統一管理。
"""

from app.core.executor.providers import PROVIDERS, build_command, get_provider, register_provider  # noqa: F401
from app.core.executor.provider_base import BaseProvider, ProviderMeta  # noqa: F401
from app.core.executor.auth import inject_auth_env, get_mcp_config_path  # noqa: F401
from app.core.executor.context import (  # noqa: F401
    MemberContext, AccountInfo,
    resolve_member_for_task, resolve_member_for_chat,
)
from app.core.executor.config_md import (  # noqa: F401
    build_config_md, build_claude_md,
    PROVIDER_CONFIG, get_config_filename, get_dot_dir,
)
from app.core.executor.emitter import (  # noqa: F401
    StreamEmitter, HookEmitter, StreamEvent,
    StreamTarget, NullTarget,  # StreamTarget + NullTarget 供測試用
    parse_stream_event, clean_ansi, sanitize_output,
)
from app.core.executor.heartbeat import heartbeat_monitor  # noqa: F401
from app.core.executor.memory import retrieve_task_memory  # noqa: F401

__all__ = [
    "PROVIDERS", "build_command", "get_provider", "register_provider",
    "BaseProvider", "ProviderMeta",
    "inject_auth_env", "get_mcp_config_path",
    "MemberContext", "AccountInfo", "resolve_member_for_task", "resolve_member_for_chat",
    "build_config_md", "build_claude_md", "PROVIDER_CONFIG", "get_config_filename", "get_dot_dir",
    "StreamEmitter", "HookEmitter", "StreamEvent", "StreamTarget", "NullTarget",
    "parse_stream_event", "clean_ansi", "sanitize_output",
    "heartbeat_monitor",
    "retrieve_task_memory",
]
