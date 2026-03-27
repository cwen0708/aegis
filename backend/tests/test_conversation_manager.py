"""conversation_manager 單元測試"""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

from app.core.conversation_manager import get_chat_history, format_history_block


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
# get_chat_history（需要 mock DB）
# ---------------------------------------------------------------------------

def _make_msg(role: str, content: str, minutes_ago: int):
    msg = MagicMock()
    msg.role = role
    msg.content = content
    msg.created_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return msg


@patch("app.core.conversation_manager.Session")
def test_get_chat_history_returns_dicts(mock_session_cls):
    """回傳格式應為 [{"role": ..., "content": ...}]"""
    msgs = [
        _make_msg("user", "Hello", 2),
        _make_msg("assistant", "Hi!", 1),
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
    """空歷史應回傳空列表"""
    mock_db = MagicMock()
    mock_db.exec.return_value.all.return_value = []
    mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_db)
    mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

    result = get_chat_history(session_id=999)
    assert result == []


@patch("app.core.conversation_manager.Session")
def test_get_chat_history_limit(mock_session_cls):
    """limit 參數應傳遞至 SQL query"""
    mock_db = MagicMock()
    mock_db.exec.return_value.all.return_value = []
    mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_db)
    mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

    get_chat_history(session_id=1, limit=5)

    # 驗證 select 鏈中有呼叫 .limit(5)
    call_args = mock_db.exec.call_args
    stmt = call_args[0][0]
    # limit 會反映在 compiled SQL 中
    compiled = str(stmt)
    assert "LIMIT" in compiled.upper()
