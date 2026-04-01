"""
runner.py — run_ai_task() asyncio.TimeoutError 超時路徑測試

驗證重點：
- asyncio.TimeoutError 觸發時 proc.kill() 被呼叫
- 回傳 {"status": "timeout", "output": "任務超時 (10 分鐘)", "provider": ...}
- 大量輸出場景下超時處理依然正確
"""
import asyncio
import pytest
from unittest.mock import MagicMock, patch


# ──────────────────────────────────────────────
# Helper
# ──────────────────────────────────────────────

def _make_proc(returncode=-9, stdout_lines=None):
    """建立模擬的 subprocess.Popen 物件"""
    mock_proc = MagicMock()
    mock_proc.returncode = returncode
    mock_proc.stdout = iter(stdout_lines or [])
    mock_proc.stdin = None
    mock_proc.kill = MagicMock()
    mock_proc.wait = MagicMock()
    return mock_proc


def _make_env_builder():
    """建立模擬的 EnvironmentBuilder（鏈式呼叫）"""
    m = MagicMock()
    for method in ("with_system_keys", "with_project_vars",
                   "with_global_api_keys", "with_member_extra", "with_auth"):
        getattr(m, method).return_value = m
    m.build.return_value = {}
    return m


# ──────────────────────────────────────────────
# 測試用例
# ──────────────────────────────────────────────

class TestRunAiTaskTimeout:
    """run_ai_task() 超時行為測試"""

    @pytest.mark.asyncio
    async def test_basic_timeout_kills_proc_and_returns_timeout_status(self):
        """基礎超時：asyncio.TimeoutError 觸發時 proc.kill() 被呼叫，回傳 timeout 狀態"""
        mock_proc = _make_proc()

        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()), \
             patch("app.core.runner.subprocess.Popen", return_value=mock_proc), \
             patch("app.core.runner.build_command", return_value=(["echo", "hi"], None)), \
             patch("app.core.runner.get_provider_config", return_value={}), \
             patch("app.core.runner.get_mcp_config_path", return_value=None), \
             patch("app.core.sandbox.get_popen_kwargs", return_value={}), \
             patch("app.core.env_builder.EnvironmentBuilder", return_value=_make_env_builder()), \
             patch("app.core.prompt_hardening.harden_prompt", side_effect=lambda p, _: p), \
             patch("app.core.data_classifier.guard_for_ai", return_value=("test prompt", {})):

            from app.core.runner import run_ai_task
            result = await run_ai_task(
                task_id=1,
                project_path="/tmp",
                prompt="hello",
                phase="chat",
            )

        assert result["status"] == "timeout"
        assert result["output"] == "任務超時 (10 分鐘)"
        assert result["provider"] == "claude"
        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_called()

    @pytest.mark.asyncio
    async def test_large_output_timeout_kills_proc_and_returns_timeout_status(self):
        """大輸出超時：stdout 有大量已緩衝行時，超時仍正確 kill 並回傳 timeout"""
        # 模擬 stdout 有 10000 行待處理（大輸出場景）
        large_output = [f"line {i}\n".encode() for i in range(10_000)]
        mock_proc = _make_proc(stdout_lines=large_output)

        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()), \
             patch("app.core.runner.subprocess.Popen", return_value=mock_proc), \
             patch("app.core.runner.build_command", return_value=(["echo", "hi"], None)), \
             patch("app.core.runner.get_provider_config", return_value={}), \
             patch("app.core.runner.get_mcp_config_path", return_value=None), \
             patch("app.core.sandbox.get_popen_kwargs", return_value={}), \
             patch("app.core.env_builder.EnvironmentBuilder", return_value=_make_env_builder()), \
             patch("app.core.prompt_hardening.harden_prompt", side_effect=lambda p, _: p), \
             patch("app.core.data_classifier.guard_for_ai", return_value=("large data", {})):

            from app.core.runner import run_ai_task
            result = await run_ai_task(
                task_id=2,
                project_path="/tmp",
                prompt="process large data",
                phase="chat",
            )

        assert result["status"] == "timeout"
        assert result["output"] == "任務超時 (10 分鐘)"
        assert result["provider"] == "claude"
        # 大輸出場景下，kill 依然必須被呼叫
        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_called()

    @pytest.mark.asyncio
    async def test_timeout_with_openai_provider_returns_correct_provider(self):
        """超時時 provider 欄位應反映實際使用的 provider（openai）"""
        mock_proc = _make_proc()

        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()), \
             patch("app.core.runner.subprocess.Popen", return_value=mock_proc), \
             patch("app.core.runner.build_command", return_value=(["openai-cli"], None)), \
             patch("app.core.runner.get_provider_config", return_value={}), \
             patch("app.core.runner.get_mcp_config_path", return_value=None), \
             patch("app.core.sandbox.get_popen_kwargs", return_value={}), \
             patch("app.core.env_builder.EnvironmentBuilder", return_value=_make_env_builder()), \
             patch("app.core.prompt_hardening.harden_prompt", side_effect=lambda p, _: p), \
             patch("app.core.data_classifier.guard_for_ai", return_value=("test", {})):

            from app.core.runner import run_ai_task
            result = await run_ai_task(
                task_id=3,
                project_path="/tmp",
                prompt="test openai",
                phase="chat",
                forced_provider="openai",
            )

        assert result["status"] == "timeout"
        assert result["output"] == "任務超時 (10 分鐘)"
        assert result["provider"] == "openai"
        mock_proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_timeout_returns_success(self):
        """正常完成（未超時）應回傳 success 狀態，kill 不被呼叫"""
        mock_proc = _make_proc(returncode=0, stdout_lines=[b"result line\n"])

        with patch("app.core.runner.subprocess.Popen", return_value=mock_proc), \
             patch("app.core.runner.build_command", return_value=(["echo", "ok"], None)), \
             patch("app.core.runner.get_provider_config", return_value={}), \
             patch("app.core.runner.get_mcp_config_path", return_value=None), \
             patch("app.core.sandbox.get_popen_kwargs", return_value={}), \
             patch("app.core.env_builder.EnvironmentBuilder", return_value=_make_env_builder()), \
             patch("app.core.prompt_hardening.harden_prompt", side_effect=lambda p, _: p), \
             patch("app.core.data_classifier.guard_for_ai", return_value=("test", {})), \
             patch("app.core.runner._parse_claude_json", return_value={}):

            from app.core.runner import run_ai_task
            result = await run_ai_task(
                task_id=4,
                project_path="/tmp",
                prompt="quick task",
                phase="chat",
            )

        assert result["status"] == "success"
        mock_proc.kill.assert_not_called()
