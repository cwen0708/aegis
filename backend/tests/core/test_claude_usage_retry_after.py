"""P0-SH-07 step 1：claude_usage._fetch_usage 的 Retry-After header 接線測試。

三個案例：
- A：429 + Retry-After: 60 → 寫入 cooldown
- B：cooldown 期間第二次呼叫直接回 cached，不重發 request
- C：429 但無 Retry-After → 不寫 cooldown，沿用舊的「回 cached / None」行為
"""
import time
import urllib.error
from email.message import Message
from unittest.mock import MagicMock, patch

import pytest

from app.core.claude_usage import _fetch_usage, _usage_cache


def _make_headers(pairs: dict) -> Message:
    """模擬 urllib HTTPError 的 headers 物件（支援 .get）"""
    msg = Message()
    for k, v in pairs.items():
        msg[k] = v
    return msg


def _http_error_429(retry_after: str | None = None) -> urllib.error.HTTPError:
    hdrs = _make_headers({"Retry-After": retry_after}) if retry_after is not None else None
    return urllib.error.HTTPError(
        url="https://api.anthropic.com/api/oauth/usage",
        code=429,
        msg="Too Many Requests",
        hdrs=hdrs,
        fp=None,
    )


@pytest.fixture(autouse=True)
def clear_cache():
    _usage_cache.clear()
    yield
    _usage_cache.clear()


class TestRetryAfterWiring:
    """claude_usage 對 Retry-After header 的最小接線行為"""

    @patch("app.core.claude_usage.urllib.request.urlopen")
    def test_case_a_429_with_retry_after_writes_cooldown(self, mock_urlopen):
        """Case A：第一次回 429 + Retry-After: 60 → cooldown 寫入快取"""
        mock_urlopen.side_effect = _http_error_429(retry_after="60")

        t0 = time.time()
        result = _fetch_usage("tok", cache_key="acct-a")

        # 沒有資料可回（第一次就 429）
        assert result is None
        # cache 應已寫入 cooldown_until ≈ t0 + 60
        assert "acct-a" in _usage_cache
        ts, data, cooldown_until = _usage_cache["acct-a"]
        assert data is None
        assert cooldown_until >= t0 + 59  # 允許 1s 執行誤差
        assert cooldown_until <= t0 + 61
        # 確實發過一次 request
        mock_urlopen.assert_called_once()

    @patch("app.core.claude_usage.urllib.request.urlopen")
    def test_case_b_cooldown_hit_skips_request(self, mock_urlopen):
        """Case B：cooldown 期間第二次呼叫直接回 cached、不重發 request"""
        # 先種一筆 cooldown 中的 cache（含 stale 資料）
        _usage_cache["acct-b"] = (
            time.time() - 10,          # ts
            {"stale": True},           # data
            time.time() + 120,         # cooldown_until（未來 120s）
        )

        result = _fetch_usage("tok", cache_key="acct-b")

        assert result == {"stale": True}
        # 重點：cooldown 命中，urlopen 不可被呼叫
        mock_urlopen.assert_not_called()

    @patch("app.core.claude_usage.urllib.request.urlopen")
    def test_case_c_429_without_retry_after_keeps_old_behavior(self, mock_urlopen):
        """Case C：429 但無 Retry-After → 不寫 cooldown，沿用舊 fallback"""
        # 既有 cache 讓舊 fallback 路徑可回 cached
        _usage_cache["acct-c"] = (
            time.time() - 10,
            {"stale": True},
            0.0,                       # 無 cooldown
        )
        mock_urlopen.side_effect = _http_error_429(retry_after=None)

        result = _fetch_usage("tok", cache_key="acct-c")

        # 舊行為：429 + cache 存在 → 回 cached
        assert result == {"stale": True}
        # 不應寫 cooldown（仍為 0.0）
        _, _, cooldown_until = _usage_cache["acct-c"]
        assert cooldown_until == 0.0

    @patch("app.core.claude_usage.urllib.request.urlopen")
    def test_case_c_variant_429_unparseable_retry_after(self, mock_urlopen):
        """Case C 變體：Retry-After 無法解析（例如 'garbage'）同樣不寫 cooldown"""
        _usage_cache["acct-c2"] = (time.time() - 10, {"stale": True}, 0.0)
        mock_urlopen.side_effect = _http_error_429(retry_after="garbage")

        result = _fetch_usage("tok", cache_key="acct-c2")

        assert result == {"stale": True}
        _, _, cooldown_until = _usage_cache["acct-c2"]
        assert cooldown_until == 0.0
