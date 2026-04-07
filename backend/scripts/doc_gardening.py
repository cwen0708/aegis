#!/usr/bin/env python3
"""
Aegis Doc Gardening Script
掃描專案文件新鮮度，偵測過時文件與壞連結，輸出 FRESHNESS_REPORT.md
"""
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
BACKEND_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent

STALE_DAYS = 30
OVERDUE_DAYS = 60

# 掃描目標
SCAN_PATTERNS = [
    ".claude/skills/*.md",
    "docs/**/*.md",
    "CLAUDE.md",
]


def collect_files() -> list[Path]:
    """收集所有需要掃描的文件"""
    files = []
    for pattern in SCAN_PATTERNS:
        matched = sorted(PROJECT_ROOT.glob(pattern))
        files.extend(matched)
    # 去重（保持順序）
    seen = set()
    result = []
    for f in files:
        resolved = f.resolve()
        if resolved not in seen:
            seen.add(resolved)
            result.append(f)
    return result


def get_last_modified(file_path: Path) -> datetime | None:
    """用 git log 取得檔案最後修改時間"""
    try:
        rel = file_path.relative_to(PROJECT_ROOT)
        proc = subprocess.run(
            ["git", "log", "-1", "--format=%aI", "--", str(rel)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return datetime.fromisoformat(proc.stdout.strip())
    except Exception:
        pass
    # fallback: 檔案系統修改時間
    try:
        mtime = file_path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc)
    except Exception:
        return None


def classify_freshness(last_modified: datetime | None, now: datetime) -> tuple[int, str]:
    """回傳 (天數, 狀態標記)"""
    if last_modified is None:
        return (-1, "unknown")
    delta = now - last_modified
    days = delta.days
    if days >= OVERDUE_DAYS:
        return (days, "overdue")
    if days >= STALE_DAYS:
        return (days, "stale")
    return (days, "fresh")


def status_emoji(status: str) -> str:
    """狀態對應的 emoji 標記"""
    return {
        "fresh": "✅",
        "stale": "⚠️",
        "overdue": "🔴",
        "unknown": "❓",
    }.get(status, "")


def find_broken_links(file_path: Path) -> list[str]:
    """掃描 Markdown 檔案中引用的本地路徑，檢查是否存在"""
    broken = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return broken

    # 匹配 Markdown 連結 [text](path) 和裸路徑引用
    link_pattern = re.compile(r'\[.*?\]\(([^)]+)\)')
    # 匹配行內程式碼中的檔案路徑
    code_path_pattern = re.compile(r'`((?:[\w./-]+/)+[\w.-]+)`')

    candidates = set()
    for match in link_pattern.finditer(content):
        ref = match.group(1).strip()
        candidates.add(ref)
    for match in code_path_pattern.finditer(content):
        ref = match.group(1).strip()
        candidates.add(ref)

    for ref in sorted(candidates):
        # 跳過 URL、錨點、mailto
        if ref.startswith(("http://", "https://", "#", "mailto:")):
            continue
        # 去除錨點部分
        clean = ref.split("#")[0]
        if not clean:
            continue
        # 相對於檔案目錄或專案根目錄解析
        resolved_from_file = file_path.parent / clean
        resolved_from_root = PROJECT_ROOT / clean
        if not resolved_from_file.exists() and not resolved_from_root.exists():
            broken.append(ref)

    return broken


def generate_report(
    files: list[Path],
    freshness: dict[Path, tuple[int, str]],
    broken_links: dict[Path, list[str]],
    now: datetime,
) -> str:
    """產生 FRESHNESS_REPORT.md 內容"""
    lines = [
        "# Doc Freshness Report",
        "",
        f"> Generated: {now.strftime('%Y-%m-%d %H:%M UTC')}",
        f"> Thresholds: stale = {STALE_DAYS} days, overdue = {OVERDUE_DAYS} days",
        "",
        "## Summary",
        "",
    ]

    total = len(files)
    fresh_count = sum(1 for _, (_, s) in freshness.items() if s == "fresh")
    stale_count = sum(1 for _, (_, s) in freshness.items() if s == "stale")
    overdue_count = sum(1 for _, (_, s) in freshness.items() if s == "overdue")
    broken_count = sum(len(v) for v in broken_links.values())

    lines.append(f"| Metric | Count |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total files scanned | {total} |")
    lines.append(f"| ✅ Fresh | {fresh_count} |")
    lines.append(f"| ⚠️ Stale (>{STALE_DAYS}d) | {stale_count} |")
    lines.append(f"| 🔴 Overdue (>{OVERDUE_DAYS}d) | {overdue_count} |")
    lines.append(f"| 🔗 Broken links | {broken_count} |")
    lines.append("")

    # Freshness 表格
    lines.append("## File Freshness")
    lines.append("")
    lines.append("| Status | File | Days Since Update |")
    lines.append("|--------|------|-------------------|")

    sorted_files = sorted(files, key=lambda f: freshness.get(f, (-1, ""))[0], reverse=True)
    for f in sorted_files:
        days, status = freshness.get(f, (-1, "unknown"))
        rel = f.relative_to(PROJECT_ROOT)
        emoji = status_emoji(status)
        days_str = str(days) if days >= 0 else "N/A"
        lines.append(f"| {emoji} {status} | `{rel}` | {days_str} |")

    lines.append("")

    # Broken links 區段
    if broken_count > 0:
        lines.append("## Broken Links")
        lines.append("")
        for f in sorted_files:
            blinks = broken_links.get(f, [])
            if not blinks:
                continue
            rel = f.relative_to(PROJECT_ROOT)
            lines.append(f"### `{rel}`")
            lines.append("")
            for link in blinks:
                lines.append(f"- `{link}`")
            lines.append("")

    return "\n".join(lines)


def main() -> int:
    now = datetime.now(tz=timezone.utc)

    print("[DocGardening] Scanning documentation files...")
    files = collect_files()

    if not files:
        print("[DocGardening] No documentation files found.")
        return 0

    print(f"[DocGardening] Found {len(files)} files to scan.")

    # 取得新鮮度
    freshness: dict[Path, tuple[int, str]] = {}
    for f in files:
        last_mod = get_last_modified(f)
        freshness[f] = classify_freshness(last_mod, now)

    # 掃描壞連結
    broken_links: dict[Path, list[str]] = {}
    for f in files:
        broken = find_broken_links(f)
        if broken:
            broken_links[f] = broken

    # 產出報告
    report = generate_report(files, freshness, broken_links, now)
    report_path = PROJECT_ROOT / "FRESHNESS_REPORT.md"
    report_path.write_text(report, encoding="utf-8")

    print(f"[DocGardening] Report written to {report_path}")

    # 摘要
    stale = sum(1 for _, (_, s) in freshness.items() if s == "stale")
    overdue = sum(1 for _, (_, s) in freshness.items() if s == "overdue")
    broken_total = sum(len(v) for v in broken_links.values())

    if overdue > 0:
        print(f"[DocGardening] WARN: {overdue} file(s) OVERDUE (>{OVERDUE_DAYS} days)")
    if stale > 0:
        print(f"[DocGardening] WARN: {stale} file(s) stale (>{STALE_DAYS} days)")
    if broken_total > 0:
        print(f"[DocGardening] WARN: {broken_total} broken link(s) detected")
    if overdue == 0 and stale == 0 and broken_total == 0:
        print("[DocGardening] OK: All docs are fresh and links are valid!")

    return 0


if __name__ == "__main__":
    sys.exit(main())
