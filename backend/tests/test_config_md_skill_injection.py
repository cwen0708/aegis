"""P0-MA-02 step 2: _build_task_md 注入 ## Available Skills 段落驗證。

接線測試：把 skill_index 透過 monkeypatch 指到 tmp 目錄，驗證
- 有 skill → task md 含 `## Available Skills` 段落，且列出 skill 名稱
- 無 skill → task md **完全不含** `Available Skills` 字串
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.core import skill_index
from app.core.executor import config_md


def _write_skill(path: Path, description: str, title: str) -> None:
    path.write_text(
        f"---\ndescription: {description}\n---\n\n# {title}\n\nbody\n",
        encoding="utf-8",
    )


@pytest.fixture
def tmp_layout(tmp_path: Path, monkeypatch):
    """tmp install root + member skills dir，並 monkeypatch 兩處 _INSTALL_ROOT / get_skills_dir。"""
    install_root = tmp_path / "install"
    shared = install_root / ".aegis" / "shared" / "skills"
    shared.mkdir(parents=True)
    member = tmp_path / "members" / "xy" / "skills"
    member.mkdir(parents=True)

    # 替換 config_md 模組裡的 _INSTALL_ROOT（_build_task_md 用此 root 找 shared）
    monkeypatch.setattr(config_md, "_INSTALL_ROOT", install_root)
    # 替換 skill_index 模組裡實際被呼叫的 get_skills_dir（指到 tmp member skills）
    monkeypatch.setattr(skill_index, "get_skills_dir", lambda slug: member)

    return shared, member


async def _empty_retrieve(*args, **kwargs):
    return []


def test_task_md_includes_skills_section_when_skills_exist(tmp_layout):
    shared, member = tmp_layout
    _write_skill(shared / "shared-skill.md", "shared 用途說明", "Shared Skill")
    _write_skill(member / "member-skill.md", "member 私有技能", "Member Skill")

    with patch(
        "app.core.member_profile.get_member_memory_dir",
        return_value="/fake/memory",
    ), patch(
        "app.core.executor.memory.retrieve_task_memory",
        side_effect=_empty_retrieve,
    ):
        result = config_md.build_config_md(
            mode="task",
            soul="你是小茵。",
            member_slug="xy",
            project_path="/fake/project",
            card_content="本次測試任務內容",
        )

    assert "## Available Skills" in result
    assert "**shared-skill**" in result
    assert "**member-skill**" in result
    # 段落應落在 # 記憶 之後、# 本次任務 之前
    idx_memory = result.index("# 記憶")
    idx_skills = result.index("## Available Skills")
    idx_task = result.index("# 本次任務")
    assert idx_memory < idx_skills < idx_task


def test_task_md_omits_skills_section_when_no_skills(tmp_layout):
    # tmp_layout 已建立空的 shared / member 目錄，皆不寫入任何 skill
    with patch(
        "app.core.member_profile.get_member_memory_dir",
        return_value="/fake/memory",
    ), patch(
        "app.core.executor.memory.retrieve_task_memory",
        side_effect=_empty_retrieve,
    ):
        result = config_md.build_config_md(
            mode="task",
            soul="你是小茵。",
            member_slug="xy",
            project_path="/fake/project",
            card_content="無 skill 任務",
        )

    assert "Available Skills" not in result
