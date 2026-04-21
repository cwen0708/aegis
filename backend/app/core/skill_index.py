"""Skill index — 從 shared / member skills 目錄建立索引（純函式）。

供後續步驟（P0-MA-02 step 2/3）注入到 CLAUDE.md 的 `## Available Skills` 區段，
取代把整個 .md 檔案 copy 進 `.claude/skills/` 的做法，改以 summary + 懶載入節省 token。

本模組**只建立機制**，不被 task_workspace.py / config_md.py / worker.py / providers.py 呼叫。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel

from app.core.member_profile import get_skills_dir

logger = logging.getLogger(__name__)

# 與 member_profile / config_md 使用相同的 install root 解析方式
_INSTALL_ROOT = Path(__file__).resolve().parent.parent.parent

_SUMMARY_MAX = 120

# 僅匹配檔案開頭的 `---\n...\n---\n` YAML frontmatter
_FM_RE = re.compile(r"\A---\s*\n(.*?\n)---\s*(?:\n|$)", re.DOTALL)


class SkillMetadata(BaseModel):
    """單一 skill 的中繼資料（不可變，純資料）。"""

    name: str
    summary: str
    scope: Literal["shared", "member"]
    path: Path
    alwaysApply: bool = False


def parse_frontmatter(md_content: str) -> dict:
    """解析 YAML frontmatter，回傳 dict；無 frontmatter 或解析失敗回傳 {}。

    不 mutate 輸入字串。
    """
    if not md_content:
        return {}
    match = _FM_RE.match(md_content)
    if not match:
        return {}
    yaml_block = match.group(1)
    try:
        parsed = yaml.safe_load(yaml_block)
    except yaml.YAMLError as exc:
        logger.warning("skill_index: frontmatter YAML parse failed: %s", exc)
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _strip_frontmatter(md_content: str) -> str:
    """回傳去掉 frontmatter 之後的 markdown 本體。不 mutate 輸入。"""
    match = _FM_RE.match(md_content)
    if not match:
        return md_content
    return md_content[match.end():]


def _first_paragraph_after_h1(body: str) -> str:
    """找 H1 之後第一個非空段落；找不到回傳 ''。"""
    lines = body.splitlines()
    i = 0
    # 找到第一個 H1
    while i < len(lines):
        if lines[i].lstrip().startswith("# "):
            i += 1
            break
        i += 1
    else:
        return ""
    # 跳過空行
    while i < len(lines) and not lines[i].strip():
        i += 1
    # 收集連續非空、非 heading 行
    collected: list[str] = []
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            break
        if line.lstrip().startswith("#"):
            break
        collected.append(line.strip())
        i += 1
    return " ".join(collected)


def _truncate(text: str, limit: int = _SUMMARY_MAX) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def extract_summary(md_content: str, fm: dict) -> str:
    """優先序：frontmatter.description → frontmatter.summary → H1 後第一段 → ''。

    回傳值長度上限 120 字（超過截斷並補「…」）。不 mutate 輸入。
    """
    for key in ("description", "summary"):
        value = fm.get(key) if isinstance(fm, dict) else None
        if isinstance(value, str) and value.strip():
            return _truncate(value)
    body = _strip_frontmatter(md_content)
    paragraph = _first_paragraph_after_h1(body)
    if paragraph:
        return _truncate(paragraph)
    return ""


def _load_from_dir(
    directory: Path, scope: Literal["shared", "member"]
) -> list[SkillMetadata]:
    """掃描 *.md（非遞迴）。目錄不存在回傳 []。"""
    if not directory.exists() or not directory.is_dir():
        return []
    out: list[SkillMetadata] = []
    for md_file in sorted(directory.glob("*.md")):
        try:
            content = md_file.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("skill_index: cannot read %s: %s", md_file, exc)
            continue
        fm = parse_frontmatter(content)
        always_apply = bool(fm.get("alwaysApply")) if isinstance(fm, dict) else False
        summary = extract_summary(content, fm)
        out.append(
            SkillMetadata(
                name=md_file.stem,
                summary=summary,
                scope=scope,
                path=md_file,
                alwaysApply=always_apply,
            )
        )
    return out


def load_skill_index(
    member_slug: str, install_root: Optional[Path] = None
) -> list[SkillMetadata]:
    """先掃 shared，再掃 member skills；同名 member 覆蓋 shared。

    回傳 list[SkillMetadata] 新物件，按 name 排序。
    """
    root = install_root if install_root is not None else _INSTALL_ROOT
    shared_dir = root / ".aegis" / "shared" / "skills"
    shared = _load_from_dir(shared_dir, "shared")
    try:
        member_dir = get_skills_dir(member_slug)
    except ValueError as exc:
        logger.warning("skill_index: invalid member slug %r: %s", member_slug, exc)
        member = []
    else:
        member = _load_from_dir(member_dir, "member")

    by_name: dict[str, SkillMetadata] = {s.name: s for s in shared}
    for item in member:
        by_name[item.name] = item
    return sorted(by_name.values(), key=lambda s: s.name)


def render_skill_list(index: list[SkillMetadata]) -> str:
    """格式化成 Markdown 清單，供注入 CLAUDE.md 使用。

    格式：
        ## Available Skills
        - **name** _(scope)_: summary
        - ★ **always-on** _(shared)_: summary    # alwaysApply=true 加 ★
    """
    lines = ["## Available Skills"]
    if not index:
        lines.append("_(無)_")
        return "\n".join(lines)
    for item in index:
        star = "★ " if item.alwaysApply else ""
        summary = item.summary if item.summary else "_(無描述)_"
        lines.append(f"- {star}**{item.name}** _({item.scope})_: {summary}")
    return "\n".join(lines)
