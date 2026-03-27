"""Tests for error_classifier module."""
import pytest
from app.core.error_classifier import classify_error, ErrorCategory


class TestDependencyMissing:
    def test_module_not_found(self):
        output = "ModuleNotFoundError: No module named 'requests'"
        result = classify_error(output)
        assert result.category == ErrorCategory.dependency_missing
        assert result.retryable is False
        assert result.confidence >= 0.9

    def test_import_error_cannot_import(self):
        output = "ImportError: cannot import name 'foo' from 'bar'"
        result = classify_error(output)
        assert result.category == ErrorCategory.dependency_missing
        assert result.retryable is False

    def test_import_error_no_module(self):
        output = "ImportError: No module named something"
        result = classify_error(output)
        assert result.category == ErrorCategory.dependency_missing


class TestSyntaxError:
    def test_syntax_error(self):
        output = "SyntaxError: invalid syntax"
        result = classify_error(output)
        assert result.category == ErrorCategory.syntax_error
        assert result.retryable is False

    def test_indentation_error(self):
        output = "IndentationError: unexpected indent"
        result = classify_error(output)
        assert result.category == ErrorCategory.syntax_error
        assert result.retryable is False


class TestTestFailure:
    def test_pytest_failed(self):
        output = "FAILED tests/test_foo.py::test_bar - AssertionError"
        result = classify_error(output)
        assert result.category == ErrorCategory.test_failure
        assert result.retryable is False

    def test_pytest_summary(self):
        output = "===== 3 failed, 10 passed in 5.2s ====="
        # This matches "pytest.*N failed" pattern
        result = classify_error(output)
        assert result.category == ErrorCategory.test_failure


class TestApiError:
    def test_rate_limit(self):
        output = "Error: rate limit exceeded, please retry after 60s"
        result = classify_error(output)
        assert result.category == ErrorCategory.api_error
        assert result.retryable is True

    def test_429(self):
        output = "HTTP 429 Too Many Requests"
        result = classify_error(output)
        assert result.category == ErrorCategory.api_error
        assert result.retryable is True

    def test_api_connection_error(self):
        output = "APIConnectionError: connection refused"
        result = classify_error(output)
        assert result.category == ErrorCategory.api_error
        assert result.retryable is True

    def test_server_error(self):
        output = "500 Internal Server Error"
        result = classify_error(output)
        assert result.category == ErrorCategory.api_error
        assert result.retryable is True


class TestPermissionDenied:
    def test_permission_error(self):
        output = "PermissionError: [Errno 13] Permission denied: '/root/file'"
        result = classify_error(output)
        assert result.category == ErrorCategory.permission_denied
        assert result.retryable is False

    def test_eacces(self):
        output = "Error: EACCES: permission denied, open '/etc/passwd'"
        result = classify_error(output)
        assert result.category == ErrorCategory.permission_denied


class TestTimeout:
    def test_timeout_error(self):
        output = "TimeoutError: operation timed out"
        result = classify_error(output)
        assert result.category == ErrorCategory.timeout
        assert result.retryable is True

    def test_etimedout(self):
        output = "connect ETIMEDOUT 10.0.0.1:443"
        result = classify_error(output)
        assert result.category == ErrorCategory.timeout
        assert result.retryable is True


class TestResourceLimit:
    def test_oom(self):
        output = "Out of memory: Killed process 12345"
        result = classify_error(output)
        assert result.category == ErrorCategory.resource_limit
        assert result.retryable is False

    def test_memory_error(self):
        output = "MemoryError: unable to allocate array"
        result = classify_error(output)
        assert result.category == ErrorCategory.resource_limit
        assert result.retryable is False

    def test_disk_full(self):
        output = "OSError: No space left on device"
        result = classify_error(output)
        assert result.category == ErrorCategory.resource_limit
        assert result.retryable is False


class TestUnknownFallback:
    def test_unknown_error(self):
        output = "Something went wrong but we don't know what"
        result = classify_error(output)
        assert result.category == ErrorCategory.unknown
        assert result.retryable is True
        assert result.confidence < 0.5

    def test_empty_output(self):
        result = classify_error("")
        assert result.category == ErrorCategory.unknown
        assert result.retryable is True
        assert result.matched_pattern == ""

    def test_none_like_empty(self):
        result = classify_error("", exit_code=0)
        assert result.category == ErrorCategory.unknown
        assert result.retryable is True


class TestExitCode:
    def test_exit_code_passed_through(self):
        """exit_code 目前用於未來擴展，確認不會造成錯誤"""
        result = classify_error("SyntaxError: bad", exit_code=2)
        assert result.category == ErrorCategory.syntax_error

    def test_exit_code_zero_with_error_output(self):
        result = classify_error("ModuleNotFoundError: No module named 'x'", exit_code=0)
        assert result.category == ErrorCategory.dependency_missing
