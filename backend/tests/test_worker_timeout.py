"""
測試 worker.py 的任務超時機制
驗證 run_task_subprocess() 在超過 max_duration 時正確 kill 子程序並回傳 timeout 狀態
"""
import time
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def mock_dependencies():
    """Mock worker 外部依賴，避免實際 DB / HTTP 呼叫"""
    with patch("app.core.sandbox.get_popen_kwargs", return_value={}), \
         patch("worker.save_task_log") as mock_save_log, \
         patch("worker.is_abort_requested", return_value=False), \
         patch("app.core.executor.heartbeat.heartbeat_monitor") as mock_hb:
        # heartbeat_monitor 回傳一個 context manager，touch 是 no-op
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=lambda: None)
        ctx.__exit__ = MagicMock(return_value=False)
        mock_hb.return_value = ctx
        yield {"save_task_log": mock_save_log}


class _SlowStdout:
    """模擬一個會持續產出行的 stdout，用於觸發超時"""

    def __init__(self, delay_per_line=0.05, max_lines=200):
        self._delay = delay_per_line
        self._remaining = max_lines

    def __iter__(self):
        return self

    def __next__(self):
        if self._remaining <= 0:
            raise StopIteration
        self._remaining -= 1
        time.sleep(self._delay)
        return b"working...\n"


class TestRunTaskSubprocessTimeout:
    """run_task_subprocess 超時行為測試"""

    def test_timeout_kills_process_and_returns_timeout_status(self, mock_dependencies):
        """超過 max_duration 時應 kill 子程序並回傳 status=timeout"""
        from worker import run_task_subprocess

        mock_proc = MagicMock()
        mock_proc.stdout = _SlowStdout(delay_per_line=0.05, max_lines=200)
        mock_proc.stdin = None
        mock_proc.returncode = -9
        mock_proc.kill = MagicMock()
        mock_proc.wait = MagicMock()

        with patch("worker.subprocess.Popen", return_value=mock_proc):
            result = run_task_subprocess(
                card_id=999,
                project_path="/tmp",
                cmd_parts=["echo", "test"],
                stdin_prompt=False,
                prompt="test prompt",
                env={},
                provider_name="claude",
                card_title="Test Card",
                project_name="TestProject",
                member_id=1,
                config={},
                start_time=time.time(),
                emitter=MagicMock(),
                max_duration=0.2,  # 200ms 超時，用於快速測試
            )

        assert result["status"] == "timeout"
        assert result["exit_code"] == -1
        assert "duration_ms" in result["token_info"]
        mock_proc.kill.assert_called_once()
        mock_dependencies["save_task_log"].assert_called_once()
        # 確認 save_task_log 的 status 參數是 "timeout"
        call_args = mock_dependencies["save_task_log"].call_args
        assert call_args[0][5] == "timeout"  # 第 6 個位置參數是 status

    def test_no_timeout_when_task_completes_quickly(self, mock_dependencies):
        """任務在時限內完成時不應觸發超時"""
        from worker import run_task_subprocess

        mock_proc = MagicMock()
        mock_proc.stdout = iter([b"line 1\n", b"line 2\n", b"done\n"])
        mock_proc.stdin = None
        mock_proc.returncode = 0
        mock_proc.wait = MagicMock()

        with patch("worker.subprocess.Popen", return_value=mock_proc):
            result = run_task_subprocess(
                card_id=999,
                project_path="/tmp",
                cmd_parts=["echo", "test"],
                stdin_prompt=False,
                prompt="test prompt",
                env={},
                provider_name="claude",
                card_title="Test Card",
                project_name="TestProject",
                member_id=1,
                config={},
                start_time=time.time(),
                emitter=MagicMock(),
                max_duration=60,  # 充裕的時限
            )

        assert result["status"] == "success"
        mock_proc.kill.assert_not_called()

    def test_timeout_emits_message(self, mock_dependencies):
        """超時時應透過 emitter 發送超時訊息"""
        from worker import run_task_subprocess

        mock_proc = MagicMock()
        mock_proc.stdout = _SlowStdout(delay_per_line=0.05, max_lines=200)
        mock_proc.stdin = None
        mock_proc.returncode = -9
        mock_proc.kill = MagicMock()
        mock_proc.wait = MagicMock()

        mock_emitter = MagicMock()

        with patch("worker.subprocess.Popen", return_value=mock_proc):
            run_task_subprocess(
                card_id=999,
                project_path="/tmp",
                cmd_parts=["echo", "test"],
                stdin_prompt=False,
                prompt="test prompt",
                env={},
                provider_name="claude",
                card_title="Test Card",
                project_name="TestProject",
                member_id=1,
                config={},
                start_time=time.time(),
                emitter=mock_emitter,
                max_duration=0.2,
            )

        # 確認 emitter 有收到超時訊息
        timeout_calls = [
            call for call in mock_emitter.emit_output.call_args_list
            if "超時" in str(call)
        ]
        assert len(timeout_calls) >= 1


class TestDefaultTaskTimeout:
    """DEFAULT_TASK_TIMEOUT 常數測試"""

    def test_default_timeout_value(self):
        from worker import DEFAULT_TASK_TIMEOUT
        assert DEFAULT_TASK_TIMEOUT == 3600

    def test_run_task_subprocess_default_param(self):
        """run_task_subprocess 預設 max_duration 應為 DEFAULT_TASK_TIMEOUT"""
        import inspect
        from worker import run_task_subprocess, DEFAULT_TASK_TIMEOUT
        sig = inspect.signature(run_task_subprocess)
        assert sig.parameters["max_duration"].default == DEFAULT_TASK_TIMEOUT
