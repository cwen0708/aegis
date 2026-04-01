"""Member profile management — soul, skills, memory, MCP directories."""
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# .aegis lives under the install root (backend/app/core/ → ../../.. → backend/ → .. → install root)
_INSTALL_ROOT = Path(__file__).resolve().parent.parent.parent.parent
MEMBERS_ROOT = _INSTALL_ROOT / ".aegis" / "members"

_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9\-]*$")


def _validate_slug(slug: str) -> str:
    """Validate slug to prevent path traversal."""
    if not slug or not _SLUG_PATTERN.match(slug) or ".." in slug:
        raise ValueError(f"Invalid member slug: {slug!r}")
    return slug


def get_member_dir(slug: str) -> Path:
    """Return (and ensure) the member's profile directory."""
    _validate_slug(slug)
    d = MEMBERS_ROOT / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "skills").mkdir(exist_ok=True)
    (d / "skills" / "drafts").mkdir(exist_ok=True)
    (d / "skills" / "active").mkdir(exist_ok=True)
    (d / "memory" / "short-term").mkdir(parents=True, exist_ok=True)
    (d / "memory" / "long-term").mkdir(parents=True, exist_ok=True)
    return d


def get_soul_content(slug: str) -> str:
    """Read soul.md content for a member. Returns empty string if missing."""
    soul_file = get_member_dir(slug) / "soul.md"
    if soul_file.exists():
        return soul_file.read_text(encoding="utf-8")
    return ""


def get_skills_dir(slug: str) -> Path:
    """Return the member's skills directory (root, for manually created skills)."""
    return get_member_dir(slug) / "skills"


def get_skills_drafts_dir(slug: str) -> Path:
    """Return the member's skills/drafts directory (auto-generated, pending review)."""
    return get_member_dir(slug) / "skills" / "drafts"


def get_skills_active_dir(slug: str) -> Path:
    """Return the member's skills/active directory (auto-generated, approved)."""
    return get_member_dir(slug) / "skills" / "active"


def get_member_memory_dir(slug: str) -> Path:
    """Return (and ensure) the member's memory directory."""
    d = get_member_dir(slug) / "memory"
    (d / "short-term").mkdir(parents=True, exist_ok=True)
    (d / "long-term").mkdir(parents=True, exist_ok=True)
    return d


def get_mcp_config_path(slug: str) -> Path:
    """回傳成員的 mcp.json 路徑"""
    return get_member_dir(slug) / "mcp.json"


def get_mcp_config(slug: str) -> dict:
    """讀取成員 MCP 設定"""
    path = get_mcp_config_path(slug)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning(f"Invalid MCP config for {slug}, returning empty")
    return {"mcpServers": {}}


def save_mcp_config(slug: str, config: dict) -> None:
    """寫入成員 MCP 設定"""
    path = get_mcp_config_path(slug)
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def _extract_title(filepath: Path) -> str:
    """從 .md 檔案提取第一個 # 標題，找不到則回傳檔名 stem。"""
    title = filepath.stem
    try:
        content = filepath.read_text(encoding="utf-8")
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("# "):
                title = line[2:].strip()
                break
    except Exception:
        pass
    return title


def list_skills(slug: str) -> list[dict]:
    """List all skills for a member.

    掃描三個位置，回傳含 status 的清單：
    - skills/*.md        → status="active"  (手動建立 / 舊格式)
    - skills/active/*.md → status="active"  (自動生成已批准)
    - skills/drafts/*.md → status="draft"   (自動生成待審核)
    """
    base_dir = get_member_dir(slug) / "skills"
    if not base_dir.exists():
        return []

    seen: dict[str, dict] = {}  # name → skill dict，防重複

    # 1. root skills/*.md → active
    for f in sorted(base_dir.glob("*.md")):
        name = f.stem
        seen[name] = {"name": name, "title": _extract_title(f), "status": "active"}

    # 2. skills/active/*.md → active
    active_dir = base_dir / "active"
    if active_dir.exists():
        for f in sorted(active_dir.glob("*.md")):
            name = f.stem
            seen[name] = {"name": name, "title": _extract_title(f), "status": "active"}

    # 3. skills/drafts/*.md → draft
    drafts_dir = base_dir / "drafts"
    if drafts_dir.exists():
        for f in sorted(drafts_dir.glob("*.md")):
            name = f.stem
            if name not in seen:  # 已批准的優先，不被 draft 覆蓋
                seen[name] = {"name": name, "title": _extract_title(f), "status": "draft"}

    return list(seen.values())


def get_skill_content(slug: str, skill_name: str) -> str:
    """Read a specific skill file content.

    依序搜尋：root skills/ → skills/active/ → skills/drafts/
    回傳第一個找到的內容，找不到回傳空字串。
    """
    # Validate skill_name to prevent path traversal
    if not skill_name or ".." in skill_name or "/" in skill_name or "\\" in skill_name:
        raise ValueError(f"Invalid skill name: {skill_name!r}")

    base_dir = get_member_dir(slug) / "skills"
    for subdir in [base_dir, base_dir / "active", base_dir / "drafts"]:
        skill_file = subdir / f"{skill_name}.md"
        if skill_file.exists():
            return skill_file.read_text(encoding="utf-8")
    return ""


def find_skill_file(slug: str, skill_name: str) -> Path | None:
    """尋找 skill 檔案所在路徑（root → active → drafts），找不到回傳 None。"""
    if not skill_name or ".." in skill_name or "/" in skill_name or "\\" in skill_name:
        return None
    base_dir = get_member_dir(slug) / "skills"
    for subdir in [base_dir, base_dir / "active", base_dir / "drafts"]:
        skill_file = subdir / f"{skill_name}.md"
        if skill_file.exists():
            return skill_file
    return None


def approve_skill(slug: str, skill_name: str) -> Path:
    """將 skills/drafts/{skill_name}.md 移動到 skills/active/{skill_name}.md。

    Returns:
        移動後的目標路徑

    Raises:
        FileNotFoundError: 若 drafts 中找不到該 skill
    """
    if not skill_name or ".." in skill_name or "/" in skill_name or "\\" in skill_name:
        raise ValueError(f"Invalid skill name: {skill_name!r}")

    drafts_dir = get_skills_drafts_dir(slug)
    active_dir = get_skills_active_dir(slug)

    src = drafts_dir / f"{skill_name}.md"
    if not src.exists():
        raise FileNotFoundError(f"Draft skill not found: {skill_name}")

    dest = active_dir / f"{skill_name}.md"
    src.rename(dest)
    logger.info(f"[member_profile] skill approved: {src} → {dest}")
    return dest
