"""stream_parsers 單元測試 — 純函式，無需 fixtures"""
import json

from app.core.stream_parsers import (
    parse_claude_json,
    parse_stream_json_text,
    parse_stream_json_tokens,
    parse_structured_content,
    _short_path,
    translate_tool,
    parse_tool_call,
    parse_ollama_stream,
    parse_openai_json,
    parse_openai_stream,
)


# ── parse_claude_json ────────────────────────────────────────

def test_parse_claude_json_full():
    data = json.dumps({
        "result": "done",
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 10,
            "cache_creation_input_tokens": 5,
        },
        "modelUsage": {"claude-3-opus": {}},
        "duration_ms": 1234,
        "total_cost_usd": 0.05,
    })
    r = parse_claude_json(data)
    assert r["result_text"] == "done"
    assert r["model"] == "claude-3-opus"
    assert r["duration_ms"] == 1234
    assert r["cost_usd"] == 0.05
    assert r["input_tokens"] == 100
    assert r["output_tokens"] == 50
    assert r["cache_read_tokens"] == 10
    assert r["cache_creation_tokens"] == 5


def test_parse_claude_json_defaults():
    r = parse_claude_json(json.dumps({}))
    assert r["result_text"] == ""
    assert r["model"] == ""
    assert r["duration_ms"] == 0
    assert r["cost_usd"] == 0
    assert r["input_tokens"] == 0
    assert r["output_tokens"] == 0


def test_parse_claude_json_empty_string():
    assert parse_claude_json("") == {}


def test_parse_claude_json_invalid():
    assert parse_claude_json("not json") == {}


def test_parse_claude_json_whitespace():
    r = parse_claude_json("  \n " + json.dumps({"result": "ok"}) + " \n ")
    assert r["result_text"] == "ok"


# ── parse_stream_json_text ───────────────────────────────────

def test_stream_text_assistant_with_text_block():
    line = json.dumps({
        "type": "assistant",
        "content": [{"type": "text", "text": "hello world"}],
    })
    assert parse_stream_json_text(line) == "hello world"


def test_stream_text_fallback_to_message_content():
    line = json.dumps({
        "type": "assistant",
        "content": [],
        "message": {"content": [{"type": "text", "text": "fallback"}]},
    })
    assert parse_stream_json_text(line) == "fallback"


def test_stream_text_non_assistant():
    line = json.dumps({"type": "result", "content": [{"type": "text", "text": "x"}]})
    assert parse_stream_json_text(line) is None


def test_stream_text_no_text_block():
    line = json.dumps({
        "type": "assistant",
        "content": [{"type": "tool_use", "name": "Bash"}],
    })
    assert parse_stream_json_text(line) is None


def test_stream_text_invalid_json():
    assert parse_stream_json_text("{bad") is None


# ── parse_stream_json_tokens ─────────────────────────────────

def test_stream_tokens_full():
    line = json.dumps({
        "type": "result",
        "result": "ok",
        "usage": {"input_tokens": 200, "output_tokens": 80},
        "modelUsage": {"claude-3-sonnet": {}},
        "duration_ms": 999,
        "total_cost_usd": 0.01,
    })
    r = parse_stream_json_tokens(line)
    assert r["model"] == "claude-3-sonnet"
    assert r["input_tokens"] == 200
    assert r["output_tokens"] == 80


def test_stream_tokens_not_result():
    line = json.dumps({"type": "assistant"})
    assert parse_stream_json_tokens(line) == {}


def test_stream_tokens_empty_model_usage():
    line = json.dumps({"type": "result", "modelUsage": {}})
    r = parse_stream_json_tokens(line)
    assert r["model"] == ""


def test_stream_tokens_missing_usage():
    line = json.dumps({"type": "result"})
    r = parse_stream_json_tokens(line)
    assert r["input_tokens"] == 0
    assert r["output_tokens"] == 0


# ── _short_path ──────────────────────────────────────────────

def test_short_path_long_unix():
    assert _short_path("/home/user/projects/aegis/backend/main.py") == "backend/main.py"


def test_short_path_windows():
    assert _short_path("C:\\Users\\dev\\project\\src\\app.py") == "src/app.py"


def test_short_path_short():
    assert _short_path("backend/main.py") == "backend/main.py"


def test_short_path_single():
    assert _short_path("main.py") == "main.py"


# ── translate_tool ───────────────────────────────────────────

def test_translate_read():
    r = translate_tool("Read", {"file_path": "/a/b/c.py"})
    assert r["event_type"] == "tool_call"
    assert r["summary"] == "📖 讀取 b/c.py"
    assert r["tool_name"] == "Read"
    assert r["arguments"] == {"file_path": "/a/b/c.py"}


def test_translate_edit():
    r = translate_tool("Edit", {"file_path": "/a/b/c.py"})
    assert r["event_type"] == "tool_call"
    assert r["summary"] == "✏️ 修改 b/c.py"
    assert r["tool_name"] == "Edit"


def test_translate_write():
    r = translate_tool("Write", {"file_path": "/a/b/c.py"})
    assert r["event_type"] == "tool_call"
    assert r["summary"] == "📝 建立 b/c.py"


def test_translate_bash_with_desc():
    r = translate_tool("Bash", {"command": "ls -la", "description": "列出檔案"})
    assert r["event_type"] == "tool_call"
    assert r["summary"] == "💻 列出檔案"
    assert r["tool_name"] == "Bash"
    assert r["arguments"]["command"] == "ls -la"


def test_translate_bash_no_desc():
    r = translate_tool("Bash", {"command": "git status"})
    assert r["summary"] == "💻 git status"


def test_translate_grep():
    r = translate_tool("Grep", {"pattern": "TODO"})
    assert r["summary"] == "🔍 搜尋 TODO"


def test_translate_glob():
    r = translate_tool("Glob", {"pattern": "**/*.py"})
    assert r["summary"] == "📁 搜尋檔案 **/*.py"


def test_translate_webfetch():
    r = translate_tool("WebFetch", {"url": "https://example.com"})
    assert r["summary"] == "🌐 取得 https://example.com"


def test_translate_websearch():
    r = translate_tool("WebSearch", {"query": "python asyncio"})
    assert r["summary"] == "🔎 搜尋 python asyncio"


def test_translate_agent():
    r = translate_tool("Agent", {"description": "分析程式碼"})
    assert r["summary"] == "🤖 分析程式碼"


def test_translate_skill():
    r = translate_tool("Skill", {"skill": "commit"})
    assert r["summary"] == "⚡ 技能 commit"


def test_translate_todowrite():
    assert translate_tool("TodoWrite", {}) is None


def test_translate_unknown():
    r = translate_tool("CustomTool", {})
    assert r["event_type"] == "tool_call"
    assert r["summary"] == "🔧 CustomTool"
    assert r["tool_name"] == "CustomTool"


def test_translate_long_truncation():
    long_pattern = "a" * 100
    r = translate_tool("Grep", {"pattern": long_pattern})
    assert len(r["summary"]) < 100  # 被截斷


# ── parse_tool_call ──────────────────────────────────────────

def test_parse_tool_call_tool_use():
    line = json.dumps({
        "content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "/x/y.py"}}]
    })
    r = parse_tool_call(line)
    assert r["event_type"] == "tool_call"
    assert "讀取" in r["summary"]
    assert r["tool_name"] == "Read"
    assert r["arguments"] == {"file_path": "/x/y.py"}
    assert r["content_blocks"] is not None


def test_parse_tool_call_short_text():
    line = json.dumps({
        "content": [{"type": "text", "text": "分析完成"}]
    })
    r = parse_tool_call(line)
    assert r["event_type"] == "output"
    assert r["summary"] == "💬 分析完成"
    assert r["tool_name"] is None
    assert r["content_blocks"] is not None


def test_parse_tool_call_long_text_skipped():
    line = json.dumps({
        "content": [{"type": "text", "text": "x" * 250}]
    })
    assert parse_tool_call(line) is None


def test_parse_tool_call_thinking():
    line = json.dumps({
        "content": [{"type": "thinking", "text": "let me think"}]
    })
    r = parse_tool_call(line)
    assert r["event_type"] == "output"
    assert r["summary"] == "💭 思考中..."
    assert r["tool_name"] is None


def test_parse_tool_call_invalid_json():
    assert parse_tool_call("not json") is None


def test_parse_tool_call_content_string():
    line = json.dumps({"content": "just a string"})
    assert parse_tool_call(line) is None


def test_parse_tool_call_todowrite_suppressed():
    line = json.dumps({
        "content": [{"type": "tool_use", "name": "TodoWrite", "input": {}}]
    })
    assert parse_tool_call(line) is None


def test_parse_tool_call_with_message_wrapper():
    line = json.dumps({
        "message": {
            "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]
        }
    })
    r = parse_tool_call(line)
    assert r["event_type"] == "tool_call"
    assert "ls" in r["summary"]
    assert r["tool_name"] == "Bash"


# ── parse_structured_content ────────────────────────────────

def test_parse_structured_content_assistant():
    line = json.dumps({
        "type": "assistant",
        "content": [{"type": "text", "text": "hello"}],
    })
    blocks = parse_structured_content(line)
    assert blocks == [{"type": "text", "text": "hello"}]


def test_parse_structured_content_with_message():
    line = json.dumps({
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "name": "Read", "input": {"file_path": "/a.py"}},
                {"type": "text", "text": "done"},
            ]
        },
    })
    blocks = parse_structured_content(line)
    assert len(blocks) == 2
    assert blocks[0]["type"] == "tool_use"


def test_parse_structured_content_non_assistant():
    line = json.dumps({"type": "result", "content": [{"type": "text", "text": "x"}]})
    assert parse_structured_content(line) is None


def test_parse_structured_content_empty_content():
    line = json.dumps({"type": "assistant", "content": []})
    assert parse_structured_content(line) is None


def test_parse_structured_content_invalid_json():
    assert parse_structured_content("{bad") is None


# ── parse_ollama_stream ─────────────────────────────────────

class TestParseOllamaStream:
    """parse_ollama_stream 函式測試。"""

    def test_chat_format_assistant(self):
        """/api/chat 格式：assistant role 正常提取內容。"""
        line = json.dumps({
            "message": {"role": "assistant", "content": "你好"},
            "done": False,
        })
        assert parse_ollama_stream(line) == "你好"

    def test_generate_format(self):
        """/api/generate 格式：response 欄位正常提取。"""
        line = json.dumps({"response": "hello world", "done": False})
        assert parse_ollama_stream(line) == "hello world"

    def test_done_true_empty_content(self):
        """done=true 且 content 為空字串 → None。"""
        line = json.dumps({
            "message": {"role": "assistant", "content": ""},
            "done": True,
        })
        assert parse_ollama_stream(line) is None

    def test_done_true_empty_response(self):
        """done=true 且 response 為空字串 → None。"""
        line = json.dumps({"response": "", "done": True})
        assert parse_ollama_stream(line) is None

    def test_non_assistant_role(self):
        """非 assistant role → None（跳過 /api/chat 分支）。"""
        line = json.dumps({
            "message": {"role": "system", "content": "你是助手"},
            "done": False,
        })
        assert parse_ollama_stream(line) is None

    def test_invalid_json(self):
        """不合法 JSON → None。"""
        assert parse_ollama_stream("{bad json") is None

    def test_empty_string(self):
        """空字串 → None。"""
        assert parse_ollama_stream("") is None

    def test_no_message_no_response(self):
        """既無 message 也無 response → None。"""
        line = json.dumps({"model": "llama3", "done": True})
        assert parse_ollama_stream(line) is None


# ── parse_openai_stream ────────────────────────────────────

class TestParseOpenaiStream:
    """parse_openai_stream 函式測試。"""

    def test_normal_sse_chunk(self):
        """正常 SSE chunk 提取 content。"""
        line = 'data: {"choices":[{"delta":{"content":"你好"}}]}'
        assert parse_openai_stream(line) == "你好"

    def test_empty_delta(self):
        """delta 無 content → None。"""
        line = 'data: {"choices":[{"delta":{}}]}'
        assert parse_openai_stream(line) is None

    def test_empty_content(self):
        """content 為空字串 → None。"""
        line = 'data: {"choices":[{"delta":{"content":""}}]}'
        assert parse_openai_stream(line) is None

    def test_done_signal(self):
        """[DONE] 終止信號 → None。"""
        assert parse_openai_stream("data: [DONE]") is None

    def test_malformed_json(self):
        """不合法 JSON → None。"""
        assert parse_openai_stream("data: {bad json}") is None

    def test_not_sse_line(self):
        """非 data: 開頭 → None。"""
        assert parse_openai_stream("event: ping") is None

    def test_empty_string(self):
        """空字串 → None。"""
        assert parse_openai_stream("") is None

    def test_empty_choices(self):
        """choices 為空陣列 → None。"""
        line = 'data: {"choices":[]}'
        assert parse_openai_stream(line) is None

    def test_whitespace_around_data(self):
        """data: 前後有空白仍可解析。"""
        line = '  data:   {"choices":[{"delta":{"content":"ok"}}]}  '
        assert parse_openai_stream(line) == "ok"

    def test_role_delta_no_content(self):
        """role delta（首個 chunk）無 content → None。"""
        line = 'data: {"choices":[{"delta":{"role":"assistant"}}]}'
        assert parse_openai_stream(line) is None


# ── parse_openai_json ───────────────────────────────────────

class TestParseOpenaiJson:
    """parse_openai_json 函式測試。"""

    def test_new_format_result_line(self):
        """新格式 stream-json：type=result 行正確解析。"""
        data = json.dumps({
            "type": "result",
            "result": "回答完成",
            "model": "gpt-4o",
            "duration_ms": 2345,
            "total_cost_usd": 0.03,
            "usage": {"input_tokens": 150, "output_tokens": 80},
        })
        r = parse_openai_json(data)
        assert r["result_text"] == "回答完成"
        assert r["model"] == "gpt-4o"
        assert r["duration_ms"] == 2345
        assert r["cost_usd"] == 0.03
        assert r["input_tokens"] == 150
        assert r["output_tokens"] == 80

    def test_new_format_multiline(self):
        """多行 stream-json：從多行中找到 type=result 行解析。"""
        lines = "\n".join([
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello"}]}}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": " world"}]}}),
            json.dumps({
                "type": "result",
                "result": "Hello world",
                "model": "gpt-4o",
                "duration_ms": 1000,
                "total_cost_usd": 0.01,
                "usage": {"input_tokens": 50, "output_tokens": 10},
            }),
        ])
        r = parse_openai_json(lines)
        assert r["result_text"] == "Hello world"
        assert r["input_tokens"] == 50
        assert r["output_tokens"] == 10

    def test_legacy_format_full_payload(self):
        """舊格式 fallback：頂層 key 仍能正確解析。"""
        data = json.dumps({
            "result_text": "回答完成",
            "model": "gpt-4o",
            "duration_ms": 2345,
            "cost_usd": 0.03,
            "input_tokens": 150,
            "output_tokens": 80,
        })
        r = parse_openai_json(data)
        assert r["result_text"] == "回答完成"
        assert r["model"] == "gpt-4o"
        assert r["duration_ms"] == 2345
        assert r["cost_usd"] == 0.03
        assert r["input_tokens"] == 150
        assert r["output_tokens"] == 80

    def test_empty_json(self):
        """空 JSON 物件 → 各欄位回傳預設值。"""
        r = parse_openai_json(json.dumps({}))
        assert r["result_text"] == ""
        assert r["model"] == ""
        assert r["duration_ms"] == 0
        assert r["cost_usd"] == 0
        assert r["input_tokens"] == 0
        assert r["output_tokens"] == 0

    def test_invalid_json(self):
        """不合法 JSON → 空 dict。"""
        assert parse_openai_json("not json") == {}

    def test_empty_string(self):
        """空字串 → 空 dict。"""
        assert parse_openai_json("") == {}

    def test_legacy_partial_fields(self):
        """舊格式部分欄位缺失 → 缺失欄位使用預設值。"""
        data = json.dumps({"result_text": "ok", "model": "gpt-4o-mini"})
        r = parse_openai_json(data)
        assert r["result_text"] == "ok"
        assert r["model"] == "gpt-4o-mini"
        assert r["duration_ms"] == 0
        assert r["input_tokens"] == 0
        assert r["output_tokens"] == 0

    def test_new_format_missing_usage(self):
        """新格式 usage 缺失 → token 欄位回傳 0。"""
        data = json.dumps({"type": "result", "result": "ok"})
        r = parse_openai_json(data)
        assert r["result_text"] == "ok"
        assert r["input_tokens"] == 0
        assert r["output_tokens"] == 0
