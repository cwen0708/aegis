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


def translate_tool(tool: str, inp: dict) -> Tuple[str, str]:
    """將工具名稱和參數翻譯成人話

    Returns: (event_type, summary)
    """
    if tool == "Read":
        return ("tool_call", f"📖 讀取 {_short_path(inp.get('file_path', ''))}")
    elif tool == "Edit":
        return ("tool_call", f"✏️ 修改 {_short_path(inp.get('file_path', ''))}")
    elif tool == "Write":
        return ("tool_call", f"📝 建立 {_short_path(inp.get('file_path', ''))}")
    elif tool == "Bash":
        cmd = inp.get("command", "")[:60]
        desc = inp.get("description", "")
        label = desc[:40] if desc else cmd
        return ("tool_call", f"💻 {label}")
    elif tool == "Grep":
        return ("tool_call", f"🔍 搜尋 {inp.get('pattern', '')[:40]}")
    elif tool == "Glob":
        return ("tool_call", f"📁 搜尋檔案 {inp.get('pattern', '')[:40]}")
    elif tool == "WebFetch":
        return ("tool_call", f"🌐 取得 {inp.get('url', '')[:60]}")
    elif tool == "WebSearch":
        return ("tool_call", f"🔎 搜尋 {inp.get('query', '')[:40]}")
    elif tool == "Agent":
        return ("tool_call", f"🤖 {inp.get('description', '子代理')[:40]}")
    elif tool == "Skill":
        return ("tool_call", f"⚡ 技能 {inp.get('skill', '')}")
    elif tool == "TodoWrite":
        return None
    else:
        return ("tool_call", f"🔧 {tool}")


def parse_tool_call(line: str) -> Optional[Tuple[str, str]]:
    """從 stream-json 行解析工具呼叫，回傳 (event_type, 人話摘要)

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
            return translate_tool(tool, inp)

        if ptype == "text":
            text = part.get("text", "").strip()
            if text and len(text) < 200:
                return ("output", f"💬 {text[:100]}")

        if ptype == "thinking":
            return ("output", "💭 思考中...")

    return None
