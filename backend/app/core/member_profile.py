"""Member profile management — soul, skills, memory directories."""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MEMBERS_ROOT = Path.home() / ".aegis" / "members"


def get_member_dir(slug: str) -> Path:
    """Return (and ensure) the member's profile directory."""
    d = MEMBERS_ROOT / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "skills").mkdir(exist_ok=True)
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
    """Return the member's skills directory."""
    return get_member_dir(slug) / "skills"


def get_member_memory_dir(slug: str) -> Path:
    """Return (and ensure) the member's memory directory."""
    d = get_member_dir(slug) / "memory"
    (d / "short-term").mkdir(parents=True, exist_ok=True)
    (d / "long-term").mkdir(parents=True, exist_ok=True)
    return d
