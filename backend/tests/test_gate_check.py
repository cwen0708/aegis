"""Tests for app.core.gate_check — build gate 閘門檢查"""
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from app.core.gate_check import run_build_gate, _get_changed_py_files, GateResult


class TestGateResult:
    def test_frozen(self):
        r = GateResult(passed=True, message="ok")
        with pytest.raises(AttributeError):
            r.passed = False  # type: ignore[misc]


class TestGetChangedPyFiles:
    def test_filters_py_files(self, tmp_path):
        fake_output = "foo.py\nbar.js\nsrc/baz.py\nREADME.md\n"
        with patch("app.core.gate_check.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=fake_output, returncode=0)
            result = _get_changed_py_files(str(tmp_path))
        assert result == ["foo.py", "src/baz.py"]

    def test_timeout_returns_empty(self, tmp_path):
        with patch("app.core.gate_check.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 30)):
            result = _get_changed_py_files(str(tmp_path))
        assert result == []


class TestRunBuildGate:
    def test_workspace_not_found(self, tmp_path):
        result = run_build_gate(str(tmp_path / "nonexistent"), project_id=1)
        assert result.passed is True
        assert "skip" in result.message

    def test_no_changed_files(self, tmp_path):
        with patch("app.core.gate_check._get_changed_py_files", return_value=[]):
            result = run_build_gate(str(tmp_path), project_id=1)
        assert result.passed is True
        assert "no changed" in result.message

    def test_valid_py_passes(self, tmp_path):
        (tmp_path / "good.py").write_text("x = 1\n", encoding="utf-8")
        with patch("app.core.gate_check._get_changed_py_files", return_value=["good.py"]):
            result = run_build_gate(str(tmp_path), project_id=1)
        assert result.passed is True
        assert "1 file(s) checked" in result.message

    def test_syntax_error_fails(self, tmp_path):
        (tmp_path / "bad.py").write_text("def f(\n", encoding="utf-8")
        with patch("app.core.gate_check._get_changed_py_files", return_value=["bad.py"]):
            result = run_build_gate(str(tmp_path), project_id=1)
        assert result.passed is False
        assert "syntax errors" in result.message
        assert "bad.py" in result.message

    def test_mixed_files(self, tmp_path):
        (tmp_path / "good.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "bad.py").write_text("def f(\n", encoding="utf-8")
        with patch("app.core.gate_check._get_changed_py_files", return_value=["good.py", "bad.py"]):
            result = run_build_gate(str(tmp_path), project_id=1)
        assert result.passed is False
        assert "1 file(s) with syntax errors" in result.message

    def test_deleted_file_skipped(self, tmp_path):
        """git diff 列出的檔案可能已被刪除，應跳過"""
        with patch("app.core.gate_check._get_changed_py_files", return_value=["deleted.py"]):
            result = run_build_gate(str(tmp_path), project_id=1)
        assert result.passed is True

    def test_compile_timeout(self, tmp_path):
        (tmp_path / "slow.py").write_text("x = 1\n", encoding="utf-8")
        with patch("app.core.gate_check._get_changed_py_files", return_value=["slow.py"]):
            with patch("app.core.gate_check.subprocess.run", side_effect=subprocess.TimeoutExpired("python", 30)):
                result = run_build_gate(str(tmp_path), project_id=1)
        assert result.passed is False
        assert "timeout" in result.message
