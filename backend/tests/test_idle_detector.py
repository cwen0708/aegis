"""測試 idle_detector 模組：IdleStatus、get_idle_status、idle_since 追蹤"""
import time
import pytest
from unittest.mock import patch, MagicMock
from sqlmodel import Session, SQLModel, create_engine
from datetime import datetime, timezone, timedelta

from app.models.core import CardIndex, ChatSession
from app.core.idle_detector import (
    get_idle_status, is_system_idle, reset_idle_tracking,
    IDLE_CPU_THRESHOLD, IdleStatus,
)


@pytest.fixture
def db_session(tmp_path):
    """建立暫時 SQLite 資料庫 session"""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(autouse=True)
def _reset_idle():
    """每個測試前重置 idle 追蹤狀態"""
    reset_idle_tracking()
    yield
    reset_idle_tracking()


def _mock_metrics(cpu=10.0):
    return {
        "cpu_percent": cpu,
        "memory_percent": 50.0,
        "memory_available_gb": 8.0,
        "disk_percent": 40.0,
        "timestamp": 0,
    }


def _pool_patch():
    """每次建立新的 patch 物件"""
    return patch("app.core.session_pool.process_pool")


class TestGetIdleStatus:
    """測試 get_idle_status() 完整狀態回傳"""

    @patch("app.core.idle_detector.get_system_metrics", return_value=_mock_metrics(cpu=10.0))
    def test_all_idle(self, mock_metrics, db_session):
        """全部信號源閒置 → is_idle=True"""
        with _pool_patch() as mock_pool:
            mock_pool.active_count.return_value = 0
            status = get_idle_status(db_session)
        assert status.is_idle is True
        assert status.busy_reasons == []
        assert status.idle_since is not None
        assert status.idle_seconds >= 0

    @patch("app.core.idle_detector.get_system_metrics", return_value=_mock_metrics(cpu=10.0))
    def test_busy_running_card(self, mock_metrics, db_session):
        """有 running card → is_idle=False，busy_reasons 包含原因"""
        db_session.add(CardIndex(card_id=1, status="running", title="deploy"))
        db_session.commit()
        with _pool_patch() as mock_pool:
            mock_pool.active_count.return_value = 0
            status = get_idle_status(db_session)
        assert status.is_idle is False
        assert any("running card" in r for r in status.busy_reasons)

    @patch("app.core.idle_detector.get_system_metrics", return_value=_mock_metrics(cpu=10.0))
    def test_busy_pending_card(self, mock_metrics, db_session):
        """有 pending card → is_idle=False"""
        db_session.add(CardIndex(card_id=2, status="pending", title="queued"))
        db_session.commit()
        with _pool_patch() as mock_pool:
            mock_pool.active_count.return_value = 0
            status = get_idle_status(db_session)
        assert status.is_idle is False
        assert any("pending card" in r for r in status.busy_reasons)

    @patch("app.core.idle_detector.get_system_metrics", return_value=_mock_metrics(cpu=90.0))
    def test_busy_high_cpu(self, mock_metrics, db_session):
        """CPU >= 80% → is_idle=False"""
        with _pool_patch() as mock_pool:
            mock_pool.active_count.return_value = 0
            status = get_idle_status(db_session)
        assert status.is_idle is False
        assert any("CPU" in r for r in status.busy_reasons)

    @patch("app.core.idle_detector.get_system_metrics", return_value=_mock_metrics(cpu=10.0))
    def test_busy_active_chat(self, mock_metrics, db_session):
        """有活躍 ChatSession → is_idle=False"""
        chat = ChatSession(
            bot_user_id=1, member_id=1, chat_id="test:chat",
            last_message_at=datetime.now(timezone.utc),
        )
        db_session.add(chat)
        db_session.commit()
        with _pool_patch() as mock_pool:
            mock_pool.active_count.return_value = 0
            status = get_idle_status(db_session)
        assert status.is_idle is False
        assert any("active chat" in r for r in status.busy_reasons)

    @patch("app.core.idle_detector.get_system_metrics", return_value=_mock_metrics(cpu=10.0))
    def test_old_chat_not_blocking(self, mock_metrics, db_session):
        """超過 5 分鐘的 ChatSession 不影響閒置判斷"""
        chat = ChatSession(
            bot_user_id=1, member_id=1, chat_id="old:chat",
            last_message_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        db_session.add(chat)
        db_session.commit()
        with _pool_patch() as mock_pool:
            mock_pool.active_count.return_value = 0
            status = get_idle_status(db_session)
        assert status.is_idle is True

    @patch("app.core.idle_detector.get_system_metrics", return_value=_mock_metrics(cpu=10.0))
    def test_busy_process_pool(self, mock_metrics, db_session):
        """ProcessPool 有活躍進程 → is_idle=False"""
        with _pool_patch() as mock_pool:
            mock_pool.active_count.return_value = 2
            status = get_idle_status(db_session)
        assert status.is_idle is False
        assert any("process pool" in r for r in status.busy_reasons)

    @patch("app.core.idle_detector.get_system_metrics", return_value=_mock_metrics(cpu=10.0))
    def test_completed_cards_dont_block(self, mock_metrics, db_session):
        """completed/failed 卡片不影響閒置判斷"""
        db_session.add(CardIndex(card_id=3, status="completed", title="done"))
        db_session.add(CardIndex(card_id=4, status="failed", title="err"))
        db_session.commit()
        with _pool_patch() as mock_pool:
            mock_pool.active_count.return_value = 0
            status = get_idle_status(db_session)
        assert status.is_idle is True


class TestIdleSinceTracking:
    """測試 idle_since 閒置起始時間追蹤"""

    @patch("app.core.idle_detector.get_system_metrics", return_value=_mock_metrics(cpu=10.0))
    def test_idle_since_stable_across_calls(self, mock_metrics, db_session):
        """連續閒置呼叫時 idle_since 不變"""
        with _pool_patch() as mock_pool:
            mock_pool.active_count.return_value = 0
            s1 = get_idle_status(db_session)
            first_idle_since = s1.idle_since
            time.sleep(0.05)
            s2 = get_idle_status(db_session)
        assert s2.idle_since == first_idle_since
        assert s2.idle_seconds > s1.idle_seconds

    @patch("app.core.idle_detector.get_system_metrics", return_value=_mock_metrics(cpu=10.0))
    def test_idle_since_resets_after_busy(self, mock_metrics, db_session):
        """從 busy → idle 轉換時 idle_since 重置"""
        with _pool_patch() as mock_pool:
            mock_pool.active_count.return_value = 0
            s1 = get_idle_status(db_session)
            first_idle_since = s1.idle_since

        # 變忙碌
        db_session.add(CardIndex(card_id=5, status="running", title="work"))
        db_session.commit()
        with _pool_patch() as mock_pool:
            mock_pool.active_count.return_value = 0
            s2 = get_idle_status(db_session)
        assert s2.is_idle is False
        assert s2.idle_since is None

        # 清除忙碌狀態
        card = db_session.get(CardIndex, 5)
        card.status = "completed"
        db_session.commit()
        time.sleep(0.05)
        with _pool_patch() as mock_pool:
            mock_pool.active_count.return_value = 0
            s3 = get_idle_status(db_session)
        assert s3.is_idle is True
        assert s3.idle_since is not None
        assert s3.idle_since > first_idle_since


class TestIsSystemIdleCompat:
    """測試 is_system_idle() 相容介面"""

    @patch("app.core.idle_detector.get_system_metrics", return_value=_mock_metrics(cpu=10.0))
    def test_returns_bool(self, mock_metrics, db_session):
        with _pool_patch() as mock_pool:
            mock_pool.active_count.return_value = 0
            result = is_system_idle(db_session)
        assert result is True

    @patch("app.core.idle_detector.get_system_metrics", return_value=_mock_metrics(cpu=90.0))
    def test_returns_false_when_busy(self, mock_metrics, db_session):
        with _pool_patch() as mock_pool:
            mock_pool.active_count.return_value = 0
            result = is_system_idle(db_session)
        assert result is False
