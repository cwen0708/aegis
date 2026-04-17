"""Tests for app.core.lint_rules — 自訂 Lint 規則框架"""
import pytest

from app.core.lint_rules import (
    BareExceptRule,
    FileLengthRule,
    LintViolation,
    MutableDefaultRule,
    run_lint_rules,
)


# ---------------------------------------------------------------------------
# FileLengthRule
# ---------------------------------------------------------------------------

class TestFileLengthRule:
    rule = FileLengthRule()

    def test_short_file_passes(self):
        content = "x = 1\n" * 100
        assert self.rule.check("ok.py", content) == []

    def test_exactly_800_passes(self):
        content = "x = 1\n" * 800
        assert self.rule.check("ok.py", content) == []

    def test_over_800_warns(self):
        content = "x = 1\n" * 801
        violations = self.rule.check("big.py", content)
        assert len(violations) == 1
        v = violations[0]
        assert v.rule_id == "file-length"
        assert v.severity == "warning"
        assert v.fix_hint
        assert "801" in v.message

    def test_fix_hint_not_empty(self):
        content = "x = 1\n" * 900
        violations = self.rule.check("big.py", content)
        assert violations[0].fix_hint != ""


# ---------------------------------------------------------------------------
# BareExceptRule
# ---------------------------------------------------------------------------

class TestBareExceptRule:
    rule = BareExceptRule()

    def test_no_except_passes(self):
        content = "x = 1\n"
        assert self.rule.check("ok.py", content) == []

    def test_specific_except_passes(self):
        content = "try:\n    pass\nexcept ValueError:\n    pass\n"
        assert self.rule.check("ok.py", content) == []

    def test_except_exception_passes(self):
        content = "try:\n    pass\nexcept Exception:\n    pass\n"
        assert self.rule.check("ok.py", content) == []

    def test_bare_except_detected(self):
        content = "try:\n    pass\nexcept:\n    pass\n"
        violations = self.rule.check("bad.py", content)
        assert len(violations) == 1
        v = violations[0]
        assert v.rule_id == "bare-except"
        assert v.severity == "error"
        assert v.line == 3

    def test_indented_bare_except(self):
        content = "if True:\n    try:\n        pass\n    except:\n        pass\n"
        violations = self.rule.check("bad.py", content)
        assert len(violations) == 1
        assert violations[0].line == 4

    def test_multiple_bare_excepts(self):
        content = "try:\n    pass\nexcept:\n    pass\ntry:\n    pass\nexcept:\n    pass\n"
        violations = self.rule.check("bad.py", content)
        assert len(violations) == 2

    def test_fix_hint_not_empty(self):
        content = "try:\n    pass\nexcept:\n    pass\n"
        violations = self.rule.check("bad.py", content)
        assert violations[0].fix_hint != ""


# ---------------------------------------------------------------------------
# MutableDefaultRule
# ---------------------------------------------------------------------------

class TestMutableDefaultRule:
    rule = MutableDefaultRule()

    def test_no_defaults_passes(self):
        content = "def foo(x, y):\n    pass\n"
        assert self.rule.check("ok.py", content) == []

    def test_immutable_default_passes(self):
        content = "def foo(x=None, y=0, z='a'):\n    pass\n"
        assert self.rule.check("ok.py", content) == []

    def test_tuple_default_passes(self):
        content = "def foo(x=(1, 2)):\n    pass\n"
        assert self.rule.check("ok.py", content) == []

    def test_list_default_detected(self):
        content = "def foo(x=[]):\n    pass\n"
        violations = self.rule.check("bad.py", content)
        assert len(violations) == 1
        v = violations[0]
        assert v.rule_id == "mutable-default"
        assert v.severity == "error"
        assert "foo" in v.message

    def test_dict_default_detected(self):
        content = "def foo(x={}):\n    pass\n"
        violations = self.rule.check("bad.py", content)
        assert len(violations) == 1

    def test_set_default_detected(self):
        content = "def foo(x={1, 2}):\n    pass\n"
        violations = self.rule.check("bad.py", content)
        assert len(violations) == 1

    def test_kwonly_mutable_default(self):
        content = "def foo(*, x=[]):\n    pass\n"
        violations = self.rule.check("bad.py", content)
        assert len(violations) == 1

    def test_async_function(self):
        content = "async def foo(x=[]):\n    pass\n"
        violations = self.rule.check("bad.py", content)
        assert len(violations) == 1

    def test_syntax_error_skipped(self):
        content = "def foo(\n"
        assert self.rule.check("broken.py", content) == []

    def test_fix_hint_not_empty(self):
        content = "def foo(x=[]):\n    pass\n"
        violations = self.rule.check("bad.py", content)
        assert violations[0].fix_hint != ""


# ---------------------------------------------------------------------------
# run_lint_rules integration
# ---------------------------------------------------------------------------

class TestRunLintRules:
    def test_nonexistent_file_returns_empty(self, tmp_path):
        result = run_lint_rules(str(tmp_path / "nope.py"))
        assert result == []

    def test_clean_file(self, tmp_path):
        f = tmp_path / "clean.py"
        f.write_text("x = 1\n", encoding="utf-8")
        result = run_lint_rules(str(f))
        assert result == []

    def test_detects_multiple_rules(self, tmp_path):
        f = tmp_path / "messy.py"
        f.write_text(
            "def foo(x=[]):\n    try:\n        pass\n    except:\n        pass\n",
            encoding="utf-8",
        )
        result = run_lint_rules(str(f))
        rule_ids = {v.rule_id for v in result}
        assert "bare-except" in rule_ids
        assert "mutable-default" in rule_ids

    def test_custom_rules(self, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("x = 1\n", encoding="utf-8")

        class AlwaysFailRule:
            def check(self, file_path, content):
                return [
                    LintViolation(
                        file=file_path, line=1, rule_id="always-fail",
                        message="nope", fix_hint="fix it", severity="error",
                    )
                ]

        result = run_lint_rules(str(f), rules=[AlwaysFailRule()])
        assert len(result) == 1
        assert result[0].rule_id == "always-fail"

    def test_all_violations_have_fix_hint(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text(
            "def foo(x=[]):\n    try:\n        pass\n    except:\n        pass\n",
            encoding="utf-8",
        )
        for v in run_lint_rules(str(f)):
            assert v.fix_hint, f"rule {v.rule_id} missing fix_hint"


# ---------------------------------------------------------------------------
# LintViolation dataclass
# ---------------------------------------------------------------------------

class TestLintViolation:
    def test_frozen(self):
        v = LintViolation(
            file="a.py", line=1, rule_id="test",
            message="msg", fix_hint="hint", severity="error",
        )
        with pytest.raises(AttributeError):
            v.line = 2  # type: ignore[misc]
