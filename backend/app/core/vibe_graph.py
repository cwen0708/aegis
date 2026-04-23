"""Vibe Graphing 純資料層：自然語言 → CronJob 草稿。

P2-MA-13 步驟 1 的最小骨架：
- `VibeCronRequest`：使用者自然語言輸入的不可變快照
- `VibeCronDraft`：LLM/子代理從自然語言產出的 CronJob 草稿（尚未落庫）
- `validate_vibe_draft`：純函式驗證器，檢查 name / prompt_template / cron_expression
- `mermaid_preview`：產生單節點 Mermaid 預覽字串

不接 LLM、不 import Session、不動 DB。接線留給後續步驟。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from croniter import croniter


@dataclass(frozen=True)
class VibeCronRequest:
    """使用者自然語言輸入的不可變快照。"""

    nl_input: str
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass(frozen=True)
class VibeCronDraft:
    """LLM/子代理從自然語言產出的 CronJob 草稿（尚未落庫）。"""

    name: str
    cron_expression: str
    prompt_template: str
    description: Optional[str] = None
    system_instruction: Optional[str] = None
    target_list_id: Optional[int] = None


def validate_vibe_draft(draft: VibeCronDraft) -> list[str]:
    """驗證草稿是否可編譯成 CronJob。

    回傳 errors list；空 list 表示通過。純函式，不拋例外。
    """
    errors: list[str] = []

    if not draft.name or not draft.name.strip():
        errors.append("name 不可為空")

    if not draft.prompt_template or not draft.prompt_template.strip():
        errors.append("prompt_template 不可為空")

    if not draft.cron_expression or not _is_valid_cron(draft.cron_expression):
        errors.append(f"cron_expression 無效：{draft.cron_expression!r}")

    return errors


def mermaid_preview(draft: VibeCronDraft) -> str:
    """產生最小 Mermaid 預覽字串（單節點 CronJob）。"""
    safe_name = (draft.name or "(unnamed)").replace('"', "'")
    safe_cron = (draft.cron_expression or "").replace('"', "'")
    return (
        "graph LR\n"
        f'    CRON["cron: {safe_cron}"] --> EXEC["{safe_name}"]'
    )


def _is_valid_cron(expr: str) -> bool:
    """croniter.is_valid 的薄包裝，把例外吞成 False。"""
    try:
        return bool(croniter.is_valid(expr))
    except Exception:
        return False
