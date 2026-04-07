"""
Provider 設定與命令建構 — Worker / Runner 共用

合併原本分散在 worker.py 和 runner.py 中的 PROVIDERS dict 與命令建構邏輯。
新增 Provider 類別註冊機制，支援透過 get_provider() 取得具型別介面的 Provider 實例。
"""
from __future__ import annotations

from typing import Optional, List, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.executor.provider_base import BaseProvider

# ── Provider 設定（舊版 dict，保留向後相容） ──
# 共用基底，mode-specific 差異由 build_command() 處理
PROVIDERS = {
    "claude": {
        "cmd_base": ["claude"],
        "json_output": False,
        "stream_json": True,
    },
    "gemini": {
        "cmd_base": ["gemini"],
        "json_output": False,
    },
    "openai": {
        "cmd_base": ["python", "scripts/openai_stream_chat.py"],
        "stream_json": True,
        "default_model": "gpt-4o",
    },
    "ollama": {
        "cmd_base": ["ollama", "run"],
        "json_output": False,
        "default_model": "llama3.1:8b",
        "stdin_prompt": True,
    },
}

# ── Provider 類別註冊表 ──
_PROVIDER_REGISTRY: dict[str, BaseProvider] = {}


def _ensure_registry() -> None:
    """延遲初始化 Provider 註冊表（避免循環 import）。"""
    if _PROVIDER_REGISTRY:
        return
    from app.core.executor.provider_openai import OpenAIProvider
    _PROVIDER_REGISTRY["openai"] = OpenAIProvider()


def get_provider(name: str) -> Optional[BaseProvider]:
    """取得已註冊的 Provider 實例。未註冊時回傳 None。"""
    _ensure_registry()
    return _PROVIDER_REGISTRY.get(name)


def register_provider(provider: BaseProvider) -> None:
    """註冊自訂 Provider（供擴充或測試用）。"""
    _PROVIDER_REGISTRY[provider.meta.name] = provider


def build_command(
    provider: str,
    prompt: str = "",
    model: str = "",
    *,
    mode: Literal["task", "chat"] = "task",
    mcp_config_path: Optional[str] = None,
    resume_session_id: Optional[str] = None,
) -> tuple[list[str], bool]:
    """根據 provider 和 mode 組裝 CLI 命令。

    Returns:
        (cmd_parts, stdin_prompt) — 命令列表和是否需要 stdin 傳 prompt
    """
    config = PROVIDERS.get(provider, PROVIDERS["claude"])
    cmd = list(config["cmd_base"])

    if provider == "claude":
        cmd = _build_claude_cmd(cmd, prompt, model, mode, mcp_config_path, resume_session_id)
        # task 模式用 stdin_prompt（避免 prompt 中的 --- 被 CLI parser 誤解析）
        # chat 模式用 -p（ProcessPool 路徑不走這裡，只有 CLI fallback 才用）
        stdin_prompt = (mode == "task")
        return cmd, stdin_prompt

    elif provider == "gemini":
        cmd = _build_gemini_cmd(cmd, prompt, model, mode)
        return cmd, False

    elif provider == "openai":
        resolved_model = model or config.get("default_model", "gpt-4o")
        cmd.extend(["--model", resolved_model])
        # prompt 從 stdin 傳入（避免 shell 特殊字元問題）
        return cmd, True

    elif provider == "ollama":
        resolved_model = model or config.get("default_model", "llama3.1:8b")
        cmd.append(resolved_model)
        return cmd, True

    # 未知 provider fallback
    return cmd, False


def get_provider_config(provider: str) -> dict:
    """取得 provider 原始設定（給需要存取 stream_json 等旗標的呼叫端用）。"""
    return PROVIDERS.get(provider, PROVIDERS["claude"])


# ── 內部建構函式 ──

def _build_claude_cmd(
    cmd: List[str],
    prompt: str,
    model: str,
    mode: str,
    mcp_config_path: Optional[str],
    resume_session_id: Optional[str],
) -> List[str]:
    """組裝 Claude CLI 命令。"""
    if mode == "chat":
        # Runner (CLI fallback)：-p 模式，stream-json
        cmd.extend([
            "-p", prompt,
            "--dangerously-skip-permissions",
            "--model", model or "opus",
            "--output-format", "stream-json",
            "--verbose",
        ])
    else:
        # Worker：stdin_prompt 模式，stream-json
        cmd.extend([
            "--dangerously-skip-permissions",
            "--model", model or "sonnet",
            "--output-format", "stream-json",
            "--verbose",
        ])

    if mcp_config_path:
        cmd.extend(["--mcp-config", mcp_config_path])

    if resume_session_id:
        cmd.extend(["--resume", resume_session_id])

    return cmd


def _build_gemini_cmd(
    cmd: List[str],
    prompt: str,
    model: str,
    mode: str,
) -> List[str]:
    """組裝 Gemini CLI 命令。"""
    resolved_model = model or ("gemini-2.5-flash" if mode == "chat" else "gemini-3.1-pro-preview")
    cmd.extend(["-p", prompt, "-y", "--model", resolved_model])
    return cmd
