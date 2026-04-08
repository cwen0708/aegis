"""Tests for GC API endpoints."""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine

from app.api.gc import GCScanRequest, trigger_gc_scan
from app.core.card_file import CardData
from app.models.core import Project


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
    """DB with project(id=1, path='/tmp/test')."""
    with Session(test_engine) as session:
        session.add(Project(id=1, name="TestProj", path="/tmp/test"))
        session.commit()
    return test_engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_data(
    card_id: int = 1,
    title: str = "test",
    tags: list[str] | None = None,
) -> CardData:
    now = datetime.now(timezone.utc)
    return CardData(
        id=card_id,
        list_id=10,
        title=title,
        description=None,
        content="",
        status="idle",
        tags=tags or [],
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Tests: POST /gc/scan
# ---------------------------------------------------------------------------

class TestTriggerGcScan:
    def test_returns_created_cards(self, seeded_db):
        """正常掃描 → 回傳新建卡片。"""
        fake_card = _card_data(
            card_id=100,
            title="chore(gc): large-file — app/big.py (File has 900 lines)",
            tags=["gc-scan", "large-file"],
        )

        with Session(seeded_db) as session:
            with patch("app.api.gc.schedule_gc_scan", return_value=[fake_card]):
                result = trigger_gc_scan(GCScanRequest(project_id=1), session=session)

        assert result.project_id == 1
        assert result.cards_created == 1
        assert len(result.cards) == 1
        assert result.cards[0].title == fake_card.title
        assert result.cards[0].status == "idle"
        assert "gc-scan" in result.cards[0].tags

    def test_empty_findings(self, seeded_db):
        """無技術債 → 回傳空清單。"""
        with Session(seeded_db) as session:
            with patch("app.api.gc.schedule_gc_scan", return_value=[]):
                result = trigger_gc_scan(GCScanRequest(project_id=1), session=session)

        assert result.cards_created == 0
        assert result.cards == []

    def test_project_not_found(self, seeded_db):
        """專案不存在 → 404。"""
        with Session(seeded_db) as session:
            with pytest.raises(HTTPException) as exc_info:
                trigger_gc_scan(GCScanRequest(project_id=999), session=session)
        assert exc_info.value.status_code == 404

    def test_project_no_path(self, test_engine):
        """專案無路徑 → 400。"""
        with Session(test_engine) as session:
            session.add(Project(id=5, name="NoPath", path=""))
            session.commit()

        with Session(test_engine) as session:
            with pytest.raises(HTTPException) as exc_info:
                trigger_gc_scan(GCScanRequest(project_id=5), session=session)
        assert exc_info.value.status_code == 400

    def test_multiple_cards(self, seeded_db):
        """多個 findings → 回傳多張卡片。"""
        cards = [
            _card_data(card_id=101, title="chore(gc): large-file — a.py (big)", tags=["gc-scan", "large-file"]),
            _card_data(card_id=102, title="chore(gc): todo-count — b.py (many)", tags=["gc-scan", "todo-count"]),
        ]

        with Session(seeded_db) as session:
            with patch("app.api.gc.schedule_gc_scan", return_value=cards):
                result = trigger_gc_scan(GCScanRequest(project_id=1), session=session)

        assert result.cards_created == 2
        assert len(result.cards) == 2


# ---------------------------------------------------------------------------
# Tests: cron_poller gc action
# ---------------------------------------------------------------------------

class TestCronPollerGcAction:
    def test_known_actions_includes_gc(self):
        """KNOWN_ACTIONS 包含 gc。"""
        from app.core.cron_poller import KNOWN_ACTIONS
        assert "gc" in KNOWN_ACTIONS

    def test_resolve_cron_url_gc(self):
        """gc action 能正確解析 URL。"""
        from unittest.mock import MagicMock
        from app.core.cron_poller import resolve_cron_url

        job = MagicMock()
        job.id = 42
        job.api_url = "gc"
        url = resolve_cron_url(job)
        assert url == "http://127.0.0.1:8899/api/v1/cron-jobs/42/gc"

    @pytest.mark.asyncio
    async def test_execute_gc_action_calls_scheduler(self, seeded_db):
        """_execute_gc_action 呼叫 schedule_gc_scan。"""
        from unittest.mock import MagicMock
        from app.core.cron_poller import _execute_gc_action

        job = MagicMock()
        job.name = "GC Scan"
        job.project_id = 1
        job.cron_expression = "0 0 * * *"

        with Session(seeded_db) as session:
            with patch("app.core.gc_scheduler.schedule_gc_scan", return_value=[]) as mock_scan:
                await _execute_gc_action(session, job, "Asia/Taipei")

        mock_scan.assert_called_once_with(1, "/tmp/test")

    @pytest.mark.asyncio
    async def test_execute_job_dispatches_gc(self, seeded_db):
        """_execute_job 遇到 gc action 走 _execute_gc_action。"""
        from unittest.mock import MagicMock
        from app.core.cron_poller import _execute_job

        job = MagicMock()
        job.name = "GC Nightly"
        job.api_url = "gc"
        job.project_id = 1
        job.cron_expression = "0 3 * * *"

        with Session(seeded_db) as session:
            with patch("app.core.cron_poller._execute_gc_action") as mock_gc:
                await _execute_job(session, job, "Asia/Taipei")

        mock_gc.assert_called_once()
