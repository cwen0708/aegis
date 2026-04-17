"""SprintContractHook 單元測試"""
import logging
import pytest
from app.hooks import TaskContext
from app.hooks.sprint_contract import SprintContractHook, _parse_criteria, _check_criteria


# ── TestParseCriteria ──

class TestParseCriteria:

    def test_bullet_dash(self):
        assert _parse_criteria("- 條目一\n- 條目二") == ["條目一", "條目二"]

    def test_bullet_asterisk(self):
        assert _parse_criteria("* item A\n* item B") == ["item A", "item B"]

    def test_bullet_dot(self):
        assert _parse_criteria("• 第一條\n• 第二條") == ["第一條", "第二條"]

    def test_bullet_check(self):
        assert _parse_criteria("✓ done\n☐ pending") == ["done", "pending"]

    def test_numbered_dot(self):
        assert _parse_criteria("1. first\n2. second\n3. third") == ["first", "second", "third"]

    def test_numbered_paren(self):
        assert _parse_criteria("1) alpha\n2) beta") == ["alpha", "beta"]

    def test_plain_text(self):
        assert _parse_criteria("some plain line\nanother line") == ["some plain line", "another line"]

    def test_empty_lines_ignored(self):
        assert _parse_criteria("- A\n\n\n- B\n   \n- C") == ["A", "B", "C"]

    def test_chinese_criteria(self):
        text = "- 新增登入功能\n- 修正密碼驗證\n- 優化查詢效能"
        assert _parse_criteria(text) == ["新增登入功能", "修正密碼驗證", "優化查詢效能"]

    def test_empty_string(self):
        assert _parse_criteria("") == []

    def test_only_whitespace(self):
        assert _parse_criteria("   \n  \n\n") == []

    def test_mixed_formats(self):
        text = "- dash item\n* star item\n1. numbered item\nplain item"
        result = _parse_criteria(text)
        assert result == ["dash item", "star item", "numbered item", "plain item"]

    def test_bullet_only_lines_skipped(self):
        assert _parse_criteria("- \n* \n1. ") == []


# ── TestCheckCriteria ──

class TestCheckCriteria:

    def test_keyword_match(self):
        items = ["login feature"]
        result = _check_criteria(items, "Implemented the login feature successfully")
        assert result == [("login feature", True)]

    def test_keyword_no_match(self):
        items = ["logout feature"]
        result = _check_criteria(items, "Implemented the login feature")
        assert result == [("logout feature", False)]

    def test_case_insensitive(self):
        items = ["Login Feature"]
        result = _check_criteria(items, "implemented the login feature")
        assert result == [("Login Feature", True)]

    def test_short_tokens_ignored(self):
        items = ["a b cd ef"]
        result = _check_criteria(items, "cd ef are present")
        assert result == [("a b cd ef", True)]

    def test_all_short_tokens_auto_pass(self):
        items = ["a b c"]
        result = _check_criteria(items, "nothing relevant")
        assert result == [("a b c", True)]

    def test_empty_output(self):
        items = ["something important"]
        result = _check_criteria(items, "")
        assert result == [("something important", False)]

    def test_multiple_items_mixed(self):
        items = ["api endpoint", "database migration", "unit tests"]
        output = "Created api endpoint and wrote unit tests"
        result = _check_criteria(items, output)
        assert result == [
            ("api endpoint", True),
            ("database migration", False),
            ("unit tests", True),
        ]

    def test_chinese_keywords(self):
        items = ["新增登入"]
        result = _check_criteria(items, "已完成新增登入功能")
        assert result == [("新增登入", True)]

    def test_partial_keyword_no_match(self):
        items = ["login endpoint"]
        result = _check_criteria(items, "the login page is ready")
        assert result == [("login endpoint", False)]


# ── TestSprintContractHook ──

class TestSprintContractHook:

    def setup_method(self):
        self.hook = SprintContractHook()

    def _make_ctx(self, **overrides) -> TaskContext:
        defaults = dict(card_id=42, output="", acceptance_criteria="")
        defaults.update(overrides)
        return TaskContext(**defaults)

    def test_no_criteria_returns_early(self, caplog):
        ctx = self._make_ctx(acceptance_criteria="")
        with caplog.at_level(logging.DEBUG):
            self.hook.on_complete(ctx)
        assert "SprintContract" not in caplog.text

    def test_unparseable_criteria_logs_skip(self, caplog):
        ctx = self._make_ctx(acceptance_criteria="   \n\n   ")
        with caplog.at_level(logging.INFO):
            self.hook.on_complete(ctx)
        assert "無法拆解為條目" in caplog.text

    def test_all_pass(self, caplog):
        ctx = self._make_ctx(
            acceptance_criteria="- login feature\n- signup page",
            output="Implemented login feature and signup page",
        )
        with caplog.at_level(logging.INFO):
            self.hook.on_complete(ctx)
        assert "PASS (2/2)" in caplog.text
        assert "✓ login feature" in caplog.text
        assert "✓ signup page" in caplog.text

    def test_partial_fail(self, caplog):
        ctx = self._make_ctx(
            acceptance_criteria="- login feature\n- dark mode\n- caching layer",
            output="Added login feature and caching layer",
        )
        with caplog.at_level(logging.WARNING):
            self.hook.on_complete(ctx)
        assert "FAIL (2/3)" in caplog.text
        assert "✓ login feature" in caplog.text
        assert "✗ dark mode" in caplog.text
        assert "✓ caching layer" in caplog.text

    def test_all_fail(self, caplog):
        ctx = self._make_ctx(
            acceptance_criteria="- feature alpha\n- feature beta",
            output="nothing relevant here",
        )
        with caplog.at_level(logging.WARNING):
            self.hook.on_complete(ctx)
        assert "FAIL (0/2)" in caplog.text

    def test_pass_uses_info_level(self, caplog):
        ctx = self._make_ctx(
            acceptance_criteria="- hello world",
            output="hello world",
        )
        with caplog.at_level(logging.DEBUG):
            self.hook.on_complete(ctx)
        info_records = [r for r in caplog.records if r.levelno == logging.INFO and "SprintContract" in r.message]
        assert len(info_records) == 1

    def test_fail_uses_warning_level(self, caplog):
        ctx = self._make_ctx(
            acceptance_criteria="- missing feature",
            output="unrelated output",
        )
        with caplog.at_level(logging.DEBUG):
            self.hook.on_complete(ctx)
        warn_records = [r for r in caplog.records if r.levelno == logging.WARNING and "SprintContract" in r.message]
        assert len(warn_records) == 1
