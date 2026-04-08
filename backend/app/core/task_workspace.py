"""Task workspace management — create/cleanup temp dirs for AI task execution."""
import logging
import shutil
from pathlib import Path

from app.core.member_profile import get_member_dir, get_soul_content, get_skills_dir, get_member_memory_dir, get_mcp_config_path
from app.core.sandbox import build_sanitized_env

logger = logging.getLogger(__name__)

# .aegis lives under the install root (backend/app/core/ → ../../.. → backend/ → .. → install root)
_INSTALL_ROOT = Path(__file__).resolve().parent.parent.parent.parent
WORKSPACES_ROOT = _INSTALL_ROOT / ".aegis" / "workspaces"

# Provider 設定檔映射統一由 executor 管理
from app.core.executor.config_md import PROVIDER_CONFIG, get_config_filename, get_dot_dir


def _build_config_content(
    soul_content: str,
    member_slug: str,
    project_path: str,
    card_content: str,
    stage_name: str = "",
    stage_description: str = "",
    stage_instruction: str = "",
    acceptance_criteria: str = "",
) -> str:
    """Assemble config content — 委託給 executor.config_md。"""
    from app.core.executor.config_md import build_config_md
    return build_config_md(
        mode="task",
        soul=soul_content,
        member_slug=member_slug,
        project_path=project_path,
        card_content=card_content,
        stage_name=stage_name,
        stage_description=stage_description,
        stage_instruction=stage_instruction,
        acceptance_criteria=acceptance_criteria,
    )


def prepare_workspace(
    card_id: int,
    member_slug: str,
    provider: str,
    project_path: str,
    card_content: str,
    stage_name: str = "",
    stage_description: str = "",
    stage_instruction: str = "",
    acceptance_criteria: str = "",
) -> Path:
    """
    Create a temp workspace directory for the AI task.
    Returns the workspace path.
    """
    cfg = PROVIDER_CONFIG.get(provider, PROVIDER_CONFIG["claude"])
    ws = WORKSPACES_ROOT / f"task-{card_id}"
    ws.mkdir(parents=True, exist_ok=True)

    # 1. Build and write config file (CLAUDE.md or .gemini.md)
    soul = get_soul_content(member_slug)
    content = _build_config_content(
        soul, member_slug, project_path, card_content,
        stage_name=stage_name,
        stage_description=stage_description,
        stage_instruction=stage_instruction,
        acceptance_criteria=acceptance_criteria,
    )
    (ws / cfg["config_file"]).write_text(content, encoding="utf-8")

    # 2a. Copy shared rules into .claude/rules/
    dot_dir = ws / cfg["dot_dir"]
    _copy_shared_rules(dot_dir)

    # 2b. Copy skills into .claude/skills/ or .gemini/skills/
    #     先載入 shared skills，再載入成員專屬（可覆蓋共用的）
    target_skills = dot_dir / "skills"
    target_skills.mkdir(parents=True, exist_ok=True)

    shared_skills = _INSTALL_ROOT / ".aegis" / "shared" / "skills"
    if shared_skills.exists():
        for md_file in shared_skills.glob("*.md"):
            shutil.copy2(md_file, target_skills / md_file.name)

    src_skills = get_skills_dir(member_slug)
    if src_skills.exists():
        for md_file in src_skills.glob("*.md"):
            shutil.copy2(md_file, target_skills / md_file.name)

    # 3. Copy MCP config to workspace root (.mcp.json)
    mcp_src = get_mcp_config_path(member_slug)
    if mcp_src.exists():
        shutil.copy2(mcp_src, ws / ".mcp.json")

    # 4. Inject GitHub PAT as git credential (if configured)
    try:
        from sqlmodel import Session as SqlSession
        from app.database import engine
        from app.models.core import SystemSetting
        with SqlSession(engine) as db_session:
            pat_setting = db_session.get(SystemSetting, "github_pat")
            if pat_setting and pat_setting.value:
                gitconfig = (
                    '[credential "https://github.com"]\n'
                    f"    helper = !echo username=x-access-token && echo password={pat_setting.value}\n"
                )
                (ws / ".gitconfig").write_text(gitconfig, encoding="utf-8")
    except Exception as e:
        logger.warning(f"[Workspace] Failed to inject git credential: {e}")

    logger.info(f"[Workspace] Created task-{card_id} for {member_slug} ({provider})")
    return ws


def _copy_shared_rules(dot_dir: Path) -> None:
    """將 .aegis/shared/rules/*.md 複製到 workspace 的 dot_dir/rules/。"""
    shared_rules = _INSTALL_ROOT / ".aegis" / "shared" / "rules"
    if not shared_rules.exists():
        return
    target_rules = dot_dir / "rules"
    target_rules.mkdir(parents=True, exist_ok=True)
    for md_file in shared_rules.glob("*.md"):
        shutil.copy2(md_file, target_rules / md_file.name)


def cleanup_workspace(card_id: int) -> None:
    """Remove the temp workspace directory."""
    ws = WORKSPACES_ROOT / f"task-{card_id}"
    if ws.exists():
        shutil.rmtree(ws, ignore_errors=True)
        logger.info(f"[Workspace] Cleaned up task-{card_id}")


def link_project_into_workspace(workspace_dir: str, project_path: str) -> None:
    """在 workspace 中建立連結指向專案目錄的原始碼。

    workspace 保持為 CWD（CLAUDE.md、.claude/ 在這裡），
    專案原始碼透過 symlink/junction 映射進來，改動直接落在開發目錄。
    """
    import platform as _platform
    ws = Path(workspace_dir)
    proj = Path(project_path)

    if not proj.exists():
        return

    is_windows = _platform.system() == "Windows"

    skip = {
        "CLAUDE.md", ".gemini.md", ".claude", ".gemini",
        ".mcp.json", ".gitconfig",
    }

    linked = 0
    for item in proj.iterdir():
        if item.name in skip or item.name.startswith(".aegis"):
            continue
        link_path = ws / item.name
        if link_path.exists() or link_path.is_symlink():
            continue
        try:
            if is_windows and item.is_dir():
                import subprocess
                subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(link_path), str(item)],
                    check=True, capture_output=True, timeout=5,
                )
            else:
                link_path.symlink_to(item)
            linked += 1
        except Exception as e:
            logger.warning(f"[Workspace] Failed to link {item.name}: {e}")

    # .git 連結
    git_link = ws / ".git"
    git_src = proj / ".git"
    if git_src.exists() and not git_link.exists():
        try:
            if is_windows:
                import subprocess
                subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(git_link), str(git_src)],
                    check=True, capture_output=True, timeout=5,
                )
            else:
                git_link.symlink_to(git_src)
            linked += 1
        except Exception:
            pass

    logger.info(f"[Workspace] Linked {linked} items from {proj} into {ws}")
