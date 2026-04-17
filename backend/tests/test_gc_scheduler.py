"""Tests for gc_scheduler module."""
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.core.card_file import CardData
from app.core.gc_scanner import TechDebtFinding
from app.core.gc_scheduler import (
    _build_dedup_key,
    _extract_dedup_key_from_title,
    _truncate_message,
    schedule_gc_scan,
)
from app.models.core import CardIndex, Project, StageList


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def test_engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def seeded_db(test_engine):
    """DB with project(id=1) + Backlog list(id=10)."""
    with Session(test_engine) as session:
        session.add(Project(id=1, name="TestProj", path="/tmp/test"))
        session.flush()
        session.add(
            StageList(id=10, project_id=1, name="Backlog", position=0)
        )
        session.commit()
    return test_engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _finding(
    file: str = "app/big.py",
    rule_id: str = "large-file",
    message: str = "File has 900 lines (max 800)",
    severity: str = "warning",
    line: int = 900,
) -> TechDebtFinding:
    return TechDebtFinding(
        file=file, line=line, rule_id=rule_id,
        message=message, severity=severity,
    )


def _card_data(
    card_id: int = 1,
    list_id: int = 10,
    title: str = "test",
    tags: list[str] | None = None,
) -> CardData:
    now = datetime.now(timezone.utc)
    return CardData(
        id=card_id, list_id=list_id, title=title,
        description=None, content="", status="idle",
        tags=tags or [], created_at=now, updated_at=now,
    )


# ---------------------------------------------------------------------------
# Unit: helper functions
# ---------------------------------------------------------------------------

class TestBuildDedupKey:
    def test_basic(self):
        assert _build_dedup_key("large-file", "app/big.py") == "large-file:app/big.py"

    def test_different_inputs(self):
        assert _build_dedup_key("todo-count", "src/x.py") == "todo-count:src/x.py"


class TestExtractDedupKeyFromTitle:
    def test_valid_title(self):
        title = "chore(gc): large-file — app/big.py (File has 900 lines)"
        assert _extract_dedup_key_from_title(title) == "large-file:app/big.py"

    def test_truncated_message(self):
        title = "chore(gc): stale-doc — docs/old.md (Document not updated for 90 da…)"
        assert _extract_dedup_key_from_title(title) == "stale-doc:docs/old.md"

    def test_invalid_title_returns_none(self):
        assert _extract_dedup_key_from_title("random title") is None

    def test_missing_separator_returns_none(self):
        assert _extract_dedup_key_from_title("chore(gc): large-file") is None


class TestTruncateMessage:
    def test_short_message_unchanged(self):
        assert _truncate_message("short") == "short"

    def test_long_message_truncated(self):
        result = _truncate_message("a" * 50, 40)
        assert len(result) == 40
        assert result.endswith("…")

    def test_exact_length_unchanged(self):
        msg = "a" * 40
        assert _truncate_message(msg, 40) == msg


# ---------------------------------------------------------------------------
# Integration: schedule_gc_scan
# ---------------------------------------------------------------------------

class TestScheduleGcScan:
    """Core integration tests — mock run_gc_scan & create_card, use real DB."""

    def test_empty_findings_creates_no_cards(self, seeded_db):
        """空 findings → 不建卡。"""
        with (
            patch("app.core.gc_scheduler.engine", seeded_db),
            patch("app.core.gc_scheduler.run_gc_scan", return_value=[]),
            patch("app.core.gc_scheduler.create_card") as mock_create,
        ):
            result = schedule_gc_scan(1, "/tmp/test")

        assert result == []
        mock_create.assert_not_called()

    def test_new_finding_creates_card(self, seeded_db):
        """新 finding → 建立卡片。"""
        finding = _finding()
        fake_card = _card_data(
            card_id=100,
            title="chore(gc): large-file — app/big.py (File has 900 lines (max 800))",
            tags=["gc-scan", "large-file"],
        )

        with (
            patch("app.core.gc_scheduler.engine", seeded_db),
            patch("app.core.gc_scheduler.run_gc_scan", return_value=[finding]),
            patch("app.core.gc_scheduler.create_card", return_value=fake_card) as mock_create,
        ):
            result = schedule_gc_scan(1, "/tmp/test")

        assert len(result) == 1
        kwargs = mock_create.call_args.kwargs
        assert kwargs["project_id"] == 1
        assert kwargs["list_id"] == 10
        assert kwargs["status"] == "idle"
        assert "gc-scan" in kwargs["tags"]
        assert "large-file" in kwargs["tags"]
        assert kwargs["title"].startswith("chore(gc): large-file — app/big.py")

    def test_existing_card_skips_duplicate(self, seeded_db):
        """已存在相同 file+rule_id 的卡片 → 跳過（去重）。"""
        finding = _finding(file="app/big.py", rule_id="large-file")

        # 種入一張已存在的 gc-scan 卡片
        with Session(seeded_db) as session:
            session.add(CardIndex(
                card_id=50, project_id=1, list_id=10,
                title="chore(gc): large-file — app/big.py (Old message)",
                tags_json=json.dumps(["gc-scan", "large-file"]),
            ))
            session.commit()

        with (
            patch("app.core.gc_scheduler.engine", seeded_db),
            patch("app.core.gc_scheduler.run_gc_scan", return_value=[finding]),
            patch("app.core.gc_scheduler.create_card") as mock_create,
        ):
            result = schedule_gc_scan(1, "/tmp/test")

        assert result == []
        mock_create.assert_not_called()

    def test_mixed_findings_dedup(self, seeded_db):
        """多個 findings 混合去重：1 existing + 2 new → 建立 2 張卡。"""
        findings = [
            _finding(file="app/big.py", rule_id="large-file"),    # 已存在
            _finding(file="app/messy.py", rule_id="todo-count",
                     message="File has 8 TODO markers (max 5)"),  # 新
            _finding(file="docs/old.md", rule_id="stale-doc",
                     message="Document not updated for 90 days"),  # 新
        ]

        # 種入一張已存在的卡片
        with Session(seeded_db) as session:
            session.add(CardIndex(
                card_id=50, project_id=1, list_id=10,
                title="chore(gc): large-file — app/big.py (File has 900 lines)",
                tags_json=json.dumps(["gc-scan", "large-file"]),
            ))
            session.commit()

        create_count = 0

        def fake_create(**kwargs):
            nonlocal create_count
            create_count += 1
            return _card_data(
                card_id=100 + create_count,
                title=kwargs["title"],
                tags=kwargs.get("tags"),
            )

        with (
            patch("app.core.gc_scheduler.engine", seeded_db),
            patch("app.core.gc_scheduler.run_gc_scan", return_value=findings),
            patch("app.core.gc_scheduler.create_card", side_effect=fake_create),
        ):
            result = schedule_gc_scan(1, "/tmp/test")

        assert len(result) == 2

    def test_no_backlog_list_returns_empty(self, test_engine):
        """專案無 Backlog list → 直接回傳空。"""
        with Session(test_engine) as session:
            session.add(Project(id=1, name="NoBacklog", path="/tmp/nb"))
            session.commit()

        with (
            patch("app.core.gc_scheduler.engine", test_engine),
            patch("app.core.gc_scheduler.run_gc_scan") as mock_scan,
        ):
            result = schedule_gc_scan(1, "/tmp/nb")

        assert result == []
        mock_scan.assert_not_called()

    def test_create_card_failure_skipped(self, seeded_db):
        """create_card 回傳 None 時不計入結果。"""
        finding = _finding()

        with (
            patch("app.core.gc_scheduler.engine", seeded_db),
            patch("app.core.gc_scheduler.run_gc_scan", return_value=[finding]),
            patch("app.core.gc_scheduler.create_card", return_value=None),
        ):
            result = schedule_gc_scan(1, "/tmp/test")

        assert result == []

    def test_same_batch_dedup(self, seeded_db):
        """同批次內相同 file+rule_id 只建一張卡。"""
        findings = [
            _finding(file="app/x.py", rule_id="large-file", message="msg A"),
            _finding(file="app/x.py", rule_id="large-file", message="msg B"),
        ]

        call_count = 0

        def fake_create(**kwargs):
            nonlocal call_count
            call_count += 1
            return _card_data(card_id=200 + call_count, title=kwargs["title"])

        with (
            patch("app.core.gc_scheduler.engine", seeded_db),
            patch("app.core.gc_scheduler.run_gc_scan", return_value=findings),
            patch("app.core.gc_scheduler.create_card", side_effect=fake_create) as mock_create,
        ):
            result = schedule_gc_scan(1, "/tmp/test")

        assert len(result) == 1
        assert mock_create.call_count == 1
