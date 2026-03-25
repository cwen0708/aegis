"""sanitize_output 去敏過濾測試"""
from app.core.executor.emitter import sanitize_output


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
