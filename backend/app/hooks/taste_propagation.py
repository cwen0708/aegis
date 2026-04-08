"""
TastePropagationHook — 從任務輸出中萃取 taste 規則並寫入 golden-rules

掃描 AI 輸出中的 <!-- taste: ... --> 標記，
自動萃取規則文字並 append 到成員的 golden-rules.md 檔案。
重複規則會自動跳過。
"""
import logging
import re
from pathlib import Path

from app.hooks import Hook, TaskContext

logger = logging.getLogger(__name__)

# 匹配 <!-- taste: 規則文字 --> 標記
_TASTE_PATTERN = re.compile(r"<!--\s*taste:\s*(.+?)\s*-->")

# golden-rules.md 的 YAML frontmatter
_FRONTMATTER = """---
name: golden-rules
description: 從 review 意見自動萃取的開發規則
type: auto-generated
---
"""


def _read_existing_rules(path: Path) -> set[str]:
    """讀取現有 golden-rules.md 中的規則（以 `- ` 開頭的行）。"""
    if not path.exists():
        return set()
    content = path.read_text(encoding="utf-8")
    rules: set[str] = set()
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            rules.add(stripped[2:].strip())
    return rules


def _ensure_golden_rules(path: Path) -> None:
    """若 golden-rules.md 不存在則建立（含 frontmatter）。"""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_FRONTMATTER, encoding="utf-8")


class TastePropagationHook(Hook):
    """掃描任務輸出中的 taste 標記，萃取規則寫入 golden-rules.md。"""

    def on_complete(self, ctx: TaskContext) -> None:
        if not ctx.output:
            return
        if not ctx.member_slug:
            return

        # 萃取所有 taste 標記
        matches = _TASTE_PATTERN.findall(ctx.output)
        if not matches:
            return

        # 去重：保持順序
        new_rules: list[str] = list(dict.fromkeys(m.strip() for m in matches))

        # 取得 golden-rules.md 路徑
        from app.core.member_profile import get_member_dir
        member_dir = get_member_dir(ctx.member_slug)
        rules_path = member_dir / "golden-rules.md"

        _ensure_golden_rules(rules_path)
        existing = _read_existing_rules(rules_path)

        # 過濾已存在的規則
        to_add = [r for r in new_rules if r not in existing]
        if not to_add:
            logger.debug(
                "[TastePropagation] all %d rules already exist, skipping",
                len(new_rules),
            )
            return

        # Append 新規則
        lines = "\n".join(f"- {rule}" for rule in to_add) + "\n"
        with open(rules_path, "a", encoding="utf-8") as f:
            f.write(lines)

        logger.info(
            "[TastePropagation] appended %d rules to %s",
            len(to_add),
            rules_path,
        )
