"""
http_retry.parse_retry_after 單元測試
"""
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

from app.core.http_retry import MAX_RETRY_AFTER_SECS, parse_retry_after


class TestParseRetryAfter:
    """RFC 7231 Retry-After header 解析"""

    def test_none_returns_none(self):
        assert parse_retry_after(None) is None

    def test_empty_string_returns_none(self):
        assert parse_retry_after("") is None
        assert parse_retry_after("   ") is None

    def test_plain_seconds(self):
        assert parse_retry_after("120") == 120.0

    def test_negative_seconds_returns_none(self):
        assert parse_retry_after("-5") is None

    def test_exceeds_max_is_clamped(self):
        assert parse_retry_after("99999") == MAX_RETRY_AFTER_SECS

    def test_future_http_date(self):
        future = datetime.now(tz=timezone.utc) + timedelta(seconds=60)
        result = parse_retry_after(format_datetime(future, usegmt=True))
        assert result is not None
        assert abs(result - 60.0) <= 5.0

    def test_past_http_date_returns_zero(self):
        past = datetime.now(tz=timezone.utc) - timedelta(seconds=30)
        assert parse_retry_after(format_datetime(past, usegmt=True)) == 0.0

    def test_invalid_string_returns_none(self):
        assert parse_retry_after("foo") is None

    def test_zero_seconds(self):
        assert parse_retry_after("0") == 0.0
