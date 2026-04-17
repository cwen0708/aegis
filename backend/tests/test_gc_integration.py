"""Tests for GC integration: seed Backlog/CronJob + trigger_cron_job gc branch."""
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.card_file import CardData
from app.models.core import CronJob, Project, StageList


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
    """DB with AEGIS system project + Backlog list."""
    with Session(test_engine) as session:
        session.add(Project(id=1, name="AEGIS", path="/tmp/aegis", is_system=True))
        session.flush()
        session.add(StageList(id=10, project_id=1, name="Backlog", position=2))
        session.commit()
    return test_engine


def _card_data(card_id: int = 1, title: str = "test", tags: list[str] | None = None) -> CardData:
    now = datetime.now(timezone.utc)
    return CardData(
        id=card_id, list_id=10, title=title,
        description=None, content="", status="idle",
        tags=tags or [], created_at=now, updated_at=now,
    )


# ---------------------------------------------------------------------------
# Tests: seed.py — Backlog list & GC CronJob
# ---------------------------------------------------------------------------

class TestSeedBacklogAndGcCron:
    def test_sync_creates_backlog_list(self, test_engine):
        """_sync_system_cron_jobs 補建 Backlog 列表。"""
        with Session(test_engine) as session:
            session.add(Project(id=1, name="AEGIS", path="/tmp/aegis", is_system=True))
            session.flush()
            # 只有 Scheduled，缺少 Backlog
            session.add(StageList(project_id=1, name="Scheduled", position=0, is_ai_stage=True))
            session.commit()

        with patch("seed._setup_dev_directory"), \
             patch("seed._seed_member_profiles"):
            from seed import _sync_system_cron_jobs
            with Session(test_engine) as session:
                _sync_system_cron_jobs(session)

        with Session(test_engine) as session:
            backlog = session.exec(
                select(StageList).where(
                    StageList.project_id == 1,
                    StageList.name == "Backlog",
                )
            ).first()
            assert backlog is not None
            assert backlog.is_ai_stage is False

    def test_sync_creates_gc_cron_job(self, test_engine):
        """_sync_system_cron_jobs 建立 GC 技術債掃描 CronJob。"""
        with Session(test_engine) as session:
            session.add(Project(id=1, name="AEGIS", path="/tmp/aegis", is_system=True))
            session.commit()

        with patch("seed._setup_dev_directory"), \
             patch("seed._seed_member_profiles"):
            from seed import _sync_system_cron_jobs
            with Session(test_engine) as session:
                _sync_system_cron_jobs(session)

        with Session(test_engine) as session:
            gc_cron = session.exec(
                select(CronJob).where(CronJob.name == "GC 技術債掃描")
            ).first()
            assert gc_cron is not None
            assert gc_cron.api_url == "gc"
            assert gc_cron.cron_expression == "0 2 * * *"
            assert gc_cron.is_enabled is True
            assert gc_cron.is_system is True

    def test_sync_idempotent(self, test_engine):
        """重複執行 _sync_system_cron_jobs 不重建已存在的 GC CronJob。"""
        with Session(test_engine) as session:
            session.add(Project(id=1, name="AEGIS", path="/tmp/aegis", is_system=True))
            session.commit()

        with patch("seed._setup_dev_directory"), \
             patch("seed._seed_member_profiles"):
            from seed import _sync_system_cron_jobs
            with Session(test_engine) as session:
                _sync_system_cron_jobs(session)
            with Session(test_engine) as session:
                _sync_system_cron_jobs(session)

        with Session(test_engine) as session:
            gc_crons = session.exec(
                select(CronJob).where(CronJob.name == "GC 技術債掃描")
            ).all()
            assert len(gc_crons) == 1


# ---------------------------------------------------------------------------
# Tests: cron_jobs.py — trigger_cron_job gc branch + execute_gc endpoint
# ---------------------------------------------------------------------------

class TestTriggerCronJobGc:
    def test_trigger_routes_to_gc(self, seeded_db):
        """trigger_cron_job 路由 gc action 到 execute_gc。"""
        with Session(seeded_db) as session:
            job = CronJob(
                id=1, project_id=1, name="GC Test",
                cron_expression="0 2 * * *",
                api_url="gc", is_enabled=True,
            )
            session.add(job)
            session.commit()

        from app.api.cron_jobs import trigger_cron_job
        with Session(seeded_db) as session:
            with patch("app.api.cron_jobs.execute_gc") as mock_gc:
                import asyncio
                mock_gc.return_value = {"ok": True, "action": "gc", "cards_created": 0}
                result = asyncio.get_event_loop().run_until_complete(
                    trigger_cron_job(1, session=session)
                )
        mock_gc.assert_called_once()

    def test_execute_gc_returns_cards(self, seeded_db):
        """execute_gc 呼叫 schedule_gc_scan 並回傳結果。"""
        with Session(seeded_db) as session:
            job = CronJob(
                id=1, project_id=1, name="GC Test",
                cron_expression="0 2 * * *",
                api_url="gc", is_enabled=True,
            )
            session.add(job)
            session.commit()

        from app.api.cron_jobs import execute_gc
        fake_cards = [
            _card_data(card_id=100, title="chore(gc): large-file — x.py", tags=["gc-scan"]),
        ]

        import asyncio
        with Session(seeded_db) as session:
            with patch("app.core.gc_scheduler.schedule_gc_scan", return_value=fake_cards):
                result = asyncio.get_event_loop().run_until_complete(
                    execute_gc(1, session=session)
                )

        assert result["ok"] is True
        assert result["action"] == "gc"
        assert result["cards_created"] == 1

    def test_execute_gc_job_not_found(self, seeded_db):
        """execute_gc 找不到 CronJob → 404。"""
        from fastapi import HTTPException
        from app.api.cron_jobs import execute_gc

        import asyncio
        with Session(seeded_db) as session:
            with pytest.raises(HTTPException) as exc_info:
                asyncio.get_event_loop().run_until_complete(
                    execute_gc(999, session=session)
                )
        assert exc_info.value.status_code == 404

    def test_execute_gc_no_project_path(self, test_engine):
        """execute_gc 專案無路徑 → 400。"""
        with Session(test_engine) as session:
            session.add(Project(id=5, name="NoPath", path=""))
            session.flush()
            session.add(CronJob(
                id=1, project_id=5, name="GC NP",
                cron_expression="0 2 * * *",
                api_url="gc", is_enabled=True,
            ))
            session.commit()

        from fastapi import HTTPException
        from app.api.cron_jobs import execute_gc

        import asyncio
        with Session(test_engine) as session:
            with pytest.raises(HTTPException) as exc_info:
                asyncio.get_event_loop().run_until_complete(
                    execute_gc(1, session=session)
                )
        assert exc_info.value.status_code == 400
