"""gemini_usage.py 單元測試 — 覆蓋 _load_oauth_constants / _get_access_token / get_gemini_quota / get_gemini_usage"""

import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import app.core.gemini_usage as mod


# ── helpers ───────────────────────────────────────────────────────

def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture(autouse=True)
def reset_quota_cache():
    """每個 test 前後清空快取，避免交叉污染"""
    mod._quota_cache.clear()
    mod._quota_cache_time = 0
    yield
    mod._quota_cache.clear()
    mod._quota_cache_time = 0


# ── 1. _load_oauth_constants ─────────────────────────────────────

class TestLoadOauthConstants:
    def test_env_vars_take_priority(self, monkeypatch, tmp_path):
        """環境變數優先讀取"""
        monkeypatch.setattr(mod, "GEMINI_DIR", tmp_path)
        monkeypatch.setenv("GEMINI_OAUTH_CLIENT_ID", "env-id")
        monkeypatch.setenv("GEMINI_OAUTH_CLIENT_SECRET", "env-secret")
        # 即使檔案存在，也應用 env
        _write_json(tmp_path / "oauth_creds.json", {
            "client_id": "file-id", "client_secret": "file-secret",
        })
        cid, csec = mod._load_oauth_constants()
        assert cid == "env-id"
        assert csec == "env-secret"

    def test_fallback_to_file(self, monkeypatch, tmp_path):
        """env 無值時 fallback 到 oauth_creds.json"""
        monkeypatch.setattr(mod, "GEMINI_DIR", tmp_path)
        monkeypatch.delenv("GEMINI_OAUTH_CLIENT_ID", raising=False)
        monkeypatch.delenv("GEMINI_OAUTH_CLIENT_SECRET", raising=False)
        _write_json(tmp_path / "oauth_creds.json", {
            "client_id": "file-id", "client_secret": "file-secret",
        })
        cid, csec = mod._load_oauth_constants()
        assert cid == "file-id"
        assert csec == "file-secret"

    def test_no_env_no_file_returns_empty(self, monkeypatch, tmp_path):
        """檔案也不存在時回傳空字串"""
        monkeypatch.setattr(mod, "GEMINI_DIR", tmp_path)
        monkeypatch.delenv("GEMINI_OAUTH_CLIENT_ID", raising=False)
        monkeypatch.delenv("GEMINI_OAUTH_CLIENT_SECRET", raising=False)
        cid, csec = mod._load_oauth_constants()
        assert cid == ""
        assert csec == ""


# ── 2. _get_access_token ─────────────────────────────────────────

class TestGetAccessToken:
    def test_creds_file_not_exists(self, monkeypatch, tmp_path):
        """creds 檔不存在 → None"""
        monkeypatch.setattr(mod, "GEMINI_DIR", tmp_path)
        assert mod._get_access_token() is None

    def test_token_not_expired(self, monkeypatch, tmp_path):
        """token 未過期 → 直接回傳 access_token"""
        monkeypatch.setattr(mod, "GEMINI_DIR", tmp_path)
        future_ms = int((time.time() + 3600) * 1000)
        _write_json(tmp_path / "oauth_creds.json", {
            "access_token": "valid-tok",
            "expiry_date": future_ms,
        })
        assert mod._get_access_token() == "valid-tok"

    def test_expiry_iso_string_parsed(self, monkeypatch, tmp_path):
        """expiry 為 ISO string 格式正確解析"""
        monkeypatch.setattr(mod, "GEMINI_DIR", tmp_path)
        # 設定一個未來的 ISO 時間字串
        _write_json(tmp_path / "oauth_creds.json", {
            "access_token": "iso-tok",
            "expiry_date": "2099-12-31T23:59:59Z",
        })
        assert mod._get_access_token() == "iso-tok"

    def test_expired_refresh_success(self, monkeypatch, tmp_path):
        """token 過期 + refresh 成功 → 新 token + 寫回檔案"""
        monkeypatch.setattr(mod, "GEMINI_DIR", tmp_path)
        monkeypatch.setattr(mod, "OAUTH_CLIENT_ID", "cid")
        monkeypatch.setattr(mod, "OAUTH_CLIENT_SECRET", "csec")
        # 已過期的 token
        _write_json(tmp_path / "oauth_creds.json", {
            "access_token": "old-tok",
            "expiry_date": 0,
            "refresh_token": "ref-tok",
        })
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "new-tok",
            "expires_in": 3600,
        }
        with patch.object(mod.http_requests, "post", return_value=mock_resp):
            result = mod._get_access_token()

        assert result == "new-tok"
        # 確認寫回檔案
        saved = json.loads((tmp_path / "oauth_creds.json").read_text())
        assert saved["access_token"] == "new-tok"
        assert saved["expiry_date"] > 0

    def test_expired_refresh_failure_fallback(self, monkeypatch, tmp_path):
        """token 過期 + refresh 失敗 → fallback 舊 token"""
        monkeypatch.setattr(mod, "GEMINI_DIR", tmp_path)
        monkeypatch.setattr(mod, "OAUTH_CLIENT_ID", "cid")
        monkeypatch.setattr(mod, "OAUTH_CLIENT_SECRET", "csec")
        _write_json(tmp_path / "oauth_creds.json", {
            "access_token": "old-tok",
            "expiry_date": 0,
            "refresh_token": "ref-tok",
        })
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        with patch.object(mod.http_requests, "post", return_value=mock_resp):
            result = mod._get_access_token()

        assert result == "old-tok"

    def test_no_refresh_token_returns_old(self, monkeypatch, tmp_path):
        """無 refresh_token → 直接回傳舊 token"""
        monkeypatch.setattr(mod, "GEMINI_DIR", tmp_path)
        _write_json(tmp_path / "oauth_creds.json", {
            "access_token": "stale-tok",
            "expiry_date": 0,
            # 沒有 refresh_token
        })
        assert mod._get_access_token() == "stale-tok"


# ── 3. get_gemini_quota ──────────────────────────────────────────

class TestGetGeminiQuota:
    def test_cache_valid_returns_cached(self, monkeypatch):
        """cache 有效期內 → 直接回傳快取"""
        mod._quota_cache = {"model-a": {"remaining": 80.0}}
        mod._quota_cache_time = time.time()
        with patch.object(mod, "_get_access_token") as mock_tok:
            result = mod.get_gemini_quota()
        mock_tok.assert_not_called()
        assert result == {"model-a": {"remaining": 80.0}}

    def test_cache_expired_calls_api(self, monkeypatch):
        """cache 過期 → 呼叫 API"""
        mod._quota_cache = {"old": True}
        mod._quota_cache_time = time.time() - mod.QUOTA_CACHE_TTL - 1

        monkeypatch.setattr(mod, "_get_access_token", lambda: "tok")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "buckets": [
                {"modelId": "gemini-pro", "remainingFraction": 0.75,
                 "resetTime": "2026-03-24T12:00:00Z", "tokenType": "rpm"},
            ]
        }
        with patch.object(mod.http_requests, "post", return_value=mock_resp):
            result = mod.get_gemini_quota()

        assert "gemini-pro" in result
        assert result["gemini-pro"]["remaining"] == 75.0

    def test_api_success_filters_vertex(self, monkeypatch):
        """API 回傳成功 → 正確解析 buckets、過濾 _vertex"""
        mod._quota_cache_time = 0
        monkeypatch.setattr(mod, "_get_access_token", lambda: "tok")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "buckets": [
                {"modelId": "gemini-pro", "remainingFraction": 0.5,
                 "resetTime": "T1", "tokenType": "rpm"},
                {"modelId": "gemini-pro_vertex", "remainingFraction": 0.9,
                 "resetTime": "T2", "tokenType": "rpm"},
                {"modelId": "gemini-flash", "remainingFraction": 1.0,
                 "resetTime": "T3", "tokenType": "tpm"},
            ]
        }
        with patch.object(mod.http_requests, "post", return_value=mock_resp):
            result = mod.get_gemini_quota()

        assert "gemini-pro" in result
        assert "gemini-flash" in result
        assert "gemini-pro_vertex" not in result
        assert result["gemini-pro"]["remaining"] == 50.0
        assert result["gemini-flash"]["remaining"] == 100.0

    def test_api_failure_returns_none(self, monkeypatch):
        """API 失敗 → 回傳 None"""
        mod._quota_cache_time = 0
        monkeypatch.setattr(mod, "_get_access_token", lambda: "tok")
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch.object(mod.http_requests, "post", return_value=mock_resp):
            result = mod.get_gemini_quota()

        assert result is None


# ── 4. get_gemini_usage ──────────────────────────────────────────

class TestGetGeminiUsage:
    def test_with_account_and_quota(self, monkeypatch, tmp_path):
        """有 account + quota → 整合回傳"""
        monkeypatch.setattr(mod, "GEMINI_DIR", tmp_path)
        _write_json(tmp_path / "google_accounts.json", {"active": "user@gmail.com"})
        monkeypatch.setattr(mod, "get_gemini_quota", lambda: {
            "gemini-pro": {"remaining": 60.0}
        })
        result = mod.get_gemini_usage()
        assert result["account"] == "user@gmail.com"
        assert result["quota"]["gemini-pro"]["remaining"] == 60.0

    def test_no_accounts_file(self, monkeypatch, tmp_path):
        """無 accounts 檔 → account=None"""
        monkeypatch.setattr(mod, "GEMINI_DIR", tmp_path)
        monkeypatch.setattr(mod, "get_gemini_quota", lambda: {})
        result = mod.get_gemini_usage()
        assert result["account"] is None
        assert result["quota"] == {}
