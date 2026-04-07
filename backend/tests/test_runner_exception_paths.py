"""
runner.py — 異常與 PromptQueue 佇列整合路徑測試

驗證重點：
- SecurityBlock 攔截 → 立即返回 error dict
- subprocess.Popen OSError → 外層 except → error dict
- chat_key + 佇列 → mark_failed / mark_processed 正確呼叫
- dequeue() 拋例外 → 吞掉，使用原始 prompt
- dequeue() 返回排隊項目 → 替換原始 prompt
- redact_map 非空 → restore() 被呼叫
"""
import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _make_proc(returncode=0, stdout_lines=None):
    mock_proc = MagicMock()
    mock_proc.returncode = returncode
    mock_proc.stdout = iter(stdout_lines or [b"ok\n"])
    mock_proc.stdin = None
    mock_proc.kill = MagicMock()
    mock_proc.wait = MagicMock()
    return mock_proc


def _make_env_builder():
    m = MagicMock()
    for method in ("with_system_keys", "with_project_vars",
                   "with_global_api_keys", "with_member_extra", "with_auth"):
        getattr(m, method).return_value = m
    m.build.return_value = {}
    return m


def _make_pq_manager(dequeue_return=None):
    """建立模擬的 PromptQueueManager"""
    m = MagicMock()
    m.dequeue.return_value = dequeue_return
    m.mark_processed = MagicMock()
    m.mark_failed = MagicMock()
    return m


def _make_queued_item(queue_id="test-queue-id-1234", prompt_text="queued prompt"):
    item = MagicMock()
    item.queue_id = queue_id
    item.prompt_text = prompt_text
    return item


# ──────────────────────────────────────────────
# 通用 patch context — 無 chat_key 版本
# ──────────────────────────────────────────────

def _base_patches(mock_proc, guard_return=("hardened prompt", {})):
    return [
        patch("app.core.runner.subprocess.Popen", return_value=mock_proc),
        patch("app.core.runner.build_command", return_value=(["echo", "hi"], None)),
        patch("app.core.runner.get_provider_config", return_value={}),
        patch("app.core.runner.get_mcp_config_path", return_value=None),
        patch("app.core.sandbox.get_popen_kwargs", return_value={}),
        patch("app.core.env_builder.EnvironmentBuilder", return_value=_make_env_builder()),
        patch("app.core.prompt_hardening.harden_prompt", side_effect=lambda p, _: p),
        patch("app.core.data_classifier.guard_for_ai", return_value=guard_return),
        patch("app.core.runner._parse_claude_json", return_value={}),
    ]


# ──────────────────────────────────────────────
# 測試用例
# ──────────────────────────────────────────────

class TestSecurityBlock:
    """SecurityBlock 攔截路徑"""

    @pytest.mark.asyncio
    async def test_security_block_returns_error_dict(self):
        """guard_for_ai 拋 SecurityBlock → 返回 error dict，proc 未建立"""
        from app.core.data_classifier import SecurityBlock

        with patch("app.core.runner.build_command", return_value=(["echo"], None)), \
             patch("app.core.runner.get_provider_config", return_value={}), \
             patch("app.core.runner.get_mcp_config_path", return_value=None), \
             patch("app.core.env_builder.EnvironmentBuilder", return_value=_make_env_builder()), \
             patch("app.core.prompt_hardening.harden_prompt", side_effect=lambda p, _: p), \
             patch("app.core.data_classifier.guard_for_ai",
                   side_effect=SecurityBlock("blocked: contains secret")) as mock_guard, \
             patch("app.core.runner.subprocess.Popen") as mock_popen:

            from app.core.runner import run_ai_task
            result = await run_ai_task(
                task_id=1,
                project_path="/tmp",
                prompt="sk-ant-secret123",
                phase="chat",
            )

        assert result["status"] == "error"
        assert "SecurityBlock" in result["output"]
        # Popen 不應被呼叫
        mock_popen.assert_not_called()


class TestOuterExceptionPaths:
    """subprocess.Popen OSError → 外層 except 路徑"""

    @pytest.mark.asyncio
    async def test_outer_exception_returns_error_dict(self):
        """Popen 拋 OSError → 外層 except → error dict"""
        with patch("app.core.runner.subprocess.Popen", side_effect=OSError("binary not found")), \
             patch("app.core.runner.build_command", return_value=(["bad-cmd"], None)), \
             patch("app.core.runner.get_provider_config", return_value={}), \
             patch("app.core.runner.get_mcp_config_path", return_value=None), \
             patch("app.core.sandbox.get_popen_kwargs", return_value={}), \
             patch("app.core.env_builder.EnvironmentBuilder", return_value=_make_env_builder()), \
             patch("app.core.prompt_hardening.harden_prompt", side_effect=lambda p, _: p), \
             patch("app.core.data_classifier.guard_for_ai", return_value=("prompt", {})):

            from app.core.runner import run_ai_task
            result = await run_ai_task(
                task_id=2,
                project_path="/tmp",
                prompt="hello",
                phase="chat",
            )

        assert result["status"] == "error"
        assert "binary not found" in result["output"]
        assert result["provider"] == "claude"

    @pytest.mark.asyncio
    async def test_outer_exception_marks_queue_failed(self):
        """Popen 拋 OSError + chat_key 設定 → mark_failed() 被呼叫"""
        mock_pq = _make_pq_manager(dequeue_return=None)
        queued_item = _make_queued_item()
        # 讓 dequeue 返回一個 item 以確保 _queue_id 被設定
        mock_pq.dequeue.return_value = queued_item

        with patch("app.core.runner.subprocess.Popen", side_effect=OSError("exec failed")), \
             patch("app.core.runner.build_command", return_value=(["bad-cmd"], None)), \
             patch("app.core.runner.get_provider_config", return_value={}), \
             patch("app.core.runner.get_mcp_config_path", return_value=None), \
             patch("app.core.sandbox.get_popen_kwargs", return_value={}), \
             patch("app.core.env_builder.EnvironmentBuilder", return_value=_make_env_builder()), \
             patch("app.core.prompt_hardening.harden_prompt", side_effect=lambda p, _: p), \
             patch("app.core.data_classifier.guard_for_ai", return_value=("prompt", {})), \
             patch("app.core.prompt_queue.PromptQueueManager", return_value=mock_pq), \
             patch("app.database.engine", MagicMock()):

            from app.core.runner import run_ai_task
            result = await run_ai_task(
                task_id=3,
                project_path="/tmp",
                prompt="hello",
                phase="chat",
                chat_key="telegram:123:xiao-yin",
            )

        assert result["status"] == "error"
        mock_pq.mark_failed.assert_called_once_with(queued_item.queue_id)


class TestQueueStatusUpdate:
    """PromptQueue 狀態更新路徑"""

    @pytest.mark.asyncio
    async def test_success_marks_queue_processed(self):
        """正常完成 + chat_key → mark_processed() 被呼叫"""
        mock_proc = _make_proc(returncode=0, stdout_lines=[b"result\n"])
        mock_pq = _make_pq_manager()
        queued_item = _make_queued_item(queue_id="qid-success-001")
        mock_pq.dequeue.return_value = queued_item

        with patch("app.core.runner.subprocess.Popen", return_value=mock_proc), \
             patch("app.core.runner.build_command", return_value=(["echo", "ok"], None)), \
             patch("app.core.runner.get_provider_config", return_value={}), \
             patch("app.core.runner.get_mcp_config_path", return_value=None), \
             patch("app.core.sandbox.get_popen_kwargs", return_value={}), \
             patch("app.core.env_builder.EnvironmentBuilder", return_value=_make_env_builder()), \
             patch("app.core.prompt_hardening.harden_prompt", side_effect=lambda p, _: p), \
             patch("app.core.data_classifier.guard_for_ai", return_value=("prompt", {})), \
             patch("app.core.runner._parse_claude_json", return_value={}), \
             patch("app.core.prompt_queue.PromptQueueManager", return_value=mock_pq), \
             patch("app.database.engine", MagicMock()):

            from app.core.runner import run_ai_task
            result = await run_ai_task(
                task_id=4,
                project_path="/tmp",
                prompt="do task",
                phase="chat",
                chat_key="telegram:123:bot",
            )

        assert result["status"] == "success"
        mock_pq.mark_processed.assert_called_once_with("qid-success-001")
        mock_pq.mark_failed.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_returncode_marks_queue_failed(self):
        """proc.returncode=1 + chat_key → mark_failed() 被呼叫"""
        mock_proc = _make_proc(returncode=1, stdout_lines=[b"error output\n"])
        mock_pq = _make_pq_manager()
        queued_item = _make_queued_item(queue_id="qid-fail-001")
        mock_pq.dequeue.return_value = queued_item

        with patch("app.core.runner.subprocess.Popen", return_value=mock_proc), \
             patch("app.core.runner.build_command", return_value=(["echo", "fail"], None)), \
             patch("app.core.runner.get_provider_config", return_value={}), \
             patch("app.core.runner.get_mcp_config_path", return_value=None), \
             patch("app.core.sandbox.get_popen_kwargs", return_value={}), \
             patch("app.core.env_builder.EnvironmentBuilder", return_value=_make_env_builder()), \
             patch("app.core.prompt_hardening.harden_prompt", side_effect=lambda p, _: p), \
             patch("app.core.data_classifier.guard_for_ai", return_value=("prompt", {})), \
             patch("app.core.runner._parse_claude_json", return_value={}), \
             patch("app.core.prompt_queue.PromptQueueManager", return_value=mock_pq), \
             patch("app.database.engine", MagicMock()):

            from app.core.runner import run_ai_task
            result = await run_ai_task(
                task_id=5,
                project_path="/tmp",
                prompt="do task",
                phase="chat",
                chat_key="telegram:123:bot",
            )

        assert result["status"] == "error"
        mock_pq.mark_failed.assert_called_once_with("qid-fail-001")
        mock_pq.mark_processed.assert_not_called()


class TestDequeueEdgeCases:
    """dequeue() 邊界情況"""

    @pytest.mark.asyncio
    async def test_dequeue_exception_swallowed(self):
        """dequeue() 拋異常 → warning log + 使用原始 prompt 繼續"""
        mock_proc = _make_proc(returncode=0, stdout_lines=[b"ok\n"])
        mock_pq = _make_pq_manager()
        mock_pq.dequeue.side_effect = RuntimeError("db connection lost")

        with patch("app.core.runner.subprocess.Popen", return_value=mock_proc), \
             patch("app.core.runner.build_command", return_value=(["echo"], None)), \
             patch("app.core.runner.get_provider_config", return_value={}), \
             patch("app.core.runner.get_mcp_config_path", return_value=None), \
             patch("app.core.sandbox.get_popen_kwargs", return_value={}), \
             patch("app.core.env_builder.EnvironmentBuilder", return_value=_make_env_builder()), \
             patch("app.core.prompt_hardening.harden_prompt", side_effect=lambda p, _: p), \
             patch("app.core.data_classifier.guard_for_ai", return_value=("original prompt", {})), \
             patch("app.core.runner._parse_claude_json", return_value={}), \
             patch("app.core.prompt_queue.PromptQueueManager", return_value=mock_pq), \
             patch("app.database.engine", MagicMock()):

            from app.core.runner import run_ai_task
            # 不應拋出例外
            result = await run_ai_task(
                task_id=6,
                project_path="/tmp",
                prompt="original prompt",
                phase="chat",
                chat_key="telegram:123:bot",
            )

        # 例外被吞掉，仍正常完成
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_chat_key_dequeue_replaces_prompt(self):
        """dequeue() 返回排隊項目 → 使用排隊文字替換原 prompt"""
        mock_proc = _make_proc(returncode=0, stdout_lines=[b"processed\n"])
        queued_item = _make_queued_item(queue_id="qid-replace-001",
                                         prompt_text="queued prompt text")
        mock_pq = _make_pq_manager(dequeue_return=queued_item)

        captured_stdin_writes = []

        def fake_popen(cmd, **kwargs):
            # 記錄用的 proc
            return mock_proc

        with patch("app.core.runner.subprocess.Popen", side_effect=fake_popen), \
             patch("app.core.runner.build_command", return_value=(["echo"], None)), \
             patch("app.core.runner.get_provider_config", return_value={}), \
             patch("app.core.runner.get_mcp_config_path", return_value=None), \
             patch("app.core.sandbox.get_popen_kwargs", return_value={}), \
             patch("app.core.env_builder.EnvironmentBuilder", return_value=_make_env_builder()), \
             patch("app.core.prompt_hardening.harden_prompt", side_effect=lambda p, _: p), \
             patch("app.core.data_classifier.guard_for_ai",
                   side_effect=lambda p, _: (p, {})) as mock_guard, \
             patch("app.core.runner._parse_claude_json", return_value={}), \
             patch("app.core.prompt_queue.PromptQueueManager", return_value=mock_pq), \
             patch("app.database.engine", MagicMock()):

            from app.core.runner import run_ai_task
            result = await run_ai_task(
                task_id=7,
                project_path="/tmp",
                prompt="original user prompt",
                phase="chat",
                chat_key="telegram:123:bot",
            )

        # guard_for_ai 收到的應該是排隊的 prompt（已替換）
        call_args = mock_guard.call_args
        assert call_args[0][0] == "queued prompt text"
        assert result["status"] == "success"
        mock_pq.mark_processed.assert_called_once_with("qid-replace-001")


class TestRedactMapRestore:
    """Data Classification redact_map restore 路徑"""

    @pytest.mark.asyncio
    async def test_redact_map_restore_applied(self):
        """guard_for_ai 返回非空 redact_map → 輸出中 restore() 被呼叫"""
        mock_proc = _make_proc(returncode=0, stdout_lines=[b"output with PLACEHOLDER_1\n"])
        redact_map = {"PLACEHOLDER_1": "secret-value"}

        with patch("app.core.runner.subprocess.Popen", return_value=mock_proc), \
             patch("app.core.runner.build_command", return_value=(["echo"], None)), \
             patch("app.core.runner.get_provider_config", return_value={}), \
             patch("app.core.runner.get_mcp_config_path", return_value=None), \
             patch("app.core.sandbox.get_popen_kwargs", return_value={}), \
             patch("app.core.env_builder.EnvironmentBuilder", return_value=_make_env_builder()), \
             patch("app.core.prompt_hardening.harden_prompt", side_effect=lambda p, _: p), \
             patch("app.core.data_classifier.guard_for_ai",
                   return_value=("redacted prompt", redact_map)), \
             patch("app.core.data_classifier.restore",
                   return_value="output with secret-value") as mock_restore, \
             patch("app.core.runner._parse_claude_json", return_value={}):

            from app.core.runner import run_ai_task
            result = await run_ai_task(
                task_id=8,
                project_path="/tmp",
                prompt="prompt with secret",
                phase="chat",
            )

        # restore() 必須被呼叫，且傳入正確 redact_map
        mock_restore.assert_called_once()
        call_args = mock_restore.call_args[0]
        assert call_args[1] == redact_map
        assert result["output"] == "output with secret-value"
