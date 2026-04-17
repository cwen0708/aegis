"""Chat Workspace — per-member per-user 專屬工作目錄。

每個 member:user 組合有一個目錄，包含：
- CLAUDE.md（soul + 用戶身份 + 安全限制）
- .claude/settings.json（trust 設定）
- .claude/skills/ → symlink 到 shared + member skills
- .mcp.json → symlink 到 member 的 mcp.json

ProcessPool 的 cwd 指向這裡，Claude CLI 自動讀取所有設定。
"""
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger(__name__)

_INSTALL_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CHAT_WS_ROOT = _INSTALL_ROOT / ".aegis" / "chat-workspaces"
_SHARED_SKILLS_DIR = _INSTALL_ROOT / ".aegis" / "shared" / "skills"
_SHARED_RULES_DIR = _INSTALL_ROOT / ".aegis" / "shared" / "rules"
_MEMBERS_ROOT = _INSTALL_ROOT / ".aegis" / "members"

_SAFE_KEY_RE = re.compile(r'[^a-zA-Z0-9_\-:]')

_SETTINGS_JSON = json.dumps({
    "trust_all_projects": True,
    "skipDangerousModePermissionPrompt": True,
}, indent=2)


def _sanitize_key(key: str) -> str:
    """清理 chat_key 中不安全的字元（保留 : 和 -）。"""
    return _SAFE_KEY_RE.sub("_", key)


def ensure_chat_workspace(
    member_slug: str,
    chat_key: str,
    bot_user_id: int,
    soul: str = "",
    user_context=None,
    accessible_projects: Optional[List] = None,
    user_level: int = 0,
    chat_id: str = "",
    platform: str = "",
    user_extra: Optional[dict] = None,
) -> str:
    """確保 chat workspace 存在且最新，回傳目錄路徑。"""
    safe_key = _sanitize_key(chat_key)
    ws = _CHAT_WS_ROOT / member_slug / safe_key
    ws.mkdir(parents=True, exist_ok=True)

    # 1. CLAUDE.md
    claude_md = ws / "CLAUDE.md"
    content = _build_chat_claude_md(
        soul=soul,
        member_slug=member_slug,
        user_context=user_context,
        accessible_projects=accessible_projects or [],
        user_level=user_level,
        chat_id=chat_id,
        platform=platform,
        user_extra=user_extra,
    )
    # 只在內容變更時才寫入（減少磁碟 IO）
    if not claude_md.exists() or claude_md.read_text(encoding="utf-8", errors="replace") != content:
        claude_md.write_text(content, encoding="utf-8")

    # 2. .claude/settings.json
    dot_claude = ws / ".claude"
    dot_claude.mkdir(exist_ok=True)
    settings_file = dot_claude / "settings.json"
    if not settings_file.exists():
        settings_file.write_text(_SETTINGS_JSON, encoding="utf-8")

    # 3. .claude/rules/ → symlink
    _ensure_rules_symlinks(ws)

    # 4. .claude/skills/ → symlink
    _ensure_skill_symlinks(ws, member_slug)

    # 5. .mcp.json → symlink
    _ensure_mcp_symlink(ws, member_slug)

    return str(ws)


def _build_chat_claude_md(
    soul: str,
    member_slug: str = "",
    user_context=None,
    accessible_projects: list = None,
    user_level: int = 0,
    chat_id: str = "",
    platform: str = "",
    user_extra: Optional[dict] = None,
) -> str:
    """生成 chat 專用設定檔 — 委託給 executor.config_md。"""
    from app.core.executor.config_md import build_config_md
    return build_config_md(
        mode="chat",
        soul=soul,
        member_slug=member_slug,
        user_context=user_context,
        accessible_projects=accessible_projects,
        user_level=user_level,
        chat_id=chat_id,
        platform=platform,
        user_extra=user_extra,
    )


def _ensure_rules_symlinks(ws: Path):
    """建立 .claude/rules/ 目錄的 symlink（shared rules）。"""
    if not _SHARED_RULES_DIR.exists():
        return
    rules_dir = ws / ".claude" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)

    targets: dict[str, Path] = {}
    for md in _SHARED_RULES_DIR.glob("*.md"):
        targets[md.name] = md

    # 清理過期 symlink
    for existing in rules_dir.iterdir():
        if existing.is_symlink():
            if existing.name not in targets:
                existing.unlink()
            elif existing.resolve() != targets[existing.name].resolve():
                existing.unlink()

    # 建立 symlink
    for name, target in targets.items():
        link = rules_dir / name
        if not link.exists():
            try:
                link.symlink_to(target.resolve())
            except OSError as e:
                logger.warning(f"[ChatWorkspace] Failed to symlink rule {name}: {e}")


def _ensure_skill_symlinks(ws: Path, member_slug: str):
    """建立 skills 目錄的 symlink（shared + member）。"""
    skills_dir = ws / ".claude" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    # 收集目標 symlink
    targets: dict[str, Path] = {}

    # Shared skills
    if _SHARED_SKILLS_DIR.exists():
        for md in _SHARED_SKILLS_DIR.glob("*.md"):
            targets[f"shared_{md.name}"] = md

    # Member skills（可覆蓋 shared 的同名檔）
    member_skills_dir = _MEMBERS_ROOT / member_slug / "skills"
    if member_skills_dir.exists():
        for md in member_skills_dir.glob("*.md"):
            targets[md.name] = md

    # 清理過期 symlink
    for existing in skills_dir.iterdir():
        if existing.is_symlink():
            if existing.name not in targets:
                existing.unlink()
            elif existing.resolve() != targets[existing.name].resolve():
                existing.unlink()  # 目標變了，重建

    # 建立 symlink
    for name, target in targets.items():
        link = skills_dir / name
        if not link.exists():
            try:
                link.symlink_to(target.resolve())
            except OSError as e:
                logger.warning(f"[ChatWorkspace] Failed to symlink {name}: {e}")


def _ensure_mcp_symlink(ws: Path, member_slug: str):
    """建立 .mcp.json symlink → member 的 mcp.json。"""
    member_mcp = _MEMBERS_ROOT / member_slug / "mcp.json"
    ws_mcp = ws / ".mcp.json"

    if member_mcp.exists():
        if ws_mcp.is_symlink():
            if ws_mcp.resolve() != member_mcp.resolve():
                ws_mcp.unlink()
                ws_mcp.symlink_to(member_mcp.resolve())
        elif not ws_mcp.exists():
            try:
                ws_mcp.symlink_to(member_mcp.resolve())
            except OSError as e:
                logger.warning(f"[ChatWorkspace] Failed to symlink .mcp.json: {e}")
    elif ws_mcp.is_symlink():
        ws_mcp.unlink()  # member mcp 被刪，清理 symlink
