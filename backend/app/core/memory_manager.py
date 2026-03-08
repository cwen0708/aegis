"""Memory management for the AEGIS system -- short-term and long-term MD files."""
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def get_memory_dir(aegis_path: str) -> Path:
    """Return the memory root directory for the AEGIS project."""
    p = Path(aegis_path) / "memory"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_short_term_dir(aegis_path: str) -> Path:
    d = get_memory_dir(aegis_path) / "short-term"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_long_term_dir(aegis_path: str) -> Path:
    d = get_memory_dir(aegis_path) / "long-term"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_short_term_memory(aegis_path: str, content: str, timestamp: datetime = None) -> Path:
    """
    Write a short-term memory file.
    Filename format: YYYY-MM-DD-HHmm.md
    Returns the path of the written file.
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    filename = timestamp.strftime("%Y-%m-%d-%H%M") + ".md"
    fpath = get_short_term_dir(aegis_path) / filename

    frontmatter = f"""---
timestamp: "{timestamp.isoformat()}"
period: "{(timestamp - timedelta(hours=4)).strftime('%Y-%m-%d %H:%M')} ~ {timestamp.strftime('%Y-%m-%d %H:%M')}"
---

"""
    fpath.write_text(frontmatter + content, encoding="utf-8")
    logger.info(f"Short-term memory written: {fpath}")
    return fpath


def write_long_term_memory(aegis_path: str, content: str, filename: str) -> Path:
    """
    Write or update a long-term memory file.
    If the file exists, it will be overwritten (AI provides the full updated content).
    """
    if not filename.endswith(".md"):
        filename += ".md"
    fpath = get_long_term_dir(aegis_path) / filename

    frontmatter = f"""---
topic: "{filename.replace('.md', '')}"
updated_at: "{datetime.now(timezone.utc).isoformat()}"
---

"""
    fpath.write_text(frontmatter + content, encoding="utf-8")
    logger.info(f"Long-term memory written: {fpath}")
    return fpath


def read_short_term_memories(aegis_path: str, days: int = 7) -> str:
    """
    Read all short-term memories from the last N days.
    Returns concatenated content as a single string.
    """
    d = get_short_term_dir(aegis_path)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    entries = []

    for f in sorted(d.glob("*.md")):
        try:
            # Parse date from filename: YYYY-MM-DD-HHmm.md
            date_str = f.stem  # e.g., "2026-03-07-0800"
            file_date = datetime.strptime(date_str, "%Y-%m-%d-%H%M").replace(tzinfo=timezone.utc)
            if file_date >= cutoff:
                entries.append(f"### {date_str}\n\n{f.read_text(encoding='utf-8')}")
        except (ValueError, OSError) as e:
            logger.warning(f"Skipping {f}: {e}")

    return "\n\n---\n\n".join(entries) if entries else "(no recent short-term memories)"


def read_long_term_memories(aegis_path: str) -> str:
    """
    Read all long-term memory files.
    Returns concatenated content as a single string.
    """
    d = get_long_term_dir(aegis_path)
    entries = []

    for f in sorted(d.glob("*.md")):
        try:
            entries.append(f"### {f.stem}\n\n{f.read_text(encoding='utf-8')}")
        except OSError as e:
            logger.warning(f"Skipping {f}: {e}")

    return "\n\n---\n\n".join(entries) if entries else "(no long-term memories yet)"


def parse_memory_output(ai_output: str) -> dict:
    """
    Parse AI output from the memory consolidation cron job.

    Expected format:
    ---SHORT_TERM---
    (short-term content)
    ---LONG_TERM---
    (long-term content, or "no update needed")
    ---LONG_TERM_FILE---
    (filename like recurring-issues.md)

    Returns dict with keys: short_term, long_term, long_term_file
    """
    result = {"short_term": "", "long_term": "", "long_term_file": ""}

    if "---SHORT_TERM---" in ai_output:
        parts = ai_output.split("---SHORT_TERM---", 1)
        remainder = parts[1] if len(parts) > 1 else ""

        if "---LONG_TERM---" in remainder:
            st_part, lt_remainder = remainder.split("---LONG_TERM---", 1)
            result["short_term"] = st_part.strip()

            if "---LONG_TERM_FILE---" in lt_remainder:
                lt_part, file_part = lt_remainder.split("---LONG_TERM_FILE---", 1)
                result["long_term"] = lt_part.strip()
                result["long_term_file"] = file_part.strip()
            else:
                result["long_term"] = lt_remainder.strip()
        else:
            result["short_term"] = remainder.strip()
    else:
        # If no delimiters, treat entire output as short-term
        result["short_term"] = ai_output.strip()

    return result


def process_memory_output(aegis_path: str, ai_output: str) -> dict:
    """
    Parse AI memory output and write to appropriate files.
    Returns dict with paths of written files.
    """
    parsed = parse_memory_output(ai_output)
    written = {}

    if parsed["short_term"]:
        path = write_short_term_memory(aegis_path, parsed["short_term"])
        written["short_term"] = str(path)

    lt = parsed["long_term"].lower()
    if parsed["long_term"] and "no update" not in lt and "no need" not in lt:
        filename = parsed["long_term_file"] or "general-observations.md"
        path = write_long_term_memory(aegis_path, parsed["long_term"], filename)
        written["long_term"] = str(path)

    return written


def cleanup_short_term(aegis_path: str, retention_days: int = 30) -> int:
    """
    Delete short-term memory files older than retention_days.
    Returns number of files deleted.
    """
    d = get_short_term_dir(aegis_path)
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted = 0

    for f in d.glob("*.md"):
        try:
            date_str = f.stem
            file_date = datetime.strptime(date_str, "%Y-%m-%d-%H%M").replace(tzinfo=timezone.utc)
            if file_date < cutoff:
                f.unlink()
                deleted += 1
                logger.info(f"Deleted old short-term memory: {f}")
        except (ValueError, OSError) as e:
            logger.warning(f"Skipping cleanup of {f}: {e}")

    return deleted


# ── Member-level memory (delegates to member_profile for paths) ──

def _get_member_short_term_dir(member_slug: str) -> Path:
    from app.core.member_profile import get_member_memory_dir
    d = get_member_memory_dir(member_slug) / "short-term"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_member_long_term_dir(member_slug: str) -> Path:
    from app.core.member_profile import get_member_memory_dir
    d = get_member_memory_dir(member_slug) / "long-term"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_member_short_term_memory(member_slug: str, content: str, timestamp: datetime = None) -> Path:
    """Write a short-term memory file for a specific member."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    filename = timestamp.strftime("%Y-%m-%d-%H%M%S") + ".md"
    fpath = _get_member_short_term_dir(member_slug) / filename

    frontmatter = f"""---
timestamp: "{timestamp.isoformat()}"
member: "{member_slug}"
---

"""
    fpath.write_text(frontmatter + content, encoding="utf-8")
    logger.info(f"Member short-term memory written: {fpath}")
    return fpath


def read_member_short_term_memories(member_slug: str, days: int = 7) -> str:
    """Read all short-term memories for a member from the last N days."""
    d = _get_member_short_term_dir(member_slug)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    entries = []

    for f in sorted(d.glob("*.md")):
        try:
            date_str = f.stem
            # 支援秒級 (%H%M%S) 與分鐘級 (%H%M) 兩種格式
            for fmt in ("%Y-%m-%d-%H%M%S", "%Y-%m-%d-%H%M"):
                try:
                    file_date = datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue
            else:
                continue
            if file_date >= cutoff:
                entries.append(f"### {date_str}\n\n{f.read_text(encoding='utf-8')}")
        except OSError as e:
            logger.warning(f"Skipping {f}: {e}")

    return "\n\n---\n\n".join(entries) if entries else "(no recent short-term memories)"


def cleanup_member_short_term(member_slug: str, retention_days: int = 30) -> int:
    """Delete member short-term memory files older than retention_days."""
    d = _get_member_short_term_dir(member_slug)
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted = 0

    for f in d.glob("*.md"):
        try:
            date_str = f.stem
            for fmt in ("%Y-%m-%d-%H%M%S", "%Y-%m-%d-%H%M"):
                try:
                    file_date = datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue
            else:
                continue
            if file_date < cutoff:
                f.unlink()
                deleted += 1
        except OSError:
            pass

    return deleted
