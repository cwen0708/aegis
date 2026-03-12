"""Task workspace management — create/cleanup temp dirs for AI task execution."""
import logging
import shutil
from pathlib import Path

from app.core.member_profile import get_member_dir, get_soul_content, get_skills_dir, get_member_memory_dir

logger = logging.getLogger(__name__)

# .aegis lives under the install root (backend/app/core/ → ../../.. → backend/ → .. → install root)
_INSTALL_ROOT = Path(__file__).resolve().parent.parent.parent.parent
WORKSPACES_ROOT = _INSTALL_ROOT / ".aegis" / "workspaces"

# Provider-specific file/dir names
PROVIDER_CONFIG = {
    "claude": {"config_file": "CLAUDE.md", "dot_dir": ".claude"},
    "gemini": {"config_file": "Gemini.md", "dot_dir": ".gemini"},
    # TODO: Codex 尚未驗證配置檔名，暫用類似 Claude 的格式
    "codex": {"config_file": "CODEX.md", "dot_dir": ".codex"},
    # Ollama 本地模型，使用通用 AI 配置
    "ollama": {"config_file": "OLLAMA.md", "dot_dir": ".ollama"},
}


def _build_config_content(
    soul_content: str,
    member_slug: str,
    project_path: str,
    card_content: str,
) -> str:
    """Assemble the CLAUDE.md / .gemini.md content."""
    memory_path = get_member_memory_dir(member_slug)
    return f"""# 工作目錄
你的專案在 {project_path}
所有程式碼修改都在那個目錄進行。

# 你的身份
{soul_content}

# 記憶
你的個人記憶存放在：
{memory_path}
- short-term/ 短期記憶（近期任務摘要）
- long-term/ 長期記憶（累積的經驗與模式）
需要回憶時可以去讀取。

# 本次任務
{card_content}
"""


def prepare_workspace(
    card_id: int,
    member_slug: str,
    provider: str,
    project_path: str,
    card_content: str,
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
    content = _build_config_content(soul, member_slug, project_path, card_content)
    (ws / cfg["config_file"]).write_text(content, encoding="utf-8")

    # 2. Copy skills into .claude/skills/ or .gemini/skills/
    #    先載入 shared skills，再載入成員專屬（可覆蓋共用的）
    dot_dir = ws / cfg["dot_dir"]
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

    logger.info(f"[Workspace] Created task-{card_id} for {member_slug} ({provider})")
    return ws


def cleanup_workspace(card_id: int) -> None:
    """Remove the temp workspace directory."""
    ws = WORKSPACES_ROOT / f"task-{card_id}"
    if ws.exists():
        shutil.rmtree(ws, ignore_errors=True)
        logger.info(f"[Workspace] Cleaned up task-{card_id}")
