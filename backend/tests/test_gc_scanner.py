"""Tests for gc_scanner module."""
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.gc_scanner import (
    LargeFileRule,
    StaleDocRule,
    TodoCountRule,
    run_gc_scan,
)


# ---------------------------------------------------------------------------
# LargeFileRule
# ---------------------------------------------------------------------------

class TestLargeFileRule:
    def test_triggers_over_800_lines(self, tmp_path: Path):
        py_file = tmp_path / "big.py"
        py_file.write_text("x = 1\n" * 801)

        findings = LargeFileRule().scan(str(tmp_path))

        assert len(findings) == 1
        assert findings[0].rule_id == "large-file"
        assert findings[0].severity == "warning"
        assert findings[0].line == 801

    def test_passes_under_800_lines(self, tmp_path: Path):
        py_file = tmp_path / "small.py"
        py_file.write_text("x = 1\n" * 100)

        findings = LargeFileRule().scan(str(tmp_path))

        assert findings == []


# ---------------------------------------------------------------------------
# TodoCountRule
# ---------------------------------------------------------------------------

class TestTodoCountRule:
    def test_triggers_over_5_todos(self, tmp_path: Path):
        py_file = tmp_path / "messy.py"
        py_file.write_text(textwrap.dedent("""\
            # TODO: fix this
            # FIXME: broken
            # HACK: workaround
            # TODO: refactor
            # TODO: cleanup
            # FIXME: urgent
        """))

        findings = TodoCountRule().scan(str(tmp_path))

        assert len(findings) == 1
        assert findings[0].rule_id == "todo-count"
        assert findings[0].severity == "warning"

    def test_passes_under_5_todos(self, tmp_path: Path):
        py_file = tmp_path / "clean.py"
        py_file.write_text(textwrap.dedent("""\
            # TODO: one thing
            # FIXME: another
            x = 1
        """))

        findings = TodoCountRule().scan(str(tmp_path))

        assert findings == []


# ---------------------------------------------------------------------------
# StaleDocRule
# ---------------------------------------------------------------------------

class TestStaleDocRule:
    def test_stale_doc_triggers(self, tmp_path: Path):
        md_file = tmp_path / "README.md"
        md_file.write_text("# Old doc\n")

        stale_date = datetime.now(tz=timezone.utc) - timedelta(days=90)
        mock_date_str = stale_date.isoformat()

        with patch("app.core.gc_scanner._git_last_modified") as mock_git:
            mock_git.return_value = stale_date
            findings = StaleDocRule().scan(str(tmp_path))

        assert len(findings) == 1
        assert findings[0].rule_id == "stale-doc"
        assert findings[0].severity == "warning"
        assert "90" in findings[0].message

    def test_fresh_doc_passes(self, tmp_path: Path):
        md_file = tmp_path / "README.md"
        md_file.write_text("# Fresh doc\n")

        recent_date = datetime.now(tz=timezone.utc) - timedelta(days=10)

        with patch("app.core.gc_scanner._git_last_modified") as mock_git:
            mock_git.return_value = recent_date
            findings = StaleDocRule().scan(str(tmp_path))

        assert findings == []

    def test_untracked_doc_skipped(self, tmp_path: Path):
        md_file = tmp_path / "NEW.md"
        md_file.write_text("# Untracked\n")

        with patch("app.core.gc_scanner._git_last_modified") as mock_git:
            mock_git.return_value = None
            findings = StaleDocRule().scan(str(tmp_path))

        assert findings == []


# ---------------------------------------------------------------------------
# run_gc_scan integration
# ---------------------------------------------------------------------------

class TestRunGcScan:
    def test_integration(self, tmp_path: Path):
        # large file
        big = tmp_path / "huge.py"
        big.write_text("line\n" * 900)

        # todo-heavy file
        messy = tmp_path / "messy.py"
        messy.write_text("# TODO\n" * 10)

        # stale doc
        doc = tmp_path / "GUIDE.md"
        doc.write_text("# Guide\n")

        stale = datetime.now(tz=timezone.utc) - timedelta(days=100)

        with patch("app.core.gc_scanner._git_last_modified") as mock_git:
            mock_git.return_value = stale
            findings = run_gc_scan(str(tmp_path))

        rule_ids = {f.rule_id for f in findings}
        assert "large-file" in rule_ids
        assert "todo-count" in rule_ids
        assert "stale-doc" in rule_ids

    def test_nonexistent_path(self):
        findings = run_gc_scan("/nonexistent/path/that/does/not/exist")
        assert findings == []

    def test_custom_rules(self, tmp_path: Path):
        big = tmp_path / "big.py"
        big.write_text("x\n" * 900)

        findings = run_gc_scan(str(tmp_path), rules=[LargeFileRule()])

        assert len(findings) == 1
        assert findings[0].rule_id == "large-file"
