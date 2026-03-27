"""Tests for worker retry count logic."""
import pytest
from worker import _count_retry_attempts, MAX_RETRY_ATTEMPTS


class TestCountRetryAttempts:
    def test_count_zero_retries(self):
        content = "一般卡片內容，沒有任何錯誤紀錄"
        assert _count_retry_attempts(content) == 0

    def test_count_zero_retries_empty(self):
        assert _count_retry_attempts("") == 0

    def test_count_single_retry(self):
        content = "任務描述\n\n### Error (retry 1/3)\n錯誤類型: network | 建議: retry"
        assert _count_retry_attempts(content) == 1

    def test_count_multiple_retries(self):
        content = (
            "任務描述\n\n"
            "### Error (retry 1/3)\n錯誤類型: network\n\n"
            "### Error (retry 2/3)\n錯誤類型: timeout\n\n"
            "### Error (retry 3/3)\n錯誤類型: network"
        )
        assert _count_retry_attempts(content) == 3

    def test_plain_error_not_counted(self):
        """'### Error' without '(retry' should not be counted as a retry attempt."""
        content = "任務描述\n\n### Error\n錯誤類型: auth_failure"
        assert _count_retry_attempts(content) == 0

    def test_mixed_error_types(self):
        content = (
            "### Error\n非重試錯誤\n\n"
            "### Error (retry 1/3)\n第一次重試\n\n"
            "### Error (retry 2/3)\n第二次重試"
        )
        assert _count_retry_attempts(content) == 2


class TestRetryWithinLimit:
    def test_retry_within_limit(self):
        """When retry_count < MAX_RETRY_ATTEMPTS, retry should be allowed."""
        content_no_retry = "任務描述"
        retry_count = _count_retry_attempts(content_no_retry)
        assert retry_count < MAX_RETRY_ATTEMPTS
        assert retry_count == 0

    def test_retry_after_one_attempt(self):
        content = "任務描述\n\n### Error (retry 1/3)\n錯誤"
        retry_count = _count_retry_attempts(content)
        assert retry_count < MAX_RETRY_ATTEMPTS
        assert retry_count == 1

    def test_retry_after_two_attempts(self):
        content = (
            "任務描述\n\n"
            "### Error (retry 1/3)\n錯誤\n\n"
            "### Error (retry 2/3)\n錯誤"
        )
        retry_count = _count_retry_attempts(content)
        assert retry_count < MAX_RETRY_ATTEMPTS
        assert retry_count == 2


class TestRetryExceedsLimit:
    def test_retry_exceeds_limit(self):
        """When retry_count >= MAX_RETRY_ATTEMPTS, no more retries."""
        content = "\n\n".join(
            f"### Error (retry {i+1}/{MAX_RETRY_ATTEMPTS})\n錯誤"
            for i in range(MAX_RETRY_ATTEMPTS)
        )
        retry_count = _count_retry_attempts(content)
        assert retry_count >= MAX_RETRY_ATTEMPTS
        assert retry_count == MAX_RETRY_ATTEMPTS

    def test_max_retry_constant(self):
        assert MAX_RETRY_ATTEMPTS == 3
