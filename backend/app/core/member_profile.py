"""Member profile management — soul, skills, memory directories."""
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
