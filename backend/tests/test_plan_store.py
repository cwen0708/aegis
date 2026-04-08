"""Tests for the file-based plan store."""
from pathlib import Path

from app.core.plan_store import PlanEntry, list_plans, load_plan, save_plan


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    text = "# Plan\n\nStep 1: do the thing."
    path = save_plan(1, 1, text, base=tmp_path)

    assert path == tmp_path / "1" / "round-1.md"
    assert path.exists()
    assert load_plan(1, 1, base=tmp_path) == text


def test_load_missing_returns_none(tmp_path: Path) -> None:
    assert load_plan(999, 1, base=tmp_path) is None


def test_list_sorted_order(tmp_path: Path) -> None:
    save_plan(2, 3, "round 3", base=tmp_path)
    save_plan(2, 1, "round 1", base=tmp_path)
    save_plan(2, 2, "round 2", base=tmp_path)

    entries = list_plans(2, base=tmp_path)

    assert len(entries) == 3
    assert [e.round_num for e in entries] == [1, 2, 3]
    for e in entries:
        assert isinstance(e, PlanEntry)
        assert e.card_id == 2


def test_list_empty_card(tmp_path: Path) -> None:
    assert list_plans(42, base=tmp_path) == []


def test_multiple_versions_accumulate(tmp_path: Path) -> None:
    save_plan(5, 1, "v1", base=tmp_path)
    save_plan(5, 2, "v2", base=tmp_path)
    save_plan(5, 3, "v3", base=tmp_path)

    assert load_plan(5, 1, base=tmp_path) == "v1"
    assert load_plan(5, 2, base=tmp_path) == "v2"
    assert load_plan(5, 3, base=tmp_path) == "v3"
    assert len(list_plans(5, base=tmp_path)) == 3
