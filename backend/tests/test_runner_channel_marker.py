"""_intercept_channel_marker 單元測試

測試 runner.py 中的 _CH_SEND_RE / _CH_EDIT_RE 正則
以及 _intercept_channel_marker() 的整體行為。
"""

import re
from unittest.mock import patch, MagicMock

from app.core.runner import _CH_SEND_RE, _CH_EDIT_RE, _intercept_channel_marker


# ── _CH_SEND_RE 正則測試 ──────────────────────────────────

class TestChSendRe:
    def test_basic_match(self):
        m = _CH_SEND_RE.search("[CH_SEND:telegram:12345:hello world]")
        assert m is not None
        assert m.group(1) == "telegram"
        assert m.group(2) == "12345"
        assert m.group(3) == "hello world"

    def test_unclosed_bracket(self):
        """結尾 ] 可省略（AI 長訊息可能不閉合）"""
        m = _CH_SEND_RE.search("[CH_SEND:telegram:12345:hello world")
        assert m is not None
        assert m.group(1) == "telegram"
        assert m.group(2) == "12345"
        assert m.group(3) == "hello world"

    def test_text_with_colons(self):
        """訊息內容可以包含冒號"""
        m = _CH_SEND_RE.search("[CH_SEND:slack:ch1:time is 10:30:00]")
        assert m is not None
        assert m.group(1) == "slack"
        assert m.group(2) == "ch1"
        # .*? 是 non-greedy，碰到 ] 就停
        assert "10:30:00" in m.group(3)

    def test_no_match_plain_text(self):
        assert _CH_SEND_RE.search("just a normal line") is None

    def test_no_match_partial_tag(self):
        assert _CH_SEND_RE.search("[CH_SEND:telegram]") is None

    def test_multiline_content(self):
        """DOTALL 模式：內容可跨行"""
        text = "[CH_SEND:line:uid:line1\nline2]"
        m = _CH_SEND_RE.search(text)
        assert m is not None
        assert m.group(3) == "line1\nline2"

    def test_empty_text(self):
        m = _CH_SEND_RE.search("[CH_SEND:telegram:12345:]")
        assert m is not None
        assert m.group(3) == ""


# ── _CH_EDIT_RE 正則測試 ──────────────────────────────────

class TestChEditRe:
    def test_basic_match(self):
        m = _CH_EDIT_RE.search("[CH_EDIT:slack:ch1:msg1:updated text]")
        assert m is not None
        assert m.group(1) == "slack"
        assert m.group(2) == "ch1"
        assert m.group(3) == "msg1"
        assert m.group(4) == "updated text"

    def test_unclosed_bracket(self):
        m = _CH_EDIT_RE.search("[CH_EDIT:slack:ch1:msg1:updated text")
        assert m is not None
        assert m.group(4) == "updated text"

    def test_no_match_plain_text(self):
        assert _CH_EDIT_RE.search("hello world") is None

    def test_edit_text_with_colons(self):
        m = _CH_EDIT_RE.search("[CH_EDIT:telegram:chat1:msg1:ETA: 10:00]")
        assert m is not None
        assert "10:00" in m.group(4)

    def test_multiline_content(self):
        text = "[CH_EDIT:discord:ch1:msg1:line1\nline2]"
        m = _CH_EDIT_RE.search(text)
        assert m is not None
        assert m.group(4) == "line1\nline2"


# ── _CH_EDIT_RE 優先於 _CH_SEND_RE ───────────────────────

class TestEditPriority:
    def test_edit_matches_before_send(self):
        """_intercept_channel_marker 迴圈先檢查 EDIT 再檢查 SEND"""
        line = "[CH_EDIT:slack:ch1:msg1:updated]"
        # EDIT 和 SEND 都能匹配的情況下，EDIT 應先命中
        assert _CH_EDIT_RE.search(line) is not None
        # SEND 也可能匹配（把 msg1:updated 當 text），但函式應優先走 EDIT
        with patch("app.core.http_client.InternalAPI") as mock_api:
            _intercept_channel_marker(line)
            mock_api.channel_send_async.assert_called_once_with(
                "slack", "ch1", "updated", "msg1"
            )


# ── _intercept_channel_marker 整合行為 ───────────────────

class TestInterceptChannelMarker:
    def test_send_calls_api(self):
        with patch("app.core.http_client.InternalAPI") as mock_api:
            _intercept_channel_marker("[CH_SEND:telegram:12345:hello world]")
            mock_api.channel_send_async.assert_called_once_with(
                "telegram", "12345", "hello world", None
            )

    def test_edit_calls_api_with_edit_id(self):
        with patch("app.core.http_client.InternalAPI") as mock_api:
            _intercept_channel_marker("[CH_EDIT:slack:ch1:msg1:updated text]")
            mock_api.channel_send_async.assert_called_once_with(
                "slack", "ch1", "updated text", "msg1"
            )

    def test_plain_text_no_api_call(self):
        with patch("app.core.http_client.InternalAPI") as mock_api:
            _intercept_channel_marker("just a normal line")
            mock_api.channel_send_async.assert_not_called()

    def test_empty_string_no_api_call(self):
        with patch("app.core.http_client.InternalAPI") as mock_api:
            _intercept_channel_marker("")
            mock_api.channel_send_async.assert_not_called()

    def test_send_unclosed_bracket(self):
        with patch("app.core.http_client.InternalAPI") as mock_api:
            _intercept_channel_marker("[CH_SEND:line:uid:unclosed message")
            mock_api.channel_send_async.assert_called_once_with(
                "line", "uid", "unclosed message", None
            )
