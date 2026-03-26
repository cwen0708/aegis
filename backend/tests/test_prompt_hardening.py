"""Tests for prompt_hardening module — per-message security injection."""
from app.core.prompt_hardening import (
    harden_prompt,
    harden_message,
    SECURITY_REMINDER,
    SECURITY_REMINDER_SHORT,
)


class TestHardenPrompt:
    """Tests for harden_prompt() — full security reminder for task prompts."""

    def test_appends_security_reminder(self):
        result = harden_prompt("Do something", "/project")
        assert "Do something" in result
        assert "<security-reminder>" in result
        assert "禁止讀寫 .env" in result

    def test_empty_prompt_unchanged(self):
        assert harden_prompt("", "/project") == ""

    def test_none_like_prompt(self):
        assert harden_prompt("", "/any") == ""

    def test_contains_full_rules(self):
        result = harden_prompt("task", "/p")
        assert "禁止存取 ~/.ssh/" in result
        assert "禁止執行 kill/pkill" in result
        assert "禁止安裝全域套件" in result


class TestHardenMessage:
    """Tests for harden_message() — short security reminder for per-message injection."""

    def test_appends_short_reminder(self):
        result = harden_message("Hello")
        assert "Hello" in result
        assert "<security-reminder>" in result

    def test_short_reminder_is_concise(self):
        result = harden_message("msg")
        # Should use the short version, not the full version
        assert "禁止" in result
        assert "洩露憑證" in result
        # Should NOT contain the verbose bullet-point list
        assert "禁止安裝全域套件或修改系統設定" not in result

    def test_empty_message_unchanged(self):
        assert harden_message("") == ""

    def test_preserves_original_message(self):
        original = "請幫我查看這段程式碼"
        result = harden_message(original)
        assert result.startswith(original)


class TestIntegrationPoints:
    """驗證注入點確實存在於 session_pool 和 runner。"""

    def test_session_pool_calls_harden_message(self):
        import inspect
        from app.core.session_pool import ProcessPool
        source = inspect.getsource(ProcessPool._send_and_read)
        assert "harden_message" in source

    def test_runner_calls_harden_prompt(self):
        import inspect
        from app.core.runner import run_ai_task
        source = inspect.getsource(run_ai_task)
        assert "harden_prompt" in source


class TestReminderTokenBudget:
    """Ensure security reminders stay within token budget."""

    def test_full_reminder_under_200_tokens(self):
        # Rough token estimate: ~4 chars per token for CJK
        estimated_tokens = len(SECURITY_REMINDER) / 3
        assert estimated_tokens < 200, f"Full reminder too long: ~{estimated_tokens:.0f} tokens"

    def test_short_reminder_under_80_tokens(self):
        estimated_tokens = len(SECURITY_REMINDER_SHORT) / 3
        assert estimated_tokens < 80, f"Short reminder too long: ~{estimated_tokens:.0f} tokens"
