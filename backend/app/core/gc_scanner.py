"""
GC Scanner — 技術債掃描模組

掃描專案目錄，偵測技術債指標（大檔案、過多 TODO、過期文件）。
作為 GC 排程功能的 Step 1，提供可擴充的規則框架。
"""
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Protocol


@dataclass(frozen=True)
class TechDebtFinding:
    file: str
    line: int
    rule_id: str
    message: str
    severity: Literal["warning", "error"]


class GCRule(Protocol):
    def scan(self, project_path: str) -> list[TechDebtFinding]: ...


# ---------------------------------------------------------------------------
# Rule implementations
# ---------------------------------------------------------------------------

class LargeFileRule:
    """Python 檔案超過 800 行 -> warning"""

    MAX_LINES = 800

    def scan(self, project_path: str) -> list[TechDebtFinding]:
        findings: list[TechDebtFinding] = []
        root = Path(project_path)

        for py_file in root.rglob("*.py"):
            if _is_excluded(py_file):
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            line_count = content.count("\n") + (
                1 if content and not content.endswith("\n") else 0
            )
            if line_count > self.MAX_LINES:
                findings.append(
                    TechDebtFinding(
                        file=str(py_file.relative_to(root)),
                        line=line_count,
                        rule_id="large-file",
                        message=f"File has {line_count} lines (max {self.MAX_LINES})",
                        severity="warning",
                    ),
                )
        return findings


class TodoCountRule:
    """單檔 TODO/FIXME/HACK 超過 5 個 -> warning"""

    MAX_TODOS = 5
    _PATTERN = re.compile(r"\b(TODO|FIXME|HACK)\b", re.IGNORECASE)

    def scan(self, project_path: str) -> list[TechDebtFinding]:
        findings: list[TechDebtFinding] = []
        root = Path(project_path)

        for py_file in root.rglob("*.py"):
            if _is_excluded(py_file):
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            matches = self._PATTERN.findall(content)
            if len(matches) > self.MAX_TODOS:
                findings.append(
                    TechDebtFinding(
                        file=str(py_file.relative_to(root)),
                        line=0,
                        rule_id="todo-count",
                        message=f"File has {len(matches)} TODO/FIXME/HACK markers (max {self.MAX_TODOS})",
                        severity="warning",
                    ),
                )
        return findings


class StaleDocRule:
    """Markdown 文件超過 60 天未更新 -> warning"""

    MAX_AGE_DAYS = 60

    def scan(self, project_path: str) -> list[TechDebtFinding]:
        findings: list[TechDebtFinding] = []
        root = Path(project_path)

        for md_file in root.rglob("*.md"):
            if _is_excluded(md_file):
                continue
            last_modified = _git_last_modified(str(md_file), project_path)
            if last_modified is None:
                continue
            age = datetime.now(tz=timezone.utc) - last_modified
            if age > timedelta(days=self.MAX_AGE_DAYS):
                findings.append(
                    TechDebtFinding(
                        file=str(md_file.relative_to(root)),
                        line=0,
                        rule_id="stale-doc",
                        message=f"Document not updated for {age.days} days (max {self.MAX_AGE_DAYS})",
                        severity="warning",
                    ),
                )
        return findings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EXCLUDED_DIRS = {"venv", "node_modules", ".git", "__pycache__", ".tox", ".eggs"}


def _is_excluded(path: Path) -> bool:
    return any(part in _EXCLUDED_DIRS for part in path.parts)


def _git_last_modified(file_path: str, cwd: str) -> datetime | None:
    """透過 git log 取得檔案最後修改時間（UTC ISO）。"""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%aI", "--", file_path],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        return datetime.fromisoformat(result.stdout.strip())
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Registry & entry point
# ---------------------------------------------------------------------------

DEFAULT_GC_RULES: list[GCRule] = [
    LargeFileRule(),
    TodoCountRule(),
    StaleDocRule(),
]


def run_gc_scan(
    project_path: str,
    *,
    rules: list[GCRule] | None = None,
) -> list[TechDebtFinding]:
    """掃描專案目錄的技術債，回傳所有發現。

    Args:
        project_path: 專案根目錄路徑
        rules: 自訂規則清單，預設使用 DEFAULT_GC_RULES
    """
    root = Path(project_path)
    if not root.is_dir():
        return []

    active_rules = rules if rules is not None else DEFAULT_GC_RULES

    findings: list[TechDebtFinding] = []
    for rule in active_rules:
        findings.extend(rule.scan(project_path))

    return findings
