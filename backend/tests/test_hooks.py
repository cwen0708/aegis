"""Hook 系統完整測試 — collect_hooks / run_hooks / run_on_stream / 各 Hook"""
import pytest
from unittest.mock import patch, MagicMock
from app.hooks import (
    Hook, TaskContext, StreamEvent,
    collect_hooks, run_hooks, run_on_stream,
)


# ════════════════════════════════════════
# Hook 基底類
# ════════════════════════════════════════

class TestHookBase:
    def test_default_on_stream_is_noop(self):
        hook = Hook()
        hook.on_stream(StreamEvent(kind="output", content="test"))  # 不拋例外

    def test_default_on_complete_is_noop(self):
        hook = Hook()
        hook.on_complete(TaskContext())  # 不拋例外


# ════════════════════════════════════════
# collect_hooks
# ════════════════════════════════════════

class TestCollectHooks:
    def test_worker_has_all_hooks(self):
        hooks = collect_hooks("worker")
        names = [type(h).__name__ for h in hooks]
        assert "WebSocketHook" in names
        assert "OneStackHook" in names
        assert "BroadcastHook" in names
        assert "DialogueHook" in names
        assert "MemoryHook" in names
        assert "CleanupHook" in names

    def test_chat_has_memory_only(self):
        hooks = collect_hooks("chat")
        names = [type(h).__name__ for h in hooks]
        assert "MemoryHook" in names
        assert "WebSocketHook" not in names
        assert "PlatformHook" not in names  # 由 chat_handler 按需插入

    def test_onestack_has_onestack_and_memory(self):
        hooks = collect_hooks("onestack")
        names = [type(h).__name__ for h in hooks]
        assert "OneStackHook" in names
        assert "MemoryHook" in names

    def test_meeting_has_token_counting_and_memory(self):
        hooks = collect_hooks("meeting")
        names = [type(h).__name__ for h in hooks]
        assert names == ["TokenCountingHook", "MemoryHook"]

    def test_unknown_source_fallback(self):
        hooks = collect_hooks("unknown")
        assert len(hooks) >= 1  # 至少有 MemoryHook

    def test_cleanup_is_last_for_worker(self):
        hooks = collect_hooks("worker")
        assert type(hooks[-1]).__name__ == "CleanupHook"


# ════════════════════════════════════════
# run_on_stream
# ════════════════════════════════════════

class TestRunOnStream:
    def test_dispatches_to_hooks(self):
        received = []

        class RecorderHook(Hook):
            def on_stream(self, event):
                received.append(event)

        hooks = [RecorderHook(), RecorderHook()]
        event = StreamEvent(kind="output", content="hello")
        run_on_stream(hooks, event)
        assert len(received) == 2
        assert received[0].content == "hello"

    def test_error_in_one_hook_doesnt_stop_others(self):
        received = []

        class BadHook(Hook):
            def on_stream(self, event):
                raise RuntimeError("boom")

        class GoodHook(Hook):
            def on_stream(self, event):
                received.append(event)

        run_on_stream([BadHook(), GoodHook()], StreamEvent(kind="output", content="x"))
        assert len(received) == 1

    def test_empty_hooks_list(self):
        run_on_stream([], StreamEvent(kind="output", content="x"))  # 不拋例外


# ════════════════════════════════════════
# run_hooks (on_complete)
# ════════════════════════════════════════

class TestRunHooks:
    def test_dispatches_on_complete(self):
        received = []

        class RecorderHook(Hook):
            def on_complete(self, ctx):
                received.append(ctx.card_id)

        ctx = TaskContext(card_id=42, status="completed")
        run_hooks(ctx, [RecorderHook()])
        assert received == [42]

    def test_error_in_one_doesnt_stop_others(self):
        received = []

        class BadHook(Hook):
            def on_complete(self, ctx):
                raise RuntimeError("boom")

        class GoodHook(Hook):
            def on_complete(self, ctx):
                received.append(ctx.card_id)

        run_hooks(TaskContext(card_id=1), [BadHook(), GoodHook()])
        assert received == [1]


# ════════════════════════════════════════
# TaskContext
# ════════════════════════════════════════

class TestTaskContext:
    def test_defaults(self):
        ctx = TaskContext()
        assert ctx.card_id == 0
        assert ctx.status == ""
        assert ctx.source == ""
        assert ctx.is_chat is False
        assert ctx.cron_job_id is None

    def test_with_values(self):
        ctx = TaskContext(card_id=99, status="completed", source="worker", member_slug="xiao-yin")
        assert ctx.card_id == 99
        assert ctx.member_slug == "xiao-yin"


# ════════════════════════════════════════
# HookEmitter
# ════════════════════════════════════════

class TestHookEmitter:
    def test_emit_raw_dispatches(self):
        from app.core.executor.emitter import HookEmitter
        received = []

        class RecorderHook(Hook):
            def on_stream(self, event):
                received.append(event.kind)

        emitter = HookEmitter([RecorderHook()])
        # 長文字（>200 chars）才走 text kind，短的會被 parse_tool_call 匹配為 output
        long_text = "A" * 250
        emitter.emit_raw('{"type": "assistant", "content": [{"type": "text", "text": "' + long_text + '"}]}')
        assert "text" in received
        assert emitter.collected_text == long_text

    def test_emit_output(self):
        from app.core.executor.emitter import HookEmitter
        received = []

        class RecorderHook(Hook):
            def on_stream(self, event):
                received.append(event)

        emitter = HookEmitter([RecorderHook()])
        emitter.emit_output("plain text line")
        assert len(received) == 1
        assert received[0].kind == "output"
        assert received[0].content == "plain text line"

    def test_emit_heartbeat(self):
        from app.core.executor.emitter import HookEmitter
        received = []

        class RecorderHook(Hook):
            def on_stream(self, event):
                received.append(event)

        emitter = HookEmitter([RecorderHook()])
        emitter.emit_heartbeat(30)
        assert len(received) == 1
        assert received[0].kind == "heartbeat"
        assert "30" in received[0].content

    def test_collects_token_info(self):
        from app.core.executor.emitter import HookEmitter
        emitter = HookEmitter([])
        emitter.emit_raw('{"type": "result", "session_id": "s1", "usage": {"input_tokens": 100}}')
        assert emitter.token_info.get("input_tokens") == 100


# ════════════════════════════════════════
# sanitize_output
# ════════════════════════════════════════

class TestSanitizeOutput:
    def test_linux_home_path(self):
        from app.core.executor.emitter import sanitize_output
        result = sanitize_output("/home/cwen0708/projects/Aegis/backend/worker.py")
        assert "/home/" not in result
        assert "worker.py" in result

    def test_any_user(self):
        from app.core.executor.emitter import sanitize_output
        assert sanitize_output("/home/john/test.py") == "test.py"

    def test_preserves_non_home(self):
        from app.core.executor.emitter import sanitize_output
        assert sanitize_output("/etc/nginx/nginx.conf") == "/etc/nginx/nginx.conf"

    def test_no_path(self):
        from app.core.executor.emitter import sanitize_output
        assert sanitize_output("Hello") == "Hello"

    def test_empty(self):
        from app.core.executor.emitter import sanitize_output
        assert sanitize_output("") == ""


# ════════════════════════════════════════
# parse_stream_event
# ════════════════════════════════════════

class TestParseStreamEvent:
    def test_system_returns_none(self):
        from app.core.executor.emitter import parse_stream_event
        assert parse_stream_event('{"type": "system"}') is None

    def test_user_returns_none(self):
        from app.core.executor.emitter import parse_stream_event
        assert parse_stream_event('{"type": "user"}') is None

    def test_result(self):
        from app.core.executor.emitter import parse_stream_event
        e = parse_stream_event('{"type": "result", "session_id": "s1", "usage": {"input_tokens": 50}}')
        assert e is not None
        assert e.kind == "result"
        assert e.token_info.get("input_tokens") == 50

    def test_tool_use(self):
        from app.core.executor.emitter import parse_stream_event
        e = parse_stream_event('{"type": "assistant", "content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "/tmp/test.py"}}]}')
        assert e is not None
        assert e.kind == "tool_call"

    def test_invalid_json(self):
        from app.core.executor.emitter import parse_stream_event
        assert parse_stream_event("not json") is None
        assert parse_stream_event("") is None
