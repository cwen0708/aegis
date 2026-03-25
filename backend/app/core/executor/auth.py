"""
認證注入與 MCP 設定查找 — Worker / Runner / ProcessPool 共用

合併原本分散在三個地方的 auth injection 邏輯。
"""
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)


def inject_auth_env(
    env: Dict[str, str],
    provider: str,
    auth_info: Dict[str, str],
    *,
    log_prefix: str = "",
) -> None:
    """將認證資訊注入環境變數 dict（原地修改）。

    支援 provider: claude, gemini, openai
    auth_info 結構: {auth_type, oauth_token, api_key}
    """
    auth_type = auth_info.get("auth_type", "cli")

    if provider == "claude":
        if auth_type == "api_key" and auth_info.get("api_key"):
            env["ANTHROPIC_API_KEY"] = auth_info["api_key"]
            if log_prefix:
                logger.info(f"{log_prefix} Using Anthropic API Key")
        elif auth_info.get("oauth_token"):
            env["CLAUDE_CODE_OAUTH_TOKEN"] = auth_info["oauth_token"]
            if log_prefix:
                logger.info(f"{log_prefix} Using Claude OAuth Token")

    elif provider == "gemini":
        if auth_info.get("api_key"):
            env["GEMINI_API_KEY"] = auth_info["api_key"]
            if log_prefix:
                logger.info(f"{log_prefix} Using Gemini API Key")

    elif provider == "openai":
        if auth_info.get("api_key"):
            env["OPENAI_API_KEY"] = auth_info["api_key"]
            if log_prefix:
                logger.info(f"{log_prefix} Using OpenAI API Key")


def inject_auth_to_os_environ(
    auth_info: Dict[str, str],
    extra_env: Optional[Dict[str, str]] = None,
) -> list[str]:
    """臨時注入認證到 os.environ（ProcessPool 專用，因為不能傳 env=）。

    Returns: 被注入的 key 列表（呼叫端負責清理）
    """
    import os

    injected_keys: list[str] = []

    if auth_info.get("api_key"):
        os.environ["ANTHROPIC_API_KEY"] = auth_info["api_key"]
        injected_keys.append("ANTHROPIC_API_KEY")

    if extra_env:
        for k, v in extra_env.items():
            os.environ[k] = v
            injected_keys.append(k)

    return injected_keys


def cleanup_os_environ(keys: list[str]) -> None:
    """清理 inject_auth_to_os_environ 注入的環境變數。"""
    import os
    for k in keys:
        os.environ.pop(k, None)


def get_mcp_config_path(member_id: int) -> Optional[str]:
    """查找成員的 mcp.json 路徑（by member_id，需查 DB）。"""
    try:
        from sqlmodel import Session
        from app.database import engine
        from app.models.core import Member

        with Session(engine) as session:
            member = session.get(Member, member_id)
            if member and member.slug:
                return get_mcp_config_path_by_slug(member.slug)
    except Exception:
        pass
    return None


def get_mcp_config_path_by_slug(slug: str) -> Optional[str]:
    """查找成員的 mcp.json 路徑（by slug，不需 DB）。

    直接使用 member_profile 的路徑函式，避免重複拼接。
    """
    try:
        from app.core.member_profile import get_mcp_config_path as _profile_mcp_path
        mcp_path = _profile_mcp_path(slug)
        if mcp_path.exists():
            return str(mcp_path)
    except Exception:
        pass
    return None
