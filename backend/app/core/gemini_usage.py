"""Gemini CLI 配額查詢（Google RetrieveUserQuota API）"""
import json
import logging
import os
import time
from datetime import datetime
import requests as http_requests
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

GEMINI_DIR = Path.home() / ".gemini"

# Gemini CLI OAuth — 優先從環境變數讀取，否則從 credential 檔案取得
def _load_oauth_constants():
    client_id = os.environ.get("GEMINI_OAUTH_CLIENT_ID", "")
    client_secret = os.environ.get("GEMINI_OAUTH_CLIENT_SECRET", "")
    if client_id and client_secret:
        return client_id, client_secret
    # Fallback: 從 ~/.gemini/oauth_creds.json 讀取
    creds_file = GEMINI_DIR / "oauth_creds.json"
    if creds_file.exists():
        try:
            with open(creds_file, encoding="utf-8") as f:
                creds = json.load(f)
            client_id = client_id or creds.get("client_id", "")
            client_secret = client_secret or creds.get("client_secret", "")
        except Exception:
            pass
    return client_id, client_secret

OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET = _load_oauth_constants()
QUOTA_API_URL = "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota"
TOKEN_REFRESH_URL = "https://oauth2.googleapis.com/token"

# 快取配額結果（避免頻繁呼叫 Google API）
_quota_cache: Dict[str, Any] = {}
_quota_cache_time: float = 0
QUOTA_CACHE_TTL = 60  # 60 秒快取


def _get_access_token() -> Optional[str]:
    """從 ~/.gemini/oauth_creds.json 取得有效的 access_token，過期則自動刷新"""
    creds_file = GEMINI_DIR / "oauth_creds.json"
    if not creds_file.exists():
        return None

    try:
        with open(creds_file, encoding="utf-8") as f:
            creds = json.load(f)
    except Exception:
        return None

    # 檢查是否過期（預留 60 秒緩衝）
    expiry = creds.get("expiry_date", 0)
    if isinstance(expiry, str):
        try:
            expiry = datetime.fromisoformat(expiry.replace("Z", "+00:00")).timestamp() * 1000
        except Exception:
            expiry = 0

    now_ms = time.time() * 1000
    if now_ms < expiry - 60000:
        return creds.get("access_token")

    # Token 過期，用 refresh_token 刷新
    refresh_token = creds.get("refresh_token")
    if not refresh_token:
        return creds.get("access_token")  # 沒有 refresh_token 就試試舊的

    try:
        resp = http_requests.post(TOKEN_REFRESH_URL, data={
            "client_id": OAUTH_CLIENT_ID,
            "client_secret": OAUTH_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }, timeout=10)
        if resp.status_code == 200:
            new_data = resp.json()
            creds["access_token"] = new_data["access_token"]
            creds["expiry_date"] = int(time.time() * 1000) + new_data.get("expires_in", 3600) * 1000
            # 寫回檔案
            with open(creds_file, "w", encoding="utf-8") as f:
                json.dump(creds, f)
            logger.info("Gemini OAuth token refreshed")
            return creds["access_token"]
    except Exception as e:
        logger.warning(f"Failed to refresh Gemini token: {e}")

    return creds.get("access_token")


def get_gemini_quota() -> Optional[Dict[str, Any]]:
    """呼叫 Google RetrieveUserQuota API 取得 per-model 配額"""
    global _quota_cache, _quota_cache_time

    # 快取檢查
    if time.time() - _quota_cache_time < QUOTA_CACHE_TTL and _quota_cache:
        return _quota_cache

    token = _get_access_token()
    if not token:
        return None

    try:
        resp = http_requests.post(
            QUOTA_API_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"project": "gemini-cli"},
            timeout=10,
        )
        if resp.status_code != 200:
            ts = datetime.now().strftime("%H:%M:%S")
            logger.warning(f"[{ts}] RetrieveUserQuota returned {resp.status_code}")
            return None

        data = resp.json()
        buckets = data.get("buckets", [])

        # 過濾 _vertex 重複，整理成簡潔格式
        quota = {}
        for b in buckets:
            model_id = b.get("modelId", "")
            if model_id.endswith("_vertex"):
                continue
            quota[model_id] = {
                "remaining": round(b.get("remainingFraction", 0) * 100, 1),
                "reset_time": b.get("resetTime", ""),
                "token_type": b.get("tokenType", ""),
            }

        _quota_cache = quota
        _quota_cache_time = time.time()
        return quota
    except Exception as e:
        logger.warning(f"Failed to fetch Gemini quota: {e}")
        return None


def get_gemini_usage() -> Dict[str, Any]:
    """取得 Gemini 帳號資訊 + 配額"""
    # 帳號資訊
    account = None
    accounts_file = GEMINI_DIR / "google_accounts.json"
    try:
        if accounts_file.exists():
            with open(accounts_file, encoding="utf-8") as fh:
                acc = json.load(fh)
            account = acc.get("active") if isinstance(acc, dict) else None
    except Exception:
        pass

    # 配額
    quota = get_gemini_quota() or {}

    return {
        "account": account,
        "quota": quota,
    }
