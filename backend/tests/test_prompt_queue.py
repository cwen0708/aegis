"""測試 PromptQueueManager — enqueue / dequeue / 優先級排序 / 狀態轉換"""
import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models.core import PromptQueueEntry
from app.core.prompt_queue import PromptQueueManager


@pytest.fixture
def pq(tmp_path):
    """建立獨立的記憶體 SQLite + PromptQueueManager"""
    db_path = tmp_path / "test_queue.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    return PromptQueueManager(engine)


# ── enqueue ──────────────────────────────────────────────────

class TestEnqueue:
    def test_returns_uuid_string(self, pq):
        queue_id = pq.enqueue("session1", "hello", priority=1)
        assert isinstance(queue_id, str)
        assert len(queue_id) == 36  # UUID 格式

    def test_initial_status_is_pending(self, pq):
        queue_id = pq.enqueue("session1", "hello", priority=1)
        assert pq.get_status(queue_id) == "pending"

    def test_enqueue_multiple_same_session(self, pq):
        id1 = pq.enqueue("session1", "first", priority=1)
        id2 = pq.enqueue("session1", "second", priority=1)
        assert id1 != id2
        assert pq.get_status(id1) == "pending"
        assert pq.get_status(id2) == "pending"

    def test_default_priority_is_1(self, pq):
        queue_id = pq.enqueue("session1", "default priority")
        assert pq.get_status(queue_id) == "pending"


# ── dequeue ──────────────────────────────────────────────────

class TestDequeue:
    def test_returns_none_when_empty(self, pq):
        assert pq.dequeue("nonexistent") is None

    def test_returns_entry(self, pq):
        pq.enqueue("session1", "hello", priority=1)
        entry = pq.dequeue("session1")
        assert entry is not None
        assert entry.prompt_text == "hello"
        assert entry.session_id == "session1"

    def test_dequeue_updates_status_to_processing(self, pq):
        queue_id = pq.enqueue("session1", "test", priority=1)
        entry = pq.dequeue("session1")
        assert entry.status == "processing"
        assert pq.get_status(queue_id) == "processing"

    def test_dequeue_empty_after_all_picked(self, pq):
        pq.enqueue("session1", "only one", priority=1)
        pq.dequeue("session1")
        assert pq.dequeue("session1") is None


# ── 優先級排序 ────────────────────────────────────────────────

class TestPriority:
    def test_high_priority_dequeued_first(self, pq):
        id_low = pq.enqueue("session1", "low priority", priority=1)
        id_high = pq.enqueue("session1", "high priority", priority=5)
        entry = pq.dequeue("session1")
        assert entry.queue_id == id_high
        assert entry.prompt_text == "high priority"

    def test_same_priority_fifo(self, pq):
        """同優先級按建立時間先進先出"""
        id1 = pq.enqueue("session1", "first", priority=2)
        id2 = pq.enqueue("session1", "second", priority=2)
        id3 = pq.enqueue("session1", "third", priority=2)
        e1 = pq.dequeue("session1")
        e2 = pq.dequeue("session1")
        e3 = pq.dequeue("session1")
        assert e1.queue_id == id1
        assert e2.queue_id == id2
        assert e3.queue_id == id3

    def test_mixed_priority_order(self, pq):
        """高優先 > 低優先，同優先 FIFO"""
        id_p1_a = pq.enqueue("session1", "p1 first", priority=1)
        id_p3 = pq.enqueue("session1", "p3", priority=3)
        id_p1_b = pq.enqueue("session1", "p1 second", priority=1)
        id_p2 = pq.enqueue("session1", "p2", priority=2)

        e1 = pq.dequeue("session1")
        e2 = pq.dequeue("session1")
        e3 = pq.dequeue("session1")
        e4 = pq.dequeue("session1")

        assert e1.queue_id == id_p3
        assert e2.queue_id == id_p2
        assert e3.queue_id == id_p1_a
        assert e4.queue_id == id_p1_b


# ── 狀態轉換 ─────────────────────────────────────────────────

class TestStatusTransition:
    def test_mark_processed(self, pq):
        queue_id = pq.enqueue("session1", "test", priority=1)
        pq.dequeue("session1")
        pq.mark_processed(queue_id)
        assert pq.get_status(queue_id) == "processed"

    def test_mark_failed(self, pq):
        queue_id = pq.enqueue("session1", "test", priority=1)
        pq.dequeue("session1")
        pq.mark_failed(queue_id)
        assert pq.get_status(queue_id) == "failed"

    def test_processed_not_dequeued_again(self, pq):
        """已 processed 的項目不再出隊"""
        queue_id = pq.enqueue("session1", "test", priority=1)
        pq.dequeue("session1")
        pq.mark_processed(queue_id)
        assert pq.dequeue("session1") is None

    def test_processing_not_dequeued_again(self, pq):
        """processing 狀態的項目不再被 dequeue"""
        pq.enqueue("session1", "test", priority=1)
        pq.dequeue("session1")  # status → processing
        assert pq.dequeue("session1") is None

    def test_get_status_nonexistent(self, pq):
        assert pq.get_status("nonexistent-queue-id") is None


# ── Session 隔離 ──────────────────────────────────────────────

class TestSessionIsolation:
    def test_different_sessions_isolated(self, pq):
        pq.enqueue("session1", "msg for 1", priority=1)
        pq.enqueue("session2", "msg for 2", priority=1)

        e1 = pq.dequeue("session1")
        e2 = pq.dequeue("session2")

        assert e1.prompt_text == "msg for 1"
        assert e2.prompt_text == "msg for 2"

    def test_dequeue_only_own_session(self, pq):
        pq.enqueue("session1", "for 1", priority=1)
        assert pq.dequeue("session2") is None
        e = pq.dequeue("session1")
        assert e.prompt_text == "for 1"
