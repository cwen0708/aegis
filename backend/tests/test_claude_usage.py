"""claude_usage.py 單元測試 — 覆蓋 _format_usage / _read_token / _read_account_info / _fetch_usage / get_all_accounts_usage"""

import json
import time
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from app.core.claude_usage import (
    _format_usage,
    _read_token,
    _read_account_info,
    _fetch_usage,
    _usage_cache,
    CACHE_TTL,
    get_all_accounts_usage,
)


# ── fixtures ──────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_cache():
    """每個 test 前清空快取，避免交叉污染"""
    _usage_cache.clear()
    yield
    _usage_cache.clear()


def _write_creds(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ── 1. _format_usage ─────────────────────────────────────────────

class TestFormatUsage:
    def test_none_input(self):
        assert _format_usage(None) is None

    def test_empty_dict(self):
        assert _format_usage({}) is None  # not raw → None

    def test_full_data(self):
        raw = {
            "five_hour": {"utilization": 0.42, "resets_at": "2026-03-24T12:00:00Z"},
            "seven_day": {"utilization": 0.8, "resets_at": "2026-03-30T00:00:00Z"},
        }
        result = _format_usage(raw)
        assert result["five_hour"]["utilization"] == 0.42
        assert result["seven_day"]["resets_at"] == "2026-03-30T00:00:00Z"

    def test_partial_fields(self):
        """只有 five_hour，其他欄位缺失"""
        raw = {"five_hour": {"utilization": 0.1}}
        result = _format_usage(raw)
        assert "five_hour" in result
        assert result["five_hour"]["resets_at"] == ""
        assert "seven_day" not in result

    def test_extra_usage_enabled(self):
        raw = {
            "extra_usage": {
                "is_enabled": True,
                "monthly_limit": 100,
                "used_credits": 30,
            }
        }
        result = _format_usage(raw)
        assert result["extra_usage"]["is_enabled"] is True
        assert result["extra_usage"]["monthly_limit"] == 100

    def test_extra_usage_disabled(self):
        raw = {"extra_usage": {"is_enabled": False}}
        result = _format_usage(raw)
        assert result["extra_usage"]["is_enabled"] is False
        assert result["extra_usage"]["used_credits"] == 0

    def test_non_dict_value_skipped(self):
        """非 dict 型別的 value 不應出現在結果"""
        raw = {"five_hour": "not-a-dict", "seven_day": 123}
        result = _format_usage(raw)
        assert result == {}

    def test_all_four_keys(self):
        raw = {k: {"utilization": 0.5, "resets_at": "T"} for k in
               ["five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet"]}
        result = _format_usage(raw)
        assert len(result) == 4


# ── 2. _read_token / _read_account_info ──────────────────────────

class TestReadToken:
    def test_normal(self, tmp_path):
        creds = tmp_path / "creds.json"
        _write_creds(creds, {"claudeAiOauth": {"accessToken": "tok-123"}})
        assert _read_token(creds) == "tok-123"

    def test_missing_oauth_key(self, tmp_path):
        creds = tmp_path / "creds.json"
        _write_creds(creds, {"other": "data"})
        assert _read_token(creds) is None

    def test_file_not_exists(self, tmp_path):
        assert _read_token(tmp_path / "nonexistent.json") is None

    def test_bad_json(self, tmp_path):
        creds = tmp_path / "creds.json"
        creds.write_text("{bad json", encoding="utf-8")
        assert _read_token(creds) is None


class TestReadAccountInfo:
    def test_normal(self, tmp_path):
        creds = tmp_path / "creds.json"
        _write_creds(creds, {
            "claudeAiOauth": {
                "subscriptionType": "pro",
                "rateLimitTier": "tier_2",
            }
        })
        info = _read_account_info(creds)
        assert info["subscriptionType"] == "pro"
        assert info["rateLimitTier"] == "tier_2"

    def test_missing_oauth(self, tmp_path):
        creds = tmp_path / "creds.json"
        _write_creds(creds, {})
        info = _read_account_info(creds)
        assert info["subscriptionType"] == "unknown"

    def test_file_not_exists(self, tmp_path):
        assert _read_account_info(tmp_path / "nope.json") == {}

    def test_bad_json(self, tmp_path):
        creds = tmp_path / "creds.json"
        creds.write_text("!!!", encoding="utf-8")
        assert _read_account_info(creds) == {}


# ── 3. _fetch_usage (TTL cache) ─────────────────────────────────

class TestFetchUsage:
    def _mock_response(self, data: dict):
        resp = MagicMock()
        resp.read.return_value = json.dumps(data).encode()
        return resp

    @patch("app.core.claude_usage.urllib.request.urlopen")
    def test_cache_miss_makes_request(self, mock_urlopen):
        payload = {"five_hour": {"utilization": 0.5}}
        mock_urlopen.return_value = self._mock_response(payload)
        result = _fetch_usage("tok", cache_key="acct1")
        assert result == payload
        mock_urlopen.assert_called_once()

    @patch("app.core.claude_usage.urllib.request.urlopen")
    def test_cache_hit_no_request(self, mock_urlopen):
        _usage_cache["acct1"] = (time.time(), {"cached": True})
        result = _fetch_usage("tok", cache_key="acct1")
        assert result == {"cached": True}
        mock_urlopen.assert_not_called()

    @patch("app.core.claude_usage.urllib.request.urlopen")
    def test_cache_expired_refetch(self, mock_urlopen):
        _usage_cache["acct1"] = (time.time() - CACHE_TTL - 1, {"old": True})
        mock_urlopen.return_value = self._mock_response({"new": True})
        result = _fetch_usage("tok", cache_key="acct1")
        assert result == {"new": True}
        mock_urlopen.assert_called_once()

    @patch("app.core.claude_usage.urllib.request.urlopen")
    def test_429_with_cache_fallback(self, mock_urlopen):
        _usage_cache["acct1"] = (time.time() - CACHE_TTL - 1, {"stale": True})
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=429, msg="Too Many Requests", hdrs=None, fp=None
        )
        result = _fetch_usage("tok", cache_key="acct1")
        assert result == {"stale": True}

    @patch("app.core.claude_usage.urllib.request.urlopen")
    def test_429_without_cache_returns_none(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=429, msg="", hdrs=None, fp=None
        )
        assert _fetch_usage("tok", cache_key="acct1") is None

    @patch("app.core.claude_usage.urllib.request.urlopen")
    def test_other_http_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=500, msg="Server Error", hdrs=None, fp=None
        )
        assert _fetch_usage("tok", cache_key="acct1") is None

    @patch("app.core.claude_usage.urllib.request.urlopen")
    def test_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = OSError("connection refused")
        assert _fetch_usage("tok", cache_key="acct1") is None

    @patch("app.core.claude_usage.urllib.request.urlopen")
    def test_no_cache_key(self, mock_urlopen):
        """cache_key 為空字串時，不使用快取"""
        mock_urlopen.return_value = self._mock_response({"data": 1})
        result = _fetch_usage("tok", cache_key="")
        assert result == {"data": 1}
        assert "" not in _usage_cache


# ── 4. get_all_accounts_usage (整合) ─────────────────────────────

class TestGetAllAccountsUsage:
    @patch("app.core.claude_usage._fetch_usage", return_value=None)
    @patch("app.core.claude_usage.PROFILES_DIR")
    @patch("app.core.claude_usage.CREDS_FILE")
    def test_no_profiles_uses_default(self, mock_creds, mock_profiles, mock_fetch, tmp_path):
        # 模擬無 profiles 目錄
        mock_profiles.exists.return_value = False
        creds = tmp_path / "creds.json"
        _write_creds(creds, {"claudeAiOauth": {"accessToken": "tok", "subscriptionType": "pro"}})
        mock_creds.__class__ = type(creds)  # 讓 Path 方法可用
        # 直接 patch 底層讀取函式
        with patch("app.core.claude_usage._read_token", return_value="tok"), \
             patch("app.core.claude_usage._read_account_info", return_value={"subscriptionType": "pro", "rateLimitTier": "unknown"}):
            result = get_all_accounts_usage()
        assert len(result) == 1
        assert result[0]["name"] == "default"
        assert result[0]["is_active"] is True
        assert result[0]["subscriptionType"] == "pro"

    @patch("app.core.claude_usage._fetch_usage", return_value=None)
    @patch("app.core.claude_usage.time.sleep")  # 避免真的 sleep
    @patch("app.core.claude_usage.PROFILES_DIR")
    def test_profiles_with_active_file(self, mock_profiles_dir, mock_sleep, mock_fetch, tmp_path):
        profiles = tmp_path / "profiles"
        profiles.mkdir()
        _write_creds(profiles / "alice.json", {"claudeAiOauth": {"accessToken": "a"}})
        _write_creds(profiles / "bob.json", {"claudeAiOauth": {"accessToken": "b"}})
        (profiles / ".active").write_text("bob", encoding="utf-8")

        mock_profiles_dir.exists.return_value = True
        mock_profiles_dir.glob.return_value = sorted(profiles.glob("*.json"))
        mock_profiles_dir.__truediv__ = lambda self, name: profiles / name

        result = get_all_accounts_usage()
        assert len(result) == 2
        names = {r["name"]: r["is_active"] for r in result}
        assert names["bob"] is True
        assert names["alice"] is False

    @patch("app.core.claude_usage._fetch_usage", return_value=None)
    @patch("app.core.claude_usage.time.sleep")
    @patch("app.core.claude_usage.CREDS_FILE")
    @patch("app.core.claude_usage.PROFILES_DIR")
    def test_profiles_no_active_token_match(self, mock_profiles_dir, mock_creds, mock_sleep, mock_fetch, tmp_path):
        profiles = tmp_path / "profiles"
        profiles.mkdir()
        _write_creds(profiles / "alice.json", {"claudeAiOauth": {"accessToken": "tok-a"}})
        _write_creds(profiles / "bob.json", {"claudeAiOauth": {"accessToken": "tok-b"}})

        mock_profiles_dir.exists.return_value = True
        mock_profiles_dir.glob.return_value = sorted(profiles.glob("*.json"))
        mock_profiles_dir.__truediv__ = lambda self, name: profiles / name

        mock_creds.exists.return_value = True

        # 建立一個 lookup 表：mock_creds → tok-b，真實 profile path → 用真實函式讀
        real_read_token = _read_token
        def token_side_effect(path):
            if path is mock_creds:
                return "tok-b"
            return real_read_token(path)

        with patch("app.core.claude_usage._read_token", side_effect=token_side_effect):
            result = get_all_accounts_usage()

        names = {r["name"]: r["is_active"] for r in result}
        assert names["bob"] is True

    @patch("app.core.claude_usage._fetch_usage", return_value=None)
    @patch("app.core.claude_usage.time.sleep")
    @patch("app.core.claude_usage.CREDS_FILE")
    @patch("app.core.claude_usage.PROFILES_DIR")
    def test_profiles_no_active_fallback_first(self, mock_profiles_dir, mock_creds, mock_sleep, mock_fetch, tmp_path):
        """無 .active、token 也不匹配 → 用第一個 profile"""
        profiles = tmp_path / "profiles"
        profiles.mkdir()
        _write_creds(profiles / "alice.json", {"claudeAiOauth": {"accessToken": "tok-a"}})
        _write_creds(profiles / "bob.json", {"claudeAiOauth": {"accessToken": "tok-b"}})

        mock_profiles_dir.exists.return_value = True
        mock_profiles_dir.glob.return_value = sorted(profiles.glob("*.json"))
        mock_profiles_dir.__truediv__ = lambda self, name: profiles / name
        mock_creds.exists.return_value = False

        result = get_all_accounts_usage()
        # 第一個（alice）應為 active
        assert result[0]["name"] == "alice"
        assert result[0]["is_active"] is True
