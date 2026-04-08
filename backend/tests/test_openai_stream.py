"""OpenAI SSE 串流適配器測試 — 驗證 stream-json 輸出格式與現有解析器相容"""
import json
import sys
import os

# 確保 scripts/ 可被 import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from app.core.stream_parsers import (
    parse_stream_json_text,
    parse_stream_json_tokens,
    parse_tool_call,
)


# ── 輔助：模擬 openai_stream_chat 的輸出格式 ─────────────────

def _make_assistant_text(text: str) -> dict:
    return {
        "type": "assistant",
        "message": {
            "content": [{"type": "text", "text": text}],
        },
    }


def _make_result(full_text: str, model: str, usage: dict, duration_ms: int) -> dict:
    return {
        "type": "result",
        "result": full_text,
        "duration_ms": duration_ms,
        "total_cost_usd": 0,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
        "modelUsage": {
            model: {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            },
        },
    }


# ── assistant 文字事件 → parse_stream_json_text 相容 ──────────

def test_assistant_text_parsed_correctly():
    """stream_parsers 能正確解析 OpenAI adapter 的 assistant 行"""
    line = json.dumps(_make_assistant_text("Hello"))
    assert parse_stream_json_text(line) == "Hello"


def test_assistant_text_unicode():
    line = json.dumps(_make_assistant_text("你好世界 🌍"))
    assert parse_stream_json_text(line) == "你好世界 🌍"


def test_assistant_text_empty():
    line = json.dumps(_make_assistant_text(""))
    # 空字串 → 解析器回傳空字串（get("text", "") 回傳 ""）
    assert parse_stream_json_text(line) == ""


def test_assistant_text_multiline():
    text = "line1\nline2\nline3"
    line = json.dumps(_make_assistant_text(text))
    assert parse_stream_json_text(line) == text


# ── result 事件 → parse_stream_json_tokens 相容 ──────────────

def test_result_tokens_parsed():
    """stream_parsers 能正確解析 OpenAI adapter 的 result 行"""
    usage = {"prompt_tokens": 150, "completion_tokens": 80, "total_tokens": 230}
    result = _make_result("完成了", "gpt-4o-2024-08-06", usage, 1500)
    line = json.dumps(result)

    tokens = parse_stream_json_tokens(line)
    assert tokens["result_text"] == "完成了"
    assert tokens["model"] == "gpt-4o-2024-08-06"
    assert tokens["input_tokens"] == 150
    assert tokens["output_tokens"] == 80
    assert tokens["duration_ms"] == 1500


def test_result_zero_usage():
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    result = _make_result("", "gpt-4o", usage, 0)
    line = json.dumps(result)

    tokens = parse_stream_json_tokens(line)
    assert tokens["input_tokens"] == 0
    assert tokens["output_tokens"] == 0


def test_result_missing_usage():
    """usage 完全缺失時也不應 crash"""
    result = {"type": "result", "result": "ok"}
    line = json.dumps(result)
    tokens = parse_stream_json_tokens(line)
    assert tokens["input_tokens"] == 0
    assert tokens["output_tokens"] == 0


# ── 完整串流模擬（多行 assistant + 最終 result）────────────────

def test_full_stream_simulation():
    """模擬完整的 OpenAI SSE 轉換後串流，驗證文字累積與 token 收集"""
    chunks = ["Hello", ", ", "world", "!"]
    usage = {"prompt_tokens": 50, "completion_tokens": 4, "total_tokens": 54}

    collected_text = []
    token_info = {}

    for chunk in chunks:
        line = json.dumps(_make_assistant_text(chunk))
        text = parse_stream_json_text(line)
        if text is not None:
            collected_text.append(text)

    result_line = json.dumps(_make_result("Hello, world!", "gpt-4o", usage, 800))
    token_info = parse_stream_json_tokens(result_line)

    assert "".join(collected_text) == "Hello, world!"
    assert token_info["result_text"] == "Hello, world!"
    assert token_info["input_tokens"] == 50
    assert token_info["output_tokens"] == 4


# ── parse_tool_call 不會誤判 assistant 文字為 tool_call ────────

def test_assistant_text_not_tool_call():
    """OpenAI 不會產生 tool_use，但 parse_tool_call 不應誤判短文字"""
    line = json.dumps(_make_assistant_text("分析完成"))
    result = parse_tool_call(line)
    # message wrapper 下的 content 會被解析
    # 短文字 < 200 字��� → {"event_type": "output", "summary": "💬 ..."}
    assert result is not None
    assert result["event_type"] == "output"


# ── Provider 設定 ─────────────────────────────────────────────

def test_openai_provider_is_stream_json():
    """OpenAI provider 設定應為 stream_json 模式"""
    from app.core.executor.providers import PROVIDERS
    config = PROVIDERS["openai"]
    assert config.get("stream_json") is True
    assert config.get("json_output") is not True  # 不能同時設定


def test_openai_build_command():
    """build_command 應正確組裝 OpenAI 串流命令"""
    from app.core.executor.providers import build_command
    cmd, stdin_prompt = build_command("openai", "test prompt", "gpt-4o-mini")
    assert "openai_stream_chat.py" in " ".join(cmd)
    assert "--model" in cmd
    assert "gpt-4o-mini" in cmd
    assert stdin_prompt is True  # prompt 從 stdin 傳入


def test_openai_build_command_default_model():
    from app.core.executor.providers import build_command
    cmd, _ = build_command("openai", "test")
    assert "gpt-4o" in cmd
