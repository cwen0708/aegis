"""測試閒時偵測 is_system_idle 及 idle_only 排程跳過邏輯"""
import json
import pytest
from unittest.mock import patch
from sqlmodel import Session, SQLModel, create_engine
from app.models.core import CardIndex
from app.core.cron_poller import is_system_idle, IDLE_CPU_THRESHOLD


@pytest.fixture
def db_session(tmp_path):
    """建立暫時 SQLite 資料庫 session"""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _mock_metrics(cpu=10.0):
    """產生模擬的系統指標"""
    return {
        "cpu_percent": cpu,
        "memory_percent": 50.0,
        "memory_available_gb": 8.0,
        "disk_percent": 40.0,
        "timestamp": 0,
    }


class TestIsSystemIdle:
    """測試 is_system_idle() 閒置判斷"""

    @patch("app.core.telemetry.get_system_metrics", return_value=_mock_metrics(cpu=10.0))
    def test_idle_when_no_cards_and_low_cpu(self, mock_metrics, db_session):
        """無 running/pending 卡片且 CPU 低 → 閒置"""
        assert is_system_idle(db_session) is True

    @patch("app.core.telemetry.get_system_metrics", return_value=_mock_metrics(cpu=10.0))
    def test_busy_when_running_card_exists(self, mock_metrics, db_session):
        """有 running 卡片 → 非閒置"""
        db_session.add(CardIndex(card_id=1, status="running", title="task"))
        db_session.commit()
        assert is_system_idle(db_session) is False

    @patch("app.core.telemetry.get_system_metrics", return_value=_mock_metrics(cpu=10.0))
    def test_busy_when_pending_card_exists(self, mock_metrics, db_session):
        """有 pending 卡片 → 非閒置"""
        db_session.add(CardIndex(card_id=2, status="pending", title="queued"))
        db_session.commit()
        assert is_system_idle(db_session) is False

    @patch("app.core.telemetry.get_system_metrics", return_value=_mock_metrics(cpu=90.0))
    def test_busy_when_cpu_high(self, mock_metrics, db_session):
        """CPU >= 80% → 非閒置"""
        assert is_system_idle(db_session) is False

    @patch("app.core.telemetry.get_system_metrics", return_value=_mock_metrics(cpu=79.9))
    def test_idle_at_cpu_boundary(self, mock_metrics, db_session):
        """CPU 剛好低於門檻 → 閒置"""
        assert is_system_idle(db_session) is True

    @patch("app.core.telemetry.get_system_metrics", return_value=_mock_metrics(cpu=80.0))
    def test_busy_at_cpu_exact_threshold(self, mock_metrics, db_session):
        """CPU 剛好等於門檻 → 非閒置"""
        assert is_system_idle(db_session) is False

    @patch("app.core.telemetry.get_system_metrics", return_value=_mock_metrics(cpu=10.0))
    def test_completed_cards_dont_block_idle(self, mock_metrics, db_session):
        """completed/failed 卡片不影響閒置判斷"""
        db_session.add(CardIndex(card_id=3, status="completed", title="done"))
        db_session.add(CardIndex(card_id=4, status="failed", title="err"))
        db_session.commit()
        assert is_system_idle(db_session) is True


class TestIdleOnlySkipLogic:
    """測試 idle_only 排程在 poll 迴圈中的跳過行為"""

    def test_idle_only_metadata_parsing(self):
        """idle_only 欄位能從 metadata_json 正確讀取"""
        meta = json.loads('{"idle_only": true}')
        assert meta.get("idle_only") is True

        meta_false = json.loads('{"idle_only": false}')
        assert meta_false.get("idle_only") is False

        meta_empty = json.loads('{}')
        assert meta_empty.get("idle_only") is None

    @patch("app.core.telemetry.get_system_metrics", return_value=_mock_metrics(cpu=10.0))
    def test_idle_only_skipped_when_busy(self, mock_metrics, db_session):
        """系統忙碌時 idle_only=true 的排程應被跳過"""
        # 模擬忙碌：加一張 running 卡片
        db_session.add(CardIndex(card_id=10, status="running", title="busy"))
        db_session.commit()

        idle = is_system_idle(db_session)
        assert idle is False

        # 模擬 idle_only 判斷邏輯
        metadata = {"idle_only": True}
        should_skip = metadata.get("idle_only") and not idle
        assert should_skip is True

    @patch("app.core.telemetry.get_system_metrics", return_value=_mock_metrics(cpu=10.0))
    def test_idle_only_executes_when_idle(self, mock_metrics, db_session):
        """系統閒置時 idle_only=true 的排程應正常執行"""
        idle = is_system_idle(db_session)
        assert idle is True

        metadata = {"idle_only": True}
        should_skip = metadata.get("idle_only") and not idle
        assert should_skip is False

    @patch("app.core.telemetry.get_system_metrics", return_value=_mock_metrics(cpu=10.0))
    def test_non_idle_only_always_executes(self, mock_metrics, db_session):
        """沒有 idle_only 的排程不受閒置狀態影響"""
        # 即使忙碌也要執行
        db_session.add(CardIndex(card_id=11, status="running", title="busy"))
        db_session.commit()

        idle = is_system_idle(db_session)
        metadata = {}  # 無 idle_only 欄位
        should_skip = metadata.get("idle_only") and not idle
        assert not should_skip
