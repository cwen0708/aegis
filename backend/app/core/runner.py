"""
Runner — 輕量 AI 呼叫器（僅供即時互動場景使用）

⚠️ 此模組【不負責】卡片任務執行。卡片任務由獨立的 worker.py 程序處理，
   worker.py 擁有完整的 PTY 串流、帳號 fallback、心跳、CronLog 等機制。

此模組的使用者：
- chat_handler.py — Bot 即時對話（Telegram/LINE 等）
- email_processor.py — Email AI 分類

這些場景不需要 PTY 串流或帳號 fallback，只需簡單的 prompt → response。
"""
import asyncio
import subprocess
import json
import re
import logging
import threading
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Channel-send 標記格式：
# [CH_EDIT:platform:chat_id:message_id:文字內容]
# [CH_SEND:platform:chat_id:文字內容]
_CH_EDIT_RE = re.compile(r'\[CH_EDIT:([^:]+):([^:]+):([^:]+):(.+)\]', re.DOTALL)
_CH_SEND_RE = re.compile(r'\[CH_SEND:([^:]+):([^:]+):(.+)\]', re.DOTALL)


def _parse_stream_json_text(line: str) -> Optional[str]:
    """從 stream-json 行提取 AI 文字輸出或 result"""
    try:
        data = json.loads(line.strip())
        msg_type = data.get("type")
        if msg_type == "assistant":
            content = data.get("content", []) or (data.get("message", {}).get("content", []))
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        return block.get("text", "")
        elif msg_type == "result":
            return data.get("result", "")
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return None


def _parse_stream_json_tokens(line: str) -> Dict[str, Any]:
    """從 stream-json result 行提取 token 用量"""
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


def _intercept_channel_marker(line: str):
    """即時攔截輸出中的 channel-send 標記，非同步發送訊息"""
    import urllib.request

    for pattern, has_edit_id in [(_CH_EDIT_RE, True), (_CH_SEND_RE, False)]:
        m = pattern.search(line)
        if not m:
            continue
        if has_edit_id:
            platform, chat_id, edit_id, text = m.group(1), m.group(2), m.group(3), m.group(4)
        else:
            platform, chat_id, text = m.group(1), m.group(2), m.group(3)
            edit_id = None

        payload = json.dumps({
            "platform": platform,
            "chat_id": chat_id,
            "text": text,
            "edit_message_id": edit_id,
        }).encode()

        def _send(data=payload):
            try:
                req = urllib.request.Request(
                    "http://127.0.0.1:8899/api/v1/internal/channel-send",
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=10)
            except Exception as e:
                logger.warning(f"[Runner] Channel send failed: {e}")

        # 用 thread 發送，不阻塞 stdout 讀取
        threading.Thread(target=_send, daemon=True).start()
        return

# 支援的 AI 提供者指令配置
PROVIDERS = {
    "gemini": {
        "cmd_base": ["gemini"],
        "args": ["-p", "{prompt}", "-y", "--model", "gemini-2.5-flash"],
        "env": {},
        "json_output": False,
    },
    "claude": {
        "cmd_base": ["claude"],
        "args": ["-p", "{prompt}", "--dangerously-skip-permissions", "--model", "opus", "--output-format", "stream-json", "--verbose"],
        "env": {},
        "json_output": True,  # 仍用 JSON 解析最終結果
        "stream_json": True,
    },
    "ollama": {
        "cmd_base": ["ollama", "run"],
        "args": ["{model}"],
        "env": {},
        "json_output": False,
        "default_model": "llama3.1:8b",
        "stdin_prompt": True,
    },
}


def _parse_claude_json(output: str) -> Dict[str, Any]:
    """從 Claude CLI JSON 輸出解析 token 用量"""
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


def _get_member_mcp_config(member_id: int) -> Optional[str]:
    """查找成員的 mcp.json 路徑，存在則回傳絕對路徑"""
    try:
        from sqlmodel import Session
        from app.database import engine
        from app.models.core import Member
        from app.core.member_profile import get_member_dir
        with Session(engine) as session:
            member = session.get(Member, member_id)
            if member and member.slug:
                mcp_path = get_member_dir(member.slug) / "mcp.json"
                if mcp_path.exists():
                    return str(mcp_path)
    except Exception:
        pass
    return None


async def run_ai_task(task_id: int, project_path: str, prompt: str, phase: str,
                      forced_provider: Optional[str] = None, card_title: str = "",
                      project_name: str = "", member_id: Optional[int] = None,
                      model_override: Optional[str] = None,
                      project_id: Optional[int] = None,
                      auth_info: Optional[Dict[str, str]] = None,
                      extra_env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    執行單一 AI 呼叫（用於 chat / email 等即時場景）。

    注意：卡片任務不走這裡，由 worker.py 負責。
    """
    provider_name = forced_provider if forced_provider and forced_provider in PROVIDERS else "claude"
    config = PROVIDERS[provider_name]

    model = model_override or config.get("default_model", "")

    cmd = list(config["cmd_base"])
    for arg in config["args"]:
        if "{prompt}" in arg:
            cmd.append(arg.replace("{prompt}", prompt))
        elif "{model}" in arg:
            cmd.append(arg.replace("{model}", model))
        else:
            cmd.append(arg)

    if model_override:
        for i, arg in enumerate(cmd):
            if arg == "--model" and i + 1 < len(cmd):
                cmd[i + 1] = model_override
                break

    # 如果有成員且是 claude，注入 MCP 設定
    if provider_name == "claude" and member_id:
        mcp_config_path = _get_member_mcp_config(member_id)
        if mcp_config_path:
            cmd.extend(["--mcp-config", mcp_config_path])

    stdin_prompt = config.get("stdin_prompt", False)

    from app.core.sandbox import build_sanitized_env, get_popen_kwargs
    env = build_sanitized_env(project_id=project_id)
    env.update(config.get("env", {}))

    # 注入額外環境變數（如 per-user AD 帳密 for MCP）
    if extra_env:
        env.update(extra_env)

    # 注入 Account 認證資訊
    auth_info = auth_info or {}
    auth_type = auth_info.get('auth_type', 'cli')
    if provider_name == "claude":
        if auth_type == 'api_key' and auth_info.get('api_key'):
            env["ANTHROPIC_API_KEY"] = auth_info['api_key']
        elif auth_info.get('oauth_token'):
            env["CLAUDE_CODE_OAUTH_TOKEN"] = auth_info['oauth_token']
    elif provider_name == "gemini":
        if auth_info.get('api_key'):
            env["GEMINI_API_KEY"] = auth_info['api_key']

    logger.info(f"[Runner] Executing {provider_name} (task_id={task_id}, phase={phase})")

    try:
        popen_kwargs = get_popen_kwargs()
        proc = subprocess.Popen(
            cmd,
            cwd=project_path,
            stdin=subprocess.PIPE if stdin_prompt else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            **popen_kwargs,
        )
        if stdin_prompt and proc.stdin:
            proc.stdin.write(prompt.encode("utf-8"))
            proc.stdin.close()

        is_stream_json = config.get("stream_json", False)
        result_text_parts = []
        stream_token_info = {}

        def _read_output():
            lines = []
            for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace")
                lines.append(line)

                if is_stream_json:
                    # stream-json 模式：逐行解析文字、即時攔截標記
                    clean = line.strip()
                    if clean.startswith("{"):
                        text = _parse_stream_json_text(clean)
                        if text:
                            result_text_parts.append(text)
                            # 即時攔截 channel-send 標記
                            for tl in text.split("\n"):
                                _intercept_channel_marker(tl.strip())
                        # 收集 token info（從 result 行）
                        ti = _parse_stream_json_tokens(clean)
                        if ti:
                            nonlocal stream_token_info
                            stream_token_info = ti
                elif not config.get("json_output"):
                    _intercept_channel_marker(line.strip())
            proc.wait()
            return lines

        try:
            output_lines = await asyncio.wait_for(
                asyncio.to_thread(_read_output),
                timeout=600,  # chat/email 10 分鐘超時（比卡片任務短）
            )
        except asyncio.TimeoutError:
            proc.kill()
            proc.wait()
            return {"status": "timeout", "output": "任務超時 (10 分鐘)", "provider": provider_name}

        output = "".join(output_lines)
        status = "success" if proc.returncode == 0 else "error"

        token_info = {}
        actual_output = output
        if provider_name == "claude":
            if is_stream_json and result_text_parts:
                # stream-json 模式：用逐行收集的文字（標記已即時攔截）
                actual_output = "".join(result_text_parts)
                token_info = stream_token_info
            else:
                # 舊 JSON 模式 fallback
                token_info = _parse_claude_json(output)
                if token_info.get("result_text"):
                    actual_output = token_info["result_text"]
                # 後處理標記
                for tl in actual_output.split("\n"):
                    _intercept_channel_marker(tl.strip())

        return {
            "status": status,
            "output": actual_output,
            "provider": provider_name,
            "exit_code": proc.returncode,
            "token_info": token_info,
        }

    except Exception as e:
        logger.exception(f"[Runner] Execution failed: {e}")
        return {"status": "error", "output": str(e), "provider": provider_name}
