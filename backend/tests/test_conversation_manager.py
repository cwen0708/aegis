"""conversation_manager 單元測試"""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.core.conversation_manager import (
    ConversationManager,
    Message,
    get_chat_history,
    format_history_block,
)
from app.models.core import ChatMessage, ChatSession


# ---------------------------------------------------------------------------
# 測試用 DB fixture（真實 SQLite）
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session(tmp_path):
    """建立暫時 SQLite DB，並回傳開啟的 Session。"""
    db_path = tmp_path / "test.db"
    test_engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        yield session


def _make_session(db: Session, chat_id: str, bot_user_id: int = 1, member_id: int = 1) -> ChatSession:
    """建立 ChatSession 測試資料。"""
    sess = ChatSession(bot_user_id=bot_user_id, member_id=member_id, chat_id=chat_id)
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return sess


def _make_message(
    db: Session,
    session_id: int,
    role: str,
    content: str,
    minutes_ago: int = 0,
) -> ChatMessage:
    """建立 ChatMessage 測試資料。"""
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    msg = ChatMessage(session_id=session_id, role=role, content=content, created_at=ts)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


# ---------------------------------------------------------------------------
# ConversationManager — chatmessage 源（真實 DB）
# ---------------------------------------------------------------------------

class TestConversationManagerChatmessage:

    def test_returns_message_dataclass(self, db_session):
        """回傳物件應為 Message dataclass。"""
        s = _make_session(db_session, chat_id="chat-001")
        _make_message(db_session, s.id, "user", "你好", minutes_ago=2)

        manager = ConversationManager(db_session=db_session)
        result = manager.get_chat_history("chat-001")

        assert len(result) == 1
        assert isinstance(result[0], Message)

    def test_message_fields(self, db_session):
        """Message 欄位應正確對應資料庫記錄。"""
        s = _make_session(db_session, chat_id="chat-002")
        raw = _make_message(db_session, s.id, "user", "測試內容", minutes_ago=1)

        manager = ConversationManager(db_session=db_session)
        result = manager.get_chat_history("chat-002")

        msg = result[0]
        assert msg.role == "user"
        assert msg.content == "測試內容"
        assert msg.session_id == s.id
        assert msg.message_id == raw.id
        assert isinstance(msg.timestamp, datetime)

    def test_chronological_order(self, db_session):
        """訊息應依 created_at ASC 排序（最舊在前）。"""
        s = _make_session(db_session, chat_id="chat-003")
        _make_message(db_session, s.id, "user",      "第一則", minutes_ago=5)
        _make_message(db_session, s.id, "assistant", "第二則", minutes_ago=3)
        _make_message(db_session, s.id, "user",      "第三則", minutes_ago=1)

        manager = ConversationManager(db_session=db_session)
        result = manager.get_chat_history("chat-003")

        assert len(result) == 3
        assert result[0].content == "第一則"
        assert result[1].content == "第二則"
        assert result[2].content == "第三則"

    def test_roles_preserved(self, db_session):
        """user / assistant role 應正確保留。"""
        s = _make_session(db_session, chat_id="chat-004")
        _make_message(db_session, s.id, "user",      "問題", minutes_ago=2)
        _make_message(db_session, s.id, "assistant", "回答", minutes_ago=1)

        manager = ConversationManager(db_session=db_session)
        result = manager.get_chat_history("chat-004")

        assert result[0].role == "user"
        assert result[1].role == "assistant"

    def test_empty_chat_id(self, db_session):
        """無對應 chat_id 應回傳空列表。"""
        manager = ConversationManager(db_session=db_session)
        result = manager.get_chat_history("nonexistent-chat-id")
        assert result == []

    def test_limit_parameter(self, db_session):
        """limit 應限制回傳筆數（取最新幾筆，再排正序）。"""
        s = _make_session(db_session, chat_id="chat-005")
        for i in range(10, 0, -1):
            _make_message(db_session, s.id, "user", f"訊息{i}", minutes_ago=i)

        manager = ConversationManager(db_session=db_session)
        result = manager.get_chat_history("chat-005", limit=3)

        # limit=3 取最新 3 筆（minutes_ago 1,2,3），排正序後應為 3,2,1
        assert len(result) == 3
        assert result[0].content == "訊息3"
        assert result[1].content == "訊息2"
        assert result[2].content == "訊息1"

    def test_multiple_sessions_same_chat_id(self, db_session):
        """同一 chat_id 若有多個 session，所有訊息皆應被合併回傳。"""
        s1 = _make_session(db_session, chat_id="chat-006", bot_user_id=1, member_id=1)
        s2 = _make_session(db_session, chat_id="chat-006", bot_user_id=2, member_id=2)
        _make_message(db_session, s1.id, "user", "來自 session1", minutes_ago=2)
        _make_message(db_session, s2.id, "user", "來自 session2", minutes_ago=1)

        manager = ConversationManager(db_session=db_session)
        result = manager.get_chat_history("chat-006")

        assert len(result) == 2

    def test_different_chat_ids_isolated(self, db_session):
        """不同 chat_id 的訊息應互相隔離。"""
        s1 = _make_session(db_session, chat_id="chat-A")
        s2 = _make_session(db_session, chat_id="chat-B")
        _make_message(db_session, s1.id, "user", "A的訊息")
        _make_message(db_session, s2.id, "user", "B的訊息")

        manager = ConversationManager(db_session=db_session)

        result_a = manager.get_chat_history("chat-A")
        result_b = manager.get_chat_history("chat-B")

        assert len(result_a) == 1
        assert result_a[0].content == "A的訊息"
        assert len(result_b) == 1
        assert result_b[0].content == "B的訊息"

    def test_invalid_source_raises(self, db_session):
        """不支援的 source 應拋出 ValueError。"""
        manager = ConversationManager(db_session=db_session)
        with pytest.raises(ValueError, match="不支援的 source"):
            manager.get_chat_history("any-chat", source="unknown")

    def test_default_source_is_chatmessage(self, db_session):
        """預設 source 為 chatmessage，應正常運作。"""
        s = _make_session(db_session, chat_id="chat-default")
        _make_message(db_session, s.id, "assistant", "預設來源", minutes_ago=1)

        manager = ConversationManager(db_session=db_session)
        result = manager.get_chat_history("chat-default")  # 不傳 source

        assert len(result) == 1
        assert result[0].content == "預設來源"


# ---------------------------------------------------------------------------
# format_history_block（純函式，不需要 DB）
# ---------------------------------------------------------------------------

def test_format_history_block_basic():
    history = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好！有什麼可以幫你的？"},
    ]
    result = format_history_block(history)
    assert "## 近期對話" in result
    assert "[user]: 你好" in result
    assert "[assistant]: 你好！有什麼可以幫你的？" in result


def test_format_history_block_empty():
    result = format_history_block([])
    assert result == ""


def test_format_history_block_truncation():
    long_content = "A" * 600
    history = [{"role": "user", "content": long_content}]
    result = format_history_block(history, max_content_len=500)
    assert "[user]: " + "A" * 500 + "..." in result


# ---------------------------------------------------------------------------
# get_chat_history 舊版函式介面（mock DB，向下相容）
# ---------------------------------------------------------------------------

def _make_mock_msg(role: str, content: str, minutes_ago: int):
    msg = MagicMock()
    msg.role = role
    msg.content = content
    msg.created_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return msg


@patch("app.core.conversation_manager.Session")
def test_get_chat_history_returns_dicts(mock_session_cls):
    """舊版函式回傳格式應為 [{"role": ..., "content": ...}]"""
    msgs = [
        _make_mock_msg("user", "Hello", 2),
        _make_mock_msg("assistant", "Hi!", 1),
    ]
    mock_db = MagicMock()
    mock_db.exec.return_value.all.return_value = list(reversed(msgs))  # DB 回傳 desc
    mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_db)
    mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

    result = get_chat_history(session_id=1, limit=10)
    assert len(result) == 2
    assert result[0] == {"role": "user", "content": "Hello"}
    assert result[1] == {"role": "assistant", "content": "Hi!"}


@patch("app.core.conversation_manager.Session")
def test_get_chat_history_empty(mock_session_cls):
    """舊版函式：空歷史應回傳空列表"""
    mock_db = MagicMock()
    mock_db.exec.return_value.all.return_value = []
    mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_db)
    mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

    result = get_chat_history(session_id=999)
    assert result == []


@patch("app.core.conversation_manager.Session")
def test_get_chat_history_limit(mock_session_cls):
    """舊版函式：limit 參數應傳遞至 SQL query"""
    mock_db = MagicMock()
    mock_db.exec.return_value.all.return_value = []
    mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_db)
    mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

    get_chat_history(session_id=1, limit=5)

    call_args = mock_db.exec.call_args
    stmt = call_args[0][0]
    compiled = str(stmt)
    assert "LIMIT" in compiled.upper()
