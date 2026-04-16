"""
測試 worker.py 的 OpenAI 串流分支：SSE delta 即時透過 emitter 推送，
type=result 行在串流結束後解析 usage / duration。

對應 Backlog #12678：complement parse_openai_stream 到 worker pipeline。
"""
import json
import time
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def mock_dependencies():
    """Mock worker 外部依賴，避免實際 DB / HTTP 呼叫。"""
    with patch("app.core.sandbox.get_popen_kwargs", return_value={}), \
         patch("worker.save_task_log"), \
         patch("worker.is_abort_requested", return_value=False), \
         patch("app.core.executor.heartbeat.heartbeat_monitor") as mock_hb:
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=lambda: None)
        ctx.__exit__ = MagicMock(return_value=False)
        mock_hb.return_value = ctx
        yield


def _make_sse_delta(text: str) -> bytes:
    return (
        "data: "
        + json.dumps({"choices": [{"delta": {"content": text}}]}, ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _make_result_line(full_text: str, input_tokens: int, output_tokens: int) -> bytes:
    return (
        json.dumps(
            {
                "type": "result",
                "result": full_text,
                "duration_ms": 1234,
                "total_cost_usd": 0.001,
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                },
                "modelUsage": {"gpt-4o": {}},
            },
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")


class TestOpenAIStreamSubprocess:
    """run_task_subprocess 對 OpenAI SSE + type=result 的整合行為。"""

    def test_sse_deltas_dispatched_via_emitter(self, mock_dependencies):
        """3 行 SSE delta 應被逐行包裝為 stream-json 並送入 emitter.emit_raw。"""
        from worker import run_task_subprocess

        mock_proc = MagicMock()
        mock_proc.stdout = iter([
            _make_sse_delta("你"),
            _make_sse_delta("好"),
            _make_sse_delta("！"),
            _make_result_line("你好！", input_tokens=10, output_tokens=3),
        ])
        mock_proc.stdin = None
        mock_proc.returncode = 0
        mock_proc.wait = MagicMock()

        emitter = MagicMock()
        emitter.token_info = {
            "result_text": "你好！",
            "model": "gpt-4o",
            "duration_ms": 1234,
            "cost_usd": 0.001,
            "input_tokens": 10,
            "output_tokens": 3,
        }

        with patch("worker.subprocess.Popen", return_value=mock_proc):
            result = run_task_subprocess(
                card_id=100,
                project_path="/tmp",
                cmd_parts=["python", "backend/scripts/openai_stream_chat.py"],
                stdin_prompt=False,
                prompt="hi",
                env={},
                provider_name="openai",
                card_title="Test OpenAI stream",
                project_name="TestProject",
                member_id=1,
                config={"stream_json": True},
                start_time=time.time() - 0.5,  # 確保 duration_ms > 0
                emitter=emitter,
                max_duration=60,
            )

        # 3 SSE delta + 1 type=result 行 → 共 4 次 emit_raw
        assert emitter.emit_raw.call_count == 4

        # 前三次 emit_raw 應為被包裝的 stream-json assistant 事件
        sse_calls = [c.args[0] for c in emitter.emit_raw.call_args_list[:3]]
        expected_deltas = ["你", "好", "！"]
        for call_arg, expected in zip(sse_calls, expected_deltas):
            payload = json.loads(call_arg)
            assert payload["type"] == "assistant"
            text_block = payload["message"]["content"][0]
            assert text_block["type"] == "text"
            assert text_block["text"] == expected

        # 第 4 次為原始 type=result 行
        last_payload = json.loads(emitter.emit_raw.call_args_list[3].args[0])
        assert last_payload["type"] == "result"

        # 最終 output 由 SSE delta 拼接而成
        assert result["status"] == "success"
        assert result["output"] == "你好！"

        # type=result 行解析出 usage / duration 資訊
        ti = result["token_info"]
        assert ti["input_tokens"] == 10
        assert ti["output_tokens"] == 3
        assert ti["duration_ms"] > 0  # 被覆寫為實際執行時間

    def test_done_line_is_consumed_but_not_emitted(self, mock_dependencies):
        """data: [DONE] 應被識別為 SSE 但不觸發 emit_raw。"""
        from worker import run_task_subprocess

        mock_proc = MagicMock()
        mock_proc.stdout = iter([
            _make_sse_delta("hello"),
            b"data: [DONE]\n",
            _make_result_line("hello", input_tokens=5, output_tokens=2),
        ])
        mock_proc.stdin = None
        mock_proc.returncode = 0
        mock_proc.wait = MagicMock()

        emitter = MagicMock()
        emitter.token_info = {}

        with patch("worker.subprocess.Popen", return_value=mock_proc):
            run_task_subprocess(
                card_id=101,
                project_path="/tmp",
                cmd_parts=["python", "backend/scripts/openai_stream_chat.py"],
                stdin_prompt=False,
                prompt="hi",
                env={},
                provider_name="openai",
                card_title="Test DONE",
                project_name="TestProject",
                member_id=1,
                config={"stream_json": True},
                start_time=time.time(),
                emitter=emitter,
                max_duration=60,
            )

        # 只有 1 SSE delta + 1 type=result → 2 次 emit_raw（[DONE] 被忽略）
        assert emitter.emit_raw.call_count == 2

    def test_non_openai_provider_ignores_sse_branch(self, mock_dependencies):
        """claude provider 不走 SSE 分支，data: 行被忽略不拋例外。"""
        from worker import run_task_subprocess

        mock_proc = MagicMock()
        mock_proc.stdout = iter([
            _make_sse_delta("should be ignored"),
            b'{"type":"assistant","message":{"content":[{"type":"text","text":"ok"}]}}\n',
        ])
        mock_proc.stdin = None
        mock_proc.returncode = 0
        mock_proc.wait = MagicMock()

        emitter = MagicMock()
        emitter.token_info = {}

        with patch("worker.subprocess.Popen", return_value=mock_proc):
            run_task_subprocess(
                card_id=102,
                project_path="/tmp",
                cmd_parts=["claude"],
                stdin_prompt=False,
                prompt="hi",
                env={},
                provider_name="claude",
                card_title="Test claude",
                project_name="TestProject",
                member_id=1,
                config={"stream_json": True},
                start_time=time.time(),
                emitter=emitter,
                max_duration=60,
            )

        # claude provider 只處理 { 開頭的 JSON 行，data: 行被跳過
        assert emitter.emit_raw.call_count == 1
        emitted = emitter.emit_raw.call_args_list[0].args[0]
        assert json.loads(emitted)["type"] == "assistant"


class TestEmitHelper:
    """_emit_openai_sse_line 單元測試。"""

    def test_data_line_extracted_and_wrapped(self):
        from worker import _emit_openai_sse_line

        emitter = MagicMock()
        parts: list = []
        handled = _emit_openai_sse_line(
            'data: {"choices":[{"delta":{"content":"hi"}}]}',
            emitter,
            parts,
        )
        assert handled is True
        assert parts == ["hi"]
        assert emitter.emit_raw.call_count == 1
        wrapped = json.loads(emitter.emit_raw.call_args.args[0])
        assert wrapped["type"] == "assistant"
        assert wrapped["message"]["content"][0]["text"] == "hi"

    def test_done_signal_recognized_but_silent(self):
        from worker import _emit_openai_sse_line

        emitter = MagicMock()
        parts: list = []
        handled = _emit_openai_sse_line("data: [DONE]", emitter, parts)
        assert handled is True  # 是 SSE，已消化
        assert parts == []
        emitter.emit_raw.assert_not_called()

    def test_non_sse_line_not_handled(self):
        from worker import _emit_openai_sse_line

        emitter = MagicMock()
        parts: list = []
        handled = _emit_openai_sse_line('{"type":"result"}', emitter, parts)
        assert handled is False
        emitter.emit_raw.assert_not_called()
