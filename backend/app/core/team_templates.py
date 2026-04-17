"""TOML 團隊模板載入器（ClawTeam 模式）。

本模組提供 Pydantic 資料模型與最小載入機制，用於定義多代理團隊的組成
（leader、agents、tasks）。支援 user override：同名 TOML 放在 user_dir
時會優先於 builtin_dir 載入。

設計原則：
- 不變性：render_task 以純函式處理 placeholder 替換，不修改輸入。
- 無 mutable 全域狀態：所有配置經由參數傳入。
- 未知 placeholder 保留原樣（_SafeDict），供上層再次渲染。
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field


class AgentDef(BaseModel):
    """單一代理定義。"""

    name: str
    type: str = "general-purpose"
    task: str = ""
    command: list[str] | None = None


class TaskDef(BaseModel):
    """單一任務定義。"""

    subject: str
    description: str = ""
    owner: str = ""


class TemplateDef(BaseModel):
    """團隊模板定義。"""

    name: str
    description: str = ""
    command: list[str] = Field(default_factory=lambda: ["claude"])
    backend: str = "tmux"
    leader: AgentDef
    agents: list[AgentDef] = Field(default_factory=list)
    tasks: list[TaskDef] = Field(default_factory=list)


class _SafeDict(dict):
    """dict 子類：遇到未知 key 時回傳 ``"{key}"`` 保留原 placeholder。

    用途：允許 render_task 分階段替換 —— 上游先填部分變數，
    下游再填剩餘變數，不會因未知 key 而拋 KeyError。
    """

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_task(task: str, **vars: object) -> str:
    """以 ``vars`` 替換 ``task`` 中的 ``{placeholder}``，未知者保留原樣。

    純函式，不修改輸入字串與 vars。
    """
    return task.format_map(_SafeDict(vars))


def _read_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def load_template(
    name: str,
    builtin_dir: Path,
    user_dir: Path | None = None,
) -> TemplateDef:
    """載入指定名稱的團隊模板。

    查找順序：
    1. ``user_dir / f"{name}.toml"``（若 user_dir 存在且檔案存在）
    2. ``builtin_dir / f"{name}.toml"``

    TOML 結構預期：
        [template]
        name = "..."
        ...
        [template.leader]
        name = "..."
        [[template.agents]]
        ...
        [[template.tasks]]
        ...

    Raises:
        FileNotFoundError: 兩個目錄皆無此模板。
        pydantic.ValidationError: TOML 缺少必要欄位或型別錯誤。
    """
    target: Path | None = None
    if user_dir is not None:
        candidate = user_dir / f"{name}.toml"
        if candidate.is_file():
            target = candidate
    if target is None:
        candidate = builtin_dir / f"{name}.toml"
        if candidate.is_file():
            target = candidate
    if target is None:
        raise FileNotFoundError(
            f"team template '{name}' not found in user_dir={user_dir} "
            f"or builtin_dir={builtin_dir}"
        )

    raw = _read_toml(target)
    template_section = raw.get("template", raw)
    return TemplateDef.model_validate(template_section)


__all__ = [
    "AgentDef",
    "TaskDef",
    "TemplateDef",
    "render_task",
    "load_template",
]
