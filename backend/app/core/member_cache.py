"""成員 soul + skills 預載快取。啟動時全量載入，檔案 mtime 變動自動重讀。"""
import logging
import threading
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# .aegis 路徑和 member_profile.py 一致
_INSTALL_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_MEMBERS_ROOT = _INSTALL_ROOT / ".aegis" / "members"
_SHARED_SKILLS_DIR = _INSTALL_ROOT / ".aegis" / "shared" / "skills"


@dataclass
class MemberProfile:
    slug: str
    soul: str = ""
    skills: list[str] = field(default_factory=list)
    shared_skills: list[str] = field(default_factory=list)
    system_prompt: str = ""  # 預組裝（soul + shared + member skills 合併）
    _mtimes: dict = field(default_factory=dict)


def _read_safe(path: Path) -> str:
    """安全讀取檔案，失敗回空字串。"""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _get_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except Exception:
        return 0.0


class MemberCache:
    """全域成員快取。啟動時掃描 .aegis/members/，預載所有成員 profile。"""

    def __init__(self):
        self._profiles: dict[str, MemberProfile] = {}
        self._shared_skills: list[str] = []
        self._shared_mtimes: dict[str, float] = {}
        self._lock = threading.Lock()

    def load_all(self):
        """啟動時呼叫。掃描所有成員目錄，載入 soul + skills。"""
        with self._lock:
            self._load_shared_skills()
            if not _MEMBERS_ROOT.exists():
                logger.warning(f"[MemberCache] Members root not found: {_MEMBERS_ROOT}")
                return
            for member_dir in _MEMBERS_ROOT.iterdir():
                if member_dir.is_dir() and not member_dir.name.startswith("."):
                    self._load_member_locked(member_dir.name)
            logger.info(f"[MemberCache] Loaded {len(self._profiles)} members, "
                        f"{len(self._shared_skills)} shared skills")

    def get(self, slug: str) -> MemberProfile:
        """取得成員 profile（如果 mtime 變了，自動重讀）。"""
        with self._lock:
            p = self._profiles.get(slug)
            if not p:
                p = self._load_member_locked(slug)
            elif self._is_stale(p):
                p = self._load_member_locked(slug)
            return p

    def get_system_prompt(self, slug: str) -> str:
        """取得預組裝的 system prompt（soul + all skills 合併）。"""
        return self.get(slug).system_prompt

    def _load_shared_skills(self):
        """載入 shared skills。"""
        self._shared_skills = []
        self._shared_mtimes = {}
        if not _SHARED_SKILLS_DIR.exists():
            return
        for md in sorted(_SHARED_SKILLS_DIR.glob("*.md")):
            content = _read_safe(md)
            if content:
                self._shared_skills.append(content)
                self._shared_mtimes[str(md)] = _get_mtime(md)

    def _load_member_locked(self, slug: str) -> MemberProfile:
        """載入單一成員（需在 lock 內呼叫）。"""
        member_dir = _MEMBERS_ROOT / slug
        mtimes: dict[str, float] = {}

        # Soul
        soul_path = member_dir / "soul.md"
        soul = _read_safe(soul_path)
        if soul_path.exists():
            mtimes[str(soul_path)] = _get_mtime(soul_path)

        # Member skills
        skills = []
        skills_dir = member_dir / "skills"
        if skills_dir.exists():
            for md in sorted(skills_dir.glob("*.md")):
                content = _read_safe(md)
                if content:
                    skills.append(content)
                    mtimes[str(md)] = _get_mtime(md)

        # 組裝 system_prompt
        all_skills = self._shared_skills + skills
        parts = []
        if soul:
            parts.append(soul)
        if all_skills:
            parts.append("\n\n---\n\n".join(all_skills))
        system_prompt = "\n\n".join(parts)

        profile = MemberProfile(
            slug=slug,
            soul=soul,
            skills=skills,
            shared_skills=list(self._shared_skills),
            system_prompt=system_prompt,
            _mtimes=mtimes,
        )
        self._profiles[slug] = profile
        return profile

    def _is_stale(self, profile: MemberProfile) -> bool:
        """檢查檔案變動（mtime 改變）或刪除（檔案不存在）或新增（目錄內容變了）。"""
        for path_str, old_mtime in profile._mtimes.items():
            p = Path(path_str)
            if not p.exists():
                return True  # 檔案被刪除
            if _get_mtime(p) != old_mtime:
                return True  # 檔案被修改
        # 檢查新增：skills 目錄的檔案數是否變了
        member_dir = _MEMBERS_ROOT / profile.slug
        skills_dir = member_dir / "skills"
        if skills_dir.exists():
            current_files = {str(md) for md in skills_dir.glob("*.md")}
            cached_files = {p for p in profile._mtimes if "/skills/" in p or "\\skills\\" in p}
            if current_files != cached_files:
                return True  # 有新增或刪除的 skill 檔案
        return False


# 全域 singleton
member_cache = MemberCache()
