"""Claude 帳號用量查詢"""
import json
import os
import logging
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import urllib.request
import ssl

logger = logging.getLogger(__name__)

CREDS_FILE = Path.home() / ".claude" / ".credentials.json"
PROFILES_DIR = Path.home() / ".claude-profiles"

# per-account 快取：{ cache_key: (timestamp, data) }
_usage_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
CACHE_TTL = 120  # 秒：同一帳號 120 秒內不重複查詢


def _fetch_usage(token: str, cache_key: str = "") -> Optional[Dict[str, Any]]:
    """用 OAuth token 查詢 Anthropic usage API，帶 TTL 快取避免 429"""
    # TTL 快取：最近查過就直接回傳
    if cache_key and cache_key in _usage_cache:
        ts, cached = _usage_cache[cache_key]
        if time.time() - ts < CACHE_TTL:
            return cached

    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/api/oauth/usage",
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20",
                "Content-Type": "application/json",
            },
        )
        ctx = ssl.create_default_context()
        resp = urllib.request.urlopen(req, context=ctx, timeout=10)
        result = json.loads(resp.read())
        if cache_key:
            _usage_cache[cache_key] = (time.time(), result)
        return result
    except urllib.error.HTTPError as e:
        if e.code == 429 and cache_key and cache_key in _usage_cache:
            logger.info(f"[Claude Usage] 429 for {cache_key}, using cached data")
            return _usage_cache[cache_key][1]
        logger.warning(f"[Claude Usage] API query failed: {e}")
        return None
    except Exception as e:
        logger.warning(f"[Claude Usage] API query failed: {e}")
        return None


def _read_token(filepath: Path) -> Optional[str]:
    """從 credentials JSON 讀取 accessToken"""
    try:
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("claudeAiOauth", {}).get("accessToken")
    except Exception:
        return None


def _read_account_info(filepath: Path) -> Dict[str, Any]:
    """讀取帳號的訂閱類型等資訊"""
    try:
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        oauth = data.get("claudeAiOauth", {})
        return {
            "subscriptionType": oauth.get("subscriptionType", "unknown"),
            "rateLimitTier": oauth.get("rateLimitTier", "unknown"),
        }
    except Exception:
        return {}


def get_all_accounts_usage() -> List[Dict[str, Any]]:
    """取得所有帳號的用量"""
    accounts = []

    # 1. 檢查 profiles 目錄
    profile_files = sorted(PROFILES_DIR.glob("*.json")) if PROFILES_DIR.exists() else []

    if profile_files:
        # 判斷活躍帳號：.active 檔案 → 或目前 credentials 同檔 → 或第一個
        active_name = ""
        active_file = PROFILES_DIR / ".active"
        if active_file.exists():
            active_name = active_file.read_text().strip()

        # 如果沒有 .active，用目前 credentials 比對
        if not active_name and CREDS_FILE.exists():
            current_token = _read_token(CREDS_FILE)
            if current_token:
                for f in profile_files:
                    if _read_token(f) == current_token:
                        active_name = f.stem
                        break

        # 還是沒有就用第一個
        if not active_name and profile_files:
            active_name = profile_files[0].stem

        for f in profile_files:
            name = f.stem
            token = _read_token(f)
            info = _read_account_info(f)
            usage = _fetch_usage(token, cache_key=name) if token else None

            accounts.append({
                "name": name,
                "is_active": name == active_name,
                **info,
                "usage": _format_usage(usage),
            })
    else:
        # 2. 只有目前帳號（無 profiles 目錄）
        token = _read_token(CREDS_FILE)
        info = _read_account_info(CREDS_FILE)
        usage = _fetch_usage(token, cache_key="default") if token else None

        accounts.append({
            "name": "default",
            "is_active": True,
            **info,
            "usage": _format_usage(usage),
        })

    return accounts


def _format_usage(raw: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """格式化 usage API 回傳"""
    if not raw:
        return None

    result = {}

    for key in ["five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet"]:
        val = raw.get(key)
        if val and isinstance(val, dict):
            result[key] = {
                "utilization": val.get("utilization", 0),
                "resets_at": val.get("resets_at", ""),
            }

    # extra_usage (overuse credits)
    extra = raw.get("extra_usage")
    if extra and isinstance(extra, dict):
        result["extra_usage"] = {
            "is_enabled": extra.get("is_enabled", False),
            "monthly_limit": extra.get("monthly_limit", 0),
            "used_credits": extra.get("used_credits", 0),
        }

    return result
