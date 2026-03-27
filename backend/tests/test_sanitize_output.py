"""sanitize_output 去敏過濾測試 + guard_for_ai → restore 端到端測試"""
from app.core.executor.emitter import sanitize_output
from app.core.data_classifier import guard_for_ai, restore


class TestSanitizeOutput:
    """路徑去敏"""

    def test_linux_home_path(self):
        assert "backend/worker.py" in sanitize_output("/home/cwen0708/projects/Aegis/backend/worker.py")
        assert "/home/cwen0708" not in sanitize_output("/home/cwen0708/projects/Aegis/backend/worker.py")

    def test_any_linux_user(self):
        """任何 /home/xxx/ 都應被脫敏"""
        assert sanitize_output("/home/john/test.py") == "test.py"
        assert sanitize_output("/home/admin/.config/secret") == ".config/secret"

    def test_nested_aegis_path(self):
        result = sanitize_output("/home/user/.local/aegis/backend/app/core/runner.py")
        assert "/home/" not in result
        assert "runner.py" in result

    def test_no_path(self):
        assert sanitize_output("Hello world") == "Hello world"

    def test_empty(self):
        assert sanitize_output("") == ""

    def test_multiple_paths_in_one_string(self):
        text = "Error in /home/cwen0708/projects/A/x.py and /home/cwen0708/projects/B/y.py"
        result = sanitize_output(text)
        assert "/home/" not in result
        assert "x.py" in result
        assert "y.py" in result

    def test_preserves_non_home_paths(self):
        """非 /home/ 路徑不應被動"""
        assert sanitize_output("/etc/nginx/nginx.conf") == "/etc/nginx/nginx.conf"
        assert sanitize_output("/var/log/syslog") == "/var/log/syslog"

    def test_partial_path_no_trailing_slash(self):
        """/home/user 沒有結尾 / 不應被替換（避免誤殺）"""
        # regex 是 /home/xxx/ 帶斜線，所以 /home/user 不會被替換
        assert "/home/user" in sanitize_output("/home/user")


class TestGuardForAiRestore:
    """guard_for_ai → AI 回應 → restore 端到端測試"""

    def test_roundtrip_single_email(self):
        """單一 email 經 guard → 模擬 AI 回應含佔位符 → restore 還原。"""
        original = "請聯絡 alice@example.com 取得報告"
        sanitized, redact_map = guard_for_ai(original)

        assert "alice@example.com" not in sanitized
        assert len(redact_map) == 1

        placeholder = list(redact_map.keys())[0]
        ai_response = f"好的，我會寄信到 {placeholder} 通知對方。"

        restored = restore(ai_response, redact_map)
        assert "alice@example.com" in restored
        assert "<<REDACTED:" not in restored

    def test_roundtrip_multiple_s2(self):
        """多個 S2 匹配（email + 手機）同時還原。"""
        original = "聯絡人：bob@corp.tw，電話 0912-345-678"
        sanitized, redact_map = guard_for_ai(original)

        assert "bob@corp.tw" not in sanitized
        assert "0912-345-678" not in sanitized
        assert len(redact_map) >= 2

        ai_response = f"已記錄：{sanitized}"
        restored = restore(ai_response, redact_map)

        assert "bob@corp.tw" in restored
        assert "0912-345-678" in restored
        assert "<<REDACTED:" not in restored

    def test_empty_mapping_noop(self):
        """redact_map 為空時 restore 不做任何操作。"""
        text = "這是一般文字，沒有敏感資料"
        sanitized, redact_map = guard_for_ai(text)

        assert redact_map == {}
        assert sanitized == text
        assert restore(sanitized, redact_map) == text

    def test_s1_passthrough(self):
        """S1 等級文字原文通過，不產生佔位符。"""
        text = "Hello world, no PII here"
        sanitized, redact_map = guard_for_ai(text)

        assert sanitized == text
        assert redact_map == {}
