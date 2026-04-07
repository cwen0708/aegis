"""卡片歷史記錄 API 測試 — GET /cards/{card_id}/history"""
import pytest
from datetime import datetime, timezone, timedelta
from sqlmodel import Session, SQLModel, create_engine

from app.models.core import CardIndex, TaskLog
from app.api.history import get_card_history


@pytest.fixture
def db_session(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _seed_card(session: Session, card_id: int, title: str = "test card") -> CardIndex:
    idx = CardIndex(card_id=card_id, project_id=1, title=title)
    session.add(idx)
    session.commit()
    return idx


def _seed_log(session: Session, card_id: int, **kwargs) -> TaskLog:
    defaults = dict(
        card_id=card_id,
        card_title="test card",
        status="success",
        provider="claude",
        model="claude-sonnet-4-6",
        input_tokens=1000,
        output_tokens=200,
        cost_usd=0.006,
        duration_ms=3000,
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    log = TaskLog(**defaults)
    session.add(log)
    session.commit()
    return log


class TestGetCardHistoryNotFound:
    def test_raises_404_when_card_missing(self, db_session):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            get_card_history(card_id=9999, days=7, limit=10, session=db_session)
        assert exc.value.status_code == 404


class TestGetCardHistoryEmpty:
    def test_returns_empty_runs_when_no_logs(self, db_session):
        _seed_card(db_session, card_id=1)
        result = get_card_history(card_id=1, days=7, limit=10, session=db_session)
        assert result["card_id"] == 1
        assert result["total_runs"] == 0
        assert result["runs"] == []
        assert result["total_input_tokens"] == 0
        assert result["total_cost_usd"] == 0.0


class TestGetCardHistoryWithLogs:
    def test_returns_correct_run_count(self, db_session):
        _seed_card(db_session, card_id=2, title="My Card")
        _seed_log(db_session, card_id=2)
        _seed_log(db_session, card_id=2, status="error", cost_usd=0.0)
        result = get_card_history(card_id=2, days=7, limit=10, session=db_session)
        assert result["total_runs"] == 2
        assert result["card_title"] == "My Card"

    def test_aggregates_token_and_cost(self, db_session):
        _seed_card(db_session, card_id=3)
        _seed_log(db_session, card_id=3, input_tokens=1000, output_tokens=200, cost_usd=0.003)
        _seed_log(db_session, card_id=3, input_tokens=2000, output_tokens=400, cost_usd=0.006)
        result = get_card_history(card_id=3, days=7, limit=10, session=db_session)
        assert result["total_input_tokens"] == 3000
        assert result["total_output_tokens"] == 600
        assert abs(result["total_cost_usd"] - 0.009) < 1e-6

    def test_run_fields_are_present(self, db_session):
        _seed_card(db_session, card_id=4)
        _seed_log(db_session, card_id=4, member_id=7, cache_read_tokens=50)
        result = get_card_history(card_id=4, days=7, limit=10, session=db_session)
        run = result["runs"][0]
        assert run["status"] == "success"
        assert run["provider"] == "claude"
        assert run["member_id"] == 7
        assert run["cache_read_tokens"] == 50
        assert "created_at" in run


class TestGetCardHistoryFiltering:
    def test_excludes_old_logs(self, db_session):
        _seed_card(db_session, card_id=5)
        old_time = datetime.now(timezone.utc) - timedelta(days=30)
        _seed_log(db_session, card_id=5, created_at=old_time)  # 超過 days=7
        _seed_log(db_session, card_id=5)  # 今天
        result = get_card_history(card_id=5, days=7, limit=10, session=db_session)
        assert result["total_runs"] == 1

    def test_limit_caps_results(self, db_session):
        _seed_card(db_session, card_id=6)
        for _ in range(5):
            _seed_log(db_session, card_id=6)
        result = get_card_history(card_id=6, days=7, limit=3, session=db_session)
        assert len(result["runs"]) == 3

    def test_only_returns_logs_for_target_card(self, db_session):
        _seed_card(db_session, card_id=7)
        _seed_card(db_session, card_id=8)
        _seed_log(db_session, card_id=7)
        _seed_log(db_session, card_id=8)  # 不同卡片，不應出現
        result = get_card_history(card_id=7, days=7, limit=10, session=db_session)
        assert result["total_runs"] == 1
