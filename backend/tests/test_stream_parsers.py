"""stream_parsers 單元測試 — 純函式，無需 fixtures"""
import json

from app.core.stream_parsers import (
    parse_claude_json,
    parse_stream_json_text,
    parse_stream_json_tokens,
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
    assert translate_tool("Read", {"file_path": "/a/b/c.py"}) == ("tool_call", "📖 讀取 b/c.py")


def test_translate_edit():
    assert translate_tool("Edit", {"file_path": "/a/b/c.py"}) == ("tool_call", "✏️ 修改 b/c.py")


def test_translate_write():
    assert translate_tool("Write", {"file_path": "/a/b/c.py"}) == ("tool_call", "📝 建立 b/c.py")


def test_translate_bash_with_desc():
    r = translate_tool("Bash", {"command": "ls -la", "description": "列出檔案"})
    assert r == ("tool_call", "💻 列出檔案")


def test_translate_bash_no_desc():
    r = translate_tool("Bash", {"command": "git status"})
    assert r == ("tool_call", "💻 git status")


def test_translate_grep():
    r = translate_tool("Grep", {"pattern": "TODO"})
    assert r == ("tool_call", "🔍 搜尋 TODO")


def test_translate_glob():
    r = translate_tool("Glob", {"pattern": "**/*.py"})
    assert r == ("tool_call", "📁 搜尋檔案 **/*.py")


def test_translate_webfetch():
    r = translate_tool("WebFetch", {"url": "https://example.com"})
    assert r == ("tool_call", "🌐 取得 https://example.com")


def test_translate_websearch():
    r = translate_tool("WebSearch", {"query": "python asyncio"})
    assert r == ("tool_call", "🔎 搜尋 python asyncio")


def test_translate_agent():
    r = translate_tool("Agent", {"description": "分析程式碼"})
    assert r == ("tool_call", "🤖 分析程式碼")


def test_translate_skill():
    r = translate_tool("Skill", {"skill": "commit"})
    assert r == ("tool_call", "⚡ 技能 commit")


def test_translate_todowrite():
    assert translate_tool("TodoWrite", {}) is None


def test_translate_unknown():
    r = translate_tool("CustomTool", {})
    assert r == ("tool_call", "🔧 CustomTool")


def test_translate_long_truncation():
    long_pattern = "a" * 100
    r = translate_tool("Grep", {"pattern": long_pattern})
    assert len(r[1]) < 100  # 被截斷


# ── parse_tool_call ──────────────────────────────────────────

def test_parse_tool_call_tool_use():
    line = json.dumps({
        "content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "/x/y.py"}}]
    })
    r = parse_tool_call(line)
    assert r[0] == "tool_call"
    assert "讀取" in r[1]


def test_parse_tool_call_short_text():
    line = json.dumps({
        "content": [{"type": "text", "text": "分析完成"}]
    })
    r = parse_tool_call(line)
    assert r == ("output", "💬 分析完成")


def test_parse_tool_call_long_text_skipped():
    line = json.dumps({
        "content": [{"type": "text", "text": "x" * 250}]
    })
    assert parse_tool_call(line) is None


def test_parse_tool_call_thinking():
    line = json.dumps({
        "content": [{"type": "thinking", "text": "let me think"}]
    })
    assert parse_tool_call(line) == ("output", "💭 思考中...")


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
    assert r[0] == "tool_call"
    assert "ls" in r[1]


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

    def test_full_payload(self):
        """完整 payload 解析所有欄位。"""
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

    def test_partial_fields(self):
        """部分欄位缺失 → 缺失欄位使用預設值。"""
        data = json.dumps({"result_text": "ok", "model": "gpt-4o-mini"})
        r = parse_openai_json(data)
        assert r["result_text"] == "ok"
        assert r["model"] == "gpt-4o-mini"
        assert r["duration_ms"] == 0
        assert r["input_tokens"] == 0
        assert r["output_tokens"] == 0
