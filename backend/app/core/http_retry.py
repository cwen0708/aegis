"""
HTTP Retry-After header 解析（RFC 7231 §7.1.3）

純函式模組，供後續 claude_usage / gemini_usage / channels adapter 整合使用。
"""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

MAX_RETRY_AFTER_SECS: float = 3600.0


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    """解析 Retry-After header，回傳等待秒數。

    支援兩種 RFC 7231 格式：
    - delta-seconds：純數字（例："120"）
    - HTTP-date (IMF-fixdate)：例 "Wed, 21 Oct 2015 07:28:00 GMT"

    規則：
    - None / 空字串 / 無法解析 → None
    - 負數 delta-seconds → None（視為無效輸入）
    - 過去時間的 HTTP-date → 0.0（可立即重試）
    - 超過 MAX_RETRY_AFTER_SECS → 截斷為上限
    """
    if value is None:
        return None

    text = value.strip()
    if not text:
        return None

    seconds = _parse_delta_seconds(text)
    if seconds is None:
        seconds = _parse_http_date(text)
    if seconds is None:
        return None

    if seconds < 0:
        return 0.0
    return min(seconds, MAX_RETRY_AFTER_SECS)


def _parse_delta_seconds(text: str) -> Optional[float]:
    """嘗試解析 delta-seconds；負數回傳 None（無效輸入）。"""
    try:
        seconds = float(text)
    except ValueError:
        return None
    if seconds < 0:
        return None
    return seconds


def _parse_http_date(text: str) -> Optional[float]:
    """嘗試解析 HTTP-date，回傳距今秒數（可為負，由呼叫端夾到 0）。"""
    try:
        target = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if target is None:
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    return (target - datetime.now(tz=timezone.utc)).total_seconds()
