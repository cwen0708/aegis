"""Tests for backend/app/core/team_templates.py (P0-MA-01 骨架)."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.team_templates import (
    TemplateDef,
    _SafeDict,
    load_template,
    render_task,
)


BUILTIN_DIR = Path(__file__).resolve().parents[1] / "templates" / "teams"


def test_load_sample_template():
    """內建 sample.toml 能成功解析成 TemplateDef 並具備正確結構。"""
    tpl = load_template("sample", builtin_dir=BUILTIN_DIR)

    assert isinstance(tpl, TemplateDef)
    assert tpl.name == "sample"
    assert tpl.leader.name == "leader"
    assert tpl.leader.type == "general-purpose"
    assert len(tpl.agents) == 2
    assert tpl.agents[0].name == "researcher"
    assert tpl.agents[1].name == "implementer"
    assert len(tpl.tasks) == 1
    assert tpl.tasks[0].owner == "leader"
    assert tpl.command == ["claude"]
    assert tpl.backend == "tmux"


def test_user_dir_overrides_builtin(tmp_path):
    """user_dir 中同名 TOML 應優先於 builtin_dir。"""
    user_dir = tmp_path / "user_teams"
    user_dir.mkdir()
    (user_dir / "sample.toml").write_text(
        """
[template]
name = "sample"
description = "user override"

[template.leader]
name = "user-leader"
""".strip(),
        encoding="utf-8",
    )

    tpl = load_template("sample", builtin_dir=BUILTIN_DIR, user_dir=user_dir)

    assert tpl.description == "user override"
    assert tpl.leader.name == "user-leader"
    assert tpl.agents == []  # user 版本未定義 agents


def test_user_dir_falls_back_to_builtin(tmp_path):
    """user_dir 無此模板時應退回 builtin_dir。"""
    empty_user_dir = tmp_path / "empty"
    empty_user_dir.mkdir()

    tpl = load_template(
        "sample", builtin_dir=BUILTIN_DIR, user_dir=empty_user_dir
    )
    assert tpl.leader.name == "leader"


def test_safe_dict_preserves_unknown_placeholder():
    """render_task 遇未知 placeholder 應保留原樣，不拋 KeyError。"""
    result = render_task("hi {name}, goal {goal}", name="A")
    assert result == "hi A, goal {goal}"


def test_safe_dict_class_directly():
    """_SafeDict.__missing__ 行為直接驗證。"""
    d = _SafeDict({"a": "1"})
    assert d["a"] == "1"
    assert d["unknown"] == "{unknown}"


def test_render_task_does_not_mutate_input():
    """render_task 為純函式，不改變輸入字串。"""
    template = "hello {name}"
    before = template
    render_task(template, name="X")
    assert template == before


def test_missing_required_field_raises(tmp_path):
    """TOML 缺少必要欄位（name）時 Pydantic 應拋 ValidationError。"""
    user_dir = tmp_path / "bad"
    user_dir.mkdir()
    (user_dir / "broken.toml").write_text(
        """
[template]
description = "missing required 'name' and 'leader'"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_template("broken", builtin_dir=BUILTIN_DIR, user_dir=user_dir)


def test_missing_template_raises_file_not_found(tmp_path):
    """找不到任何模板檔時應拋 FileNotFoundError。"""
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        load_template("nonexistent-xyz", builtin_dir=empty)
