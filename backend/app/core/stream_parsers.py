"""
統一 stream-json 解析器 — 從 Claude/Gemini CLI 輸出提取結構化資料
避免 worker.py 和 runner.py 各自維護重複的解析邏輯
"""
import json
import logging
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger(__name__)


def parse_claude_json(output: str) -> Dict[str, Any]:
    """從 Claude CLI 的 JSON 輸出解析 token 用量

    支援兩種格式：
    - 單一 JSON（非 stream 模式）
    - stream-json 最後一行 result
    """
    try:
        data = json.loads(output.strip())
        usage = data.get("usage", {})
        model_usage = data.get("modelUsage", {})
        model_name = ""
        if model_usage:
            model_name = list(model_usage.keys())[0]
        return {
            "result_text": data.get("result", ""),
            "session_id": data.get("session_id"),
            "model": model_name,
            "duration_ms": data.get("duration_ms", 0),
            "cost_usd": data.get("total_cost_usd", 0),
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
            "cache_creation_tokens": usage.get("cache_creation_input_tokens", 0),
        }
    except (json.JSONDecodeError, KeyError, IndexError):
        return {}


def parse_stream_json_text(line: str) -> Optional[str]:
    """從 stream-json 單行提取 assistant 文字內容"""
    try:
        data = json.loads(line.strip())
        msg_type = data.get("type")
        if msg_type == "assistant":
            content = data.get("content", []) or (data.get("message", {}).get("content", []))
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        return block.get("text", "")
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return None


def parse_stream_json_tokens(line: str) -> Dict[str, Any]:
    """從 stream-json 的 result 行提取 token 用量"""
    try:
        data = json.loads(line.strip())
        if data.get("type") != "result":
            return {}
        usage = data.get("usage", {})
        model_usage = data.get("modelUsage", {})
        model_name = list(model_usage.keys())[0] if model_usage else ""
        return {
            "result_text": data.get("result", ""),
            "session_id": data.get("session_id"),
            "model": model_name,
            "duration_ms": data.get("duration_ms", 0),
            "cost_usd": data.get("total_cost_usd", 0),
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
            "cache_creation_tokens": usage.get("cache_creation_input_tokens", 0),
        }
    except (json.JSONDecodeError, KeyError, IndexError):
        return {}


def _short_path(fp: str) -> str:
    """縮短檔案路徑，只保留最後 2 段"""
    parts = fp.replace("\\", "/").split("/")
    return "/".join(parts[-2:]) if len(parts) > 2 else fp


_TOOL_SUMMARIES = {
        "Read":      lambda t, i: f"📖 讀取 {_short_path(i.get('file_path', ''))}",
        "Edit":      lambda t, i: f"✏️ 修改 {_short_path(i.get('file_path', ''))}",
        "Write":     lambda t, i: f"📝 建立 {_short_path(i.get('file_path', ''))}",
        "Bash":      lambda t, i: f"💻 {i.get('description', '')[:40] or i.get('command', '')[:60]}",
        "Grep":      lambda t, i: f"🔍 搜尋 {i.get('pattern', '')[:40]}",
        "Glob":      lambda t, i: f"📁 搜尋檔案 {i.get('pattern', '')[:40]}",
        "WebFetch":  lambda t, i: f"🌐 取得 {i.get('url', '')[:60]}",
        "WebSearch":  lambda t, i: f"🔎 搜尋 {i.get('query', '')[:40]}",
        "Agent":     lambda t, i: f"🤖 {i.get('description', '子代理')[:40]}",
    "Skill":     lambda t, i: f"⚡ 技能 {i.get('skill', '')}",
}


def translate_tool(tool: str, inp: dict) -> Optional[Dict[str, Any]]:
    """將工具名稱和參數翻譯成結構化 dict

    Returns: dict with event_type, summary, tool_name, arguments
             或 None（不值得顯示的工具，如 TodoWrite）
    """
    if tool == "TodoWrite":
        return None

    fmt = _TOOL_SUMMARIES.get(tool)
    summary = fmt(tool, inp) if fmt else f"🔧 {tool}"

    return {
        "event_type": "tool_call",
        "summary": summary,
        "tool_name": tool,
        "arguments": inp,
    }


def parse_tool_call(line: str) -> Optional[Dict[str, Any]]:
    """從 stream-json 行解析工具呼叫，回傳結構化 dict

    Returns dict with keys:
        event_type: "tool_call" | "output"
        summary: 人話摘要（emoji + 說明）
        tool_name: 工具名稱（僅 tool_call）
        arguments: 工具參數（僅 tool_call）
        content_blocks: 原始 content blocks

    Returns None 表示不是工具呼叫或不值得顯示
    """
    try:
        data = json.loads(line)
    except (ValueError, TypeError):
        return None

    msg = data.get("message", {}) if isinstance(data, dict) else {}
    if not msg:
        msg = data

    content = msg.get("content", [])
    if isinstance(content, str) or not isinstance(content, list):
        return None

    for part in content:
        if not isinstance(part, dict):
            continue
        ptype = part.get("type", "")

        if ptype == "tool_use":
            tool = part.get("name", "")
            inp = part.get("input", {})
            result = translate_tool(tool, inp)
            if result is not None:
                result["content_blocks"] = content
            return result

        if ptype == "text":
            text = part.get("text", "").strip()
            if text and len(text) < 200:
                return {
                    "event_type": "output",
                    "summary": f"💬 {text[:100]}",
                    "tool_name": None,
                    "arguments": None,
                    "content_blocks": content,
                }

        if ptype == "thinking":
            return {
                "event_type": "output",
                "summary": "💭 思考中...",
                "tool_name": None,
                "arguments": None,
                "content_blocks": content,
            }

    return None


def parse_structured_content(line: str) -> Optional[list]:
    """從 assistant 訊息提取完整 content blocks

    Returns: content blocks list 或 None
    """
    try:
        data = json.loads(line.strip())
    except (json.JSONDecodeError, ValueError):
        return None

    if data.get("type") != "assistant":
        return None

    msg = data.get("message", {}) if isinstance(data, dict) else {}
    if not msg:
        msg = data

    content = msg.get("content", [])
    if isinstance(content, list) and content:
        return content
    return None


def parse_ollama_stream(line: str) -> Optional[str]:
    """從 Ollama 流式輸出單行提取文字內容。

    支援兩種 Ollama API 格式：
    - /api/chat：{"message": {"role": "assistant", "content": "..."}, "done": false}
    - /api/generate：{"response": "...", "done": false}

    Returns:
        提取的文字內容，或 None（非文字行或解析失敗）
    """
    try:
        data = json.loads(line.strip())
        # /api/chat 格式
        message = data.get("message")
        if isinstance(message, dict) and message.get("role") == "assistant":
            content = message.get("content", "")
            return content if content else None
        # /api/generate 格式
        response = data.get("response")
        if response is not None:
            return response if response else None
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return None


def parse_openai_stream(line: str) -> Optional[str]:
    """從 OpenAI SSE 流式輸出單行提取文字內容。

    支援格式：
    - data: {"choices":[{"delta":{"content":"..."}}]}
    - data: [DONE] 終止信號 → None

    Returns:
        提取的文字內容，或 None（非文字行、空 delta 或解析失敗）
    """
    stripped = line.strip()
    if not stripped.startswith("data:"):
        return None
    payload = stripped[5:].strip()
    if payload == "[DONE]":
        return None
    try:
        data = json.loads(payload)
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            delta = choices[0].get("delta", {})
            content = delta.get("content")
            if content:
                return content
    except (json.JSONDecodeError, KeyError, TypeError, IndexError):
        pass
    return None


def parse_openai_json(output: str) -> Dict[str, Any]:
    """從 OpenAI CLI wrapper 的 JSON 輸出解析結果與 token 用量

    支援兩種格式：
    - 多行 stream-json：逐行掃描找 type=result 的行
    - 單一 JSON（舊格式）：直接解析整段輸出
    """
    # 多行 stream-json：逐行掃描找 type=result
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if data.get("type") == "result":
                usage = data.get("usage", {})
                return {
                    "result_text": data.get("result", ""),
                    "model": data.get("model", ""),
                    "duration_ms": data.get("duration_ms", 0),
                    "cost_usd": data.get("total_cost_usd", 0),
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                }
        except (json.JSONDecodeError, ValueError):
            continue

    # 舊格式 fallback：單一 JSON，key 在頂層
    try:
        data = json.loads(output.strip())
        return {
            "result_text": data.get("result_text", ""),
            "model": data.get("model", ""),
            "duration_ms": data.get("duration_ms", 0),
            "cost_usd": data.get("cost_usd", 0),
            "input_tokens": data.get("input_tokens", 0),
            "output_tokens": data.get("output_tokens", 0),
        }
    except (json.JSONDecodeError, KeyError):
        return {}
