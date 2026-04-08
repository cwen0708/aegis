"""structured_data 單元測試 — 驗證 parse_stream_event 產出正確的 structured_data

測試重點：
1. 每種 event kind 的 structured_data 正確填入
2. 向後相容：content 欄位不變
3. WebSocket broadcast payload 包含 structured_data
"""
import json

from app.core.executor.emitter import StreamEvent, parse_stream_event


# ── tool_call event ────────────────────────────────────────────

def test_tool_call_structured_data():
    """tool_use → structured_data 包含 tool_name, arguments, content_blocks"""
    line = json.dumps({
        "type": "assistant",
        "content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "/a/b.py"}}],
    })
    event = parse_stream_event(line)
    assert event is not None
    assert event.kind == "tool_call"
    assert "讀取" in event.content  # 向後相容：人話摘要不變
    sd = event.structured_data
    assert sd["event_type"] == "tool_call"
    assert sd["tool_name"] == "Read"
    assert sd["arguments"] == {"file_path": "/a/b.py"}
    assert isinstance(sd["content_blocks"], list)
    assert sd["content_blocks"][0]["type"] == "tool_use"


def test_tool_call_edit_structured_data():
    """Edit tool → structured_data 正確保留 arguments"""
    line = json.dumps({
        "type": "assistant",
        "content": [{"type": "tool_use", "name": "Edit", "input": {
            "file_path": "/x/y.py", "old_string": "foo", "new_string": "bar",
        }}],
    })
    event = parse_stream_event(line)
    sd = event.structured_data
    assert sd["tool_name"] == "Edit"
    assert sd["arguments"]["old_string"] == "foo"
    assert sd["arguments"]["new_string"] == "bar"


def test_tool_call_todowrite_suppressed():
    """TodoWrite → 仍然回傳 None（被過濾）"""
    line = json.dumps({
        "type": "assistant",
        "content": [{"type": "tool_use", "name": "TodoWrite", "input": {}}],
    })
    assert parse_stream_event(line) is None


# ── text event ─────────────────────────────────────────────────

def test_text_structured_data():
    """assistant 長文字 (≥200 chars) → text kind with structured_data"""
    long_text = "這是一段很長的分析結果。" * 20  # >200 chars
    line = json.dumps({
        "type": "assistant",
        "content": [{"type": "text", "text": long_text}],
    })
    event = parse_stream_event(line)
    assert event is not None
    assert event.kind == "text"
    assert event.content == long_text  # 向後相容
    sd = event.structured_data
    assert sd["event_type"] == "text"
    assert isinstance(sd["content_blocks"], list)


# ── thinking event（via parse_tool_call 分支）────────────────

def test_thinking_structured_data():
    """thinking block → output event with structured_data"""
    line = json.dumps({
        "type": "assistant",
        "content": [{"type": "thinking", "text": "let me reason about this"}],
    })
    event = parse_stream_event(line)
    assert event is not None
    assert event.kind == "output"
    assert "思考中" in event.content  # 向後相容
    sd = event.structured_data
    assert sd["event_type"] == "output"
    assert sd["tool_name"] is None


# ── result event ───────────────────────────────────────────────

def test_result_structured_data():
    """result → structured_data 包含 token_info"""
    line = json.dumps({
        "type": "result",
        "result": "ok",
        "usage": {"input_tokens": 100, "output_tokens": 50},
        "modelUsage": {"claude-3-sonnet": {}},
        "duration_ms": 999,
        "total_cost_usd": 0.01,
    })
    event = parse_stream_event(line)
    assert event is not None
    assert event.kind == "result"
    assert event.content == ""  # 向後相容
    sd = event.structured_data
    assert sd["event_type"] == "result"
    assert sd["token_info"]["input_tokens"] == 100
    assert sd["token_info"]["model"] == "claude-3-sonnet"


# ── directive event ────────────────────────────────────────────

def test_directive_structured_data():
    """directive 標記（長文字繞過 parse_tool_call）→ structured_data 包含 directive payload"""
    directive = {"action": "notify", "params": {"msg": "done"}}
    # 文字需要 ≥200 chars 才會繞過 parse_tool_call 到 parse_stream_json_text → directive 分支
    padding = "分析報告內容" * 40
    text = f"{padding} <!-- directive:{json.dumps(directive)} -->"
    line = json.dumps({
        "type": "assistant",
        "content": [{"type": "text", "text": text}],
    })
    event = parse_stream_event(line)
    assert event is not None
    assert event.kind == "directive"
    assert text in event.content  # 向後相容
    sd = event.structured_data
    assert sd["event_type"] == "directive"
    assert sd["directive"]["action"] == "notify"


# ── 忽略的 event type ─────────────────────────────────────────

def test_system_event_ignored():
    """system type → None"""
    line = json.dumps({"type": "system", "content": "starting"})
    assert parse_stream_event(line) is None


def test_user_event_ignored():
    """user type → None"""
    line = json.dumps({"type": "user", "content": "hello"})
    assert parse_stream_event(line) is None


def test_invalid_json_ignored():
    """不合法 JSON → None"""
    assert parse_stream_event("{bad json") is None


# ── 向後相容 ──────────────────────────────────────────────────

def test_backward_compat_content_unchanged():
    """確認所有 event 的 content 欄位格式不變"""
    # tool_call
    tool_line = json.dumps({
        "type": "assistant",
        "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}],
    })
    tool_event = parse_stream_event(tool_line)
    assert "💻" in tool_event.content
    assert tool_event.event_type == "tool_call"

    # short text → parse_tool_call 攔截為 output（向後相容行為）
    text_line = json.dumps({
        "type": "assistant",
        "content": [{"type": "text", "text": "hello world"}],
    })
    text_event = parse_stream_event(text_line)
    assert "hello world" in text_event.content
    assert text_event.kind == "output"

    # long text → 走 parse_stream_json_text 成為 text kind
    long_text = "x" * 250
    long_line = json.dumps({
        "type": "assistant",
        "content": [{"type": "text", "text": long_text}],
    })
    long_event = parse_stream_event(long_line)
    assert long_event.content == long_text
    assert long_event.kind == "text"

    # result
    result_line = json.dumps({
        "type": "result",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    })
    result_event = parse_stream_event(result_line)
    assert result_event.content == ""
    assert result_event.kind == "result"


def test_structured_data_none_for_heartbeat():
    """手動建立的 heartbeat event → structured_data 預設 None"""
    event = StreamEvent(kind="heartbeat", content="⏳ 處理中... (5s)")
    assert event.structured_data is None


def test_short_text_via_tool_call_branch():
    """短文字走 parse_tool_call 分支 → structured_data 有 content_blocks"""
    line = json.dumps({
        "type": "assistant",
        "content": [{"type": "text", "text": "ok"}],
    })
    event = parse_stream_event(line)
    # 短文字 (<200 chars) 會被 parse_tool_call 攔截為 output
    assert event.kind == "output"
    assert event.structured_data["event_type"] == "output"
    assert event.structured_data["content_blocks"] is not None


def test_message_wrapper_structured_data():
    """message wrapper 格式 → structured_data 正確解析"""
    line = json.dumps({
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "name": "Grep", "input": {"pattern": "TODO"}}]
        },
    })
    event = parse_stream_event(line)
    assert event is not None
    sd = event.structured_data
    assert sd["tool_name"] == "Grep"
    assert sd["arguments"]["pattern"] == "TODO"
