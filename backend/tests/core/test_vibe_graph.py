"""P2-MA-13 步驟 1：Vibe Graphing 骨架測試。

測試純資料層：VibeCronRequest / VibeCronDraft / validate_vibe_draft / mermaid_preview
不觸及 LLM / DB / Session，僅驗證 frozen dataclass 與純函式行為。
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest

from app.core.vibe_graph import (
    VibeCronDraft,
    VibeCronRequest,
    mermaid_preview,
    validate_vibe_draft,
)


def test_vibe_cron_request_is_frozen():
    req = VibeCronRequest(nl_input="每天早上八點提醒我")
    with pytest.raises(dataclasses.FrozenInstanceError):
        req.nl_input = "改掉"  # type: ignore[misc]


def test_vibe_cron_request_default_created_at_is_utc():
    req = VibeCronRequest(nl_input="hello")
    assert isinstance(req.created_at, datetime)
    assert req.created_at.tzinfo is not None
    assert req.created_at.utcoffset() == timezone.utc.utcoffset(req.created_at)


def test_vibe_cron_draft_has_required_fields():
    draft = VibeCronDraft(
        name="morning-reminder",
        cron_expression="0 8 * * *",
        prompt_template="提醒我：{task}",
    )
    assert draft.name == "morning-reminder"
    assert draft.cron_expression == "0 8 * * *"
    assert draft.prompt_template == "提醒我：{task}"
    assert draft.description is None
    assert draft.system_instruction is None
    assert draft.target_list_id is None


def test_vibe_cron_draft_is_frozen():
    draft = VibeCronDraft(
        name="x", cron_expression="0 8 * * *", prompt_template="p"
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        draft.name = "y"  # type: ignore[misc]


def test_validator_catches_empty_name():
    draft = VibeCronDraft(
        name="   ",
        cron_expression="0 8 * * *",
        prompt_template="ok",
    )
    errors = validate_vibe_draft(draft)
    assert any("name" in e for e in errors)


def test_validator_catches_invalid_cron():
    draft = VibeCronDraft(
        name="valid-name",
        cron_expression="not a cron",
        prompt_template="ok",
    )
    errors = validate_vibe_draft(draft)
    assert len(errors) > 0
    assert any("cron_expression" in e for e in errors)


def test_validator_catches_empty_prompt():
    draft = VibeCronDraft(
        name="valid-name",
        cron_expression="0 8 * * *",
        prompt_template="",
    )
    errors = validate_vibe_draft(draft)
    assert any("prompt_template" in e for e in errors)


def test_validator_accepts_valid_draft():
    draft = VibeCronDraft(
        name="daily-digest",
        cron_expression="0 8 * * *",
        prompt_template="總結今日工作",
    )
    assert validate_vibe_draft(draft) == []


def test_mermaid_preview_contains_cron_and_name():
    draft = VibeCronDraft(
        name="daily-digest",
        cron_expression="0 8 * * *",
        prompt_template="p",
    )
    out = mermaid_preview(draft)
    assert "0 8 * * *" in out
    assert "daily-digest" in out
