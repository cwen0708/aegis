"""Tests for Plans API endpoints."""
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api.plans import list_card_plans, get_card_plan
from app.core.plan_store import save_plan, list_plans, load_plan


def test_list_empty():
    """GET /plans/9999 → 回傳空列表"""
    with patch("app.api.plans.list_plans", return_value=[]):
        result = list_card_plans(9999)

    assert result.card_id == 9999
    assert result.plans == []


def test_list_after_save(tmp_path: Path):
    """save 後 GET → 回傳正確版本列表"""
    save_plan(42, 1, "# Plan v1", base=tmp_path)
    save_plan(42, 2, "# Plan v2", base=tmp_path)

    entries = list_plans(42, base=tmp_path)
    with patch("app.api.plans.list_plans", return_value=entries):
        result = list_card_plans(42)

    assert result.card_id == 42
    assert len(result.plans) == 2
    assert result.plans[0].round_num == 1
    assert result.plans[0].filename == "round-1.md"
    assert result.plans[1].round_num == 2
    assert result.plans[1].filename == "round-2.md"


def test_get_specific_round(tmp_path: Path):
    """GET /plans/{id}/{round} → 回傳內容"""
    text = "# Round 3 Plan\nStep 1: refactor module."
    save_plan(10, 3, text, base=tmp_path)

    loaded = load_plan(10, 3, base=tmp_path)
    with patch("app.api.plans.load_plan", return_value=loaded):
        result = get_card_plan(10, 3)

    assert result.card_id == 10
    assert result.round_num == 3
    assert result.content == text


def test_get_missing_round():
    """GET /plans/{id}/999 → 404"""
    with patch("app.api.plans.load_plan", return_value=None):
        with pytest.raises(HTTPException) as exc_info:
            get_card_plan(1, 999)

    assert exc_info.value.status_code == 404
