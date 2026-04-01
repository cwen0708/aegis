"""EventLogHook 測試 — 覆蓋 on_stream / on_complete 六大場景"""
import json

from app.core.executor.emitter import StreamEvent
from app.hooks import TaskContext
from app.hooks.event_log import EventLogHook, _RECORD_KINDS, _TEXT_MAX_LEN


# ── on_stream ────────────────────────────────────────────


def test_on_stream_buffer_accumulates():
    """on_stream — buffer 正常累積 (happy path)"""
    hook = EventLogHook(card_id=1)
    hook.on_stream(StreamEvent(kind="text", content="hello", event_type="output"))
    hook.on_stream(StreamEvent(kind="tool_call", content="ls", event_type="tool_call"))
    assert len(hook._buffer) == 2
    assert hook._buffer[0]["kind"] == "text"
    assert hook._buffer[0]["content"] == "hello"
    assert hook._buffer[1]["kind"] == "tool_call"


def test_on_stream_filters_non_record_kinds():
    """on_stream — _RECORD_KINDS 過濾非目標 kind"""
    hook = EventLogHook(card_id=1)
    hook.on_stream(StreamEvent(kind="thinking", content="hmm", event_type=""))
    hook.on_stream(StreamEvent(kind="heartbeat", content="", event_type=""))
    assert len(hook._buffer) == 0


def test_on_stream_truncates_long_text():
    """on_stream — _TEXT_MAX_LEN 截斷超長文本"""
    hook = EventLogHook(card_id=1)
    long_text = "x" * (_TEXT_MAX_LEN + 100)
    hook.on_stream(StreamEvent(kind="text", content=long_text, event_type="output"))
    assert len(hook._buffer) == 1
    assert hook._buffer[0]["content"] == "x" * _TEXT_MAX_LEN + "..."


# ── on_complete ──────────────────────────────────────────


def test_on_complete_writes_jsonl(tmp_path):
    """on_complete — 正常寫入 JSONL 檔案 (happy path)"""
    hook = EventLogHook(card_id=42, project_path=str(tmp_path))
    hook.on_stream(StreamEvent(kind="text", content="hi", event_type="output"))
    hook.on_stream(StreamEvent(kind="result", content="done", event_type="result"))

    ctx = TaskContext(card_id=42, project_path=str(tmp_path))
    hook.on_complete(ctx)

    out_file = tmp_path / ".aegis" / "cards" / "card-42.events.jsonl"
    assert out_file.exists()
    lines = out_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["kind"] == "text"
    assert first["content"] == "hi"
    assert "ts" in first
    # buffer 應已清空
    assert len(hook._buffer) == 0


def test_on_complete_early_return_no_buffer(tmp_path):
    """on_complete — 無 buffer 時 early return，不建立檔案"""
    hook = EventLogHook(card_id=1, project_path=str(tmp_path))
    ctx = TaskContext(card_id=1, project_path=str(tmp_path))
    hook.on_complete(ctx)

    cards_dir = tmp_path / ".aegis" / "cards"
    assert not cards_dir.exists()


def test_on_complete_early_return_no_card_id(tmp_path):
    """on_complete — 無 card_id 時 early return"""
    hook = EventLogHook(card_id=0)
    # card_id=0 → on_stream 也會 early return，手動塞 buffer 模擬
    hook._buffer.append({"ts": 0, "kind": "text", "content": "x", "event_type": ""})

    ctx = TaskContext(card_id=0, project_path=str(tmp_path))
    hook.on_complete(ctx)

    cards_dir = tmp_path / ".aegis" / "cards"
    assert not cards_dir.exists()
