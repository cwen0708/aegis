"""GC Scanner — 技術債掃描核心模組（Step 1 MVP）。

掃描原始碼目錄，從註解中偵測 TODO / FIXME / XXX / HACK 技術債標記，
並以不可變 dataclass 回傳。後續會由排程器與自動建卡模組呼叫此函式。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

__all__ = ["TechDebtMarker", "scan_todo_comments"]

_MARKER_PATTERN = re.compile(r"\b(TODO|FIXME|XXX|HACK)[:\s]")
_EXCLUDED_DIRS = frozenset({"__pycache__", "venv", ".git", "node_modules"})


@dataclass(frozen=True)
class TechDebtMarker:
    file_path: str
    line_no: int
    kind: str
    content: str


def scan_todo_comments(
    root: Path,
    include_ext: Iterable[str] = (".py",),
) -> list[TechDebtMarker]:
    """遞迴掃描 root，回傳所有技術債 marker（依檔案與行號排序）。

    Args:
        root: 掃描起始目錄
        include_ext: 納入掃描的副檔名集合
    """
    if not root.is_dir():
        return []

    allowed_ext = tuple(include_ext)
    markers: list[TechDebtMarker] = []

    for path in _iter_source_files(root, allowed_ext):
        markers.extend(_scan_file(path))

    return sorted(markers, key=lambda m: (m.file_path, m.line_no))


def _iter_source_files(root: Path, allowed_ext: tuple[str, ...]) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in allowed_ext:
            continue
        if _is_excluded(path, root):
            continue
        yield path


def _is_excluded(path: Path, root: Path) -> bool:
    try:
        relative_parts = path.relative_to(root).parts
    except ValueError:
        relative_parts = path.parts
    return any(part in _EXCLUDED_DIRS for part in relative_parts)


def _scan_file(path: Path) -> list[TechDebtMarker]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    file_path = str(path)
    results: list[TechDebtMarker] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        match = _MARKER_PATTERN.search(line)
        if match is None:
            continue
        results.append(
            TechDebtMarker(
                file_path=file_path,
                line_no=idx,
                kind=match.group(1),
                content=line.strip(),
            )
        )
    return results
